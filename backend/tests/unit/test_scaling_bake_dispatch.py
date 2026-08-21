"""Task 13 (C1) — the scaling_stat bake dispatch table.

`scaling_stat` names a *basis*: a stat of the modifier's owner that the
modifier's value is derived from at snapshot-build time. Before this task the
builder dispatched on it with a hardcoded if-chain replicated at four call
sites, so a `scaling_stat` nobody had written an `elif` for was loaded,
displayed in the UI, and then contributed literally nothing to the calc.

`_SCALING_BAKERS` replaces the chain, and is the schema contract L0
(`scripts/validate_kits.py`) validates every kit JSON against — hence
`TestTableIsTheContract`, which pins the table to both the corpus and the
validator so the three cannot drift apart.

Sources for the values asserted here (read this session, ZO @ 0c9bde8f):
  Ben     — "Ben's initial ATK increases along with his initial DEF. He gains
            40%…80% of his initial DEF as ATK." (DB core text, tiers A..F)
            ZO Ben.ts: `ownBuff.initial.atk.add(prod(own.initial.def, core.atk))`
  Manato  — "gains extra Sheer Force based on his Max HP, with every 1 point of
  Yidhari   Max HP increasing Sheer Force by 0.1." (DB core text)
            ZO: `ownBuff.initial.sheerForce.add(prod(own.final.hp, core.sheerForce))`
            `core.sheerForce = 0.1` for Manato, Yidhari and Yixuan alike — so this
            is the intrinsic Rupture HP→SheerForce path, NOT an HP-scaled flat-ATK
            modifier. See D-KV9.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.build_damage_service import _SHEER_INTRINSIC_HP_RATIOS
from app.services.modifier_loader import load_agent_modifiers
from app.services.modifiers import Modifier, ModifierSource, ModifierTarget
from app.services.snapshot_builder import (
    _SCALING_BAKERS,
    _bake_owner_scaled,
    _initial_def,
    _ScalingBases,
    _support_base_atk,
    _support_total_atk,
    _support_total_impact,
    _support_total_pen_ratio,
    build_snapshot_from_db,
)

MODIFIERS_DIR = Path(__file__).parents[2] / "app" / "data" / "modifiers"

BEN = "1121"
MANATO = "1441"
YIDHARI = "1051"
ASTRA = "1311"

BEN_CORE_DEF_TO_ATK_BP = 8000  # 80% at max core tier (F)
SHEER_HP_RATIO_BP = 1000  # 0.1 SheerForce per point of Max HP


# ---------------------------------------------------------------------------
# Fakes — build_snapshot_from_db only reads plain attributes off Build/Agent.
# ---------------------------------------------------------------------------


def _agent(
    hakushin_id: str,
    name: str,
    *,
    base_atk: int = 700,
    base_def: int = 600,
    base_hp: int = 8000,
    specialty: str = "defense",
    element: str = "fire",
) -> SimpleNamespace:
    return SimpleNamespace(
        hakushin_id=hakushin_id,
        name=name,
        base_atk=base_atk,
        base_def=base_def,
        base_hp=base_hp,
        atk_growth=0,
        def_growth=0,
        hp_growth=0,
        promotion_stats=None,
        core_stats=None,
        base_crit_rate=500,
        base_crit_dmg=5000,
        base_anomaly_proficiency=93,
        base_anomaly_mastery=93,
        base_impact=95,
        base_pen_ratio=0,
        base_pen_flat=0,
        base_energy_regen=12000,
        ex_energy_cost=60,
        specialty=specialty,
        element=element,
    )


def _build(agent: SimpleNamespace, *, mindscape: int = 0, level: int = 60) -> SimpleNamespace:
    return SimpleNamespace(
        agent=agent,
        agent_level=level,
        w_engine=None,
        w_engine_level=None,
        w_engine_refinement=1,
        discs=[],
        mindscape_level=mindscape,
        core_skill_level=5,
        skill_levels=None,
        stack_counts=None,
        disabled_buffs=None,
    )


def _flat_atk_mods(snapshot) -> list[Modifier]:
    return [m for m in snapshot.modifiers if m.stat == "flat_atk"]


def _kit(slug: str) -> dict:
    return json.loads((MODIFIERS_DIR / "agents" / f"{slug}.json").read_text())


# ---------------------------------------------------------------------------
# The table is the contract
# ---------------------------------------------------------------------------


class TestTableIsTheContract:
    def test_every_scaling_stat_in_the_corpus_is_dispatched(self) -> None:
        """No kit may name a basis the builder cannot bake — that is a silent no-op."""
        used: dict[str, str] = {}
        for path in sorted(MODIFIERS_DIR.rglob("*.json")):
            for mod in json.loads(path.read_text()).get("modifiers", []):
                if mod.get("scaling_stat"):
                    used[mod["scaling_stat"]] = path.name

        unbaked = {stat: src for stat, src in used.items() if stat not in _SCALING_BAKERS}
        assert not unbaked, f"scaling_stat with no baker (contributes nothing): {unbaked}"

    def test_l0_validator_reads_this_table(self) -> None:
        """L0's answer key is introspected from the builder, never restated."""
        from scripts.validate_kits import baked_scaling_stats

        assert baked_scaling_stats() >= frozenset(_SCALING_BAKERS)

    def test_unknown_basis_passes_through_unbaked(self) -> None:
        """The builder does not guess. An unknown basis stays unbaked — L0 is the guard.

        `hp` is deliberately absent from `_SCALING_BAKERS` (D-KV9) — the Rupture
        HP→SheerForce intrinsic is not an ATK buff, so `hp` stays a real,
        never-dispatched basis even after Task 27 (C8) added `pen_ratio`/`impact`.
        """
        mod = Modifier(
            stat="flat_atk",
            value=0,
            scaling_stat="hp",
            scaling_ratio=5000,
            source=ModifierSource.CORE_SKILL,
            source_label="Core: nonsense",
        )
        agent = _agent(BEN, "Ben")
        out = _bake_owner_scaled(mod, _ScalingBases(_build(agent)))

        assert out.scaling_stat == "hp"
        assert out.value == 0


