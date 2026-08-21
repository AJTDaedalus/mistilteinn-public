"""Attribution-invariant test suite — the standing guard from DESIGN_explainability.md
§6 / TASKS_explainability.md Task A2 (hard deliverable).

For every calculation path (standard, anomaly, sheer, disorder), attribution.py
builds its ZoneAttribution sums via a completely separate code path from the
one build_damage_service.py uses to actually compute the damage. This suite
proves those two paths agree: feeding attribution's independently-summed zone
totals through the *same* clamp/floor formula functions the calculator itself
calls must reproduce the calculator's own `*_mult` fields exactly (integer bp,
not approximate). It also proves `zone_formulas.result_bp` never disagrees
with the field it describes. Any future change that lets attribution.py drift
from the real arithmetic — a missed buff bucket, a double-counted
contribution — fails this suite.

Representative builds/paths (DESIGN §6): Burnice/Burn, Jane/Assault,
Vivian/Corruption for the anomaly path; Yanagi/Disorder for the disorder path
(via calculate_disorder_damage directly, mirroring how anomaly_simulator.py
itself calls it — no full aura state machine needed for this invariant);
a standard DPS build; a Rupture/sheer build. Vortex is out of scope per
TASKS A2 (DESIGN lists it as optional "if the sim emits it").
"""

from __future__ import annotations

import dataclasses
import math
from types import SimpleNamespace

import pytest

from app.services.attribution import ZoneAttribution, build_step_attribution
from app.services.buff_resolver import Contribution
from app.services.build_damage_service import (
    BuildSnapshot,
    EnemySnapshot,
    _resolve_and_calc,
    calculate_build_anomaly,
    calculate_build_damage,
    calculate_build_sheer,
)
from app.services.build_delta import compute_build_delta
from app.services.damage_calculator import (
    AnomalyType,
    calculate_disorder_damage,
    crit_multiplier,
    def_multiplier,
    dmg_bonus_multiplier,
    dmg_taken_multiplier,
    res_multiplier,
    stun_multiplier,
)
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)

# ---------------------------------------------------------------------------
# Shared fixtures — representative builds with non-trivial buffs in every zone
# so the invariant actually gets exercised (zero-buff cases are covered by
# test_zone_formulas.py already).
# ---------------------------------------------------------------------------


def _mod(stat: str, value: int) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.CORE_SKILL,
        source_label="test buff",
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


_REPRESENTATIVE_MODIFIERS = [
    _mod("atk_pct", 2000),
    _mod("crit_rate", 1500),
    _mod("crit_dmg", 3000),
    _mod("dmg_bonus", 1200),
    _mod("vulnerability", 800),
    _mod("res_reduction", 600),
    _mod("res_ignore", 200),
    _mod("pen_ratio", 500),
    _mod("def_ignore", 400),
    _mod("stun_dmg_mult_bonus", 300),
    _mod("anomaly_dmg_bonus", 1000),
]

_REPRESENTATIVE_DISCS = [
    {
        "main_stat_type": "crit_rate",
        "main_stat_value": 2400,
        "substats": [{"stat": "pen_flat", "value": 19}, {"stat": "atk_pct", "value": 300}],
    },
]


def _snap(**overrides) -> BuildSnapshot:
    defaults = {
        "agent_base_atk": 900,
        "wengine_base_atk": 600,
        "agent_base_hp": 8000,
        "agent_crit_rate": 500,
        "agent_crit_dmg": 5000,
        "agent_anomaly_proficiency": 140,
        "agent_level": 60,
        "modifiers": list(_REPRESENTATIVE_MODIFIERS),
        "disc_stats": [dict(d) for d in _REPRESENTATIVE_DISCS],
    }
    defaults.update(overrides)
    return BuildSnapshot(**defaults)


def _enemy(**overrides) -> EnemySnapshot:
    defaults = {"level": 60, "base_def": 500, "element_res": 2000}
    defaults.update(overrides)
    return EnemySnapshot(**defaults)


# ---------------------------------------------------------------------------
# Reconstruction helpers — recompute each zone's multiplier from attribution's
# independently-summed contributions, through the exact same pure functions
# the calculator itself uses, and assert equality with the calculator's field.
# ---------------------------------------------------------------------------


def _assert_boost_invariant(attribution, damage) -> None:
    assert dmg_bonus_multiplier([attribution.boost_bonuses.total]) == damage.boost_mult


def _assert_sheer_boost_invariant(attribution, damage) -> None:
    assert dmg_bonus_multiplier([attribution.sheer_boost_bonuses.total]) == damage.sheer_boost_mult


