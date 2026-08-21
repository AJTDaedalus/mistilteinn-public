"""Integration tests for OptimizationJobRepository."""

import pytest

from app.repositories.optimization_job import OptimizationJobRepository


@pytest.fixture
async def repo(db_session):
    return OptimizationJobRepository(db_session)


@pytest.fixture
async def queued_job(repo):
    return await repo.create(
        {
            "status": "queued",
            "request": {"combo_id": "c1"},
            "agent_name": "Zhu Yuan",
            "enemy_name": "Metal Crab",
            "combo_name": "DPS Combo",
        }
    )


class TestOptimizationJobRepo:
    async def test_create_and_get(self, repo, queued_job):
        fetched = await repo.get_by_id(queued_job.id)
        assert fetched is not None
        assert fetched.status == "queued"
        assert fetched.agent_name == "Zhu Yuan"

    async def test_list_all(self, repo, queued_job):
        jobs = await repo.list()
        ids = [j.id for j in jobs]
        assert queued_job.id in ids

    async def test_list_filter_by_status(self, repo, queued_job):
        failed_job = await repo.create(
            {
                "status": "failed",
                "request": {},
                "agent_name": "Jane",
                "enemy_name": "Crab",
                "combo_name": "Combo",
            }
        )
        queued = await repo.list(status=["queued"])
        assert any(j.id == queued_job.id for j in queued)
        assert not any(j.id == failed_job.id for j in queued)

    async def test_mark_running(self, repo, db_session, queued_job):
        await repo.mark_running(queued_job.id)
        await db_session.refresh(queued_job)
        assert queued_job.status == "running"
        assert queued_job.started_at is not None

    async def test_update_progress(self, repo, db_session, queued_job):
        await repo.mark_running(queued_job.id)
        await repo.update_progress(
            queued_job.id,
            assignments_done=5,
            assignments_total=20,
            evaluated=1000,
            pruned_sets=10,
            pruned_stats=5,
            elapsed_seconds=2.5,
            eta_seconds=7.5,
        )
        await db_session.refresh(queued_job)
        assert queued_job.assignments_done == 5
        assert queued_job.assignments_total == 20
        assert queued_job.eta_seconds == 7.5

    async def test_mark_succeeded(self, repo, db_session, queued_job):
        await repo.mark_succeeded(
            queued_job.id,
            result={"builds": []},
            top_damage=12345.0,
        )
        await db_session.refresh(queued_job)
        assert queued_job.status == "succeeded"
        assert queued_job.top_damage == 12345.0
        assert queued_job.result == {"builds": []}
        assert queued_job.finished_at is not None

    async def test_mark_failed(self, repo, db_session, queued_job):
        await repo.mark_failed(queued_job.id, error_message="Something broke")
        await db_session.refresh(queued_job)
        assert queued_job.status == "failed"
        assert "Something broke" in queued_job.error_message
        assert queued_job.finished_at is not None

    async def test_mark_cancelled(self, repo, db_session, queued_job):
        await repo.mark_cancelled(queued_job.id)
        await db_session.refresh(queued_job)
        assert queued_job.status == "cancelled"
        assert queued_job.finished_at is not None

    async def test_sweep_orphans(self, repo, db_session):
        running = await repo.create({"status": "running", "request": {}})
        queued = await repo.create({"status": "queued", "request": {}})
        await repo.create({"status": "succeeded", "request": {}})
        count = await repo.sweep_orphans()
        assert count >= 2
        await db_session.refresh(running)
        await db_session.refresh(queued)
        assert running.status == "failed"
        assert queued.status == "failed"
        assert "Backend restarted" in running.error_message

    async def test_delete(self, repo, queued_job):
        deleted = await repo.delete(queued_job.id)
        assert deleted is True
        assert await repo.get_by_id(queued_job.id) is None
