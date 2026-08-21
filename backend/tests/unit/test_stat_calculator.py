"""F.3 — a build's parts become registered contributions, and the graph totals them.

Driven by the **committed nanoka payloads and the committed YuanShen snapshot**, so these
run offline and assert against the same data the seeded database holds. The end-to-end
check is Ayaka at 90/6: three sources (nanoka's published base, Project Amber's independent
copy of it, and the YuanShen growth curve) meeting at one number.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.formula.genshin import stats, tags
from app.pando.calculator import Calculator, NodeRegistry
from app.services.stat_calculator import (
    ArtifactStats,
    CharacterStats,
    StatInputError,
    WeaponStats,
    add_artifact,
    add_character,
    add_weapon,
    build_log,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"


def _payload(name: str) -> dict:
    return json.loads((_FIX / f"{name}.json").read_text(encoding="utf-8"))


def _ayaka() -> CharacterStats:
    payload = _payload("character_10000002")
    modifier = payload["stats_modifier"]
    return CharacterStats(
        name=payload["name"],
        base_hp=payload["base_hp"],
        base_atk=payload["base_atk"],
        base_def=payload["base_def"],
        prop_curves={
            entry["type"]: entry["grow_curve"] for entry in modifier["prop_grow_curves"]
        },
        ascension_rows=modifier["ascension"],
        elemental_mastery=payload["elemental_mastery"],
        crit_rate=payload["crit_rate"],
        crit_dmg=payload["crit_dmg"],
    )


def _aquila() -> WeaponStats:
    payload = _payload("weapon_11501")
    return WeaponStats(
        name=payload["name"],
        props=payload["weapon_prop"],
        ascension=payload["ascension"],
    )


def _totals(log) -> Calculator:
    return Calculator(registry=log.registry)


# ---- The end-to-end number ------------------------------------------------

def test_ayaka_at_ninety_six_has_the_base_stats_three_sources_agree_on():
    """`published base * curve(90) + ascension[5]`.

    12858 HP / 342 ATK / 784 DEF. Every input is committed: nanoka's base values (which
    Project Amber independently publishes identically), the YuanShen growth curve at the
    pinned commit, and nanoka's ascension row — whose phase-6 identity Amber's
    `promoteLevel: 6` entry confirms.
    """
    log = build_log(NodeRegistry())
    add_character(log, _ayaka(), level=90, ascension_phase=6)
    calculator = _totals(log)

    assert calculator.compute(stats.HP_NODE) == pytest.approx(12858.2, abs=0.1)
    assert calculator.compute(stats.ATK_NODE) == pytest.approx(342.0, abs=0.1)
    assert calculator.compute(stats.DEF_NODE) == pytest.approx(783.9, abs=0.1)


def test_the_ascension_row_also_carries_the_bonus_stat():
    """Ayaka's phase-6 row adds 38.4% CRIT DMG on top of her base 50%."""
    log = build_log(NodeRegistry())
    add_character(log, _ayaka(), level=90, ascension_phase=6)

    assert _totals(log).compute(stats.CRIT_DMG_NODE) == pytest.approx(0.884)


def test_phase_zero_adds_nothing_and_level_one_is_the_published_base():
    log = build_log(NodeRegistry())
    add_character(log, _ayaka(), level=1, ascension_phase=0)
    calculator = _totals(log)

    assert calculator.compute(stats.HP_NODE) == pytest.approx(1000.986)
    assert calculator.compute(stats.CRIT_DMG_NODE) == pytest.approx(0.5)


def test_ascension_row_i_is_phase_i_plus_one():
    """The off-by-one that would be a silent ~9% error at max level.

    Phase 6 must pick the last published row; phase 5 must not.
    """
    rows = _ayaka().ascension_rows
    log_six = build_log(NodeRegistry())
    add_character(log_six, _ayaka(), level=1, ascension_phase=6)
    log_five = build_log(NodeRegistry())
    add_character(log_five, _ayaka(), level=1, ascension_phase=5)

    six = _totals(log_six).compute(stats.HP_NODE) - 1000.986
    five = _totals(log_five).compute(stats.HP_NODE) - 1000.986

    assert six == pytest.approx(rows[5]["fight_prop_base_hp"])
    assert five == pytest.approx(rows[4]["fight_prop_base_hp"])