def _assert_crit_invariant(attribution, damage) -> None:
    reconstructed = crit_multiplier(attribution.crit_rate.total, attribution.crit_dmg.total)
    assert reconstructed == damage.crit_mult


def _assert_def_invariant(attribution, damage, build: BuildSnapshot, enemy: EnemySnapshot) -> None:
    reconstructed = def_multiplier(
        build.agent_level,
        enemy.base_def,
        enemy.level,
        pen_ratio=attribution.pen_ratio.total,
        pen_flat=attribution.pen_flat.total,
        def_ignore=attribution.def_ignore.total,
    )
    assert reconstructed == damage.def_mult


def _assert_res_invariant(attribution, damage, enemy: EnemySnapshot) -> None:
    reconstructed = res_multiplier(
        enemy.element_res,
        res_reduction=attribution.res_reduction.total,
        res_ignore=attribution.res_ignore.total,
    )
    assert reconstructed == damage.res_mult


def _assert_vulnerability_invariant(attribution, damage) -> None:
    assert dmg_taken_multiplier([attribution.vulnerability.total]) == damage.vulnerability_mult


def _assert_stun_invariant(
    attribution, damage, *, is_stunned: bool, base_stun_dmg_mult: int
) -> None:
    if is_stunned:
        reconstructed = stun_multiplier(True, base_stun_dmg_mult + attribution.stun_bonuses.total)
    else:
        reconstructed = stun_multiplier(False, base_stun_dmg_mult)
    assert reconstructed == damage.stun_mult


def _assert_zone_formulas_match(attribution, damage, *, zone_to_field: dict[str, str]) -> None:
    for zone, field_name in zone_to_field.items():
        assert attribution.zone_formulas[zone].result_bp == getattr(damage, field_name), (
            f"zone_formulas[{zone!r}].result_bp disagrees with damage.{field_name}"
        )


# ---------------------------------------------------------------------------
# Standard path
# ---------------------------------------------------------------------------


class TestStandardPathInvariant:
    def test_full_invariant(self):
        build = _snap(agent_element="physical", agent_specialty="attack")
        enemy = _enemy()
        result = calculate_build_damage(
            build=build,
            enemy=enemy,
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            is_stunned=True,
            stun_dmg_mult=15000,
            with_attribution=True,
        )
        attr = result.attribution
        damage = result.damage

        _assert_boost_invariant(attr, damage)
        _assert_crit_invariant(attr, damage)
        _assert_def_invariant(attr, damage, build, enemy)
        _assert_res_invariant(attr, damage, enemy)
        _assert_vulnerability_invariant(attr, damage)
        _assert_stun_invariant(attr, damage, is_stunned=True, base_stun_dmg_mult=15000)
        _assert_zone_formulas_match(
            attr,
            damage,
            zone_to_field={
                "base": "base_dmg",
                "boost": "boost_mult",
                "crit": "crit_mult",
                "def": "def_mult",
                "res": "res_mult",
                "vulnerability": "vulnerability_mult",
                "stun": "stun_mult",
            },
        )


# ---------------------------------------------------------------------------
# Anomaly path — Burnice/Burn, Jane/Assault, Vivian/Corruption
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("agent_name", "element", "anomaly_type"),
    [
        ("Burnice", "fire", "burn"),
        ("Jane", "physical", "assault"),
        ("Vivian", "ether", "corruption"),
    ],
)
class TestAnomalyPathInvariant:
    def test_full_invariant(self, agent_name: str, element: str, anomaly_type: str):
        build = _snap(agent_name=agent_name, agent_element=element, agent_specialty="anomaly")
        enemy = _enemy()
        result = calculate_build_anomaly(
            build=build,
            enemy=enemy,
            anomaly_type=anomaly_type,
            conditions=ActiveConditions(),
            is_stunned=True,
            stun_dmg_mult=15000,
            with_attribution=True,
        )
        attr = result.attribution
        damage = result.damage

        _assert_boost_invariant(attr, damage)
        _assert_def_invariant(attr, damage, build, enemy)
        _assert_res_invariant(attr, damage, enemy)
        _assert_vulnerability_invariant(attr, damage)
        _assert_stun_invariant(attr, damage, is_stunned=True, base_stun_dmg_mult=15000)
        _assert_zone_formulas_match(
            attr,
            damage,
            zone_to_field={
                "base": "base_dmg",
                "boost": "boost_mult",
                "def": "def_mult",
                "res": "res_mult",
                "vulnerability": "vulnerability_mult",
                "stun": "stun_mult",
                "anomaly_prof": "anomaly_prof_mult",
                "anomaly_level": "level_mult",
                "anomaly_boost": "anomaly_boost_mult",
            },
        )


