"""F.8 — this repo's numbers against gcsim's, on a committed fixture.

Two levels, because they fail for different reasons and a single number would not say which:

* **stats** — the build's resolved totals against gcsim's own reported snapshot. A failure
  here means the stat layer, the growth curves, or the seeded data.
* **damage** — one hit's figure against gcsim's total. A failure here *given a passing stats
  level* means the damage chain.

Both read the character, the weapon and the talent multiplier from the **seeded database**,
not from the fixtures. That is the point: crossval validates the pipeline that produced the
database, and a version reading the payloads directly would pass while the importer was
broken.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.formula.genshin import stats as stat_nodes
from app.formula.genshin.damage import Hit
from app.models.character import Character, Talent, TalentScaling
from app.models.enums import TalentType
from app.models.weapon import Weapon
from app.pando.calculator import Calculator, NodeRegistry
from app.services.damage_calculator import BuildEvaluator, Enemy
from app.services.stat_calculator import (
    CharacterStats,
    WeaponStats,
    add_character,
    add_weapon,
    build_log,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "crossval"

#: The gcsim commit these fixtures must have come from — the pin in `docs/CROSSVAL_gcsim.md`.
PINNED_GCSIM = "3647a07a7cc3004bc1e79d9bb5f7444de20dceaa"

#: gcsim's `character_details[].snapshot` is indexed by its `Stat` enum
#: (`pkg/core/attributes/stats.go:12-40`). These four indices were confirmed **empirically**
#: — by adding a known flat HP, ATK%, crit rate and EM to a config and watching which slots
#: moved — rather than counted off the enum, because an off-by-one here would make a passing
#: assertion meaningless.
SNAPSHOT_TOTAL_DEF = 2
SNAPSHOT_TOTAL_HP = 3
SNAPSHOT_TOTAL_ATK = 5
SNAPSHOT_ENERGY_RECHARGE = 7
SNAPSHOT_ELEMENTAL_MASTERY = 8
SNAPSHOT_CRIT_RATE = 9
SNAPSHOT_CRIT_DMG = 10

#: **The tolerance, and its justification.** DESIGN's exit condition for Chunk F asks for
#: exactly this paragraph, so it is a paragraph and not a number someone tuned until green.
#:
#: The case itself is exact — one hit, no rotation, no crit averaging, no artifacts, a
#: weapon with no passive — so both sides evaluate the same closed-form expression. There is
#: nevertheless one **understood, quantified** difference, and it is not arithmetic:
#:
#: > The growth curves this repo uses come from the YuanShenResources dump, which stores
#: > them as the game's binary does: `GROW_CURVE_HP_S5` at level 90 is
#: > `8.73900032043457`, which is *exactly* the float32 representation of `8.739`. gcsim's
#: > data pipeline rounds that back to the decimal `8.739`. Neither is wrong — one is the
#: > value in the binary, the other the value a designer typed — and they differ by
#: > **3.7e-8 relative**, which propagates to ≤2.5e-8 on any stat and on the damage figure.
#:
#: 1e-7 covers that with room and is still **five orders of magnitude** tighter than any
#: formula error could be: the smallest plausible mistake — a dropped 10% resistance, the
#: wrong ascension row, a missing substat — moves the answer by percent, not by parts per
#: ten-million. A tolerance that could hide a formula error would make the exercise
#: decorative, and this one demonstrably cannot: with the enemy's resistance dropped, the
#: figure moves by 10%, six orders of magnitude outside it.
#:
#: Crit rate and crit DMG, which no curve touches, agree **bit for bit** — which is the
#: check that the residual really is curve provenance and not something structural.
#:
#: Cases that add a rotation or crit averaging will need a looser, separately argued number.
#: Do not widen this one to accommodate them; add the case with its own tolerance and say why.
RELATIVE_TOLERANCE = 1e-7


def _case(name: str) -> dict:
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


async def _ayaka_dull_blade(session: AsyncSession):
    """The `ayaka_normal_1` build, assembled from **seeded rows**."""
    character = await session.scalar(
        select(Character).where(Character.nanoka_id == "10000002"),
    )
    weapon = await session.scalar(select(Weapon).where(Weapon.nanoka_id == 11101))
    if character is None or weapon is None:
        pytest.fail(
            "the seeded database has no Ayaka (10000002) or Dull Blade (11101); "
            "re-run `python -m scripts.seed_db`",
        )

    log = build_log(NodeRegistry())
    add_character(log, CharacterStats(
        name=character.name,
        base_hp=character.base_hp,
        base_atk=character.base_atk,
        base_def=character.base_def,
        prop_curves=character.prop_curves,
        ascension_rows=character.ascension_stats,
        elemental_mastery=character.base_elemental_mastery,
        crit_rate=character.base_crit_rate,
        crit_dmg=character.base_crit_dmg,
    ), level=90, ascension_phase=6)
    add_weapon(log, WeaponStats(
        name=weapon.name,
        props=[
            {"prop_type": "FIGHT_PROP_BASE_ATTACK", "init_value": weapon.base_atk,
             "type": weapon.base_atk_curve},
            {"prop_type": weapon.sub_stat_type, "init_value": weapon.sub_stat_base_value,
             "type": weapon.sub_stat_curve},
        ],
        ascension=weapon.ascension_atk,
    ), level=70, ascension_phase=4)
    return log, character


async def _first_normal_attack_multiplier(session: AsyncSession, character_id: str) -> float:
    """Ayaka's 1-Hit DMG at talent level 1, **from the seeded talent scaling table**."""
    talent = await session.scalar(
        select(Talent).where(
            Talent.character_id == character_id,
            Talent.talent_type == TalentType.NORMAL_ATTACK,
        ),
    )
    scaling = await session.scalar(
        select(TalentScaling).where(
            TalentScaling.talent_id == talent.id, TalentScaling.level == 1,
        ),
    )
    # `labels[0]` is `"1-Hit DMG|{param1:F1P}"`; `params[0]` is what it refers to.
    assert scaling.labels[0].startswith("1-Hit DMG"), scaling.labels[0]
    return float(scaling.params[0])


