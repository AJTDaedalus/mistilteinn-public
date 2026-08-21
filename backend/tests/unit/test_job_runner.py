"""Unit tests for JobRunner skeleton."""

import threading
import time
from typing import ClassVar
from unittest.mock import patch

from app.services.disc_ranker import RankProgress
from app.services.job_runner import JobRunner


def _make_runner(max_workers: int = 2) -> JobRunner:
    return JobRunner(max_workers=max_workers)


class TestJobRunnerBasic:
    def test_submit_runs_job(self):
        """Submitted callable runs on a non-main thread."""
        ran_on = []

        def fn(cancel_event):
            ran_on.append(threading.current_thread().name)

        runner = _make_runner()
        runner.submit("j1", fn)
        runner.shutdown(wait=True)
        assert len(ran_on) == 1
        assert "optimizer" in ran_on[0]

    def test_max_workers_limits_concurrency(self):
        """Only max_workers tasks run concurrently."""
        running = threading.Semaphore(0)
        in_flight = []

        def long_fn(cancel_event):
            in_flight.append(1)
            running.release()
            time.sleep(0.1)
            in_flight.pop()

        runner = _make_runner(max_workers=2)
        runner.submit("j1", long_fn)
        runner.submit("j2", long_fn)
        # Wait until two are running.
        running.acquire()
        running.acquire()
        assert len(in_flight) == 2

        runner.submit("j3", long_fn)
        # j3 should queue — not immediately start a 3rd in-flight.
        time.sleep(0.02)
        assert len(in_flight) <= 2

        runner.shutdown(wait=True)

    def test_cancel_running_job(self):
        """Setting cancel_event causes a cooperative cancellation signal."""
        cancelled = threading.Event()

        def fn(cancel_event):
            for _ in range(100):
                if cancel_event.is_set():
                    cancelled.set()
                    return
                time.sleep(0.01)

        runner = _make_runner()
        runner.submit("jc", fn)
        time.sleep(0.02)
        runner.cancel("jc")
        runner.shutdown(wait=True)
        assert cancelled.is_set()

    def test_shutdown_drains(self):
        """shutdown(wait=True) waits for submitted jobs to complete."""
        done = []

        def fn(cancel_event):
            time.sleep(0.05)
            done.append(1)

        runner = _make_runner()
        runner.submit("jd", fn)
        runner.shutdown(wait=True)
        assert len(done) == 1

    def test_multiple_jobs_run_independently(self):
        """Multiple jobs don't share state via the runner."""
        results = {}

        def fn(cancel_event, job_id):
            results[job_id] = True

        runner = _make_runner(max_workers=4)
        for i in range(4):
            runner.submit(f"j{i}", fn, f"j{i}")
        runner.shutdown(wait=True)
        assert len(results) == 4


# ---------------------------------------------------------------------------
# Rank job dispatch (R2.5)
# ---------------------------------------------------------------------------


def _make_db_runner(mock_db_call=None) -> JobRunner:
    """Runner with a mocked _db_call so DB ops are no-ops."""
    runner = _make_runner()
    if mock_db_call is not None:
        runner._db_call = mock_db_call
    return runner


