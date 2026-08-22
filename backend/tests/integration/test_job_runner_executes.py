"""G.10 — the `JobRunner` contract: a submitted search runs, reports, and persists.

Separate from `test_optimizer_jobs.py` because the two levels can only honestly assert
different things. The route tests run against `conftest`'s mocked runner and prove the
*handoff* — a queued row and a submitted search. This drives a **real** runner and proves
what happens after: `queued` → `running` → a terminal status, with progress written on the
way and the result persisted at the end.

Nothing here goes through HTTP. The runner writes through its own `session_factory` on the
event loop, so it cannot see the rolled-back transaction `db_session` runs in — these tests
commit their own rows and delete them, which is also why the job ids are unique per test.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.optimization_job import OptimizationJob
from app.services.artifact_optimizer import OptimizerProgress
from app.services.artifact_prefilter import Cancelled
from app.services.job_runner import JobRunner

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
async def committed_factory(test_engine: AsyncEngine) -> async_sessionmaker:
    """A session factory that really commits, like the one `main.py` hands the runner."""
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture
async def runner(committed_factory: async_sessionmaker) -> AsyncGenerator[JobRunner, None]:
    made = JobRunner(
        max_workers=2,
        session_factory=committed_factory,
        loop=asyncio.get_running_loop(),
    )
    yield made
    made.shutdown(wait=True)


async def _queued_job(factory: async_sessionmaker) -> str:
    async with factory() as session:
        job = OptimizationJob(job_type="optimizer", status="queued", request={})
        session.add(job)
        await session.commit()
        return str(job.id)


async def _read(factory: async_sessionmaker, job_id: str) -> OptimizationJob:
    async with factory() as session:
        return await session.get(OptimizationJob, job_id)


async def _await_status(
    factory: async_sessionmaker, job_id: str, *, tries: int = 100,
) -> OptimizationJob:
    """Poll until terminal, or fail loudly.

    Loudly, because a test that shrugged at a still-queued job would pass whether or not the
    runner ever executed anything — which is exactly the state the route-level tests are in,
    and the reason this file exists.
    """
    row = None
    for _ in range(tries):
        row = await _read(factory, job_id)
        if row.status in ("succeeded", "failed", "cancelled"):
            return row
        await asyncio.sleep(0.05)
    pytest.fail(f"job {job_id} never finished; last status {row.status if row else '?'!r}")
    raise AssertionError


async def _cleanup(factory: async_sessionmaker, job_id: str) -> None:
    async with factory() as session:
        await session.execute(delete(OptimizationJob).where(OptimizationJob.id == job_id))
        await session.commit()


@pytest.mark.asyncio
async def test_a_submitted_search_runs_reports_and_persists(
    runner: JobRunner, committed_factory: async_sessionmaker,
):
    job_id = await _queued_job(committed_factory)

    def search(_cancel: threading.Event, report: Callable[[OptimizerProgress], None]) -> dict:
        report(OptimizerProgress(
            combinations_done=50, combinations_total=100, evaluated=40,
            rejected_by_sets=6, rejected_by_stats=4, elapsed_seconds=1.0,
        ))
        return {"builds": [{"damage": 1234.5}], "search": {"is_exact": True}}

    runner.submit_search(job_id, search)
    row = await _await_status(committed_factory, job_id)

    try:
        assert row.status == "succeeded"
        assert row.result == {"builds": [{"damage": 1234.5}], "search": {"is_exact": True}}
        # The summary column a job list shows without loading every result.
        assert row.top_damage == pytest.approx(1234.5)
        # Progress was written while it ran, in the vocabulary the migration renamed to.
        assert row.combinations_done == 50
        assert row.rejected_by_sets == 6
        assert row.started_at is not None
        assert row.finished_at is not None
    finally:
        await _cleanup(committed_factory, job_id)


@pytest.mark.asyncio
async def test_a_search_that_finds_nothing_reports_no_top_damage(
    runner: JobRunner, committed_factory: async_sessionmaker,
):
    """`None`, not `0.0`. A job that found no build and a job whose best build does no
    damage are different outcomes, and a zero renders as the second."""
    job_id = await _queued_job(committed_factory)

    runner.submit_search(job_id, lambda _c, _r: {"builds": [], "search": {}})
    row = await _await_status(committed_factory, job_id)

    try:
        assert row.status == "succeeded"
        assert row.top_damage is None
    finally:
        await _cleanup(committed_factory, job_id)


@pytest.mark.asyncio
async def test_a_raising_search_is_recorded_as_failed(
    runner: JobRunner, committed_factory: async_sessionmaker,
):
    """A failed job is data. A worker thread that died would take the runner's slot
    accounting with it, and the next job would queue behind one that no longer exists."""
    job_id = await _queued_job(committed_factory)

    def explode(_cancel: threading.Event, _report: Callable) -> dict:
        msg = "synthetic failure"
        raise RuntimeError(msg)

    runner.submit_search(job_id, explode)
    row = await _await_status(committed_factory, job_id)

    try:
        assert row.status == "failed"
        assert "synthetic failure" in row.error_message
    finally:
        await _cleanup(committed_factory, job_id)


@pytest.mark.asyncio
async def test_cancelling_a_running_search_records_it_as_cancelled(
    runner: JobRunner, committed_factory: async_sessionmaker,
):
    """Cooperative: the search sees the event through its progress callback and raises.

    `artifact_optimizer.optimize` does exactly this — there is no other way into a
    synchronous CPU-bound loop, which is why it takes the callback at all.
    """
    job_id = await _queued_job(committed_factory)
    started = threading.Event()

    def search(cancel: threading.Event, _report: Callable) -> dict:
        started.set()
        for _ in range(200):
            if cancel.is_set():
                raise Cancelled
            cancel.wait(0.01)
        msg = "was never cancelled"
        raise AssertionError(msg)

    runner.submit_search(job_id, search)
    await asyncio.get_running_loop().run_in_executor(None, started.wait, 5.0)
    runner.cancel(job_id)
    row = await _await_status(committed_factory, job_id)

    try:
        assert row.status == "cancelled"
    finally:
        await _cleanup(committed_factory, job_id)


@pytest.mark.asyncio
async def test_a_second_job_waits_for_the_concurrency_slot(
    committed_factory: async_sessionmaker,
):
    """The cap is why a job list can show one running and one waiting rather than both
    claiming to run. Its queue-and-dispatch machinery is the part of `JobRunner` that
    survived the demolition precisely because it was hard to get right."""
    made = JobRunner(
        max_workers=2, max_optimizer_concurrency=1,
        session_factory=committed_factory, loop=asyncio.get_running_loop(),
    )
    first_id = await _queued_job(committed_factory)
    second_id = await _queued_job(committed_factory)
    release = threading.Event()
    order: list[str] = []

    def blocking(name: str) -> Callable:
        def run(_cancel: threading.Event, _report: Callable) -> dict:
            order.append(name)
            release.wait(5.0)
            return {"builds": []}
        return run

    try:
        made.submit_search(first_id, blocking("first"))
        made.submit_search(second_id, blocking("second"))
        await asyncio.sleep(0.2)

        assert order == ["first"], "the second must not start while the cap is full"
        release.set()
        await _await_status(committed_factory, first_id)
        await _await_status(committed_factory, second_id)
        assert order == ["first", "second"]
    finally:
        release.set()
        made.shutdown(wait=True)
        await _cleanup(committed_factory, first_id)
        await _cleanup(committed_factory, second_id)
