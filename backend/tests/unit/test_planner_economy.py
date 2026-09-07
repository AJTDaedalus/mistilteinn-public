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

from app.services.planner.economy import economy

CURATED = Path(__file__).resolve().parents[2] / "app" / "data" / "planner" / "curated_rates.json"


@pytest.fixture(scope="module")
def curated() -> dict:
    return json.loads(CURATED.read_text(encoding="utf-8"))


def test_every_curated_value_cites_a_source(curated: dict) -> None:
    """A number without a provenance string is the failure mode fairy shipped."""
    uncited = [
        key
        for key, rec in curated["drop_rates"].items()
        if rec.get("expected_per_run") is not None and not rec.get("source", "").strip()
    ]
    assert uncited == [], (
        f"{len(uncited)} curated drop rate(s) carry a value but no source: {uncited}. "
        "Name where the number came from, or set it back to null and let the planner "
        "report the material as resin-unknown."
    )
    for target, rec in curated["mora_per_exp"].items():
        if rec.get("divisor") is not None:
            assert rec.get("source", "").strip(), f"mora_per_exp.{target} has no source"


def test_curated_entries_are_the_ones_the_dump_cannot_price() -> None:
    """Every curated id is genuinely absent from the derived rates, not a duplicate of one."""
    eco = economy()
    derived = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "app" / "data" / "yuanshen" / "snapshot" / "planner_economy.json"
        ).read_text(encoding="utf-8"),
    )
    overlap = set(derived["drop_rates"]) & {str(i) for i in eco.uncurated()}
    assert overlap == set(), (
        f"{overlap} appear in both the derived snapshot and the curated file. The curated "
        "file exists only for what the dump does not publish."
    )


def test_an_unpriced_material_reports_none_rather_than_a_guess() -> None:
    eco = economy()
    for material_id in eco.uncurated():
        assert eco.rate(material_id) is None, (
            f"{material_id} is listed as needing curation but resolved to a rate"
        )


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
