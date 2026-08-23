"""G.9's citation — the substat roll schedule, read from the primary source.

This task sat **BLOCKED** from Chunk G, on the grounds that "five rolls for a 5-star" written
from memory would be a confident number with nothing behind it. The schedule turned out to be
published all along, in a table the E.5 toolkit already caches:
`ReliquaryExcelConfigData.addPropLevels`.

These tests exist to keep that citation honest. They assert against the **committed snapshot**
and, where it matters, against the raw values the snapshot carries beside the converted ones —
so a bad conversion cannot pass by agreeing with itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.data.snapshot import (
    SnapshotUnavailableError,
    artifact_max_level,
    artifact_rolls_remaining,
    artifact_upgrade_levels,
)

SNAPSHOT = (
    Path(__file__).resolve().parents[2]
    / "app" / "data" / "yuanshen" / "snapshot" / "artifact_roll_schedule.json"
)


def _snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text())


# ── The citation ──────────────────────────────────────────────────────────────


def test_the_schedule_is_from_the_pinned_commit():
    """Same discipline as every other snapshot file: derived, at a pin, reviewable."""
    document = _snapshot()
    assert document["sources"] == ["ReliquaryExcelConfigData"]
    assert len(document["pinned_commit_sha"]) == 40


def test_the_snapshot_matches_the_provenance_pin():
    provenance = json.loads(
        (SNAPSHOT.parent.parent / "schema" / "provenance.json").read_text(),
    )
    assert _snapshot()["pinned_commit_sha"] == provenance["pinned_commit_sha"]


def test_the_converted_levels_are_the_raw_levels_shifted_by_one():
    """The tables are 1-indexed — internal level 1 is the artifact's +0.

    Asserted against `raw_add_prop_levels`, which the snapshot carries **specifically** so
    this can be checked rather than trusted. A conversion checked only against itself is not
    checked.
    """
    for rarity, entry in _snapshot()["schedules"].items():
        assert entry["upgrade_levels"] == [n - 1 for n in entry["raw_add_prop_levels"]], rarity
        assert entry["max_level"] == entry["raw_max_level"] - 1, rarity


def test_a_rarity_never_upgrades_past_its_own_ceiling():
    """Reading the schedule without `maxLevel` would credit a 3-star with a 5-star's rolls."""
    for rarity, entry in _snapshot()["schedules"].items():
        assert max(entry["upgrade_levels"]) <= entry["max_level"], rarity


def test_the_setless_starter_relics_are_counted_not_dropped():
    """32 one-star rows carry no `addPropLevels` and no `setId` — they cannot be upgraded.

    A builder that silently dropped 32 rows is one whose output nobody can reconcile against
    the source, so the count is published.
    """
    assert _snapshot()["excluded_unupgradable"] == 32


def test_a_zero_initial_substat_count_survives_the_dump_omitting_it():
    """These dumps omit zero-valued integers, so a missing `appendPropNum` is 0, not absent.

    That is checkable rather than assumed: in `ReliquaryLevelExcelConfigData` exactly one row
    omits `exp` and exactly one omits `rank` — the same row, `{"level": 1}`, which is rank 0
    at zero exp. Reading the omission as "absent" would drop the 0-substat variant from every
    rarity and leave these lists quietly starting at 1.
    """
    for rarity, counts in _snapshot()["initial_substat_counts"].items():
        assert counts[0] == 0, f"rarity {rarity} lost its zero-substat variant"


# ── What the accessor answers ─────────────────────────────────────────────────


def test_a_five_star_upgrades_every_four_levels_to_twenty():
    assert artifact_upgrade_levels(5) == (4, 8, 12, 16, 20)
    assert artifact_max_level(5) == 20


@pytest.mark.parametrize(("rarity", "expected"), [
    (5, (4, 8, 12, 16, 20)),
    (4, (4, 8, 12, 16)),
    (3, (4, 8, 12)),
    (2, (4,)),
    (1, (4,)),
])
def test_every_rarity_has_its_own_schedule(rarity: int, expected: tuple[int, ...]):
    assert artifact_upgrade_levels(rarity) == expected


@pytest.mark.parametrize(("level", "remaining"), [
    (0, 5), (3, 5), (4, 4), (7, 4), (8, 3), (12, 2), (16, 1), (19, 1), (20, 0),
])
def test_rolls_remaining_counts_only_upgrades_still_ahead(level: int, remaining: int):
    """A piece at exactly an upgrade level has already had it."""
    assert artifact_rolls_remaining(5, level) == remaining


def test_a_maxed_piece_has_no_rolls_left():
    assert artifact_rolls_remaining(5, 20) == 0
    assert artifact_rolls_remaining(3, 12) == 0


def test_an_impossible_level_raises_rather_than_returning_zero():
    """Zero is a real answer — a +20 five-star has none left — and a +25 five-star is a
    caller bug. Collapsing the two would hide the bug behind a plausible number."""
    with pytest.raises(SnapshotUnavailableError, match=r"caps at \+20"):
        artifact_rolls_remaining(5, 25)
    with pytest.raises(SnapshotUnavailableError, match=r"caps at \+12"):
        artifact_rolls_remaining(3, 16)
    with pytest.raises(SnapshotUnavailableError):
        artifact_rolls_remaining(5, -1)


def test_an_unknown_rarity_raises_and_says_what_is_available():
    with pytest.raises(SnapshotUnavailableError, match="no upgrade schedule for rarity 6"):
        artifact_upgrade_levels(6)
