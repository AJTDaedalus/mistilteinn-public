"""The artifact draw model is cited, complete, and kept out of the derived snapshot.

`TASKS_artifact_ranking.md` A.2. These numbers decide every probability the artifact ranker
reports, and **no primary source publishes them** — see `app/data/external.py`. So the tests
that matter are not "does it load" but: are the values the ones actually fetched, does the
provenance still name both sources, and is the file still in the directory that says it is not
derived.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.data import external
from app.data.external import (
    EXTERNAL_DIR,
    SLOTS,
    ExternalDataUnavailableError,
    draw_model_provenance,
    main_stat_probabilities,
    substat_weights,
)

#: Read off `libs/gi/upopt/src/consts.ts` at the pinned commit, 2026-09-05. Written out here
#: rather than compared to the file against itself: a test that loads the JSON and asserts the
#: JSON agrees with it cannot fail, which is the shape this repo has shipped twice.
EXPECTED_WEIGHTS = {
    "hp": 6,
    "atk": 6,
    "def": 6,
    "hp_": 4,
    "atk_": 4,
    "def_": 4,
    "eleMas": 4,
    "enerRech_": 4,
    "critRate_": 3,
    "critDMG_": 3,
}

PINNED_SHA = "14d534d5910dac500f3198073741a54b4ec1832f"


def test_substat_weights_are_the_values_that_were_fetched() -> None:
    assert substat_weights() == EXPECTED_WEIGHTS


def test_the_three_weight_tiers_are_distinct() -> None:
    """Flat > percent > crit, and the gaps are the whole signal.

    If every stat carried the same weight the model would still load and still produce a
    distribution — a plausible, wrong one. This is the assertion that a flattened table breaks.
    """
    assert substat_weights()["hp"] > substat_weights()["hp_"] > substat_weights()["critRate_"]


@pytest.mark.parametrize("slot", SLOTS)
def test_main_stat_probabilities_sum_to_one(slot: str) -> None:
    assert sum(main_stat_probabilities(slot).values()) == pytest.approx(1.0)


def test_flower_and_plume_are_certain() -> None:
    """A flower is always HP and a plume always flat ATK — the two slots with no choice."""
    assert main_stat_probabilities("flower") == {"hp": 1}
    assert main_stat_probabilities("plume") == {"atk": 1}


def test_goblet_offers_every_element_plus_physical() -> None:
    """Eight damage bonuses, and the goblet is the only slot that has them.

    A missing element here would silently make one character's best-in-slot unreachable in any
    model built on this table, and nothing else in the file would look wrong.
    """
    dmg = {k for k in main_stat_probabilities("goblet") if k.endswith("_dmg_")}
    assert len(dmg) == 8
    assert "physical_dmg_" in dmg


def test_an_unknown_slot_raises_rather_than_returning_empty() -> None:
    with pytest.raises(ExternalDataUnavailableError, match="is not an artifact slot"):
        main_stat_probabilities("circlet_")


def test_provenance_names_both_sources_and_keeps_the_caveat() -> None:
    """The citation is the reason this file is allowed to exist. It has to stay legible."""
    prov = draw_model_provenance()
    blob = json.dumps(prov)
    assert PINNED_SHA in blob, "the GO commit these values were read at is no longer pinned"
    assert "genshin-impact.fandom.com" in blob, "the origin GO itself cites is missing"
    assert prov["caveat"].strip(), "the caveat that these are unverified must not be emptied"


def test_the_draw_model_is_not_in_the_derived_snapshot() -> None:
    """It must not sit where `build_snapshot.py` output sits.

    A reader who finds a number under `yuanshen/snapshot/` may assume the toolkit can reproduce
    it. For this file that assumption is false, and a false one is worse than none.
    """
    assert (EXTERNAL_DIR / "artifact_draw_model.json").exists()
    snapshot = EXTERNAL_DIR.parent / "yuanshen" / "snapshot"
    assert not (snapshot / "artifact_draw_model.json").exists()


def test_the_snapshot_builder_does_not_claim_to_produce_it() -> None:
    """The other half of the rule above, checked in the code rather than in a comment."""
    builder = Path(external.__file__).resolve().parents[2] / "scripts" / "yuanshen"
    assert builder.is_dir(), f"{builder} does not exist, so this test would pass vacuously"
    modules = sorted(builder.rglob("*.py"))
    assert modules, f"no modules under {builder}, so this test would pass vacuously"
    sources = "\n".join(p.read_text(encoding="utf-8") for p in modules)
    assert "artifact_draw_model" not in sources


def test_a_missing_file_raises_with_a_message_that_says_what_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SnapshotUnavailableError`'s rule, applied here: absent is never empty."""
    monkeypatch.setattr(external, "EXTERNAL_DIR", tmp_path)
    external._load.cache_clear()
    external.substat_weights.cache_clear()
    try:
        with pytest.raises(ExternalDataUnavailableError, match="not something"):
            substat_weights()
    finally:
        external._load.cache_clear()
        external.substat_weights.cache_clear()
