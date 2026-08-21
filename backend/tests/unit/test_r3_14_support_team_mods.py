"""Unit tests for ORM-free support team-modifier recompute (Phase 3 — R3.14).

Verifies that support_team_mods_orm_free mirrors _support_modifiers for
agent-kit, W-Engine, and disc-set sources, and that
rebuild_primary_snapshot_with_support produces a snapshot whose modifiers
(and therefore combo damage) match build_snapshot_from_db for both an
unchanged and a changed-set support disc loadout.
"""

from __future__ import annotations

import pickle
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from app.services.build_damage_service import BuildSnapshot
from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.rank_pipeline import PlainBuildDisc
from app.services.snapshot_builder import _support_modifiers
from app.services.support_recompute import (
    SupportRecomputeKit,
    build_support_recompute_kit,
    rebuild_primary_snapshot_with_support,
    support_team_mods_orm_free,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plain_disc(
    slot: int,
    set_id: int,
    main_stat_type: str = "atk",
    main_stat_value: int = 0,
    substats: list | None = None,
) -> PlainBuildDisc:
    return PlainBuildDisc(
        slot=slot,
        main_stat_type=main_stat_type,
        main_stat_value=main_stat_value,
        substats=substats or [],
        set_hakushin_id=set_id,
    )


def _orm_disc(
    slot: int,
    set_id: int,
    main_stat_type: str = "atk",
    main_stat_value: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        slot=SimpleNamespace(value=slot),
        main_stat_type=SimpleNamespace(value=main_stat_type),
        main_stat_value=main_stat_value,
        substats=[],
        disc_set=SimpleNamespace(hakushin_id=set_id),
    )


def _make_modifier(
    stat: str = "atk_pct",
    value: int = 500,
    source: ModifierSource = ModifierSource.CORE_SKILL,
    source_label: str = "TestBuff",
    target: ModifierTarget = ModifierTarget.SELF,
    conditions: tuple = (Condition.ALWAYS,),
) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=source,
        source_label=source_label,
        target=target,
        conditions=conditions,
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


def _make_team_disc_mod(stat: str = "atk_pct", value: int = 800) -> Modifier:
    return _make_modifier(
        stat=stat,
        value=value,
        source=ModifierSource.DISC_SET_2PC,
        source_label="2pc team buff",
        target=ModifierTarget.TEAM,
    )


def _mock_support_build(
    discs: list,
    *,
    hakushin_id: int = 0,
    name: str = "Supporter",
    specialty: str = "support",
    element: str = "electric",
    mindscape_level: int = 0,
    disabled_buffs: list | None = None,
    w_engine: object = None,
) -> SimpleNamespace:
    agent = SimpleNamespace(
        hakushin_id=hakushin_id,
        name=name,
        specialty=SimpleNamespace(value=specialty),
        element=SimpleNamespace(value=element),
        base_hp=10000,
        hp_growth=0,
        base_atk=1000,
        atk_growth=0,
        promotion_stats=None,
        core_stats=None,
    )
    return SimpleNamespace(
        agent=agent,
        agent_level=60,
        core_skill_level=None,
        mindscape_level=mindscape_level,
        disabled_buffs=disabled_buffs or [],
        discs=discs,
        w_engine=w_engine,
        w_engine_refinement=1,
        w_engine_level=60,
    )


def _minimal_primary_snap(modifiers: list[Modifier] | None = None) -> BuildSnapshot:
    """Minimal primary snapshot for testing modifier injection."""
    return BuildSnapshot(
        agent_base_hp=50000,
        agent_base_atk=1000,
        agent_base_def=600,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        agent_pen_ratio=0,
        agent_pen_flat=0,
        wengine_base_atk=500,
        agent_name="DPS",
        agent_element="fire",
        agent_level=60,
        disc_stats=[],
        modifiers=modifiers or [],
    )


class TestSupportTeamModsOrmFree:
    def test_empty_kit_returns_empty_list(self):
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={},
            build_discs=[],
        )
        assert support_team_mods_orm_free(kit, []) == []

    def test_agent_kit_mods_passed_through(self):
        """Prefiltered agent kit mods appear in output unchanged (no HP scaling)."""
        mod = _make_modifier(stat="crit_rate", value=400, target=ModifierTarget.SELF)
        mod_with_name = replace(mod, owner_name="Supporter")
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={},
            build_discs=[],
            agent_name="Supporter",
            agent_kit_mods_prefiltered=[mod_with_name],
        )
        result = support_team_mods_orm_free(kit, [])
        assert len(result) == 1
        assert result[0].stat == "crit_rate"
        assert result[0].value == 400

    def test_hp_scaled_mod_baked_with_current_loadout_hp(self):
        """HP-scaled modifier is baked using the recomputed HP for the given discs."""
        # agent_base_hp=10000; disc has hp_pct=3000 → total HP=10000*1.3=13000
        hp_disc = _plain_disc(1, 999, "hp_pct", 3000)
        # Modifier: base=100, starts scaling at 10000 HP, +50bp per 1000 HP
        mod = Modifier(
            stat="atk_pct",
            value=999,  # cap (won't be reached in this test)
            source=ModifierSource.CORE_SKILL,
            source_label="HpScaleBuff",
            target=ModifierTarget.TEAM,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
            hp_scale_base=100,
            hp_scale_threshold=10000,
            hp_scale_per_unit=1000,
            hp_scale_unit=50,
        )
        mod_with_name = replace(mod, owner_name="Supporter")
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={999: []},
            build_discs=[hp_disc],
            agent_name="Supporter",
            agent_kit_mods_prefiltered=[mod_with_name],
        )
        result = support_team_mods_orm_free(kit, [hp_disc])
        assert len(result) == 1
        # HP=13000: (13000-10000)/1000 = 3 units → 100 + 3*50 = 250
        assert result[0].value == 250

    def test_we_team_mods_included(self):
        we_mod = _make_modifier(stat="pen_ratio", value=1200, target=ModifierTarget.TEAM)
        we_mod = replace(we_mod, owner_name="Supporter")
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={},
            build_discs=[],
            we_team_mods=[we_mod],
        )
        result = support_team_mods_orm_free(kit, [])
        assert len(result) == 1
        assert result[0].stat == "pen_ratio"

    def test_disc_set_team_mod_included_when_2pc_threshold_met(self):
        team_mod = _make_team_disc_mod(stat="atk_pct", value=1000)
        discs = [_plain_disc(i, 100) for i in range(1, 3)]  # 2x set 100 → 2pc met
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={100: [team_mod]},
            build_discs=discs,
            agent_name="Supporter",
        )
        result = support_team_mods_orm_free(kit, discs)
        assert any(m.stat == "atk_pct" and m.value == 1000 for m in result)

    def test_disc_set_team_mod_excluded_when_2pc_threshold_not_met(self):
        team_mod = _make_team_disc_mod(stat="atk_pct", value=1000)
        discs = [_plain_disc(1, 100)]  # only 1x set 100 → 2pc NOT met
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={100: [team_mod]},
            build_discs=discs,
            agent_name="Supporter",
        )
        result = support_team_mods_orm_free(kit, discs)
        assert not any(m.stat == "atk_pct" for m in result)

    def test_disc_set_self_mod_not_included(self):
        """SELF-target disc set mods must not leak into the team mods list."""
        self_mod = _make_modifier(
            stat="atk_pct",
            value=1000,
            source=ModifierSource.DISC_SET_2PC,
            source_label="2pc self",
            target=ModifierTarget.SELF,
        )
        discs = [_plain_disc(i, 100) for i in range(1, 3)]
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={100: [self_mod]},
            build_discs=discs,
            agent_name="Supporter",
        )
        assert support_team_mods_orm_free(kit, discs) == []

    def test_changed_set_loadout_changes_disc_mods(self):
        """Swapping from a 2pc set to a different set removes the original set bonus."""
        team_mod_100 = _make_team_disc_mod(stat="atk_pct", value=1000)
        team_mod_200 = _make_team_disc_mod(stat="crit_rate", value=800)
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={100: [team_mod_100], 200: [team_mod_200]},
            build_discs=[],
            agent_name="Supporter",
        )
        # Original: 2x set 100 → atk_pct bonus active
        original = [_plain_disc(i, 100) for i in range(1, 3)]
        mods_original = support_team_mods_orm_free(kit, original)
        assert any(m.stat == "atk_pct" for m in mods_original)
        assert not any(m.stat == "crit_rate" for m in mods_original)

        # Changed: 2x set 200 → crit_rate bonus active
        changed = [_plain_disc(i, 200) for i in range(1, 3)]
        mods_changed = support_team_mods_orm_free(kit, changed)
        assert any(m.stat == "crit_rate" for m in mods_changed)
        assert not any(m.stat == "atk_pct" for m in mods_changed)


