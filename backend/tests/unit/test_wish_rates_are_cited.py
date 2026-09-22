"""Every gacha rate must name where it came from.

`CLAUDE.md`: *do not write damage or reaction formulas from memory … fairy's hardest-won
lesson was fabricated citations in curated data.* A drop rate is the same class of claim as a
damage multiplier — it is unfalsifiable from inside the repository, it looks equally
authoritative whether or not anyone checked it, and a wrong one produces a number no test can
distinguish from a right one.

`app/data/planner/curated_rates.json` has the same rule and
`tests/unit/test_planner_economy.py` enforces it there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.wishes import BannerKind, rates_for
from app.services.wishes.rates import primogems_per_wish, radiance_win_rates

_DATA = Path(__file__).resolve().parents[2] / "app" / "data" / "wishes" / "banner_rates.json"

#: Keys holding prose rather than a number, which therefore need no source of their own.
_PROSE = {"note", "comment", "source", "model_risk", "no_capturing_radiance_source"}


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def test_every_entry_holding_numbers_cites_a_source(raw: dict) -> None:
    """A new banner or rate added without a citation fails here, not in review."""
    uncited = [
        key
        for key, entry in raw.items()
        if key not in _PROSE
        and isinstance(entry, dict)
        and not entry.get("source", "").strip()
    ]
    assert not uncited, f"entries with no `source`: {uncited}"


def test_no_entry_is_left_as_a_placeholder(raw: dict) -> None:
    for key, entry in raw.items():
        if key in _PROSE or not isinstance(entry, dict):
            continue
        source = entry.get("source", "")
        assert "TODO" not in source.upper(), f"{key} still carries a placeholder source"


def test_the_published_anchors_are_recorded(raw: dict) -> None:
    """The consolidated rate is what the soft-pity ramp was fitted to, so it must be kept.

    Without it nobody can re-derive the curve, and the ramp becomes an unsourced number
    inside a sourced file.
    """
    assert raw["character"]["published_consolidated_rate"] == pytest.approx(0.016)
    assert raw["weapon"]["published_consolidated_rate"] == pytest.approx(0.0185)


def test_the_worst_case_is_published_rather_than_fitted(raw: dict) -> None:
    """`published_worst_case` exists because the fitted curve's tail is not identified.

    The weapon curve reaches certainty at pity 77, three short of the published 80, so a
    "worst case" read off the curve would be wrong in the player's favour.
    """
    assert raw["character"]["published_worst_case"] == 180
    assert raw["weapon"]["published_worst_case"] == 160
    weapon = rates_for(BannerKind.WEAPON)
    assert weapon.drop_curve().index(1.0) + 1 < weapon.hard_pity


def test_capturing_radiance_reproduces_the_published_55_percent() -> None:
    """The stationary win rate is the anchor that discriminates between radiance models.

    HoYoverse publishes 55%; this model's steady state is 55.65%. If a future edit to the
    four win rates breaks that, the model has stopped matching the only number the publisher
    actually gave us.
    """
    rates = radiance_win_rates()
    assert rates[-1] == 1.0, "a fourth consecutive loss must be impossible"

    # Stationary distribution of a counter that advances on a loss and resets on a win.
    mass, weight = [], 1.0
    for win in rates:
        mass.append(weight)
        weight *= 1.0 - win
    total = sum(mass)
    stationary = sum(m * w for m, w in zip(mass, rates, strict=True)) / total
    assert stationary == pytest.approx(0.55, abs=0.01)


def test_acquaint_fate_is_not_a_currency_here() -> None:
    """Owner ruling, 2026-09-22: primogems and Intertwined Fate only.

    Acquaint Fate buys Wanderlust Invocation, which this planner does not model.
    """
    assert primogems_per_wish() == 160
    raw_text = _DATA.read_text(encoding="utf-8").lower()
    assert "acquaint" in raw_text, "the exclusion should be written down, not merely implied"
