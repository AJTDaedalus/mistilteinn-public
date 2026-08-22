"""JobRunner — bounded threadpool executor for async search jobs.

Submits CPU-bound search tasks to a dedicated ThreadPoolExecutor so they
run off the async event loop. Provides cooperative cancellation via
per-job threading.Events and DB persistence via run_coroutine_threadsafe.

TODO(chunk-G.10): this module kept its generic machinery through the ZZZ demolition
(B.2) but lost both concrete job types. **Their replacements now exist** —
``app.services.artifact_optimizer.optimize`` and ``app.services.artifact_ranker.rank``,
landed in G.1/G.3/G.4 — and G.6c calls both *synchronously inside the request*. G.10 is the
wiring that moves them here, which matters because ``artifact_prefilter``'s automatic budget
targets 300 seconds of work and no HTTP client waits that long.

Two things G.10 will hit, recorded here rather than rediscovered:

* ``SearchProgress`` below still describes fairy's ZZZ payload
  (``combinations_done`` / ``rejected_by_sets``). ``OptimizerProgress`` reports
  ``combinations_done`` / ``combinations_total`` / ``evaluated`` / ``elapsed_seconds``
  and does **not** satisfy this protocol. One of the two has to move; the ETA formula
  below is what the protocol exists for, so read that before changing either.
* ``artifact_optimizer.optimize`` already takes a ``progress_callback`` and honours
  ``artifact_prefilter.Cancelled``, so cooperative cancellation needs no new mechanism.

The per-kind concurrency cap and the queue-drop-on-cancel semantics are the parts that were
hard to get right, which is why the queues are kept rather than deleted and rewritten.
Recover the deleted bodies from fairy@76909c4:backend/app/services/job_runner.py.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Protocol

from app.repositories.optimization_job import OptimizationJobRepository
from app.services.artifact_prefilter import Cancelled

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)

# Throttle for progress writes from a worker thread. Unreferenced since B.2 removed the
# two concrete job types; kept rather than deleted because it is a tuned value, and Chunk G
# restores the code that reads it (see the module TODO).
PROGRESS_WRITE_INTERVAL_S = 0.5


async def run_orphan_sweep(session_factory: async_sessionmaker) -> int:
    """Mark any queued/running jobs as failed (called on startup)."""
    async with session_factory() as session:
        repo = OptimizationJobRepository(session)
        count = await repo.sweep_orphans()
    if count:
        logger.warning("Orphan sweep: marked %d stale job(s) as failed", count)
    return count


class SearchProgress(Protocol):
    """Structural type for a search-progress callback payload.

    Was ``disc_optimizer.OptimizerProgress``, deleted in G.8. Stated structurally so the
    ETA formula and the progress writer survive without importing the optimizer — this
    module is generic machinery and should not know which search it is running.

    ``artifact_optimizer.OptimizerProgress`` satisfies it, and G.10 is where the two were
    reconciled. The ZZZ shape it used to describe — ``assignments_done`` over
    set-assignment *frames* — was renamed to combinations in the same change, because the
    Genshin search has no frames to count; see the migration.
    """

    combinations_done: int
    combinations_total: int
    evaluated: int
    rejected_by_sets: int
    rejected_by_stats: int
    elapsed_seconds: float


#: What `submit_search` runs on the worker thread: given a cancel event and a progress
#: reporter, produce the result dict to persist.
SearchFn = Callable[[threading.Event, Callable[["SearchProgress"], None]], dict]


def _top_damage(result: dict) -> float | None:
    """The best build's damage, for the job list's summary column.

    `None` rather than `0.0` when a search returned nothing: a job that found no build and
    a job whose best build does no damage are different outcomes, and a zero would render
    as the second.
    """
    builds = result.get("builds") or []
    if not builds:
        return None
    return float(builds[0].get("damage", 0.0))


def _eta(p: SearchProgress) -> float | None:
    """ETA in seconds per §Q6 formula; None during warmup."""
    threshold = max(3, math.ceil(p.combinations_total * 0.05))
    if p.combinations_done < threshold or p.combinations_done == 0:
        return None
    return p.elapsed_seconds * (p.combinations_total - p.combinations_done) / p.combinations_done


class JobRunner:
    """Bounded threadpool runner for optimizer jobs.

    DB persistence is handled via ``asyncio.run_coroutine_threadsafe``
    against the event loop captured at construction time.
    """

    def __init__(
        self,
        *,
        max_workers: int = 2,
        max_optimizer_concurrency: int = 1,
        max_rank_concurrency: int = 1,
        session_factory: async_sessionmaker | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="optimizer",
        )
        self._cancel_events: dict[str, threading.Event] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()

        # Per-kind concurrency caps and in-memory queues.
        # Jobs that exceed the cap stay in `queued` status in the DB
        # until the running job finishes and dispatches the next one.
        self._max_optimizer = max_optimizer_concurrency
        self._max_rank = max_rank_concurrency
        self._optimizer_running = 0
        self._rank_running = 0
        self._optimizer_queue: deque[tuple[str, threading.Event, Any]] = deque()
        self._rank_queue: deque[tuple[str, threading.Event, Any]] = deque()

        # session_factory and loop are optional for unit tests (stub mode).
        self._session_factory = session_factory
        self._loop = loop

    # ------------------------------------------------------------------
    # Public API

    def submit_search(self, job_id: str, search_fn: SearchFn) -> None:
        """Queue a search, honouring the per-kind concurrency cap.

        `search_fn(cancel_event, report)` runs on a worker thread. It reports progress
        through `report`, returns the result dict to persist, and is expected to stop when
        `cancel_event` is set — `artifact_optimizer.optimize` does that by raising
        `artifact_prefilter.Cancelled` from its progress callback.

        The job stays `queued` in the database until a slot frees, so a user watching two
        submissions sees one running and one waiting rather than both claiming to run.
        """
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = cancel_event
            if self._optimizer_running >= self._max_optimizer:
                self._optimizer_queue.append((job_id, cancel_event, search_fn))
                return
            self._optimizer_running += 1
        self._dispatch(job_id, cancel_event, search_fn)

    def _dispatch(
        self, job_id: str, cancel_event: threading.Event, search_fn: SearchFn,
    ) -> None:
        future = self._executor.submit(self._run_search, job_id, cancel_event, search_fn)
        with self._lock:
            self._futures[job_id] = future

    def _run_search(
        self, job_id: str, cancel_event: threading.Event, search_fn: SearchFn,
    ) -> None:
        """Worker-thread body: mark running, run, persist, then free the slot."""
        try:
            self._db_call(self._mark_running(job_id))
            result = search_fn(cancel_event, lambda p: self._report(job_id, p))
        except Cancelled:
            self._db_call(self._mark_cancelled(job_id))
        except Exception as exc:
            logger.exception("Optimizer job %s failed", job_id)
            self._db_call(self._mark_failed(job_id, f"{type(exc).__name__}: {exc}"))
        else:
            top = _top_damage(result)
            self._db_call(self._mark_succeeded(job_id, result, top))
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)
                self._futures.pop(job_id, None)
                self._optimizer_running -= 1
                queued = self._optimizer_queue.popleft() if self._optimizer_queue else None
                if queued is not None:
                    self._optimizer_running += 1
            if queued is not None:
                self._dispatch(*queued)

    def _report(self, job_id: str, progress: SearchProgress) -> None:
        """Persist one progress snapshot. Called from the worker thread."""
        self._db_call(self._update_progress(job_id, progress, _eta(progress)))

    def submit(self, job_id: str, runner_fn: Callable, *args: Any, **kwargs: Any) -> None:
        """Submit a generic callable to the threadpool.

        Kept alongside `submit_search` because it is what the runner's own tests exercise —
        the queueing and cancellation machinery is worth testing without a database or a
        real search behind it.

        ``runner_fn`` is called with ``cancel_event`` as the first positional
        arg, followed by ``*args`` and ``**kwargs``.
        """
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = cancel_event

        future = self._executor.submit(
            self._wrap,
            job_id,
            cancel_event,
            runner_fn,
            args,
            kwargs,
        )
        with self._lock:
            self._futures[job_id] = future

    def cancel(self, job_id: str) -> None:
        """Request cancellation for a queued or running job.

        If the job is still sitting in an in-memory queue it is dropped so it
        never gets dispatched (and never consumes a concurrency slot). If it is
        already running, its cancel event is set so the worker stops at the next
        cooperative checkpoint and frees its slot for the next queued job.
        """
        with self._lock:
            event = self._cancel_events.get(job_id)
            removed = self._drop_from_queue(
                self._optimizer_queue, job_id
            ) or self._drop_from_queue(self._rank_queue, job_id)
            if removed:
                # A queued-then-cancelled job never executes, so its finally
                # block never runs — clean up its cancel event here.
                self._cancel_events.pop(job_id, None)
        if event is not None:
            event.set()

    @staticmethod
    def _drop_from_queue(queue: deque[tuple[str, threading.Event, Any]], job_id: str) -> bool:
        """Remove the entry for ``job_id`` from ``queue`` in place. Returns True if found.

        Rebuilds the deque rather than using ``deque.remove`` so we match on
        ``job_id`` alone and never invoke ``__eq__`` on the payload object.
        """
        kept = [entry for entry in queue if entry[0] != job_id]
        if len(kept) == len(queue):
            return False
        queue.clear()
        queue.extend(kept)
        return True

    def shutdown(self, *, wait: bool = False) -> None:
        """Shut down the executor."""
        self._executor.shutdown(wait=wait, cancel_futures=not wait)

    # ------------------------------------------------------------------
    # Internal — generic submit path (unit tests)

    def _wrap(
        self,
        job_id: str,
        cancel_event: threading.Event,
        runner_fn: Callable,
        args: tuple,
        kwargs: dict,
    ) -> None:
        try:
            runner_fn(cancel_event, *args, **kwargs)
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)
                self._futures.pop(job_id, None)

    # ------------------------------------------------------------------
    # Internal — optimizer job path

    def _db_call(self, coro: Coroutine) -> None:
        """Run an async coroutine on the main event loop from a worker thread."""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=30)

    async def _mark_running(self, job_id: str) -> None:
        async with self._session_factory() as session:  # type: ignore[misc]
            repo = OptimizationJobRepository(session)
            await repo.mark_running(job_id)

    async def _update_progress(self, job_id: str, p: SearchProgress, eta: float | None) -> None:
        async with self._session_factory() as session:  # type: ignore[misc]
            repo = OptimizationJobRepository(session)
            await repo.update_progress(
                job_id,
                combinations_done=p.combinations_done,
                combinations_total=p.combinations_total,
                evaluated=p.evaluated,
                rejected_by_sets=p.rejected_by_sets,
                rejected_by_stats=p.rejected_by_stats,
                elapsed_seconds=p.elapsed_seconds,
                eta_seconds=eta,
            )

    async def _mark_succeeded(self, job_id: str, result: dict, top_damage: float | None) -> None:
        async with self._session_factory() as session:  # type: ignore[misc]
            repo = OptimizationJobRepository(session)
            await repo.mark_succeeded(job_id, result=result, top_damage=top_damage)

    async def _mark_failed(self, job_id: str, error_message: str) -> None:
        async with self._session_factory() as session:  # type: ignore[misc]
            repo = OptimizationJobRepository(session)
            await repo.mark_failed(job_id, error_message=error_message)

    async def _mark_cancelled(self, job_id: str) -> None:
        async with self._session_factory() as session:  # type: ignore[misc]
            repo = OptimizationJobRepository(session)
            await repo.mark_cancelled(job_id)
