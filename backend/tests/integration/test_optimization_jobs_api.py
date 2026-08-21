"""Integration tests for the async optimizer job API (T4.1 / T4.2 / T4.3)."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.database import get_db
from app.main import create_app
from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType, UserStatus
from app.models.user import User
from app.models.w_engine import WEngine
from app.repositories.optimization_job import OptimizationJobRepository
from tests.conftest import TEST_DATABASE_URL, make_session_for

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.optimization_job import OptimizationJob


# ---------------------------------------------------------------------------
# Fixtures


def _get_test_settings() -> Settings:
    return Settings(DATABASE_URL=TEST_DATABASE_URL, TESTING=True)


@pytest.fixture
async def mock_runner():
    return MagicMock()


@pytest.fixture
async def test_user(db_session) -> tuple[User, str]:
    """Create an approved user with a session; return (user, raw_token)."""
    from app.services.password import hash_password

    user = User(
        email=f"jobtest_{secrets.token_hex(4)}@test.example",
        label="Job Test",
        password_hash=hash_password("alpha-test-password-1234"),
        status=UserStatus.APPROVED,
    )
    db_session.add(user)
    await db_session.flush()
    raw_token = await make_session_for(user, db_session)
    return user, raw_token


@pytest.fixture
async def api_client(
    db_session,
    mock_runner,
    test_user,
) -> AsyncGenerator[AsyncClient, None]:
    """Client with a mocked JobRunner and a pre-authenticated approved user."""
    _, raw_token = test_user

    app = create_app()
    app.state.job_runner = mock_runner
    app.dependency_overrides[get_settings] = _get_test_settings

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {raw_token}"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seeding helper (minimal — one combo, small disc pool)


async def _seed(authed_client: AsyncClient, db_session: AsyncSession) -> dict:
    agent = Agent(
        hakushin_id=9300,
        name="JobAgent",
        element=Element.ICE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    engine = WEngine(
        hakushin_id=9301,
        name="JobEngine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=600,
    )
    enemy = EnemyProfile(name="JobDummy", level=60, defense=60, ice_res=0)
    disc_set = DiscSet(
        hakushin_id=9400,
        name="JobSet",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +15%",
    )
    db_session.add_all([agent, engine, enemy, disc_set])
    await db_session.flush()

    attack = Attack(
        agent_id=agent.id,
        hakushin_skill_id=200,
        skill_key="Basic",
        name="JobHit",
        hit_index=0,
        element=Element.ICE,
        damage_base=10000,
        damage_growth=0,
    )
    db_session.add(attack)
    await db_session.flush()

    build_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "JobBuild",
            "agent_id": str(agent.id),
            "w_engine_id": str(engine.id),
        },
    )
    build_id = build_resp.json()["id"]

    for slot in DiscSlot:
        d = Disc(
            disc_set_id=str(disc_set.id),
            rarity=Rarity.S,
            slot=slot,
            level=15,
            main_stat_type=StatType.ATK_PCT,
            main_stat_value=3000,
            substats=[],
            build_id=build_id,
        )
        db_session.add(d)
    await db_session.flush()

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "JobTeam", "build1_id": build_id},
    )
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "JobCombo",
            "team_id": team_id,
            "sequence": [{"attack_id": str(attack.id), "label": "BA1"}],
        },
    )

    return {
        "combo_id": combo_resp.json()["id"],
        "enemy_id": str(enemy.id),
    }


async def _seed_job(
    db_session: AsyncSession,
    status: str = "queued",
    job_type: str = "optimize",
    owner_id: str | None = None,
    result: dict | None = None,
) -> OptimizationJob:
    repo = OptimizationJobRepository(db_session, owner_id=owner_id)
    return await repo.create(
        {
            "status": status,
            "job_type": job_type,
            "request": {"combo_id": "test-combo"},
            "agent_name": "Agent",
            "enemy_name": "Enemy",
            "combo_name": "Combo",
            "result": result,
        }
    )


# ---------------------------------------------------------------------------
# T4.1 — POST /optimizer/discs → 202


class TestSubmitJob:
    async def test_returns_202_with_queued_summary(self, api_client, db_session, mock_runner):
        s = await _seed(api_client, db_session)
        resp = await api_client.post(
            "/api/v1/optimizer/discs",
            json={
                "combo_id": s["combo_id"],
                "enemy_profile_id": s["enemy_id"],
                "top_n": 1,
            },
        )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["status"] == "queued"
        assert data["agent_name"] == "JobAgent"
        assert data["enemy_name"] == "JobDummy"
        assert data["combo_name"] == "JobCombo"
        assert "id" in data

    async def test_submit_calls_runner(self, api_client, db_session, mock_runner):
        """submit_optimizer_job is called on the runner with a string job_id."""
        s = await _seed(api_client, db_session)
        resp = await api_client.post(
            "/api/v1/optimizer/discs",
            json={
                "combo_id": s["combo_id"],
                "enemy_profile_id": s["enemy_id"],
                "top_n": 1,
            },
        )
        assert resp.status_code == 202
        job_id = resp.json()["id"]
        mock_runner.submit_optimizer_job.assert_called_once()
        call_job_id = mock_runner.submit_optimizer_job.call_args[0][0]
        assert call_job_id == job_id

    async def test_invalid_combo_returns_404(self, api_client, db_session):
        enemy = EnemyProfile(name="JobDummy2", level=60, defense=60, ice_res=0)
        db_session.add(enemy)
        await db_session.flush()
        resp = await api_client.post(
            "/api/v1/optimizer/discs",
            json={
                "combo_id": "00000000-0000-0000-0000-000000000000",
                "enemy_profile_id": str(enemy.id),
                "top_n": 1,
            },
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Active-job cap (max 3 queued/running per user, combined optimize + rank)


class TestActiveJobLimit:
    async def test_rejects_when_three_active_jobs(self, api_client, db_session, test_user):
        user, _ = test_user
        s = await _seed(api_client, db_session)
        for _ in range(3):
            await _seed_job(db_session, status="queued", owner_id=str(user.id))
        await db_session.flush()

        resp = await api_client.post(
            "/api/v1/optimizer/discs",
            json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"], "top_n": 1},
        )
        assert resp.status_code == 429, resp.text

    async def test_running_and_queued_both_count(self, api_client, db_session, test_user):
        user, _ = test_user
        s = await _seed(api_client, db_session)
        await _seed_job(db_session, status="running", owner_id=str(user.id))
        await _seed_job(db_session, status="running", owner_id=str(user.id))
        await _seed_job(db_session, status="queued", owner_id=str(user.id))
        await db_session.flush()

        resp = await api_client.post(
            "/api/v1/optimizer/discs",
            json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"], "top_n": 1},
        )
        assert resp.status_code == 429, resp.text

    async def test_terminal_jobs_do_not_count(self, api_client, db_session, test_user):
        user, _ = test_user
        s = await _seed(api_client, db_session)
        for status in ("succeeded", "failed", "cancelled"):
            await _seed_job(db_session, status=status, owner_id=str(user.id))
        await _seed_job(db_session, status="queued", owner_id=str(user.id))
        await db_session.flush()

        resp = await api_client.post(
            "/api/v1/optimizer/discs",
            json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"], "top_n": 1},
        )
        assert resp.status_code == 202, resp.text

    async def test_other_users_jobs_do_not_count(self, api_client, db_session, test_user):
        from app.services.password import hash_password

        s = await _seed(api_client, db_session)
        # Three active jobs owned by a *different* user must not block this user.
        other = User(
            email=f"other_{secrets.token_hex(4)}@test.example",
            label="Other",
            password_hash=hash_password("alpha-test-password-1234"),
            status=UserStatus.APPROVED,
        )
        db_session.add(other)
        await db_session.flush()
        for _ in range(3):
            await _seed_job(db_session, status="running", owner_id=str(other.id))
        await db_session.flush()

        resp = await api_client.post(
            "/api/v1/optimizer/discs",
            json={"combo_id": s["combo_id"], "enemy_profile_id": s["enemy_id"], "top_n": 1},
        )
        assert resp.status_code == 202, resp.text


# ---------------------------------------------------------------------------
# T4.2 — GET /optimizer/jobs (list) and GET /optimizer/jobs/{id} (detail)


class TestListAndDetail:
    async def test_list_returns_all_jobs_desc(self, api_client, db_session, test_user):
        user, _ = test_user
        for status in ("queued", "running", "succeeded"):
            await _seed_job(db_session, status=status, owner_id=str(user.id))

        resp = await api_client.get("/api/v1/optimizer/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 3
        statuses = [j["status"] for j in data]
        assert "queued" in statuses
        assert "succeeded" in statuses

    async def test_list_filters_by_status(self, api_client, db_session, test_user):
        user, _ = test_user
        await _seed_job(db_session, status="queued", owner_id=str(user.id))
        await _seed_job(db_session, status="failed", owner_id=str(user.id))

        resp = await api_client.get("/api/v1/optimizer/jobs?status=queued")
        assert resp.status_code == 200
        data = resp.json()
        assert all(j["status"] == "queued" for j in data)

    async def test_list_filters_multiple_statuses(self, api_client, db_session, test_user):
        user, _ = test_user
        await _seed_job(db_session, status="queued", owner_id=str(user.id))
        await _seed_job(db_session, status="failed", owner_id=str(user.id))
        await _seed_job(db_session, status="succeeded", owner_id=str(user.id))

        resp = await api_client.get("/api/v1/optimizer/jobs?status=queued,failed")
        assert resp.status_code == 200
        data = resp.json()
        assert all(j["status"] in ("queued", "failed") for j in data)

    async def test_detail_returns_full_job(self, api_client, db_session, test_user):
        user, _ = test_user
        job = await _seed_job(db_session, status="succeeded", owner_id=str(user.id))
        resp = await api_client.get(f"/api/v1/optimizer/jobs/{job.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(job.id)
        assert data["status"] == "succeeded"
        assert "request" in data

    async def test_detail_404_on_unknown(self, api_client, db_session):
        resp = await api_client.get("/api/v1/optimizer/jobs/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_detail_surfaces_auto_prefilter_k(self, api_client, db_session, test_user):
        """Task 7: the auto-prefilter signal in the result blob is surfaced as a
        top-level field so the UI can show "fast mode auto-applied (K=N)" without
        parsing the nested result."""
        user, _ = test_user
        job = await _seed_job(
            db_session,
            status="succeeded",
            owner_id=str(user.id),
            result={"builds": [], "evaluated": 10, "auto_prefilter_k": 7},
        )
        resp = await api_client.get(f"/api/v1/optimizer/jobs/{job.id}")
        assert resp.status_code == 200
        assert resp.json()["auto_prefilter_k"] == 7

    async def test_detail_auto_prefilter_k_none_when_absent(
        self, api_client, db_session, test_user
    ):
        user, _ = test_user
        job = await _seed_job(
            db_session,
            status="succeeded",
            owner_id=str(user.id),
            result={"builds": [], "evaluated": 10},
        )
        resp = await api_client.get(f"/api/v1/optimizer/jobs/{job.id}")
        assert resp.status_code == 200
        assert resp.json()["auto_prefilter_k"] is None

    async def test_list_surfaces_auto_prefilter_k(self, api_client, db_session, test_user):
        user, _ = test_user
        await _seed_job(
            db_session,
            status="succeeded",
            owner_id=str(user.id),
            result={"builds": [], "evaluated": 10, "auto_prefilter_k": 9},
        )
        resp = await api_client.get("/api/v1/optimizer/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert any(j.get("auto_prefilter_k") == 9 for j in data)


# ---------------------------------------------------------------------------
# T4.3 — DELETE /optimizer/jobs/{id}


class TestDeleteJob:
    async def test_delete_succeeded_job_returns_204(
        self,
        api_client,
        db_session,
        test_user,
    ):
        user, _ = test_user
        job = await _seed_job(db_session, status="succeeded", owner_id=str(user.id))
        resp = await api_client.delete(f"/api/v1/optimizer/jobs/{job.id}")
        assert resp.status_code == 204

    async def test_delete_calls_cancel_on_runner(
        self,
        api_client,
        db_session,
        mock_runner,
        test_user,
    ):
        user, _ = test_user
        job = await _seed_job(db_session, status="running", owner_id=str(user.id))
        await api_client.delete(f"/api/v1/optimizer/jobs/{job.id}")
        mock_runner.cancel.assert_called_once_with(str(job.id))

    async def test_delete_removes_row_from_db(self, api_client, db_session, test_user):
        user, _ = test_user
        job = await _seed_job(db_session, status="queued", owner_id=str(user.id))
        resp = await api_client.delete(f"/api/v1/optimizer/jobs/{job.id}")
        assert resp.status_code == 204
        # Verify gone.
        resp2 = await api_client.get(f"/api/v1/optimizer/jobs/{job.id}")
        assert resp2.status_code == 404

    async def test_delete_404_on_unknown(self, api_client, db_session):
        unknown_id = "00000000-0000-0000-0000-000000000000"
        resp = await api_client.delete(f"/api/v1/optimizer/jobs/{unknown_id}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# R3.1 — job_type filter + job_type in summary response


class TestJobTypeFilter:
    async def test_job_type_rank_returns_only_rank_jobs(
        self,
        api_client,
        db_session,
        test_user,
    ):
        user, _ = test_user
        await _seed_job(db_session, job_type="optimize", owner_id=str(user.id))
        await _seed_job(db_session, job_type="rank", owner_id=str(user.id))

        resp = await api_client.get("/api/v1/optimizer/jobs?job_type=rank")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert all(j["job_type"] == "rank" for j in data)

    async def test_job_type_optimize_returns_only_optimize_jobs(
        self,
        api_client,
        db_session,
        test_user,
    ):
        user, _ = test_user
        await _seed_job(db_session, job_type="optimize", owner_id=str(user.id))
        await _seed_job(db_session, job_type="rank", owner_id=str(user.id))

        resp = await api_client.get("/api/v1/optimizer/jobs?job_type=optimize")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert all(j["job_type"] == "optimize" for j in data)

    async def test_no_job_type_param_returns_all(
        self,
        api_client,
        db_session,
        test_user,
    ):
        user, _ = test_user
        await _seed_job(db_session, job_type="optimize", owner_id=str(user.id))
        await _seed_job(db_session, job_type="rank", owner_id=str(user.id))

        resp = await api_client.get("/api/v1/optimizer/jobs")
        assert resp.status_code == 200
        data = resp.json()
        types = {j["job_type"] for j in data}
        assert "optimize" in types
        assert "rank" in types

    async def test_summary_includes_job_type(
        self,
        api_client,
        db_session,
        test_user,
    ):
        user, _ = test_user
        job = await _seed_job(db_session, job_type="rank", owner_id=str(user.id))
        resp = await api_client.get("/api/v1/optimizer/jobs")
        assert resp.status_code == 200
        matching = [j for j in resp.json() if j["id"] == str(job.id)]
        assert matching
        assert matching[0]["job_type"] == "rank"
