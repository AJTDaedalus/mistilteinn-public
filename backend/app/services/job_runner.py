"""JobRunner — bounded threadpool executor for async optimizer jobs.

Submits CPU-bound search tasks to a dedicated ThreadPoolExecutor so they
run off the async event loop. Provides cooperative cancellation via
per-job threading.Events and DB persistence via run_coroutine_threadsafe.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from app.repositories.optimization_job import OptimizationJobRepository
from app.services.disc_optimizer import OptimizerCancelled, OptimizerProgress
from app.services.disc_ranker import RankCancelled, RankProgress
from app.services.optimizer_pipeline import run_optimizer_pipeline_with_progress
from app.services.rank_pipeline import run_rank_pipeline_with_progress

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.optimizer_pipeline import ResolvedPayload

logger = logging.getLogger(__name__)

PROGRESS_WRITE_INTERVAL_S = 0.5


async def run_orphan_sweep(session_factory: async_sessionmaker) -> int:
    """Mark any queued/running jobs as failed (called on startup)."""
    async with session_factory() as session:
        repo = OptimizationJobRepository(session)
        count = await repo.sweep_orphans()
    if count:
        logger.warning("Orphan sweep: marked %d stale job(s) as failed", count)
    return count


def _eta(p: OptimizerProgress) -> float | None:
    """ETA in seconds per §Q6 formula; None during warmup."""
    threshold = max(3, math.ceil(p.assignments_total * 0.05))
    if p.assignments_done < threshold or p.assignments_done == 0:
        return None
    return p.elapsed_seconds * (p.assignments_total - p.assignments_done) / p.assignments_done


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

    def submit(self, job_id: str, runner_fn: Callable, *args: Any, **kwargs: Any) -> None:
        """Submit a generic callable to the threadpool (used by unit tests).

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

    def submit_optimizer_job(self, job_id: str, payload: ResolvedPayload) -> None:
        """Submit an optimizer job with full DB lifecycle management.

        If the per-kind concurrency cap is reached the job is held in an
        in-memory queue; it stays ``queued`` in the DB until the running job
        completes and the next one is dispatched automatically.
        """
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = cancel_event
            if self._optimizer_running < self._max_optimizer:
                self._optimizer_running += 1
                future = self._executor.submit(
                    self._execute_optimizer, job_id, cancel_event, payload
                )
                self._futures[job_id] = future
            else:
                self._optimizer_queue.append((job_id, cancel_event, payload))

    def submit_rank_job(self, job_id: str, payload: Any) -> None:
        """Submit a rank job with full DB lifecycle management.

        Same queuing semantics as ``submit_optimizer_job`` but with a
        separate concurrency cap so rank and optimizer jobs don't share slots.
        """
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = cancel_event
            if self._rank_running < self._max_rank:
                self._rank_running += 1
                future = self._executor.submit(self._execute_rank, job_id, cancel_event, payload)
                self._futures[job_id] = future
            else:
                self._rank_queue.append((job_id, cancel_event, payload))

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

    async def _update_progress(self, job_id: str, p: OptimizerProgress, eta: float | None) -> None:
        async with self._session_factory() as session:  # type: ignore[misc]
            repo = OptimizationJobRepository(session)
            await repo.update_progress(
                job_id,
                assignments_done=p.assignments_done,
                assignments_total=p.assignments_total,
                evaluated=p.evaluated,
                pruned_sets=p.pruned_sets,
                pruned_stats=p.pruned_stats,
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

    def _execute_optimizer(
        self,
        job_id: str,
        cancel_event: threading.Event,
        payload: ResolvedPayload,
    ) -> None:
        try:
            self._db_call(self._mark_running(job_id))

            last_write_at = [0.0]

            def cb(p: OptimizerProgress) -> None:
                if cancel_event.is_set():
                    raise OptimizerCancelled  # noqa: TRY301
                now = time.perf_counter()
                if (
                    now - last_write_at[0] < PROGRESS_WRITE_INTERVAL_S
                    and p.assignments_done < p.assignments_total
                ):
                    return
                last_write_at[0] = now
                self._db_call(self._update_progress(job_id, p, _eta(p)))

            response = run_optimizer_pipeline_with_progress(payload, cb)
            top_damage = response.builds[0].total_damage if response.builds else None
            self._db_call(self._mark_succeeded(job_id, response.model_dump(), top_damage))

        except OptimizerCancelled:
            self._db_call(self._mark_cancelled(job_id))
        except Exception:
            logger.exception("Optimizer job %s failed", job_id)
            err = repr(sys.exc_info()[1])[:2000]
            self._db_call(self._mark_failed(job_id, err))
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)
                self._futures.pop(job_id, None)
                self._optimizer_running -= 1
                if self._optimizer_queue:
                    next_id, next_cancel, next_payload = self._optimizer_queue.popleft()
                    self._optimizer_running += 1
                    try:
                        future = self._executor.submit(
                            self._execute_optimizer, next_id, next_cancel, next_payload
                        )
                        self._futures[next_id] = future
                    except RuntimeError:
                        # Executor is shutting down; queued job won't run this
                        # session.  Orphan sweep on next startup will recover it.
                        self._optimizer_running -= 1

    # ------------------------------------------------------------------
    # Internal — rank job path

    async def _update_rank_progress(self, job_id: str, p: RankProgress) -> None:
        eta = (
            p.elapsed_seconds * (p.discs_total - p.discs_done) / p.discs_done
            if p.discs_done > 0
            else None
        )
        async with self._session_factory() as session:  # type: ignore[misc]
            repo = OptimizationJobRepository(session)
            await repo.update_progress(
                job_id,
                assignments_done=p.discs_done,
                assignments_total=p.discs_total,
                evaluated=p.discs_done,
                pruned_sets=0,
                pruned_stats=0,
                elapsed_seconds=p.elapsed_seconds,
                eta_seconds=eta,
            )

    def _execute_rank(
        self,
        job_id: str,
        cancel_event: threading.Event,
        payload: Any,
    ) -> None:
        try:
            self._db_call(self._mark_running(job_id))

            last_write_at = [0.0]

            def cb(p: RankProgress) -> None:
                if cancel_event.is_set():
                    raise RankCancelled  # noqa: TRY301
                now = time.perf_counter()
                if (
                    now - last_write_at[0] < PROGRESS_WRITE_INTERVAL_S
                    and p.discs_done < p.discs_total
                ):
                    return
                last_write_at[0] = now
                self._db_call(self._update_rank_progress(job_id, p))

            result_list = run_rank_pipeline_with_progress(
                payload, cb, max_workers=max(1, (os.cpu_count() or 2) // 2)
            )
            self._db_call(self._mark_succeeded(job_id, {"discs": result_list}, None))

        except RankCancelled:
            self._db_call(self._mark_cancelled(job_id))
        except Exception:
            logger.exception("Rank job %s failed", job_id)
            err = repr(sys.exc_info()[1])[:2000]
            self._db_call(self._mark_failed(job_id, err))
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)
                self._futures.pop(job_id, None)
                self._rank_running -= 1
                if self._rank_queue:
                    next_id, next_cancel, next_payload = self._rank_queue.popleft()
                    self._rank_running += 1
                    try:
                        future = self._executor.submit(
                            self._execute_rank, next_id, next_cancel, next_payload
                        )
                        self._futures[next_id] = future
                    except RuntimeError:
                        # Executor is shutting down; queued job won't run this
                        # session.  Orphan sweep on next startup will recover it.
                        self._rank_running -= 1