# ---- The fixture is what it claims to be ----------------------------------

def test_the_fixture_came_from_the_pinned_gcsim():
    """A fixture from a patched or unpinned gcsim is not an oracle.

    gcsim writes both fields itself, so this is the oracle's own account of what produced it.
    """
    case = _case("ayaka_normal_1")

    assert case["sim_version"] == PINNED_GCSIM
    assert case["modified"] is False


def test_the_committed_config_is_the_one_that_produced_the_fixture():
    """The `.txt` is re-runnable and the JSON embeds what it was actually run with; if they
    drift, the config someone re-runs is not the one the numbers came from."""
    case = _case("ayaka_normal_1")
    config = (_FIXTURES / "ayaka_normal_1.txt").read_text(encoding="utf-8")

    assert case["config_file"].strip() == config.strip()


# ---- Level 1: stats -------------------------------------------------------

async def test_the_stat_layer_matches_gcsims_snapshot(crossval_session: AsyncSession):
    """Every total gcsim reports for this build, from rows the importer wrote."""
    log, _ = await _ayaka_dull_blade(crossval_session)
    calculator = Calculator(registry=log.registry)
    snapshot = _case("ayaka_normal_1")["character_details"][0]["snapshot"]

    # Crit rate and crit DMG are asserted **exactly**: no growth curve touches them, so the
    # float32-vs-decimal provenance difference cannot apply, and an exact match there is what
    # tells you the residual on the others is curve storage rather than arithmetic.
    for index, node, label in (
        (SNAPSHOT_CRIT_RATE, stat_nodes.CRIT_RATE_NODE, "crit rate"),
        (SNAPSHOT_CRIT_DMG, stat_nodes.CRIT_DMG_NODE, "crit DMG"),
        (SNAPSHOT_ENERGY_RECHARGE, stat_nodes.ENERGY_RECHARGE_NODE, "energy recharge"),
    ):
        assert calculator.compute(node) == snapshot[index], f"{label} disagrees with gcsim"

    for index, node, label in (
        (SNAPSHOT_TOTAL_HP, stat_nodes.HP_NODE, "HP"),
        (SNAPSHOT_TOTAL_ATK, stat_nodes.ATK_NODE, "ATK"),
        (SNAPSHOT_TOTAL_DEF, stat_nodes.DEF_NODE, "DEF"),
        (SNAPSHOT_ELEMENTAL_MASTERY, stat_nodes.ELEMENTAL_MASTERY_NODE, "elemental mastery"),
    ):
        assert calculator.compute(node) == pytest.approx(
            snapshot[index], rel=RELATIVE_TOLERANCE,
        ), f"{label} disagrees with gcsim"


# ---- Level 2: damage ------------------------------------------------------

