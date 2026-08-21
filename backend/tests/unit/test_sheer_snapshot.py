"""Unit tests for SheerForce resolution and snapshot construction.

All expected values are hand-computed against:
  SheerForce = floor(ATK * 3000 / 10000)          # universal 30% ATK conversion
             + floor(HP * hp_ratio / 10000)        # per-agent intrinsic extra
             + sheer_force_flat                    # from buffs (supports, W-engines)

Reference: DESIGN_sheer_damage.md §SheerForce resolution
"""

from __future__ import annotations

from app.services.buff_resolver import ResolvedBuffs
from app.services.build_damage_service import (
    SHEER_ATK_RATIO,
    BuildSnapshot,
    resolve_sheer_force,
)
from app.services.stat_calculator import TotalStats


def _stats(atk: int, hp: int = 0) -> TotalStats:
    return TotalStats(atk=atk, hp=hp)


def _buffs(sheer_force_flat: int = 0) -> ResolvedBuffs:
    bonuses = {}
    if sheer_force_flat:
        bonuses["sheer_force_flat"] = sheer_force_flat
    return ResolvedBuffs(combat_bonuses=bonuses)


def _snap(hp_ratio: int = 0, specialty: str = "attack") -> BuildSnapshot:
    return BuildSnapshot(
        agent_sheer_force_hp_ratio=hp_ratio,
        agent_specialty=specialty,
    )


class TestSheerAtkRatioConstant:
    def test_constant_is_3000(self):
        assert SHEER_ATK_RATIO == 3000


class TestResolveSheerForce:
    def test_atk_only_no_hp_no_flat(self):
        # ATK=2000, hp_ratio=0, flat=0 → floor(2000*3000/10000) = floor(600) = 600
        sf = resolve_sheer_force(
            stats=_stats(atk=2000),
            snap=_snap(hp_ratio=0),
            buffs=_buffs(),
        )
        assert sf == 600

    def test_yixuan_setup_atk_and_hp(self):
        # ATK=2000, HP=30000, hp_ratio=1000 → 600 + floor(30000*1000/10000) = 600+3000 = 3600
        sf = resolve_sheer_force(
            stats=_stats(atk=2000, hp=30000),
            snap=_snap(hp_ratio=1000),
            buffs=_buffs(),
        )
        assert sf == 3600

    def test_atk_buff_flows_into_sheer_force(self):
        # Flat ATK buff (e.g. +500) baked into TotalStats.atk:
        # floor((2000+500)*3000/10000) = floor(2500*3000/10000) = floor(750) = 750
        sf = resolve_sheer_force(
            stats=_stats(atk=2500),
            snap=_snap(hp_ratio=0),
            buffs=_buffs(),
        )
        assert sf == 750

    def test_external_flat_sheer_force_from_supports(self):
        # ATK=2000, flat=400 (Lucia/Pan Yinhu) → 600+400 = 1000
        sf = resolve_sheer_force(
            stats=_stats(atk=2000),
            snap=_snap(hp_ratio=0),
            buffs=_buffs(sheer_force_flat=400),
        )
        assert sf == 1000

    def test_all_three_sources_combined(self):
        # ATK=2000, HP=30000, hp_ratio=1000, flat=400 → 600+3000+400 = 4000
        sf = resolve_sheer_force(
            stats=_stats(atk=2000, hp=30000),
            snap=_snap(hp_ratio=1000),
            buffs=_buffs(sheer_force_flat=400),
        )
        assert sf == 4000

    def test_non_rupture_resolver_returns_value_but_unused(self):
        # For non-Rupture the resolver still computes (it's cheap), just not used.
        # ATK=2000, hp_ratio=0, flat=0 → 600 (same as case 1)
        sf = resolve_sheer_force(
            stats=_stats(atk=2000),
            snap=_snap(hp_ratio=0, specialty="attack"),
            buffs=_buffs(),
        )
        assert sf == 600


class TestBuildSnapshotSheerFields:
    def test_default_hp_ratio_is_zero(self):
        snap = BuildSnapshot()
        assert snap.agent_sheer_force_hp_ratio == 0

    def test_default_specialty_is_empty_string(self):
        snap = BuildSnapshot()
        assert snap.agent_specialty == ""

    def test_yixuan_snap_hp_ratio_is_1000(self):
        # Simulates what snapshot_builder will produce for Yixuan
        snap = BuildSnapshot(
            agent_sheer_force_hp_ratio=1000,
            agent_specialty="rupture",
        )
        assert snap.agent_sheer_force_hp_ratio == 1000
        assert snap.agent_specialty == "rupture"

    def test_ellen_snap_hp_ratio_is_zero(self):
        # Non-Rupture agent
        snap = BuildSnapshot(
            agent_sheer_force_hp_ratio=0,
            agent_specialty="attack",
        )
        assert snap.agent_sheer_force_hp_ratio == 0
        assert snap.agent_specialty == "attack"
