"""Integration tests for SQLAlchemy models — verifies schema, relationships, and basic CRUD."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.models.agent import Agent, AgentSkill, Attack, CoreSkill, Mindscape

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
from app.models.build import Build, Combo, EnemyProfile
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType
from app.models.team import Team
from app.models.w_engine import WEngine


@pytest.fixture
async def sample_agent(db_session: AsyncSession) -> Agent:
    agent = Agent(
        hakushin_id=9999,
        name="TestAgent",
        full_name="TestAgent Full",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        faction="Test Faction",
        faction_id=99,
        base_hp=600,
        base_atk=120,
        base_def=50,
        hp_growth=800000,
        atk_growth=50000,
        def_growth=60000,
        base_crit_rate=500,
        base_crit_dmg=5000,
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.fixture
async def sample_w_engine(db_session: AsyncSession) -> WEngine:
    engine = WEngine(
        hakushin_id=99999,
        name="Test W-Engine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=46,
        secondary_stat_type="crit_rate",
        secondary_stat_value=960,
        level_scaling={"level": {}, "stars": {}},
        passive_name="Test Passive",
        passive_descriptions={"1": "Test effect R1"},
        description="A test weapon",
    )
    db_session.add(engine)
    await db_session.flush()
    return engine


@pytest.fixture
async def sample_disc_set(db_session: AsyncSession) -> DiscSet:
    disc_set = DiscSet(
        hakushin_id=99999,
        name="Test Set",
        two_piece_text="CRIT Rate +8%",
        four_piece_text="ATK increases by 25%",
        two_piece_effects=[{"stat": "crit_rate", "value": 800, "is_conditional": False}],
        four_piece_effects=[{"stat": "atk_pct", "value": 2500, "is_conditional": True}],
    )
    db_session.add(disc_set)
    await db_session.flush()
    return disc_set


class TestAgentModel:
    async def test_create_agent(self, sample_agent: Agent) -> None:
        assert sample_agent.id is not None
        assert sample_agent.name == "TestAgent"
        assert sample_agent.element == Element.FIRE
        assert sample_agent.specialty == Specialty.ATTACK
        assert sample_agent.rarity == Rarity.S
        assert sample_agent.base_hp == 600
        assert sample_agent.base_atk == 120

    async def test_agent_unique_hakushin_id(
        self,
        db_session: AsyncSession,
        sample_agent: Agent,
    ) -> None:
        duplicate = Agent(
            hakushin_id=9999,
            name="Duplicate",
            element=Element.ICE,
            specialty=Specialty.STUN,
            rarity=Rarity.A,
        )
        nested = await db_session.begin_nested()
        db_session.add(duplicate)
        with pytest.raises(Exception):  # noqa: B017, PT011
            await db_session.flush()
        await nested.rollback()

    async def test_query_agent_by_hakushin_id(
        self,
        db_session: AsyncSession,
        sample_agent: Agent,
    ) -> None:
        result = await db_session.execute(select(Agent).where(Agent.hakushin_id == 9999))
        found = result.scalar_one()
        assert found.name == "TestAgent"
        assert found.id == sample_agent.id


class TestAgentSkillModel:
    async def test_create_skill(
        self,
        db_session: AsyncSession,
        sample_agent: Agent,
    ) -> None:
        skill = AgentSkill(
            agent_id=sample_agent.id,
            skill_key="Basic",
            name="Test Basic Attack",
            description="A test basic attack description",
        )
        db_session.add(skill)
        await db_session.flush()
        assert skill.id is not None
        assert skill.agent_id == sample_agent.id


class TestAttackModel:
    async def test_create_attack(
        self,
        db_session: AsyncSession,
        sample_agent: Agent,
    ) -> None:
        attack = Attack(
            agent_id=sample_agent.id,
            hakushin_skill_id=1234001,
            skill_key="Basic",
            name="1st Hit",
            hit_index=0,
            element=Element.FIRE,
            damage_base=3120,
            damage_growth=290,
            stun_base=1560,
            stun_growth=80,
            energy_gain=5620,
            anomaly_buildup=0,
        )
        db_session.add(attack)
        await db_session.flush()
        assert attack.id is not None
        assert attack.damage_base == 3120

    async def test_damage_at_level(
        self,
        db_session: AsyncSession,
        sample_agent: Agent,
    ) -> None:
        attack = Attack(
            agent_id=sample_agent.id,
            hakushin_skill_id=1234002,
            skill_key="Basic",
            name="Test Hit",
            hit_index=0,
            element=Element.FIRE,
            damage_base=10000,
            damage_growth=1000,
        )
        db_session.add(attack)
        await db_session.flush()

        calc = attack.damage_at_level
        assert calc(1) == pytest.approx(1.0)  # 10000 / 10000
        assert calc(2) == pytest.approx(1.1)  # (10000 + 1000) / 10000
        assert calc(12) == pytest.approx(2.1)  # (10000 + 11000) / 10000


class TestCoreSkillModel:
    async def test_create_core_skill(
        self,
        db_session: AsyncSession,
        sample_agent: Agent,
    ) -> None:
        core = CoreSkill(
            agent_id=sample_agent.id,
            hakushin_id=9999501,
            level=1,
            name="Core Passive: Test",
            description="Test passive description",
        )
        db_session.add(core)
        await db_session.flush()
        assert core.id is not None


class TestMindscapeModel:
    async def test_create_mindscape(
        self,
        db_session: AsyncSession,
        sample_agent: Agent,
    ) -> None:
        ms = Mindscape(
            agent_id=sample_agent.id,
            level=1,
            name="M1: Test Mindscape",
            description="Test mindscape effect",
        )
        db_session.add(ms)
        await db_session.flush()
        assert ms.id is not None
        assert ms.level == 1


class TestWEngineModel:
    async def test_create_w_engine(self, sample_w_engine: WEngine) -> None:
        assert sample_w_engine.id is not None
        assert sample_w_engine.name == "Test W-Engine"
        assert sample_w_engine.base_atk == 46
        assert sample_w_engine.secondary_stat_type == "crit_rate"

    async def test_w_engine_jsonb_fields(self, sample_w_engine: WEngine) -> None:
        assert sample_w_engine.passive_descriptions == {"1": "Test effect R1"}
        assert "level" in sample_w_engine.level_scaling
        assert "stars" in sample_w_engine.level_scaling


class TestDiscSetModel:
    async def test_create_disc_set(self, sample_disc_set: DiscSet) -> None:
        assert sample_disc_set.id is not None
        assert sample_disc_set.name == "Test Set"
        assert sample_disc_set.two_piece_text == "CRIT Rate +8%"

    async def test_disc_set_effects_jsonb(self, sample_disc_set: DiscSet) -> None:
        effects = sample_disc_set.two_piece_effects
        assert len(effects) == 1
        assert effects[0]["stat"] == "crit_rate"
        assert effects[0]["value"] == 800


class TestDiscModel:
    async def test_create_disc(
        self,
        db_session: AsyncSession,
        sample_disc_set: DiscSet,
    ) -> None:
        disc = Disc(
            disc_set_id=sample_disc_set.id,
            slot=DiscSlot.FOUR,
            rarity=Rarity.S,
            level=15,
            main_stat_type=StatType.CRIT_RATE,
            main_stat_value=2400,
            substats=[
                {"stat": "crit_dmg", "value": 480, "rolls": 1},
                {"stat": "atk_pct", "value": 300, "rolls": 1},
            ],
        )
        db_session.add(disc)
        await db_session.flush()
        assert disc.id is not None
        assert disc.substats[0]["stat"] == "crit_dmg"


class TestBuildModel:
    async def test_create_build(
        self,
        db_session: AsyncSession,
        sample_agent: Agent,
        sample_w_engine: WEngine,
    ) -> None:
        build = Build(
            agent_id=sample_agent.id,
            w_engine_id=sample_w_engine.id,
            mindscape_level=0,
            agent_level=60,
            skill_levels="12,12,12,12,12",
        )
        db_session.add(build)
        await db_session.flush()
        assert build.id is not None
        assert build.agent_level == 60


class TestTeamModel:
    async def test_create_team(
        self,
        db_session: AsyncSession,
        sample_agent: Agent,
        sample_w_engine: WEngine,
    ) -> None:
        builds = []
        for _ in range(3):
            b = Build(
                agent_id=sample_agent.id,
                w_engine_id=sample_w_engine.id,
            )
            db_session.add(b)
            builds.append(b)
        await db_session.flush()

        team = Team(
            name="Test Team",
            build1_id=builds[0].id,
            build2_id=builds[1].id,
            build3_id=builds[2].id,
        )
        db_session.add(team)
        await db_session.flush()
        assert team.id is not None


class TestEnemyProfileModel:
    async def test_create_enemy(self, db_session: AsyncSession) -> None:
        enemy = EnemyProfile(
            hakushin_id=88888,
            name="Test Boss",
            level=60,
            hp=50000,
            atk=500,
            defense=60,
            physical_res=0,
            fire_res=-2000,
            ice_res=1000,
            electric_res=0,
            ether_res=0,
            stun_threshold=1000,
            stun_dmg_taken_ratio=5000,
            rarity=3,
            tags="boss,fire_weakness",
        )
        db_session.add(enemy)
        await db_session.flush()
        assert enemy.id is not None
        assert enemy.fire_res == -2000
        assert enemy.ice_res == 1000


class TestComboModel:
    async def test_create_combo(
        self,
        db_session: AsyncSession,
        sample_agent: Agent,
        sample_w_engine: WEngine,
    ) -> None:
        build = Build(
            agent_id=sample_agent.id,
            w_engine_id=sample_w_engine.id,
        )
        db_session.add(build)
        await db_session.flush()

        team = Team(build1_id=build.id)
        db_session.add(team)
        await db_session.flush()

        combo = Combo(
            name="Basic Rotation",
            team_id=team.id,
            sequence=[
                {"attack_id": "fake-uuid-1", "label": "BA1"},
                {"attack_id": "fake-uuid-2", "label": "BA2"},
                {"attack_id": "fake-uuid-3", "label": "EX"},
            ],
            description="Standard 3-hit combo",
        )
        db_session.add(combo)
        await db_session.flush()
        assert combo.id is not None
        assert len(combo.sequence) == 3