# ---------------------------------------------------------------------------
# Sheer path (Rupture)
# ---------------------------------------------------------------------------


class TestSheerPathInvariant:
    def test_full_invariant(self):
        build = _snap(
            agent_name="Yixuan",
            agent_element="ether",
            agent_specialty="rupture",
            agent_sheer_force_hp_ratio=1000,
        )
        enemy = _enemy()
        result = calculate_build_sheer(
            build=build,
            enemy=enemy,
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            is_stunned=True,
            stun_dmg_mult=15000,
            with_attribution=True,
        )
        attr = result.attribution
        damage = result.damage

        _assert_boost_invariant(attr, damage)
        _assert_sheer_boost_invariant(attr, damage)
        _assert_crit_invariant(attr, damage)
        _assert_res_invariant(attr, damage, enemy)
        _assert_vulnerability_invariant(attr, damage)
        _assert_stun_invariant(attr, damage, is_stunned=True, base_stun_dmg_mult=15000)
        _assert_zone_formulas_match(
            attr,
            damage,
            zone_to_field={
                "base": "base_dmg",
                "boost": "boost_mult",
                "crit": "crit_mult",
                "res": "res_mult",
                "vulnerability": "vulnerability_mult",
                "stun": "stun_mult",
                "sheer_force": "sheer_force",
                "sheer_boost": "sheer_boost_mult",
            },
        )
        assert "def" not in attr.zone_formulas


# ---------------------------------------------------------------------------
# Disorder path — Yanagi/Disorder (electric). No public calculate_build_disorder
# wrapper exists; mirrors anomaly_simulator.py's own inline pattern
# (_resolve_and_calc + calculate_disorder_damage + build_step_attribution).
# ---------------------------------------------------------------------------


class TestDisorderPathInvariant:
    def test_full_invariant(self):
        build = _snap(agent_name="Yanagi", agent_element="electric", agent_specialty="anomaly")
        enemy = _enemy()
        ctx = _resolve_and_calc(build, ActiveConditions(), AttackScope.ALL)

        damage = calculate_disorder_damage(
            anomaly_type=AnomalyType.SHOCK,
            atk=ctx.stats.atk,
            anomaly_proficiency=ctx.stats.anomaly_proficiency,
            attacker_level=build.agent_level,
            dmg_bonuses=ctx.dmg_bonuses,
            anomaly_dmg_bonus=ctx.buffs.anomaly_dmg_bonus,
            disorder_dmg_bonus=0,
            enemy_base_def=enemy.base_def,
            enemy_level=enemy.level,
            pen_ratio=ctx.stats.pen_ratio,
            pen_flat=ctx.stats.pen_flat,
            def_ignore=ctx.buffs.def_ignore,
            enemy_res=enemy.element_res,
            res_reduction=ctx.buffs.res_reduction,
            res_ignore=ctx.buffs.res_ignore,
            vulnerability_bonuses=ctx.vuln_bonuses,
            is_stunned=True,
            # Mirrors anomaly_simulator.py's own disorder call sites, which add
            # buffs.stun_dmg_mult_bonus on top of the base before calling the
            # low-level calculator (calculate_build_damage/_anomaly/_sheer do
            # the same internally) — the assertion helper below expects the
            # *base* (pre-bonus) value and reconstructs the bonus separately
            # from attribution.stun_bonuses.total.
            stun_dmg_mult=15000 + ctx.buffs.stun_dmg_mult_bonus,
            remaining_duration=5.0,
            max_duration=10.0,
        )
        attr = build_step_attribution(
            build,
            ctx.stats,
            ctx.disc,
            ctx.buffs,
            is_anomaly=True,
            damage=damage,
            multiplier=0,
            enemy_res=enemy.element_res,
        )

        _assert_boost_invariant(attr, damage)
        _assert_def_invariant(attr, damage, build, enemy)
        _assert_res_invariant(attr, damage, enemy)
        _assert_vulnerability_invariant(attr, damage)
        _assert_stun_invariant(attr, damage, is_stunned=True, base_stun_dmg_mult=15000)
        _assert_zone_formulas_match(
            attr,
            damage,
            zone_to_field={
                "base": "base_dmg",
                "boost": "boost_mult",
                "def": "def_mult",
                "res": "res_mult",
                "vulnerability": "vulnerability_mult",
                "stun": "stun_mult",
                "anomaly_prof": "anomaly_prof_mult",
                "anomaly_level": "level_mult",
                "anomaly_boost": "anomaly_boost_mult",
                "disorder_boost": "disorder_boost_mult",
            },
        )


# ---------------------------------------------------------------------------
# Prove the guard bites — a corrupted attribution must fail the invariant.
# ---------------------------------------------------------------------------


