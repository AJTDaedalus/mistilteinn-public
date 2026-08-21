"""Task A4 — post-reseed DB verification for F-14, F-30, F-15.

Requires the SEEDED app DB (not the isolated `fairy_test` DB used by the
`db_session` fixture). Run manually after `alembic upgrade head` +
`python -m scripts.seed_db`:

    docker compose exec backend python -m pytest \
        tests/integration/test_seed_math_review.py -v

Skips automatically when the seeded data is absent (matches the
`app_db` skip-if-no-DB pattern in test_zo_crossval.py).
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine as _app_engine
from app.models.agent import Agent
from app.models.build import EnemyProfile

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def app_db():
    """AsyncSession connected to the REAL seeded app DB (not the test DB)."""
    try:
        async with AsyncSession(_app_engine) as session:
            result = await session.execute(select(Agent).limit(1))
            if result.scalar_one_or_none() is None:
                pytest.skip("App DB has no agents — seeded DB required")
            yield session
    except Exception as exc:
        pytest.skip(f"App DB not reachable: {exc}")


class TestSeedMathReview:
    async def test_f14_pompey_fire_anomaly_capacity(self, app_db: AsyncSession) -> None:
        result = await app_db.execute(
            select(EnemyProfile).where(EnemyProfile.hakushin_id == 30021)
        )
        pompey = result.scalar_one()
        assert pompey.anomaly_capacity_fire == 3000

    async def test_f14_all_rarity4_bosses_have_boss_tier_gauges(
        self, app_db: AsyncSession
    ) -> None:
        normal_tier_values = (600, 720)
        result = await app_db.execute(
            select(EnemyProfile).where(EnemyProfile.rarity == 4)
        )
        rarity4_enemies = result.scalars().all()
        # A FLOOR, not an equality. The substantive assertion is the per-enemy gauge
        # check below; this only guards against the set silently emptying. As an equality
        # it rotted on every patch that shipped enemies — it read 26 and the 3.2.2 seed
        # made it 30 — and a rotted count teaches reviewers to edit the number rather
        # than read the failure. Growth is expected; shrinkage is the signal.
        assert len(rarity4_enemies) >= 26, (
            f"only {len(rarity4_enemies)} rarity-4 enemies — the set shrank, which no "
            f"patch should do"
        )

        for enemy in rarity4_enemies:
            gauges = [
                enemy.anomaly_capacity_physical,
                enemy.anomaly_capacity_fire,
                enemy.anomaly_capacity_ice,
                enemy.anomaly_capacity_electric,
                enemy.anomaly_capacity_ether,
                enemy.anomaly_capacity_wind,
            ]
            assert not any(g in normal_tier_values for g in gauges), (
                f"{enemy.name} (hakushin_id={enemy.hakushin_id}) has a "
                f"normal-tier anomaly gauge: {gauges}"
            )

    async def test_f30_promotion_stats_populated_for_all_agents(
        self, app_db: AsyncSession
    ) -> None:
        total = await app_db.scalar(select(func.count()).select_from(Agent))
        non_null = await app_db.scalar(
            select(func.count())
            .select_from(Agent)
            .where(Agent.promotion_stats.is_not(None))
        )
        # A FLOOR, for the same reason as f14 above: the roster only grows, and the
        # substantive assertion is the second line — EVERY agent has promotion_stats,
        # whatever the roster size. Frozen at 58, this failed the moment two agents
        # shipped.
        assert total >= 58, f"roster is {total} — it shrank, which no patch should do"
        assert non_null == total

    async def test_f30_agent_1221_tier6_matches_source(self, app_db: AsyncSession) -> None:
        result = await app_db.execute(select(Agent).where(Agent.hakushin_id == 1221))
        yanagi = result.scalar_one()
        tier6 = yanagi.promotion_stats[5]
        assert tier6 == {"hp": 2149, "atk": 224, "def": 169}

    async def test_f15_stun_threshold_from_stun_field(self, app_db: AsyncSession) -> None:
        result = await app_db.execute(
            select(EnemyProfile).where(EnemyProfile.hakushin_id == 30021)
        )
        pompey = result.scalar_one()
        assert pompey.stun_threshold == 6762

        result = await app_db.execute(
            select(EnemyProfile).where(EnemyProfile.hakushin_id == 300211)
        )
        notorious_pompey = result.scalar_one()
        assert notorious_pompey.stun_threshold == 7084

    async def test_f15_stun_threshold_not_zero_across_the_board(
        self, app_db: AsyncSession
    ) -> None:
        total = await app_db.scalar(select(func.count()).select_from(EnemyProfile))
        zero_stun = await app_db.scalar(
            select(func.count())
            .select_from(EnemyProfile)
            .where(EnemyProfile.stun_threshold == 0)
        )
        # A handful of rarity-1 non-combat mobs (Bangboos, drones, training
        # dummies) legitimately have no stun gauge; the bulk must be non-zero.
        assert zero_stun < total * 0.1
