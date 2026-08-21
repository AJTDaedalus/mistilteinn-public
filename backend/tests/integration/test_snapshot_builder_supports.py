"""Integration tests for snapshot_builder Phase 2: support build gear propagation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from app.models.agent import Agent
from app.models.build import Build
from app.models.enums import Element, Rarity, Specialty
from app.models.w_engine import WEngine
from app.repositories.build import BuildRepository
from app.services.modifiers import Modifier, ModifierSource, ModifierTarget
from app.services.snapshot_builder import build_snapshot_from_db

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def agent(db_session: AsyncSession) -> Agent:
    a = Agent(
        hakushin_id=11000,
        name="DPS",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_hp=800,
        base_atk=150,
        base_def=60,
        hp_growth=500000,
        atk_growth=40000,
        def_growth=50000,
        base_crit_rate=500,
        base_crit_dmg=5000,
    )
    db_session.add(a)
    await db_session.flush()
    return a


@pytest.fixture
async def support_agent(db_session: AsyncSession) -> Agent:
    a = Agent(
        hakushin_id=11001,
        name="Support",
        element=Element.ICE,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.S,
        base_hp=700,
        base_atk=120,
        base_def=55,
        hp_growth=450000,
        atk_growth=35000,
        def_growth=45000,
        base_crit_rate=500,
        base_crit_dmg=5000,
    )
    db_session.add(a)
    await db_session.flush()
    return a


@pytest.fixture
async def support_wengine(db_session: AsyncSession) -> WEngine:
    w = WEngine(
        hakushin_id=11002,
        name="Support Engine",
        rarity=Rarity.S,
        specialty=Specialty.SUPPORT,
        base_atk=40,
    )
    db_session.add(w)
    await db_session.flush()
    return w


def _make_team_mod(stat: str, value: int) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.WENGINE_PASSIVE,
        source_label="Team Buff",
        target=ModifierTarget.TEAM,
    )


def _make_self_mod(stat: str, value: int) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.CORE_SKILL,
        source_label="Core A",
        target=ModifierTarget.SELF,
    )


def _make_mc_mod(mc_level: int, stat: str, value: int) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.MINDSCAPE,
        source_label=f"M{mc_level}: Kit",
        target=ModifierTarget.TEAM,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSnapshotBuilderSupports:
    async def test_no_supports_baseline(
        self,
        db_session: AsyncSession,
        agent: Agent,
    ):
        """DPS with no supports uses no extra modifiers from support slot."""
        build = Build(agent_id=agent.id)
        db_session.add(build)
        await db_session.flush()

        repo = BuildRepository(db_session)
        full_build = await repo.get_by_id(build.id)
        assert full_build is not None

        with patch(
            "app.services.snapshot_builder.load_agent_modifiers",
            return_value=[],
        ):
            snap = build_snapshot_from_db(full_build, agent)

        assert snap.modifiers == []

    async def test_support_team_wengine_mod_included(
        self,
        db_session: AsyncSession,
        agent: Agent,
        support_agent: Agent,
        support_wengine: WEngine,
    ):
        """Support W-Engine target=team modifier propagates to DPS snapshot."""
        sup_build = Build(
            agent_id=support_agent.id,
            w_engine_id=support_wengine.id,
            w_engine_level=60,
            w_engine_refinement=1,
        )
        dps_build = Build(agent_id=agent.id)
        db_session.add_all([sup_build, dps_build])
        await db_session.flush()

        repo = BuildRepository(db_session)
        full_dps = await repo.get_by_id(dps_build.id)
        full_sup = await repo.get_by_id(sup_build.id)
        assert full_dps is not None
        assert full_sup is not None

        team_buff = _make_team_mod("atk_pct", 1000)
        with (
            patch("app.services.snapshot_builder.load_agent_modifiers", return_value=[]),
            patch(
                "app.services.snapshot_builder.load_wengine_modifiers",
                return_value=[team_buff],
            ),
        ):
            snap = build_snapshot_from_db(full_dps, agent, support_builds=[full_sup])

        assert any(m.stat == "atk_pct" and m.value == 1000 for m in snap.modifiers)

    async def test_support_self_wengine_mod_excluded(
        self,
        db_session: AsyncSession,
        agent: Agent,
        support_agent: Agent,
        support_wengine: WEngine,
    ):
        """Support W-Engine target=self modifier does NOT propagate to DPS snapshot."""
        sup_build = Build(
            agent_id=support_agent.id,
            w_engine_id=support_wengine.id,
            w_engine_level=60,
        )
        dps_build = Build(agent_id=agent.id)
        db_session.add_all([sup_build, dps_build])
        await db_session.flush()

        repo = BuildRepository(db_session)
        full_dps = await repo.get_by_id(dps_build.id)
        full_sup = await repo.get_by_id(sup_build.id)
        assert full_dps is not None
        assert full_sup is not None

        self_buff = _make_self_mod("atk_pct", 1000)
        with (
            patch("app.services.snapshot_builder.load_agent_modifiers", return_value=[]),
            patch(
                "app.services.snapshot_builder.load_wengine_modifiers",
                return_value=[self_buff],
            ),
        ):
            snap = build_snapshot_from_db(full_dps, agent, support_builds=[full_sup])

        assert not any(m.stat == "atk_pct" for m in snap.modifiers)

    async def test_support_mindscape_level_filters_mods(
        self,
        db_session: AsyncSession,
        agent: Agent,
        support_agent: Agent,
    ):
        """Support at M2 excludes M3+ kit mods; M1/M2 mods are included."""
        sup_build = Build(
            agent_id=support_agent.id,
            mindscape_level=2,
        )
        dps_build = Build(agent_id=agent.id)
        db_session.add_all([sup_build, dps_build])
        await db_session.flush()

        repo = BuildRepository(db_session)
        full_dps = await repo.get_by_id(dps_build.id)
        full_sup = await repo.get_by_id(sup_build.id)
        assert full_dps is not None
        assert full_sup is not None

        m1_mod = _make_mc_mod(1, "atk_pct", 500)
        m3_mod = _make_mc_mod(3, "atk_pct", 800)

        with patch(
            "app.services.snapshot_builder.load_agent_modifiers",
            return_value=[m1_mod, m3_mod],
        ):
            snap = build_snapshot_from_db(full_dps, agent, support_builds=[full_sup])

        atk_mods = [m for m in snap.modifiers if m.stat == "atk_pct"]
        values = {m.value for m in atk_mods}
        assert 500 in values  # M1 included (support is M2)
        assert 800 not in values  # M3 excluded

    async def test_support_disabled_buffs_honored(
        self,
        db_session: AsyncSession,
        agent: Agent,
        support_agent: Agent,
    ):
        """Support's own disabled_buffs exclude mods independently of DPS disabled_buffs."""
        sup_build = Build(
            agent_id=support_agent.id,
            mindscape_level=6,
            disabled_buffs=["11001:core_a"],
        )
        dps_build = Build(agent_id=agent.id)
        db_session.add_all([sup_build, dps_build])
        await db_session.flush()

        repo = BuildRepository(db_session)
        full_dps = await repo.get_by_id(dps_build.id)
        full_sup = await repo.get_by_id(sup_build.id)
        assert full_dps is not None
        assert full_sup is not None

        mod = Modifier(
            stat="atk_pct",
            value=700,
            source=ModifierSource.CORE_SKILL,
            source_label="Core A",
            target=ModifierTarget.TEAM,
        )

        def mods_by_hid(hid):
            # Only the support agent (11001) yields the mod; DPS (11000) yields nothing.
            return [mod] if hid == "11001" else []

        with patch(
            "app.services.snapshot_builder.load_agent_modifiers",
            side_effect=mods_by_hid,
        ):
            snap = build_snapshot_from_db(full_dps, agent, support_builds=[full_sup])

        # "11001:core_a" is in disabled_buffs so mod should be excluded.
        assert not any(m.stat == "atk_pct" and m.value == 700 for m in snap.modifiers)

    async def test_dps_refinement_uses_build_field(
        self,
        db_session: AsyncSession,
        agent: Agent,
        support_wengine: WEngine,
    ):
        """DPS w_engine_refinement is read from build.w_engine_refinement."""
        build = Build(
            agent_id=agent.id,
            w_engine_id=support_wengine.id,
            w_engine_level=60,
            w_engine_refinement=5,
        )
        db_session.add(build)
        await db_session.flush()

        repo = BuildRepository(db_session)
        full_build = await repo.get_by_id(build.id)
        assert full_build is not None

        captured = {}

        def fake_wengine_mods(hid, *, refinement=1):
            captured["refinement"] = refinement
            return []

        with (
            patch("app.services.snapshot_builder.load_agent_modifiers", return_value=[]),
            patch(
                "app.services.snapshot_builder.load_wengine_modifiers",
                side_effect=fake_wengine_mods,
            ),
        ):
            build_snapshot_from_db(full_build, agent)

        assert captured["refinement"] == 5