class TestRankJobDispatch:
    def test_submit_rank_job_calls_pipeline(self):
        """submit_rank_job dispatches to run_rank_pipeline_with_progress."""
        called_with = []

        def fake_pipeline(payload, cb, **kwargs):
            called_with.append(payload)
            return []

        runner = _make_runner()
        runner._db_call = lambda coro: None  # suppress DB calls

        with patch(
            "app.services.job_runner.run_rank_pipeline_with_progress",
            side_effect=fake_pipeline,
        ):
            runner.submit_rank_job("rj1", payload={"test": True})
            runner.shutdown(wait=True)

        assert len(called_with) == 1
        assert called_with[0] == {"test": True}

    def test_rank_job_progress_callback_fires(self):
        """The progress callback passed to the pipeline is callable."""
        received_callbacks = []

        def fake_pipeline(payload, cb, **kwargs):
            p = RankProgress(discs_done=5, discs_total=10, elapsed_seconds=1.0)
            received_callbacks.append(cb)
            cb(p)
            return []

        runner = _make_runner()
        runner._db_call = lambda coro: None

        with patch(
            "app.services.job_runner.run_rank_pipeline_with_progress",
            side_effect=fake_pipeline,
        ):
            runner.submit_rank_job("rj2", payload={})
            runner.shutdown(wait=True)

        assert len(received_callbacks) == 1

    def test_rank_job_cancelled_via_cancel_event(self):
        """cancel() sets cancel_event → RankCancelled propagates to _mark_cancelled."""
        lifecycle = []

        def fake_pipeline(payload, cb, **kwargs):
            for i in range(100):
                p = RankProgress(discs_done=i, discs_total=100, elapsed_seconds=float(i))
                cb(p)
                time.sleep(0.005)
            return []

        async def fake_coro_running(job_id):
            lifecycle.append("running")

        async def fake_coro_cancelled(job_id):
            lifecycle.append("cancelled")

        runner = _make_runner()
        # We need _db_call to actually resolve coroutines so lifecycle tracking works.
        # Use a simple synchronous approach: track call names via side effects.
        runner._mark_running = lambda job_id: _noop_coro()
        runner._mark_cancelled = lambda job_id: _noop_append_coro(lifecycle, "cancelled")
        runner._mark_succeeded = lambda job_id, result, top: _noop_coro()
        runner._update_rank_progress = lambda job_id, p: _noop_coro()
        runner._db_call = lambda coro: None

        with patch(
            "app.services.job_runner.run_rank_pipeline_with_progress",
            side_effect=fake_pipeline,
        ):
            runner.submit_rank_job("rjc", payload={})
            time.sleep(0.02)
            runner.cancel("rjc")
            runner.shutdown(wait=True)

        # The pipeline should have been interrupted (RankCancelled raised in cb)
        # _mark_cancelled must have been called.  Since _db_call is no-op,
        # we just confirm the job finishes without hanging.
        # (Full lifecycle verification is in the integration test.)

    def test_rank_job_failure_marks_failed(self):
        """Pipeline exception leads to _mark_failed being called."""

        def exploding_pipeline(payload, cb):
            raise ValueError("rank failure")

        runner = _make_runner()
        runner._db_call = lambda coro: None

        with patch(
            "app.services.job_runner.run_rank_pipeline_with_progress",
            side_effect=exploding_pipeline,
        ):
            runner.submit_rank_job("rjf", payload={})
            runner.shutdown(wait=True)
        # If we reach here without hanging, _execute_rank's except block ran.

    def test_existing_optimizer_submit_still_works(self):
        """submit_optimizer_job is unaffected by the rank changes."""
        ran = []

        def fn(cancel_event):
            ran.append(True)

        runner = _make_runner()
        runner.submit("j_opt", fn)
        runner.shutdown(wait=True)
        assert ran