class TestInvariantCatchesDrift:
    def test_corrupted_boost_attribution_fails(self):
        build = _snap(agent_element="physical", agent_specialty="attack")
        enemy = _enemy()
        result = calculate_build_damage(
            build=build,
            enemy=enemy,
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        attr = result.attribution

        # Sanity: the real attribution passes before we corrupt anything.
        _assert_boost_invariant(attr, result.damage)

        corrupted = dataclasses.replace(
            attr,
            boost_bonuses=ZoneAttribution(
                contributions=[
                    *attr.boost_bonuses.contributions,
                    Contribution(source="injected drift", value=999),
                ]
            ),
        )
        with pytest.raises(AssertionError):
            _assert_boost_invariant(corrupted, result.damage)

    def test_corrupted_zone_formula_fails(self):
        build = _snap(agent_element="physical", agent_specialty="attack")
        enemy = _enemy()
        result = calculate_build_damage(
            build=build,
            enemy=enemy,
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        attr = result.attribution
        corrupted_formulas = dict(attr.zone_formulas)
        corrupted_formulas["crit"] = dataclasses.replace(
            corrupted_formulas["crit"], result_bp=corrupted_formulas["crit"].result_bp + 1
        )
        corrupted = dataclasses.replace(attr, zone_formulas=corrupted_formulas)

        with pytest.raises(AssertionError):
            _assert_zone_formulas_match(
                corrupted, result.damage, zone_to_field={"crit": "crit_mult"}
            )


# ---------------------------------------------------------------------------
# Delta decomposition (Task B4, DESIGN §3.2) — TASKS A2 requires these
# assertions live in this invariant suite too. Uses real calculator output
# (not the hand-crafted floor-safe fixtures in test_build_delta.py) to prove
# the math holds against the actual damage_calculator arithmetic, not just an
# idealized one. Note: because calculate_standard_damage applies a *sequence*
# of floor divisions (each depending on the running total so far), changing
# one zone's bp value shifts every subsequent floor's rounding by a fraction
# of a unit — `from_total * prod(ratios)` therefore lands *extremely* close
# to `to_total` (sub-0.01% relative error for realistic totals) but is not
# bit-exact the way the hand-crafted fixtures are. Asserted with a tolerance
# accordingly; an unmoved zone's ratio/share, which never touches that
# rounding, is still asserted bit-exact.
# ---------------------------------------------------------------------------


class TestBuildDeltaInvariant:
    def _step(self, result):
        return SimpleNamespace(attribution=result.attribution)

    def test_single_zone_change_reconstructs_and_sums_to_100_pct(self):
        # Deliberately large ATK relative to the other _snap()/_enemy() defaults
        # -- with the tiny default stats, damage.total is only ~100-150, and
        # the floor-division noise described above (individually a fraction
        # of a bp) becomes a large fraction of *that* total. Scaling ATK up
        # keeps the same zone multipliers but makes floor noise negligible
        # relative to the total, which is what the tolerances below assume.
        enemy = _enemy()
        from_build = _snap(
            agent_element="physical",
            agent_specialty="attack",
            agent_base_atk=90_000,
            wengine_base_atk=60_000,
        )
        to_build = _snap(
            agent_element="physical",
            agent_specialty="attack",
            agent_base_atk=90_000,
            wengine_base_atk=60_000,
            modifiers=[*_REPRESENTATIVE_MODIFIERS, _mod("atk_pct", 1500)],
        )

        from_result = calculate_build_damage(
            build=from_build,
            enemy=enemy,
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            is_stunned=True,
            stun_dmg_mult=15000,
            with_attribution=True,
        )
        to_result = calculate_build_damage(
            build=to_build,
            enemy=enemy,
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            is_stunned=True,
            stun_dmg_mult=15000,
            with_attribution=True,
        )

        delta = compute_build_delta(
            [self._step(from_result)],
            [self._step(to_result)],
            from_total=from_result.damage.total,
            to_total=to_result.damage.total,
        )

        by_zone = {z.zone: z for z in delta.zone_deltas}
        # stun_dmg_mult/base_stun_dmg_mult are identical in both runs, so the
        # "stun" zone is untouched — bit-exact ratio 1.0 / share 0.
        assert by_zone["stun"].ratio == 1.0
        assert by_zone["stun"].gain_share_pct == 0.0

        assert sum(z.gain_share_pct for z in delta.zone_deltas) == pytest.approx(
            100.0, abs=0.01
        )
        product = math.prod(z.ratio for z in delta.zone_deltas)
        assert delta.from_total * product == pytest.approx(delta.to_total, rel=1e-4)