# ---------------------------------------------------------------------------
# def → ATK (Ben)
# ---------------------------------------------------------------------------


class TestDefScalingBakes:
    def test_ben_core_bakes_def_into_flat_atk(self) -> None:
        agent = _agent(BEN, "Ben", base_def=600)
        build = _build(agent)

        snap = build_snapshot_from_db(build, agent)
        core = next(m for m in _flat_atk_mods(snap) if m.source_label == "Core: DEF-to-ATK")

        expected = _initial_def(build) * BEN_CORE_DEF_TO_ATK_BP // 10000
        assert expected > 0
        assert core.value == expected
        assert core.scaling_stat is None  # consumed — cannot double-bake

    def test_initial_def_includes_disc_def(self) -> None:
        """ZO's basis is `own.initial.def` — equipment-inclusive, buff-exclusive."""
        agent = _agent(BEN, "Ben", base_def=600)
        bare = _build(agent)
        with_disc = _build(agent)
        with_disc.discs = [
            SimpleNamespace(
                slot=SimpleNamespace(value=4),
                main_stat_type=SimpleNamespace(value="def"),
                main_stat_value=300,
                substats=[],
                disc_set=SimpleNamespace(hakushin_id=31000),
            )
        ]

        assert _initial_def(with_disc) == _initial_def(bare) + 300


# ---------------------------------------------------------------------------
# hp → SheerForce (Manato, Yidhari) — an intrinsic, not a modifier
# ---------------------------------------------------------------------------


class TestSheerForceHpIsIntrinsic:
    @pytest.mark.parametrize("slug", ["manato", "yidhari"])
    def test_kit_has_no_hp_scaled_flat_atk_row(self, slug: str) -> None:
        """The HP term feeds SheerForce, not ATK — a flat_atk row is the wrong shape."""
        mods = _kit(slug)["modifiers"]
        assert not [m for m in mods if m.get("scaling_stat") == "hp"]

    @pytest.mark.parametrize("name", ["Manato", "Yidhari", "Yixuan"])
    def test_intrinsic_hp_ratio_is_registered(self, name: str) -> None:
        assert _SHEER_INTRINSIC_HP_RATIOS[name] == SHEER_HP_RATIO_BP


# ---------------------------------------------------------------------------
# pen_ratio / impact → C8 (Task 27, D-KV20)
#
# Rina's core: "min(cap, 25% of Rina's OWN PEN Ratio + a flat per-core-level
# term)" — Qingyi's core: flat ATK from her own Impact stat. Neither basis has
# an in-game "base vs. total" split (unlike ATK), so — like anomaly_mastery —
# the provider totals agent base + disc + the agent's own kit/W-Engine/disc-set
# grants (_support_total_am's pattern), not just the bare agent stat.
# ---------------------------------------------------------------------------