def test_a_character_starts_at_one_hundred_percent_energy_recharge():
    """gcsim basestat.go:82 — the one base value the payload does not publish."""
    log = build_log(NodeRegistry())
    add_character(log, _ayaka(), level=90, ascension_phase=6)

    assert _totals(log).compute(stats.ENERGY_RECHARGE_NODE) == pytest.approx(1.0)


def test_the_curve_comes_from_the_payload_not_from_the_stats_name():
    """Ayaka's DEF grows on `GROW_CURVE_HP_S5`; Amber says so too.

    Deriving "the DEF curve" from the fact that it is DEF would be wrong for this character
    and right for most, which is the worst way to be wrong.
    """
    curves = _ayaka().prop_curves

    assert curves["FIGHT_PROP_BASE_DEFENSE"] == "GROW_CURVE_HP_S5"
    assert curves["FIGHT_PROP_BASE_ATTACK"] == "GROW_CURVE_ATTACK_S5"


def test_a_character_with_no_published_curve_raises():
    character = CharacterStats(
        name="Curveless", base_hp=1.0, base_atk=1.0, base_def=1.0,
        prop_curves={"FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_S5"}, ascension_rows=[],
    )

    with pytest.raises(StatInputError, match="publishes no growth curve"):
        add_character(build_log(NodeRegistry()), character, level=90, ascension_phase=0)


@pytest.mark.parametrize(
    ("level", "phase"), [(0, 0), (91, 0), (90, 7), (90, -1)],
)
def test_out_of_range_levels_and_phases_are_rejected(level: int, phase: int):
    with pytest.raises(StatInputError, match="outside"):
        add_character(build_log(NodeRegistry()), _ayaka(), level=level, ascension_phase=phase)


# ---- Weapons --------------------------------------------------------------

def test_a_weapons_base_atk_joins_the_characters_before_the_percentage():
    """One `base_atk` pool: `(character + weapon) * (1 + atk%)`."""
    log = build_log(NodeRegistry())
    add_character(log, _ayaka(), level=90, ascension_phase=6)
    add_weapon(log, _aquila(), level=90, ascension_phase=6)

    total = _totals(log).compute(stats.ATK_NODE)
    character_only = 342.0

    assert total > character_only + 600  # Aquila is a 674-base-ATK sword
    assert total == pytest.approx(342.0 + 674.0, abs=1.0)


def test_a_weapons_substat_grows_on_its_own_curve():
    """Aquila's Physical DMG bonus is 9% at level 1 and much more at 90 — it is not flat."""
    at_one = build_log(NodeRegistry())
    add_weapon(at_one, _aquila(), level=1, ascension_phase=0)
    at_ninety = build_log(NodeRegistry())
    add_weapon(at_ninety, _aquila(), level=90, ascension_phase=6)

    node = stats.dmg_bonus_node("physical")
    low = _totals(at_one).compute(node)
    high = _totals(at_ninety).compute(node)

    assert low == pytest.approx(0.09)
    assert high > low * 4


def test_a_weapon_with_no_substat_contributes_only_base_atk():
    """The ten `FIGHT_PROP_NONE` weapons (D.4). Absent is absent, not a stat worth zero."""
    dull_blade = WeaponStats(
        name="Dull Blade",
        props=[
            {"prop_type": "FIGHT_PROP_BASE_ATTACK", "init_value": 23.0,
             "type": "GROW_CURVE_ATTACK_101"},
            {"prop_type": "FIGHT_PROP_NONE", "init_value": 0,
             "type": "GROW_CURVE_CRITICAL_101"},
        ],
    )
    log = build_log(NodeRegistry())
    add_weapon(log, dull_blade, level=1, ascension_phase=0)

    assert [c.quantity for c in log.contributions] == [tags.Q_BASE_ATK]


