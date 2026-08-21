"""Integration test for orphan-job sweep on startup (T3.3)."""

from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.optimization_job import OptimizationJob
from app.repositories.optimization_job import OptimizationJobRepository
from app.services.job_runner import run_orphan_sweep


@pytest.fixture
async def direct_session_factory(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def cleanup_jobs(direct_session_factory):
    yield
    async with direct_session_factory() as session:
        await session.execute(delete(OptimizationJob))
        await session.commit()


async def _create_job(factory, status: str) -> str:
    async with factory() as session:
        repo = OptimizationJobRepository(session)
        job = await repo.create(
            {
                "status": status,
                "request": {},
                "character_name": "A",
                "enemy_name": "E",
                "rotation_name": "C",
            }
        )
        await session.commit()
        return str(job.id)


async def _get_job(factory, job_id: str) -> OptimizationJob | None:
    async with factory() as session:
        repo = OptimizationJobRepository(session)
        return await repo.get_by_id(job_id)


class TestOrphanSweep:
    async def test_sweep_marks_running_and_queued_as_failed(self, direct_session_factory):
        """Running and queued rows become 'failed' after sweep_orphans()."""
        running_id = await _create_job(direct_session_factory, "running")
        queued_id = await _create_job(direct_session_factory, "queued")

        async with direct_session_factory() as session:
            repo = OptimizationJobRepository(session)
            count = await repo.sweep_orphans()

        assert count >= 2  # may be more if other tests leaked rows

        running = await _get_job(direct_session_factory, running_id)
        queued = await _get_job(direct_session_factory, queued_id)

        assert running is not None
        assert running.status == "failed"
        assert running.error_message is not None
        assert queued is not None
        assert queued.status == "failed"

    async def test_sweep_leaves_terminal_rows_untouched(self, direct_session_factory):
        """Succeeded / failed / cancelled rows are not modified by the sweep."""
        succeeded_id = await _create_job(direct_session_factory, "succeeded")
        failed_id = await _create_job(direct_session_factory, "failed")
        cancelled_id = await _create_job(direct_session_factory, "cancelled")

        async with direct_session_factory() as session:
            repo = OptimizationJobRepository(session)
            count = await repo.sweep_orphans()

        assert count == 0

        for jid, expected in [
            (succeeded_id, "succeeded"),
            (failed_id, "failed"),
            (cancelled_id, "cancelled"),
        ]:
            job = await _get_job(direct_session_factory, jid)
            assert job is not None
            assert job.status == expected

    async def test_sweep_called_in_lifespan(self, direct_session_factory):
        """run_orphan_sweep with the test factory correctly sweeps orphans."""
        orphan_id = await _create_job(direct_session_factory, "running")
        await run_orphan_sweep(direct_session_factory)

        job = await _get_job(direct_session_factory, orphan_id)
        assert job is not None
        assert job.status == "failed"