class TestPenRatioAndImpactScalingBake:
    def test_pen_ratio_bakes_to_nonzero(self) -> None:
        mod = Modifier(
            stat="pen_ratio",
            value=0,
            scaling_stat="pen_ratio",
            scaling_ratio=2500,  # Rina's core: 25% of her own PEN Ratio
            target=ModifierTarget.TEAM,
            source=ModifierSource.CORE_SKILL,
            source_label="Core: PEN Ratio",
        )
        agent = _agent("1211", "Rina", specialty="support", element="electric")
        agent.base_pen_ratio = 2000
        build = _build(agent)

        out = _bake_owner_scaled(mod, _ScalingBases(build))

        basis = _support_total_pen_ratio(build)
        assert basis > 0
        assert out.value == basis * 2500 // 10000
        assert out.value > 0
        assert out.scaling_stat is None  # consumed — cannot double-bake

    def test_impact_bakes_to_nonzero(self) -> None:
        mod = Modifier(
            stat="flat_atk",
            value=0,
            scaling_stat="impact",
            scaling_ratio=5000,  # Qingyi's core: 50% of her own Impact
            source=ModifierSource.CORE_SKILL,
            source_label="Core: Impact->ATK",
        )
        agent = _agent("1251", "Qingyi")
        build = _build(agent)

        out = _bake_owner_scaled(mod, _ScalingBases(build))

        basis = _support_total_impact(build)
        assert basis > 0
        assert out.value == basis * 5000 // 10000
        assert out.value > 0
        assert out.scaling_stat is None

    def test_total_pen_ratio_includes_disc_pen_ratio(self) -> None:
        agent = _agent("1211", "Rina", specialty="support", element="electric")
        bare = _build(agent)
        with_disc = _build(agent)
        with_disc.discs = [
            SimpleNamespace(
                slot=SimpleNamespace(value=6),
                main_stat_type=SimpleNamespace(value="pen_ratio"),
                main_stat_value=1980,
                substats=[],
                disc_set=SimpleNamespace(hakushin_id=31000),
            )
        ]

        assert _support_total_pen_ratio(with_disc) == _support_total_pen_ratio(bare) + 1980

    @pytest.mark.parametrize(("hid", "name"), [(MANATO, "Manato"), (YIDHARI, "Yidhari")])
    def test_snapshot_carries_the_ratio(self, hid: str, name: str) -> None:
        agent = _agent(hid, name, specialty="rupture")
        snap = build_snapshot_from_db(_build(agent), agent)

        assert snap.agent_sheer_force_hp_ratio == SHEER_HP_RATIO_BP


# ---------------------------------------------------------------------------
# Regressions — the bases that already worked must not move
# ---------------------------------------------------------------------------


class TestExistingBasesUnchanged:
    def test_base_atk_bakes_off_base_atk_not_total(self) -> None:
        mod = Modifier(
            stat="flat_atk",
            value=0,
            scaling_stat="base_atk",
            scaling_ratio=4000,  # Soukaku's core: 40% of base ATK
            target=ModifierTarget.TEAM,
            source=ModifierSource.CORE_SKILL,
            source_label="Core: ATK",
        )
        agent = _agent("1131", "Soukaku", base_atk=700, specialty="support")
        build = _build(agent)

        out = _bake_owner_scaled(mod, _ScalingBases(build))

        # Base ATK, not total: level-scaled agent base + core flat ATK, no gear.
        assert out.value == _support_base_atk(build) * 4000 // 10000
        assert out.value > 0
        assert out.scaling_stat is None

    def test_zero_ratio_is_not_baked(self) -> None:
        """Preserves the old `and scaling_ratio > 0` gate — L0 flags the incoherence."""
        mod = Modifier(
            stat="flat_atk",
            value=250,
            scaling_stat="base_atk",
            scaling_ratio=0,
            source=ModifierSource.CORE_SKILL,
            source_label="Core",
        )
        agent = _agent("1131", "Soukaku")

        out = _bake_owner_scaled(mod, _ScalingBases(_build(agent)))

        assert out.value == 250
        assert out.scaling_stat == "base_atk"

    def test_am_excess_bakes_off_the_supplied_am(self) -> None:
        mod = Modifier(
            stat="anomaly_proficiency_flat",
            value=0,
            scaling_stat="anomaly_mastery_excess",
            scaling_ratio=1.5,  # Promeia's core: +1.5 AP per AM above 150
            excess_threshold=150,
            source=ModifierSource.CORE_SKILL,
            source_label="Core: AP",
        )
        agent = _agent("1541", "Promeia", specialty="anomaly")

        out = _bake_owner_scaled(mod, _ScalingBases(_build(agent), anomaly_mastery=200))

        assert out.value == 75  # floor(50 * 1.5)
        assert out.scaling_stat is None

    def test_baking_is_idempotent(self) -> None:
        """Support mods are baked against their own owner before the DPS pass sees them."""
        agent = _agent(BEN, "Ben")
        bases = _ScalingBases(_build(agent))
        mod = next(m for m in load_agent_modifiers(BEN) if m.scaling_stat == "def")

        once = _bake_owner_scaled(mod, bases)
        twice = _bake_owner_scaled(once, bases)

        assert once == twice