async def test_one_normal_attack_matches_gcsims_damage(crossval_session: AsyncSession):
    """**The Chunk F exit condition.**

    Ayaka's first normal-attack hit, computed from seeded rows, against gcsim's reported
    total for the same config. Physical damage, so nothing here depends on elemental
    application or reactions; one hit, so nothing depends on rotation or crit averaging.
    """
    log, character = await _ayaka_dull_blade(crossval_session)
    multiplier = await _first_normal_attack_multiplier(crossval_session, character.id)
    case = _case("ayaka_normal_1")
    expected = case["statistics"]["total_damage"]["mean"]

    result = BuildEvaluator(
        registry=log.registry,
        enemy=Enemy(level=90, resistances=dict.fromkeys(
            ("anemo", "cryo", "dendro", "electro", "geo", "hydro", "physical", "pyro"), 0.1,
        )),
        character_level=90,
    ).evaluate(Hit(multiplier=multiplier, channel="physical", scope="normal"))

    assert result.non_crit == pytest.approx(expected, rel=RELATIVE_TOLERANCE), (
        f"crossval mismatch\n{result.explain()}\n  gcsim: {expected}"
    )


async def test_the_crossval_hit_did_not_crit_in_gcsim(crossval_session: AsyncSession):
    """Which of the three figures to compare is a decision, not a detail.

    gcsim rolls crit; this repo reports non-crit, crit and expected. The fixture's single
    hit did **not** crit — Ayaka's base rate is 5% — so `non_crit` is the comparable field.
    If a regenerated fixture ever crits, this test says so instead of the damage test
    failing by exactly `1 + crit_dmg` and looking like a formula error.
    """
    log, character = await _ayaka_dull_blade(crossval_session)
    multiplier = await _first_normal_attack_multiplier(crossval_session, character.id)
    expected = _case("ayaka_normal_1")["statistics"]["total_damage"]["mean"]

    result = BuildEvaluator(
        registry=log.registry,
        enemy=Enemy(level=90, resistances=dict.fromkeys(
            ("anemo", "cryo", "dendro", "electro", "geo", "hydro", "physical", "pyro"), 0.1,
        )),
        character_level=90,
    ).evaluate(Hit(multiplier=multiplier, channel="physical", scope="normal"))

    assert abs(result.crit - expected) > abs(result.non_crit - expected)


# ---- Why the tolerance is not zero ----------------------------------------

def test_the_residual_is_float32_curve_storage_and_nothing_else():
    """Pins the *cause* of the tolerance, so nobody later "fixes" the snapshot.

    `GROW_CURVE_HP_S5` at level 90 is `8.73900032043457` in the YuanShenResources dump —
    exactly the float32 representation of `8.739`, which is what gcsim's data pipeline
    stores. One value is what the game's binary holds; the other is what a designer typed.

    This repo keeps the datamined one: rounding it to look tidier would be inventing a
    number, and the whole snapshot exists so that values are read rather than chosen.
    """
    import struct

    from app.data.snapshot import growth_curve

    datamined = growth_curve("avatar", "GROW_CURVE_HP_S5", 90)
    float32_of_decimal = struct.unpack("f", struct.pack("f", 8.739))[0]

    assert datamined == float32_of_decimal
    assert datamined != 8.739
    assert abs(datamined - 8.739) / 8.739 < RELATIVE_TOLERANCE


async def test_the_tolerance_cannot_hide_a_formula_error(crossval_session: AsyncSession):
    """A tolerance that could absorb a real mistake would make the exercise decorative.

    Dropping the enemy's resistance — the smallest single error available — moves the figure
    by 10%, six orders of magnitude outside the tolerance. If this test ever passes, the
    tolerance has been widened past the point of meaning anything.
    """
    log, character = await _ayaka_dull_blade(crossval_session)
    multiplier = await _first_normal_attack_multiplier(crossval_session, character.id)
    expected = _case("ayaka_normal_1")["statistics"]["total_damage"]["mean"]

    wrong = BuildEvaluator(
        registry=log.registry,
        enemy=Enemy(level=90, resistances=dict.fromkeys(
            ("anemo", "cryo", "dendro", "electro", "geo", "hydro", "physical", "pyro"), 0.0,
        )),
        character_level=90,
    ).evaluate(Hit(multiplier=multiplier, channel="physical", scope="normal"))

    assert wrong.non_crit != pytest.approx(expected, rel=RELATIVE_TOLERANCE)
    assert abs(wrong.non_crit - expected) / expected > 0.1