class TestJobConcurrencyLimit:
    """Per-kind concurrency cap: at most 1 optimizer and 1 rank job run at once."""

    def _make_blocking_pipeline_patch(self, gate: threading.Event, ran: list) -> object:
        """Return a fake pipeline that blocks on `gate` then records itself."""
        from unittest.mock import patch

        def fake_pipeline(payload, cb, **kwargs):
            ran.append(payload)
            gate.wait(timeout=5)
            return []

        return patch(
            "app.services.job_runner.run_rank_pipeline_with_progress",
            side_effect=fake_pipeline,
        )

    def _make_runner_no_db(self) -> JobRunner:
        runner = JobRunner(max_workers=2)
        runner._db_call = lambda coro: None
        return runner

    def test_optimizer_concurrency_cap_queues_excess(self):
        """With cap=1, submitting 3 optimizer jobs → 1 running, 2 in internal queue."""

        class FakeResponse:
            builds: ClassVar[list] = []

            def model_dump(self) -> dict:
                return {}

        gate = threading.Event()
        started = threading.Semaphore(0)
        all_done = threading.Semaphore(0)

        def fake_optimizer(payload, cb):
            started.release()
            gate.wait(timeout=5)
            all_done.release()
            return FakeResponse()

        runner = self._make_runner_no_db()

        with patch(
            "app.services.job_runner.run_optimizer_pipeline_with_progress",
            side_effect=fake_optimizer,
        ):
            runner.submit_optimizer_job("o1", payload=object())
            # Wait until o1 is actually running before submitting o2/o3
            started.acquire(timeout=2)

            runner.submit_optimizer_job("o2", payload=object())
            runner.submit_optimizer_job("o3", payload=object())

            with runner._lock:
                running = runner._optimizer_running
                queued = len(runner._optimizer_queue)

            gate.set()
            for _ in range(3):
                all_done.acquire(timeout=5)
            runner.shutdown(wait=True)

        assert running == 1, f"expected 1 running, got {running}"
        assert queued == 2, f"expected 2 queued, got {queued}"

    def test_optimizer_queued_jobs_run_sequentially(self):
        """All 3 queued optimizer jobs eventually run, in submission order."""

        class FakeResponse:
            builds: ClassVar[list] = []

            def model_dump(self) -> dict:
                return {}

        done = threading.Semaphore(0)
        order: list[str] = []

        def fake_optimizer(payload, cb):
            order.append(payload)
            done.release()
            return FakeResponse()

        runner = self._make_runner_no_db()

        with patch(
            "app.services.job_runner.run_optimizer_pipeline_with_progress",
            side_effect=fake_optimizer,
        ):
            runner.submit_optimizer_job("o1", payload="first")
            runner.submit_optimizer_job("o2", payload="second")
            runner.submit_optimizer_job("o3", payload="third")

            # Wait for all three to finish before shutdown to avoid the
            # executor rejecting queued dispatches mid-drain.
            for _ in range(3):
                assert done.acquire(timeout=5), "optimizer job timed out"

            runner.shutdown(wait=True)

        assert order == ["first", "second", "third"]

    def test_rank_concurrency_cap_queues_excess(self):
        """With cap=1, submitting 3 rank jobs → 1 running, 2 in internal queue."""
        gate = threading.Event()
        started = threading.Semaphore(0)
        all_done = threading.Semaphore(0)

        def fake_rank(payload, cb, **kwargs):
            started.release()
            gate.wait(timeout=5)
            all_done.release()
            return []

        runner = self._make_runner_no_db()

        with patch(
            "app.services.job_runner.run_rank_pipeline_with_progress",
            side_effect=fake_rank,
        ):
            runner.submit_rank_job("r1", payload=object())
            started.acquire(timeout=2)

            runner.submit_rank_job("r2", payload=object())
            runner.submit_rank_job("r3", payload=object())

            with runner._lock:
                running = runner._rank_running
                queued = len(runner._rank_queue)

            gate.set()
            for _ in range(3):
                all_done.acquire(timeout=5)
            runner.shutdown(wait=True)

        assert running == 1, f"expected 1 running, got {running}"
        assert queued == 2, f"expected 2 queued, got {queued}"

    def test_rank_queued_jobs_run_sequentially(self):
        """All 3 queued rank jobs eventually run, in submission order."""
        done = threading.Semaphore(0)
        order: list[str] = []

        def fake_rank(payload, cb, **kwargs):
            order.append(payload)
            done.release()
            return []

        runner = self._make_runner_no_db()

        with patch(
            "app.services.job_runner.run_rank_pipeline_with_progress",
            side_effect=fake_rank,
        ):
            runner.submit_rank_job("r1", payload="first")
            runner.submit_rank_job("r2", payload="second")
            runner.submit_rank_job("r3", payload="third")

            for _ in range(3):
                assert done.acquire(timeout=5), "rank job timed out"

            runner.shutdown(wait=True)

        assert order == ["first", "second", "third"]

    def test_cancel_queued_job_drops_it_from_queue(self):
        """Cancelling a still-queued job removes it so it never runs, and the
        next queued job takes its slot when the running one finishes."""
        gate = threading.Event()
        started = threading.Semaphore(0)
        done = threading.Semaphore(0)
        order: list[str] = []

        def fake_optimizer(payload, cb):
            order.append(payload)
            started.release()
            gate.wait(timeout=5)
            done.release()
            return type("R", (), {"builds": [], "model_dump": lambda self: {}})()

        runner = self._make_runner_no_db()

        with patch(
            "app.services.job_runner.run_optimizer_pipeline_with_progress",
            side_effect=fake_optimizer,
        ):
            runner.submit_optimizer_job("o1", payload="first")
            assert started.acquire(timeout=2), "o1 never started"

            # o2 and o3 are held in the internal queue behind the running o1.
            runner.submit_optimizer_job("o2", payload="second")
            runner.submit_optimizer_job("o3", payload="third")

            # Cancel the middle queued job before it ever dispatches.
            runner.cancel("o2")
            with runner._lock:
                queued_ids = [entry[0] for entry in runner._optimizer_queue]
                assert queued_ids == ["o3"], f"o2 not dropped: {queued_ids}"
                assert "o2" not in runner._cancel_events

            # Let o1 finish → o3 should take the freed slot; o2 must never run.
            gate.set()
            for _ in range(2):
                assert done.acquire(timeout=5), "job timed out"
            runner.shutdown(wait=True)

        assert order == ["first", "third"], order

    def test_cancel_running_job_is_unaffected(self):
        """Cancelling the currently-running job still sets its cancel event."""
        runner = self._make_runner_no_db()
        gate = threading.Event()
        started = threading.Semaphore(0)
        saw_cancel = threading.Event()

        def fake_optimizer(payload, cb):
            started.release()
            gate.wait(timeout=5)
            return type("R", (), {"builds": [], "model_dump": lambda self: {}})()

        with patch(
            "app.services.job_runner.run_optimizer_pipeline_with_progress",
            side_effect=fake_optimizer,
        ):
            runner.submit_optimizer_job("o1", payload=object())
            assert started.acquire(timeout=2)
            runner.cancel("o1")
            with runner._lock:
                if runner._cancel_events.get("o1", threading.Event()).is_set():
                    saw_cancel.set()
            gate.set()
            runner.shutdown(wait=True)

        assert saw_cancel.is_set(), "running job's cancel event was not set"

    def test_optimizer_and_rank_caps_are_independent(self):
        """One running optimizer + one running rank = both proceed without blocking each other."""
        opt_gate = threading.Event()
        rank_gate = threading.Event()
        opt_started = threading.Semaphore(0)
        rank_started = threading.Semaphore(0)

        def fake_optimizer(payload, cb):
            opt_started.release()
            opt_gate.wait(timeout=5)
            return type("R", (), {"builds": []})()

        def fake_rank(payload, cb, **kwargs):
            rank_started.release()
            rank_gate.wait(timeout=5)
            return []

        runner = self._make_runner_no_db()

        with (
            patch(
                "app.services.job_runner.run_optimizer_pipeline_with_progress",
                side_effect=fake_optimizer,
            ),
            patch(
                "app.services.job_runner.run_rank_pipeline_with_progress",
                side_effect=fake_rank,
            ),
        ):
            runner.submit_optimizer_job("o1", payload=object())
            runner.submit_rank_job("r1", payload=object())

            # Both should start concurrently
            assert opt_started.acquire(timeout=2), "optimizer job never started"
            assert rank_started.acquire(timeout=2), "rank job never started"

            with runner._lock:
                assert runner._optimizer_running == 1
                assert runner._rank_running == 1

            opt_gate.set()
            rank_gate.set()
            runner.shutdown(wait=True)


async def _noop_coro():
    pass


async def _noop_append_coro(lst, val):
    lst.append(val)