class TestMatchesSupportModifiers:
    def test_no_agent_mods_no_we_no_disc_set_mods(self):
        """Without any contributing mods, both paths return empty lists."""
        orm_discs = [_orm_disc(i, 100) for i in range(1, 3)]
        plain_discs = [_plain_disc(i, 100) for i in range(1, 3)]
        support_build = _mock_support_build(orm_discs)

        _sb = "app.services.snapshot_builder"
        _sr = "app.services.support_recompute"
        with (
            patch(f"{_sb}.load_agent_modifiers", return_value=[]),
            patch(f"{_sr}.load_agent_modifiers", return_value=[]),
            patch(f"{_sb}.load_disc_set_modifiers", return_value=[]),
            patch(f"{_sr}.load_disc_set_modifiers", return_value=[]),
        ):
            orm_mods = _support_modifiers(support_build)
            kit = build_support_recompute_kit(support_build, plain_discs)
            ormfree_mods = support_team_mods_orm_free(kit, plain_discs)

        assert ormfree_mods == orm_mods

    def test_agent_kit_mod_propagated(self):
        """A synthetic agent kit mod appears identically in both paths."""
        synthetic_mod = _make_modifier(
            stat="crit_rate",
            value=600,
            target=ModifierTarget.TEAM,
        )
        orm_discs = [_orm_disc(i, 100) for i in range(1, 3)]
        plain_discs = [_plain_disc(i, 100) for i in range(1, 3)]
        support_build = _mock_support_build(
            orm_discs,
            name="Supporter",
            specialty="support",
            element="electric",
        )

        _sb = "app.services.snapshot_builder"
        _sr = "app.services.support_recompute"
        with (
            patch(f"{_sb}.load_agent_modifiers", return_value=[synthetic_mod]),
            patch(f"{_sr}.load_agent_modifiers", return_value=[synthetic_mod]),
            patch(f"{_sb}.load_disc_set_modifiers", return_value=[]),
            patch(f"{_sr}.load_disc_set_modifiers", return_value=[]),
        ):
            orm_mods = _support_modifiers(support_build)
            kit = build_support_recompute_kit(support_build, plain_discs)
            ormfree_mods = support_team_mods_orm_free(kit, plain_discs)

        assert len(ormfree_mods) == len(orm_mods) == 1
        assert ormfree_mods[0].stat == orm_mods[0].stat == "crit_rate"
        assert ormfree_mods[0].value == orm_mods[0].value

    def test_agent_kit_base_atk_scaling_mod_propagated(self):
        """A base ATK-scaling agent kit mod is correctly baked in both paths."""
        scaling_mod = replace(
            _make_modifier(
                stat="flat_atk",
                value=0,
                target=ModifierTarget.TEAM,
            ),
            scaling_stat="base_atk",
            scaling_ratio=20000,  # 200% base ATK (Lucy's Cheer On max)
        )

        orm_discs = [_orm_disc(i, 100) for i in range(1, 3)]
        plain_discs = [_plain_disc(i, 100) for i in range(1, 3)]
        support_build = _mock_support_build(
            orm_discs,
            name="Supporter",
            specialty="support",
            element="electric",
        )

        _sb = "app.services.snapshot_builder"
        _sr = "app.services.support_recompute"
        with (
            patch(f"{_sb}.load_agent_modifiers", return_value=[scaling_mod]),
            patch(f"{_sr}.load_agent_modifiers", return_value=[scaling_mod]),
            patch(f"{_sb}.load_disc_set_modifiers", return_value=[]),
            patch(f"{_sr}.load_disc_set_modifiers", return_value=[]),
        ):
            orm_mods = _support_modifiers(support_build)
            kit = build_support_recompute_kit(support_build, plain_discs)
            ormfree_mods = support_team_mods_orm_free(kit, plain_discs)

        assert len(ormfree_mods) == len(orm_mods) == 1
        assert ormfree_mods[0].stat == orm_mods[0].stat == "flat_atk"
        # Mock base ATK 1000 → scaled 2790 at L60 with promotion. 2790 * 200% = 5580.
        assert ormfree_mods[0].value == orm_mods[0].value == 5580

    def test_disc_set_team_mod_propagated(self):
        """A disc-set TEAM mod appears from both paths when 2pc threshold is met."""
        team_mod = _make_team_disc_mod(stat="pen_ratio", value=1500)
        orm_discs = [_orm_disc(i, 100) for i in range(1, 3)]
        plain_discs = [_plain_disc(i, 100) for i in range(1, 3)]
        support_build = _mock_support_build(orm_discs)

        _sb = "app.services.snapshot_builder"
        _sr = "app.services.support_recompute"
        with (
            patch(f"{_sb}.load_agent_modifiers", return_value=[]),
            patch(f"{_sr}.load_agent_modifiers", return_value=[]),
            patch(f"{_sb}.load_disc_set_modifiers", return_value=[team_mod]),
            patch(f"{_sr}.load_disc_set_modifiers", return_value=[team_mod]),
        ):
            orm_mods = _support_modifiers(support_build)
            kit = build_support_recompute_kit(support_build, plain_discs)
            ormfree_mods = support_team_mods_orm_free(kit, plain_discs)

        assert len(ormfree_mods) == len(orm_mods) == 1
        assert ormfree_mods[0].stat == "pen_ratio"

    def test_mindscape_filter_applied(self):
        """Mindscape mods above the build's mindscape level are filtered out."""
        m6_mod = _make_modifier(
            stat="atk_pct",
            value=1000,
            source=ModifierSource.MINDSCAPE,
            source_label="M6 Buff",
        )
        orm_discs = [_orm_disc(1, 100)]
        plain_discs = [_plain_disc(1, 100)]
        support_build = _mock_support_build(orm_discs, mindscape_level=0)

        _sb = "app.services.snapshot_builder"
        _sr = "app.services.support_recompute"
        with (
            patch(f"{_sb}.load_agent_modifiers", return_value=[m6_mod]),
            patch(f"{_sr}.load_agent_modifiers", return_value=[m6_mod]),
            patch(f"{_sb}.load_disc_set_modifiers", return_value=[]),
            patch(f"{_sr}.load_disc_set_modifiers", return_value=[]),
        ):
            orm_mods = _support_modifiers(support_build)
            kit = build_support_recompute_kit(support_build, plain_discs)
            ormfree_mods = support_team_mods_orm_free(kit, plain_discs)

        # M6 > mindscape_level=0 → filtered in both paths
        assert orm_mods == []
        assert ormfree_mods == []