class TestSelfTargetScaleFields:
    def test_own_team_buff_is_capped_when_the_owner_is_the_dps(self) -> None:
        """Astra's core caps at 1200 flat ATK or 35% of her own ATK, whichever is lower.

        Her row is `target: team`, so when she is played as the DPS it is collected
        as one of her own modifiers — a path that baked no scale fields at all before
        this task, handing the calc the raw cap (1200) instead of the scaled value.
        """
        astra = _agent(ASTRA, "Astra Yao", base_atk=700, specialty="support", element="ether")
        build = _build(astra)
        snap = build_snapshot_from_db(build, astra)

        core = next(m for m in _flat_atk_mods(snap) if m.source == ModifierSource.CORE_SKILL)

        assert core.atk_scale_ratio == 0  # consumed
        assert core.value == min(1200, _support_total_atk(build) * 3500 // 10000)
        assert core.value < 1200  # scaled, not the bare cap the old path handed over


# ---------------------------------------------------------------------------
# flat_addend → C8 (Task 27, D-KV20) — Lucy's "Cheer On!": min(cap, ratio*ATK + flat)
# ---------------------------------------------------------------------------


class TestFlatAddendCombinesWithAtkScaleRatio:
    def test_flat_addend_adds_to_the_atk_scaled_term_under_the_shared_cap(self) -> None:
        mod = Modifier(
            stat="flat_atk",
            value=9999999,  # cap set high enough to not bind, isolating the sum
            atk_scale_ratio=2500,  # 25% of ATK
            flat_addend=123,
            source=ModifierSource.CORE_SKILL,
            source_label="Core: Cheer On!",
        )
        agent = _agent(BEN, "Ben")
        build = _build(agent)

        out = _bake_owner_scaled(mod, _ScalingBases(build))

        assert out.value == _support_total_atk(build) * 2500 // 10000 + 123
        assert out.atk_scale_ratio == 0  # consumed
        assert out.flat_addend == 0  # consumed

    def test_the_cap_still_wins_over_ratio_plus_flat(self) -> None:
        """One baked value under the shared cap — flat_addend cannot bypass it."""
        agent = _agent(BEN, "Ben", base_atk=100000)  # inflate ATK so ratio*ATK+flat > cap
        build = _build(agent)
        mod = Modifier(
            stat="flat_atk",
            value=50,  # the cap
            atk_scale_ratio=2500,
            flat_addend=123,
            source=ModifierSource.CORE_SKILL,
            source_label="Core: Cheer On!",
        )

        out = _bake_owner_scaled(mod, _ScalingBases(build))

        assert out.value == 50

    def test_flat_addend_defaults_to_zero_no_regression(self) -> None:
        """Existing atk_scale_ratio rows (no flat_addend authored) bake unchanged."""
        astra = _agent(ASTRA, "Astra Yao", base_atk=700, specialty="support", element="ether")
        build = _build(astra)
        mod = Modifier(
            stat="flat_atk",
            value=1200,
            atk_scale_ratio=3500,
            source=ModifierSource.CORE_SKILL,
            source_label="Core: ATK",
        )

        out = _bake_owner_scaled(mod, _ScalingBases(build))

        assert out.value == min(1200, _support_total_atk(build) * 3500 // 10000)
