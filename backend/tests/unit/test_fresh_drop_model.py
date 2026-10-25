"""The upgrade estimator's drop model is cited, in range, and in the app's vocabulary.

`docs/TASKS_upgrade_estimator.md` Task 2. Every value is written out here rather than compared
to the file against itself — a test that loads the JSON and asserts the JSON agrees with it
cannot fail.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from app.data import external
from app.data.external import ExternalDataUnavailableError, domain_drop_model
from app.services import artifact_potential
from app.services.artifact_potential import fresh_drop_model
from app.services.planner.economy import economy

if TYPE_CHECKING:
    from pathlib import Path

KERNEL_SLOTS = {"equip_bracer", "equip_necklace", "equip_shoes", "equip_ring", "equip_dress"}


def test_domain_drops_are_the_values_that_were_researched() -> None:
    """RESEARCH_artifact_drop_model.md §§1.2, 1.3, 2 and 4.1; the 20% confirmed by the owner."""
    assert domain_drop_model() == {
        "five_star_per_run": 1.065,
        "four_line_share": 0.20,
        "set_share": 0.5,
        "slot_share": 0.2,
    }


def test_every_drop_number_carries_a_url() -> None:
    block = json.loads(
        (external.EXTERNAL_DIR / "artifact_draw_model.json").read_text(encoding="utf-8"),
    )["domain_drops"]
    for key in ("five_star_per_run", "four_line_share", "set_share", "slot_share"):
        urls = block[f"{key}_source"]["urls"]
        assert urls, key
        assert all(u.startswith("https://") for u in urls), key
    assert "ASSUMED" in block["five_star_count_shape"], "the shape is an assumption and says so"


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("five_star_per_run", 0, "outside"),
        ("five_star_per_run", 10.65, "outside"),
        ("four_line_share", 1.0, "outside"),
        ("set_share", 0, "outside"),
        ("slot_share", "0.2", "not a number"),
        ("slot_share_source", None, "no source"),
    ],
)
def test_a_bad_drop_number_refuses_rather_than_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, value: object, match: str,
) -> None:
    """A 5-star count of 0 makes every upgrade unreachable and one of 10 makes them ten times
    cheaper; neither would look wrong on a chart."""
    data = json.loads(
        (external.EXTERNAL_DIR / "artifact_draw_model.json").read_text(encoding="utf-8"),
    )
    data["domain_drops"][key] = value
    (tmp_path / "artifact_draw_model.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(external, "EXTERNAL_DIR", tmp_path)
    external._load.cache_clear()
    domain_drop_model.cache_clear()
    try:
        with pytest.raises(ExternalDataUnavailableError, match=match):
            domain_drop_model()
    finally:
        external._load.cache_clear()
        domain_drop_model.cache_clear()
        artifact_potential.fresh_drop_model.cache_clear()


def test_resin_per_run_is_read_from_the_planner_not_restated() -> None:
    assert economy().domain_resin_per_run() == 20
    assert fresh_drop_model().resin_per_run == economy().domain_resin_per_run()


def test_main_stat_probabilities_are_keyed_by_kernel_slot_and_sum_to_one() -> None:
    probs = fresh_drop_model().main_stat_probabilities
    assert set(probs) == KERNEL_SLOTS
    for slot, row in probs.items():
        assert sum(row.values()) == pytest.approx(1.0), slot
    assert probs["equip_bracer"] == {"flat_hp": 1.0}
    assert probs["equip_necklace"] == {"flat_atk": 1.0}
    assert probs["equip_dress"]["crit_dmg"] == pytest.approx(0.1)
    # Eight damage bonuses, none dropped in translation: a goblet that lost Pyro DMG would make
    # a Pyro DPS's goblet unreachable and nothing else would look wrong.
    assert sum(1 for q in probs["equip_ring"] if q.endswith("_dmg_bonus")) == 8


def test_main_stat_values_are_the_five_star_plus_twenty_values() -> None:
    """Hand-read anchors from `artifact_main_stat_values.json` (rarity 5, internal level 21)."""
    values = fresh_drop_model().main_stat_values
    assert values["flat_hp"] == 4780.0
    assert values["flat_atk"] == 311.0
    assert values["crit_dmg"] == pytest.approx(0.622, abs=1e-6)
    assert values["physical_dmg_bonus"] == pytest.approx(0.583, abs=1e-6)
    every_main = {q for row in fresh_drop_model().main_stat_probabilities.values() for q in row}
    assert every_main == set(values), "every main stat that can drop has a value"