class TestRebuildPrimarySnapshotWithSupport:
    def _kit_with_team_mod(self, stat: str = "atk_pct", value: int = 1000) -> SupportRecomputeKit:
        team_mod = _make_team_disc_mod(stat=stat, value=value)
        discs = [_plain_disc(i, 100) for i in range(1, 3)]
        return SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={100: [team_mod]},
            build_discs=discs,
            agent_name="Supporter",
        )

    def test_support_mods_appended_to_primary(self):
        """Support team mods are appended to the primary snapshot's modifiers."""
        existing_mod = _make_modifier(stat="crit_rate", value=200)
        primary = _minimal_primary_snap(modifiers=[existing_mod])
        kit = self._kit_with_team_mod(stat="atk_pct", value=1000)
        discs = [_plain_disc(i, 100) for i in range(1, 3)]

        rebuilt = rebuild_primary_snapshot_with_support(primary, kit, discs)

        stats = [m.stat for m in rebuilt.modifiers]
        assert "crit_rate" in stats
        assert "atk_pct" in stats
        assert len(rebuilt.modifiers) == 2

    def test_empty_support_discs_gives_no_extra_mods(self):
        """With an empty support loadout (no 2pc threshold), no set mods are added."""
        primary = _minimal_primary_snap()
        kit = self._kit_with_team_mod(stat="atk_pct", value=1000)

        rebuilt = rebuild_primary_snapshot_with_support(primary, kit, [])

        # No 2pc threshold met → no disc set team mods
        assert all(m.stat != "atk_pct" for m in rebuilt.modifiers)

    def test_changed_set_loadout_changes_snapshot_mods(self):
        """Swapping support discs produces a snapshot with different team mods."""
        team_mod_100 = _make_team_disc_mod(stat="atk_pct", value=1000)
        team_mod_200 = _make_team_disc_mod(stat="crit_rate", value=800)
        discs_original = [_plain_disc(i, 100) for i in range(1, 3)]
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={100: [team_mod_100], 200: [team_mod_200]},
            build_discs=discs_original,
            agent_name="Supporter",
        )
        primary = _minimal_primary_snap()

        snap_original = rebuild_primary_snapshot_with_support(primary, kit, discs_original)
        discs_changed = [_plain_disc(i, 200) for i in range(1, 3)]
        snap_changed = rebuild_primary_snapshot_with_support(primary, kit, discs_changed)

        original_stats = {m.stat for m in snap_original.modifiers}
        changed_stats = {m.stat for m in snap_changed.modifiers}
        assert "atk_pct" in original_stats
        assert "crit_rate" not in original_stats
        assert "crit_rate" in changed_stats
        assert "atk_pct" not in changed_stats

    def test_output_is_picklable(self):
        """Rebuilt snapshot survives pickle round-trip (process-pool safety)."""
        primary = _minimal_primary_snap()
        kit = self._kit_with_team_mod()
        discs = [_plain_disc(i, 100) for i in range(1, 3)]
        rebuilt = rebuild_primary_snapshot_with_support(primary, kit, discs)
        restored = pickle.loads(pickle.dumps(rebuilt))
        assert len(restored.modifiers) == len(rebuilt.modifiers)

    def test_primary_base_stats_unchanged(self):
        """Rebuilding does not alter any base stat of the primary snapshot."""
        primary = _minimal_primary_snap()
        kit = self._kit_with_team_mod()
        discs = [_plain_disc(i, 100) for i in range(1, 3)]
        rebuilt = rebuild_primary_snapshot_with_support(primary, kit, discs)

        assert rebuilt.agent_base_hp == primary.agent_base_hp
        assert rebuilt.agent_base_atk == primary.agent_base_atk
        assert rebuilt.wengine_base_atk == primary.wengine_base_atk
        assert rebuilt.agent_element == primary.agent_element


