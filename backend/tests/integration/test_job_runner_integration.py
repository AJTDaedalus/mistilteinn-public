"""Integration tests for JobRunner ↔ optimizer pipeline ↔ DB (T3.2)."""

from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.optimization_job import OptimizationJob
from app.repositories.optimization_job import OptimizationJobRepository
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.damage_calculator import CritMode
from app.services.disc_optimizer import (
    DiscCandidate,
    OptimizerConstraints,
)
from app.services.job_runner import JobRunner
from app.services.modifiers import ActiveConditions, AttackScope, Condition
from app.services.optimizer_pipeline import ResolvedPayload

# ---------------------------------------------------------------------------
# Fixtures


@pytest.fixture
async def direct_session_factory(test_engine):
    """Session factory that creates committed sessions (no rollback pattern)."""
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def cleanup_jobs(direct_session_factory):
    """Delete all optimization_jobs rows after each test."""
    yield
    async with direct_session_factory() as session:
        await session.execute(delete(OptimizationJob))
        await session.commit()


def _make_minimal_payload() -> ResolvedPayload:
    """Minimal ResolvedPayload requiring no DB entities."""
    base = BuildSnapshot(agent_base_atk=900, wengine_base_atk=600, agent_element="ice")
    enemy = EnemySnapshot(level=60, base_def=50, element_res=0)
    step = ComboStep(
        label="BA1",
        attack_id="a1",
        attack_name="Basic",
        scope=AttackScope.BASIC,
        multiplier=10000,
        element="ice",
    )
    inventory = [
        DiscCandidate(disc_id=f"d{i}", slot=i, set_id=1, main_stat_type="atk", main_stat_value=0)
        for i in range(1, 7)
    ]
    return ResolvedPayload(
        scoring_base=base,
        scoring_snap=base,
        enemy_snap=enemy,
        all_step_lists=[[step]],
        inventory=inventory,
        disc_summary_map={},
        disc_set_modifiers={1: []},
        constraints=OptimizerConstraints(top_n=1),
        conditions=ActiveConditions(active={Condition.ALWAYS}),
        crit_mode=CritMode.EXPECTED,
        is_stunned=False,
        stun_dmg_mult=15000,
        combo_ids_ordered=["combo-1"],
        combo_id="combo-1",
        combo_name="Test Combo",
        agent_name="TestAgent",
        enemy_name="TestEnemy",
    )


async def _create_queued_job(factory) -> str:
    async with factory() as session:
        repo = OptimizationJobRepository(session)
        job = await repo.create(
            {
                "status": "queued",
                "request": {"combo_id": "combo-1"},
                "agent_name": "TestAgent",
                "enemy_name": "TestEnemy",
                "combo_name": "Test Combo",
            }
        )
        await session.commit()
        return str(job.id)


async def _get_job(factory, job_id: str) -> OptimizationJob | None:
    async with factory() as session:
        repo = OptimizationJobRepository(session)
        return await repo.get_by_id(job_id)


async def _poll_until_terminal(factory, job_id: str, timeout: float = 10.0) -> OptimizationJob:
    terminal = {"succeeded", "failed", "cancelled"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = await _get_job(factory, job_id)
        if job and job.status in terminal:
            return job
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Job {job_id} did not reach terminal state in {timeout}s")


# ---------------------------------------------------------------------------
# Tests


class TestJobRunnerIntegration:
    async def test_full_lifecycle(self, direct_session_factory):
        """Happy path: queued → running → succeeded; result + timestamps set."""
        loop = asyncio.get_running_loop()
        runner = JobRunner(max_workers=2, session_factory=direct_session_factory, loop=loop)

        job_id = await _create_queued_job(direct_session_factory)
        payload = _make_minimal_payload()

        runner.submit_optimizer_job(job_id, payload)
        job = await _poll_until_terminal(direct_session_factory, job_id)
        runner.shutdown(wait=True)

        assert job.status == "succeeded"
        assert job.result is not None
        assert "builds" in job.result
        assert job.top_damage is not None
        assert job.top_damage > 0
        assert job.started_at is not None
        assert job.finished_at is not None
        assert job.assignments_total >= 1
        assert job.evaluated >= 1

    async def test_failure_marks_failed(self, direct_session_factory):
        """If the optimizer pipeline raises, status becomes 'failed'."""
        loop = asyncio.get_running_loop()
        runner = JobRunner(max_workers=2, session_factory=direct_session_factory, loop=loop)

        job_id = await _create_queued_job(direct_session_factory)
        # Bad payload: empty inventory — optimizer completes with no builds,
        # but won't error. Use None combo_steps to force a crash.
        payload = _make_minimal_payload()
        # Replace all_step_lists with None to cause a TypeError in the pipeline.
        bad_payload = dataclasses.replace(payload, all_step_lists=None)  # type: ignore[arg-type]

        runner.submit_optimizer_job(job_id, bad_payload)
        job = await _poll_until_terminal(direct_session_factory, job_id)
        runner.shutdown(wait=True)

        assert job.status == "failed"
        assert job.error_message is not None

    async def test_cancel_during_run(self, direct_session_factory):
        """cancel() on a running job → status becomes 'cancelled'."""
        loop = asyncio.get_running_loop()
        runner = JobRunner(max_workers=2, session_factory=direct_session_factory, loop=loop)

        # Use a large inventory to give the optimizer time to be cancelled.
        base = BuildSnapshot(agent_base_atk=900, wengine_base_atk=600, agent_element="ice")
        enemy = EnemySnapshot(level=60, base_def=50, element_res=0)
        step = ComboStep(
            label="BA1",
            attack_id="a1",
            attack_name="Basic",
            scope=AttackScope.BASIC,
            multiplier=10000,
            element="ice",
        )
        # 5 discs per slot = 5^6 combos, gives many progress ticks. atk vs crit_rate
        # trade off in opposite directions so no disc dominates another — the Task 5e
        # Pareto layer (P1d) would otherwise collapse a single-dimension monotone
        # chain down to 1 survivor/slot and finish before the cancel fires.
        inventory = [
            DiscCandidate(
                disc_id=f"d{slot}_{i}",
                slot=slot,
                set_id=1,
                main_stat_type="atk",
                main_stat_value=i * 100,
                substats=[{"stat": "crit_rate", "value": (4 - i) * 100}],
            )
            for slot in range(1, 7)
            for i in range(5)
        ]
        payload = ResolvedPayload(
            scoring_base=base,
            scoring_snap=base,
            enemy_snap=enemy,
            all_step_lists=[[step]],
            inventory=inventory,
            disc_summary_map={},
            disc_set_modifiers={1: []},
            constraints=OptimizerConstraints(top_n=1),
            conditions=ActiveConditions(active={Condition.ALWAYS}),
            crit_mode=CritMode.EXPECTED,
            is_stunned=False,
            stun_dmg_mult=15000,
            combo_ids_ordered=["c1"],
            combo_id="c1",
            combo_name="Combo",
            agent_name="Agent",
            enemy_name="Enemy",
        )

        job_id = await _create_queued_job(direct_session_factory)
        runner.submit_optimizer_job(job_id, payload)

        # Give it a moment to start, then cancel.
        await asyncio.sleep(0.15)
        runner.cancel(job_id)

        job = await _poll_until_terminal(direct_session_factory, job_id, timeout=5.0)
        runner.shutdown(wait=True)

        assert job.status == "cancelled"