# ---- Artifacts ------------------------------------------------------------

def test_an_artifacts_main_stat_value_comes_from_the_snapshot_table():
    """A +20 5★ circlet of CRIT DMG is 62.2%, from `artifact_main_stat_values.json`."""
    log = build_log(NodeRegistry())
    add_artifact(log, ArtifactStats(
        slot="equip_dress", rarity=5, level=20, main_stat="FIGHT_PROP_CRITICAL_HURT",
    ))

    assert _totals(log).compute(stats.CRIT_DMG_NODE) == pytest.approx(0.622, abs=0.001)


def test_substats_are_taken_as_rolled():
    log = build_log(NodeRegistry())
    add_artifact(log, ArtifactStats(
        slot="equip_bracer", rarity=5, level=20, main_stat="FIGHT_PROP_HP",
        substats=[
            {"stat": "FIGHT_PROP_CRITICAL", "value": 0.105},
            {"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.099},
        ],
    ))
    calculator = _totals(log)

    assert calculator.compute(stats.CRIT_RATE_NODE) == pytest.approx(0.105)
    assert calculator.compute(stats.HP_NODE) == pytest.approx(4780.0, abs=1.0)


def test_a_five_artifact_build_sums_into_one_pool_per_stat():
    log = build_log(NodeRegistry())
    for slot in ("equip_bracer", "equip_necklace", "equip_shoes", "equip_ring", "equip_dress"):
        add_artifact(log, ArtifactStats(
            slot=slot, rarity=5, level=20, main_stat="FIGHT_PROP_HP",
            substats=[{"stat": "FIGHT_PROP_CRITICAL", "value": 0.05}],
        ))

    assert _totals(log).compute(stats.CRIT_RATE_NODE) == pytest.approx(0.25)


def test_an_unknown_prop_raises_rather_than_being_dropped():
    """D.4's lesson one layer down: a stat this build does not know must not import as none."""
    log = build_log(NodeRegistry())

    with pytest.raises(StatInputError, match="no DAG quantity"):
        add_artifact(log, ArtifactStats(
            slot="equip_ring", rarity=5, level=20, main_stat="FIGHT_PROP_LUNAR_CHARGE",
        ))


# ---- The explanation ------------------------------------------------------

def test_the_build_explains_where_each_number_came_from():
    """A6: the account is built by the same pass that builds the graph."""
    log = build_log(NodeRegistry())
    add_character(log, _ayaka(), level=90, ascension_phase=6)
    add_weapon(log, _aquila(), level=90, ascension_phase=6)

    account = log.explain(tags.Q_BASE_ATK)

    assert "Kamisato Ayaka level 90" in account
    assert "Aquila Favonia level 90" in account
    assert "GROW_CURVE_ATTACK_S5" in account


def test_an_ascension_phase_beyond_the_published_rows_raises():
    """Six rows are published; a seventh phase would be a payload change, not a default."""
    thin = CharacterStats(
        name="Half-ascended", base_hp=1.0, base_atk=1.0, base_def=1.0,
        prop_curves={
            "FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_S5",
            "FIGHT_PROP_BASE_ATTACK": "GROW_CURVE_ATTACK_S5",
            "FIGHT_PROP_BASE_DEFENSE": "GROW_CURVE_HP_S5",
        },
        ascension_rows=[{"fight_prop_base_hp": 10.0}],
    )

    with pytest.raises(StatInputError, match="only 1 rows are published"):
        add_character(build_log(NodeRegistry()), thin, level=1, ascension_phase=3)


def test_the_absent_stat_marker_is_not_a_quantity_outside_a_weapon_prop():
    """Weapons may publish `FIGHT_PROP_NONE`; an artifact main stat may not be nothing."""
    with pytest.raises(StatInputError, match="absent-stat marker"):
        add_artifact(build_log(NodeRegistry()), ArtifactStats(
            slot="equip_ring", rarity=5, level=20, main_stat="FIGHT_PROP_NONE",
        ))