# ---------------------------------------------------------------------------
# Regression: target=active modifiers reach DPS in the stateless path
# ---------------------------------------------------------------------------


class TestActiveModifierStatelessPath:
    """target=active+always support modifiers must reach DPS via team_calculator.

    Regression for the ACTIVE-modifier change (Task 13). Before the fix,
    only target=team mods passed _collect_team_modifiers; target=active mods
    were silently dropped even though in-game they buff the on-field agent.

    Warning (MODIFIER_AUTHORING.md): tagging a support buff as target=active
    when it should be target=team leaks it into DPS; tagging it as target=self
    when it should be target=team or target=active silently under-counts the
    support contribution. Both mistaggings are invisible at seed time.
    """

    def _make_mod(
        self,
        stat: str,
        value: int,
        target: ModifierTarget,
        *,
        label: str = "",
    ) -> Modifier:
        return Modifier(
            stat=stat,
            value=value,
            source=ModifierSource.CORE_SKILL,
            source_label=label or f"{target.value}_{stat}",
            target=target,
            conditions=(Condition.ALWAYS,),
        )

    def test_active_mod_collected_by_team_calculator(self):
        """_collect_team_modifiers includes target=active alongside target=team."""
        from app.services.team_calculator import (
            TeamMember,
            _collect_team_modifiers,
        )

        active_mod = self._make_mod("flat_atk", 500, ModifierTarget.ACTIVE)
        team_mod = self._make_mod("flat_atk", 300, ModifierTarget.TEAM)
        self_mod = self._make_mod("flat_atk", 200, ModifierTarget.SELF)

        support = TeamMember(
            build_id="sup-1",
            agent_name="Support",
            agent_element="fire",
            agent_specialty="support",
            agent_faction_id=0,
            modifiers=[active_mod, team_mod, self_mod],
        )

        collected = _collect_team_modifiers([support])
        targets = {m.target for m in collected}

        assert ModifierTarget.ACTIVE in targets, (
            "target=active modifier was dropped — ACTIVE-modifier change may have been reverted"
        )
        assert ModifierTarget.TEAM in targets
        assert ModifierTarget.SELF not in targets, (
            "target=self modifier leaked into DPS — filter is broken"
        )

    def test_active_mod_increases_dps_damage(self):
        """End-to-end: support target=active flat_atk buff raises DPS combo damage."""
        from app.services.build_damage_service import EnemySnapshot
        from app.services.combo_types import ComboStep
        from app.services.modifiers import ActiveConditions, AttackScope
        from app.services.team_calculator import (
            TeamMember,
            calculate_team_combo,
        )

        enemy = EnemySnapshot(
            level=60,
            base_def=50,
            element_res=0,
            stun_dmg_mult=15000,
        )
        dps_snapshot = BuildSnapshot(
            agent_name="DPS",
            agent_element="physical",
            agent_level=60,
            agent_base_atk=1000,
        )
        dps_member = TeamMember(
            build_id="dps-1",
            agent_name="DPS",
            agent_element="physical",
            agent_specialty="attack",
            agent_faction_id=0,
            modifiers=[],
        )
        combo = [
            ComboStep(
                label="basic",
                attack_id="a1",
                attack_name="Basic",
                scope=AttackScope.ALL,
                multiplier=10000,
                element="physical",
            )
        ]
        base_result = calculate_team_combo(
            dps_member=dps_member,
            support_members=[],
            dps_snapshot=dps_snapshot,
            enemy=enemy,
            combo_steps=combo,
            conditions=ActiveConditions(),
        )

        active_mod = self._make_mod("flat_atk", 500, ModifierTarget.ACTIVE)
        support_active = TeamMember(
            build_id="sup-1",
            agent_name="Support",
            agent_element="fire",
            agent_specialty="support",
            agent_faction_id=0,
            modifiers=[active_mod],
        )
        buffed_result = calculate_team_combo(
            dps_member=dps_member,
            support_members=[support_active],
            dps_snapshot=dps_snapshot,
            enemy=enemy,
            combo_steps=combo,
            conditions=ActiveConditions(),
        )

        base_dmg = base_result.combo_result.total_damage
        buffed_dmg = buffed_result.combo_result.total_damage
        assert buffed_dmg > base_dmg, (
            f"target=active support buff did not raise DPS damage: {base_dmg=} {buffed_dmg=}"
        )

    def test_self_mod_does_not_reach_dps(self):
        """target=self support modifier must NOT flow to DPS (self-only damage path)."""
        from app.services.build_damage_service import EnemySnapshot
        from app.services.combo_types import ComboStep
        from app.services.modifiers import ActiveConditions, AttackScope
        from app.services.team_calculator import (
            TeamMember,
            calculate_team_combo,
        )

        enemy = EnemySnapshot(
            level=60,
            base_def=50,
            element_res=0,
            stun_dmg_mult=15000,
        )
        dps_snapshot = BuildSnapshot(
            agent_name="DPS",
            agent_element="physical",
            agent_level=60,
            agent_base_atk=1000,
        )
        dps_member = TeamMember(
            build_id="dps-1",
            agent_name="DPS",
            agent_element="physical",
            agent_specialty="attack",
            agent_faction_id=0,
            modifiers=[],
        )
        combo = [
            ComboStep(
                label="basic",
                attack_id="a1",
                attack_name="Basic",
                scope=AttackScope.ALL,
                multiplier=10000,
                element="physical",
            )
        ]
        base_result = calculate_team_combo(
            dps_member=dps_member,
            support_members=[],
            dps_snapshot=dps_snapshot,
            enemy=enemy,
            combo_steps=combo,
            conditions=ActiveConditions(),
        )
        self_mod = self._make_mod("flat_atk", 500, ModifierTarget.SELF)
        support_self = TeamMember(
            build_id="sup-2",
            agent_name="Support",
            agent_element="fire",
            agent_specialty="support",
            agent_faction_id=0,
            modifiers=[self_mod],
        )
        self_result = calculate_team_combo(
            dps_member=dps_member,
            support_members=[support_self],
            dps_snapshot=dps_snapshot,
            enemy=enemy,
            combo_steps=combo,
            conditions=ActiveConditions(),
        )

        assert self_result.combo_result.total_damage == base_result.combo_result.total_damage, (
            "target=self support modifier leaked into DPS damage — filter broken"
        )
