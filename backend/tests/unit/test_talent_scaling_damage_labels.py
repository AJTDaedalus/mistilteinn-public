"""Damage rows whose label does not say `DMG` (math-fallback P0 follow-up, P1).

The parser decided damage by `"DMG" in label`, so Neuvillette's `Charged Attack: Equitable
Judgment` and every bow user's `Aimed Shot` / `Fully-Charged Aimed Shot` were never offered as
hits. The fix is an **exact** list of eleven labels, not a looser rule, and every other
percentage row without `DMG` must be accounted for as non-damage or it is refused by name.

The survey below is every distinct percentage-formatted, `DMG`-less level-1 label in the seeded
catalogue (nanoka 7.2.51, 2026-11-13) — 91 labels, 11 damage and 80 not.
`scripts.gcsim.crossval_multipliers` against that seed: **20,906 hits matched** (20,021 before),
**0 mismatched, 0 refused**, 1,065 scaling stats checked (1,050 before — the 15 new ones are
Equitable Judgment's Max HP at every level).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.formula.genshin.damage import ScalingStat
from app.services.talent_scaling import (
    _DAMAGE_WITHOUT_DMG,
    classify_talent_row,
    parse_talent_row,
)

_SNAPSHOT = (
    Path(__file__).resolve().parents[2] / "app" / "data" / "gcsim" / "talent_multipliers.json"
)

#: The previously-excluded rows that are now hits, with what each scales off. Level-1 counts
#: over the seeded catalogue in the comment: 64 hits across 34 released characters and one
#: beta character.
NEWLY_OFFERED: dict[str, ScalingStat] = {
    "Aimed Shot": ScalingStat.ATK,  # 22 characters
    "Aimed Shot Charge Level 1": ScalingStat.ATK,  # Ganyu, Lyney, Sethos
    "Fully-Charged Aimed Shot": ScalingStat.ATK,  # 18
    "Level 1 Aimed Shot": ScalingStat.ATK,  # Tighnari
    "Charged Attack": ScalingStat.ATK,  # Hu Tao, Heizou, Yanfei (5 alternatives), Yun Jin
    "Charged Attack: Equitable Judgment": ScalingStat.HP,  # Neuvillette
    "DoT": ScalingStat.ATK,  # Diluc, Kazuha, Mona, Shenhe, Sucrose, Venti, Xinyan
    "Ice Lance DoT": ScalingStat.ATK,  # Rosaria
    "Pyro DoT": ScalingStat.ATK,  # Xinyan
    "Coda at Dawn's Tolling DoT": ScalingStat.ATK,  # Odette
    "Riptide Slash": ScalingStat.ATK,  # Tartaglia
}

#: The other 80 surveyed labels: healing, costs, shields, buffs, debuffs, thresholds.
NOT_DAMAGE = [
    "ATK Bonus", "ATK Bonus Ratio", "ATK Decrease", "ATK Increase", "ATK SPD Bonus",
    "Activation Cost", "Additional Shield Absorption", "Adeptal Legacy White Jade Radish Healing",
    "Amount of HP Restored", "Anemo RES Decrease", "Blazing Threshold",
    "Bolstering Bubblebalm Healing", "Bond of Life Conversion", "Bond of Life Gain",
    "Cast Healing", "Continuous Healing", "Continuous Regeneration",
    "Continuous Regeneration Per Sec", "Cryo RES Decrease", "DEF Bonus",
    "Damage Reduction Ratio", "Dendro RES Bonus", "Eagleplume Healing", "Electro RES Bonus",
    "Elemental RES Decrease", "Energy Recharge Bonus", "Energy Recharge Increase",
    "Fanfare to Incoming Healing Bonus Conversion Ratio", "Field Activation Healing",
    "Final Bounce Healing", "Gentilhomme Usher HP Consumption",
    "Grace of Kenosis ATK Bonus Ratio", "Grass Ring of Sanctification Healing",
    "Grin-Malkin Hat Inherited HP", "HP Cost", "HP Loss", "HP Regeneration",
    "HP Regeneration Over Time", "HP Regeneration Per Hit", "HP Restored", "Healing",
    "Healing Triggering Chance", "High Nightsoul Points ATK Conversion Rate",
    "Hunter's Precision ATK Bonus", "Hydro/Cryo RES Reduction", "Impale the Night Healing",
    "Inherited HP", "Initial Healing Amount", "Kamera Continuous Regeneration", "Life Drain",
    "Low HP Skill Regeneration", "Low Nightsoul Points ATK Conversion Rate",
    "Lowest HP Character Additional Healing", "Mademoiselle Crabaletta HP Consumption",
    "Masque of the Red Death Increase", "Mitigation", "Muji-Muji Daruma Healing",
    "Normal ATK SPD Bonus", "Physical RES Decrease",
    "Purrsonal Coordinated Assistance Robot Healing", "RES Decrease",
    "Redmane's Blood Maximum", "Regeneration", "Regeneration on Hit", "Resolve Bonus",
    "Scarlet Seal Stamina Consumption Decrease", "Scorching Threshold",
    "Seamless Shield Healing", "Serpent's Subtlety Bonus", "Singer of Many Waters Healing",
    "Skill Activation Healing", "Skill HP Regeneration", "Skill Healing",
    "Snack Pick-Up HP Regeneration", "Song of Ages Past Healing", "Suffusion HP Cost",
    "Surintendante Chevalmarin HP Consumption", "Swift Hunt Bond of Life Gain",
    "Tonicshot Healing On Hit", "White Jade Radish Healing",
]


def test_the_newly_offered_labels_are_exactly_the_reviewed_list():
    assert set(NEWLY_OFFERED) == _DAMAGE_WITHOUT_DMG
    assert len(NOT_DAMAGE) == 80


def test_neuvillettes_equitable_judgment_is_a_max_hp_hit():
    """The row named in the P0 follow-up. gcsim's tail for the same table is `Max HP`."""
    hits = parse_talent_row(["Charged Attack: Equitable Judgment|{param1:F2P} Max HP"], [0.073186])
    assert len(hits) == 1
    assert hits[0].scaling_stat is ScalingStat.HP
    assert hits[0].multiplier == pytest.approx(0.073186)


