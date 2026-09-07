"""The planner's price list holds together, and refuses to invent a number.

Two failures this guards against, both of which this repository has met before in other
shapes:

* **A curated number with no source.** `docs/RESEARCH_leveling_planner_data.md` §10 explains
  why twelve drop rates cannot be derived. The risk is not that they are missing, it is that
  somebody fills one in from memory. An entry with a value must say where the value came from.
* **A missing rate silently becoming a plausible one.** `rate()` returns `None` and the
  callers carry it through; nothing substitutes an average.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.planner.economy import MaterialSource, economy

CURATED = Path(__file__).resolve().parents[2] / "app" / "data" / "planner" / "curated_rates.json"


@pytest.fixture(scope="module")
def curated() -> dict:
    return json.loads(CURATED.read_text(encoding="utf-8"))


def test_every_curated_value_cites_a_source(curated: dict) -> None:
    """A number without a provenance string is the failure mode fairy shipped."""
    uncited = [
        key
        for key, rec in curated["source_defaults"].items()
        if rec.get("expected_per_run") is not None and not rec.get("source", "").strip()
    ]
    assert uncited == [], (
        f"{len(uncited)} curated source rate(s) carry a value but no source: {uncited}. "
        "Name where the number came from, or set it back to null and let the planner "
        "report that source as resin-unknown."
    )
    for target, rec in curated["mora_per_exp"].items():
        if rec.get("mora_per_point") is not None:
            assert rec.get("source", "").strip(), f"mora_per_exp.{target} has no source"


def test_every_resin_source_is_now_priced() -> None:
    """All five curated numbers arrived on 2026-09-07, so nothing is left unpriced.

    This is the test that should fail when a new patch adds a source nobody has costed —
    which is the moment the planner would otherwise start reporting it as free.
    """
    assert economy().uncurated_sources() == []


@pytest.mark.parametrize(
    ("material_id", "name", "resin", "expected_per_run"),
    [
        # 2.2 items per trounce run split across the boss's three materials.
        (113018, "Bloodjade Branch", 30, 0.733333),
        (202, "Mora", 20, 60_000),
        # 6.5 blue x 5,000 + 4.5 purple x 20,000, at World Level 9.
        (104003, "Hero's Wit", 20, 122_500),
    ],
)
def test_the_curated_sources_carry_the_owners_numbers(
    material_id, name, resin, expected_per_run,
) -> None:
    rate = economy().rate(material_id)
    assert rate is not None, name
    assert rate.resin == resin
    assert rate.expected_per_run == pytest.approx(expected_per_run)
    assert rate.curated is True


def test_feeding_exp_material_costs_no_mora() -> None:
    """Zero, and zero is a fact rather than a gap.

    Owner, 2026-09-07: *"there is no more per exp point conversion"*. Ascension and talent
    levels still charge mora from the payload's own `cost` fields, so this is the levelling
    half only.
    """
    eco = economy()
    assert eco.mora_per_exp("character") == 0.0
    assert eco.mora_per_exp("weapon") == 0.0


@pytest.mark.parametrize(
    ("material_id", "name", "expected"),
    [
        (104161, "Shivada Jade Sliver", MaterialSource.NONE),
        (101202, "Sakura Bloom", MaterialSource.NONE),
        (112053, "Spectral Husk", MaterialSource.NONE),
        (104013, "Mystic Enhancement Ore", MaterialSource.NONE),
        (104319, "Crown of Insight", MaterialSource.NONE),
        (104301, "Teachings of Freedom", MaterialSource.DOMAIN),
        (114001, "Tile of Decarabian's Tower", MaterialSource.DOMAIN),
        (113023, "Perpetual Heart", MaterialSource.WORLD_BOSS),
        (113018, "Bloodjade Branch", MaterialSource.WEEKLY_BOSS),
        (104003, "Hero's Wit", MaterialSource.LEY_LINE_EXP),
        (202, "Mora", MaterialSource.LEY_LINE_MORA),
    ],
)
def test_only_the_owners_six_sources_cost_resin(material_id, name, expected) -> None:
    """Owner, 2026-09-07: mora, talent books, weapon ascension mats, world boss drops,
    character XP books and weekly boss mats -- and nothing else.

    **Gems are the interesting one.** They drop from a world boss *alongside* the boss's own
    material in the same 40-resin run, so charging for both bills that run twice. A first pass
    listed all seven gem Slivers as needing a curated rate; they need none, because their
    resin cost is zero.

    **Spectral Husk is the bug this test would have caught.** An elite enemy's reward preview
    lists it with an expected count, so classifying by "does a preview mention it" priced an
    ordinary overworld mob drop at 40 resin a run.
    """
    assert economy().source_of(material_id) is expected, name


def test_level_caps_are_the_published_ladder() -> None:
    """20/40/50/60/70/80/90, from `AvatarPromoteExcelConfigData.unlockMaxLevel`."""
    eco = economy()
    assert eco.character_level_caps == {0: 20, 1: 40, 2: 50, 3: 60, 4: 70, 5: 80, 6: 90}
    assert eco.weapon_level_caps == {0: 20, 1: 40, 2: 50, 3: 60, 4: 70, 5: 80, 6: 90}


def test_exp_denominations_are_read_not_recalled() -> None:
    eco = economy()
    assert [(i.id, i.exp) for i in eco.character_exp_items] == [
        (104003, 20000), (104002, 5000), (104001, 1000),
    ]
    assert [(i.id, i.exp) for i in eco.weapon_exp_items] == [
        (104013, 10000), (104012, 2000), (104011, 400),
    ]


def test_crafting_reduces_through_the_published_ratios() -> None:
    """Six Shivada Jade Gemstones are 162 Slivers — three 3:1 rungs, with the mora charged."""
    eco = economy()
    root, count, mora = eco.reduce_to_root(104164, 6)
    assert (root, count) == (104161, 162)
    assert mora > 0


def test_domain_days_are_derived() -> None:
    """Teachings of Freedom runs Mon/Thu/Sun, from `DailyDungeonConfigData`."""
    assert economy().domain_days(104301) == ["monday", "thursday", "sunday"]


def test_material_icons_are_cited_basenames() -> None:
    eco = economy()
    assert eco.icon(104161) == "UI_ItemIcon_104161"
    assert eco.icon(-1) is None