def test_yelans_aimed_shots_are_hits():
    hits = parse_talent_row(
        ["Aimed Shot|{param1:F1P}", "Fully-Charged Aimed Shot|{param2:F1P}", "CD|{param3:F1}s"],
        [0.4386, 1.24, 10.0],
    )
    assert [(h.label, h.multiplier, h.scaling_stat) for h in hits] == [
        ("Aimed Shot", 0.4386, ScalingStat.ATK),
        ("Fully-Charged Aimed Shot", 1.24, ScalingStat.ATK),
    ]


@pytest.mark.parametrize(("label", "stat"), sorted(NEWLY_OFFERED.items()))
def test_each_newly_offered_label_scales_off_what_gcsims_tail_says(label, stat):
    """Cross-checked against gcsim's tables, not reviewed by eye.

    Every label but `Riptide Slash` has a gcsim table of the same name, and every one of those
    tables' tails names the stat listed here (an empty tail is ATK).
    """
    tails = {
        table["tail"]
        for tables in json.loads(_SNAPSHOT.read_text())["characters"].values()
        for table in tables
        if table["label"] == label
    }
    if label == "Riptide Slash":
        assert not tails
        return
    assert tails, f"gcsim has no table labelled {label!r}"
    words = {"": ScalingStat.ATK, "Max HP": ScalingStat.HP}
    # Only the words before the first `/` describe this table; the rest are other alternatives.
    assert {words[tail.split("/", 1)[0].strip()] for tail in tails} == {stat}


@pytest.mark.parametrize("label", NOT_DAMAGE)
def test_a_surveyed_non_damage_row_stays_out_and_is_not_refused(label):
    row = classify_talent_row([f"{label}|{{param1:F1P}}"], [0.25])
    assert row.hits == []
    assert row.refused == []


@pytest.mark.parametrize(
    "entry",
    [
        "Duration|{param1:F1}s",
        "CD|{param1:F1}s",
        "Interval|{param1:F1}s",
        "Energy Cost|{param1:I}",
        "Charged Attack Stamina Cost|{param1:F1}",
        "Shield DMG Absorption|{param1:P} Max HP+{param2:I}",
        "Healing|{param1:P} Max HP+{param2:I}",
    ],
)
def test_durations_cds_costs_healing_and_shields_are_not_hits(entry):
    row = classify_talent_row([entry], [0.25, 100.0])
    assert row.hits == []
    assert row.refused == []


def test_an_unknown_percentage_label_is_refused_by_name():
    """The next patch's wording arrives red in crossval_multipliers, not as a silent skip."""
    row = classify_talent_row(["Stellar Lance Strike|{param1:F1P}"], [1.5])
    assert row.hits == []
    assert [r.label for r in row.refused] == ["Stellar Lance Strike"]
    assert row.refused[0].unrecognised


def test_a_non_percentage_unknown_label_is_not_a_multiplier_and_is_not_refused():
    row = classify_talent_row(["Stellar Lance Count|{param1:I}"], [3])
    assert row == classify_talent_row([], [])
