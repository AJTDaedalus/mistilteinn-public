"""A.5 — how much upgrading a piece has left. Closes G.9.

**Potential, not value** (OQ-A1). With no build there are no substat weights, and inventing
them produces a ranking that looks authoritative and answers nobody's question. What is
knowable from `artifact_roll_schedule.json` alone is how many rolls remain and how far from
maximum the piece is, and that is what this reports.

**Where a roll lands is deliberately not claimed.** The schedule says *when* a piece gains a
substat, not *which* substat it enhances — the placement rule is not in the committed data, so
this reports the substats a piece has rather than asserting what will happen to them. Writing
that rule from memory is the failure this repo exists not to repeat.
"""

from __future__ import annotations

import pytest

from app.services.artifact_potential import upgrade_potential


def potential_of(piece: _Piece):
    """The calculation takes three values; the tests build a piece for readability."""
    return upgrade_potential(stars=piece.stars, level=piece.level, substats=piece.substats)


class _Piece:
    """The three fields the calculation reads. A stand-in, so this stays a unit test."""

    def __init__(self, stars: int, level: int, substats: list | None = None) -> None:
        self.stars = stars
        self.level = level
        self.substats = substats if substats is not None else []


def test_a_fresh_five_star_has_every_roll_ahead_of_it() -> None:
    """`(4, 8, 12, 16, 20)` — five, from `ReliquaryExcelConfigData.addPropLevels`."""
    potential = potential_of(_Piece(5, 0))

    assert potential.rolls_remaining == 5
    assert potential.rolls_total == 5
    assert potential.max_level == 20
    assert potential.levels_to_max == 20


def test_a_maxed_piece_has_none_left() -> None:
    """Zero is a real answer, not a failure to compute one."""
    potential = potential_of(_Piece(5, 20))

    assert potential.rolls_remaining == 0
    assert potential.levels_to_max == 0


def test_rarity_changes_the_answer_at_the_same_level() -> None:
    """The schedules genuinely differ: a 4-star caps at +16 with four rolls, a 3-star at +12
    with three. A calculation that ignored rarity would agree with this at +0 for a 5-star and
    nowhere else."""
    assert potential_of(_Piece(5, 0)).rolls_total == 5
    assert potential_of(_Piece(4, 0)).rolls_total == 4
    assert potential_of(_Piece(3, 0)).rolls_total == 3

    assert potential_of(_Piece(4, 8)).rolls_remaining == 2
    assert potential_of(_Piece(3, 8)).rolls_remaining == 1


def test_a_partly_levelled_piece_counts_only_what_is_ahead() -> None:
    """A +9 five-star has passed +4 and +8 and has +12, +16, +20 to come."""
    assert potential_of(_Piece(5, 9)).rolls_remaining == 3


def test_the_substats_it_has_are_reported_not_what_they_will_become() -> None:
    """The schedule says *when* a piece gains a substat, not *which* one a roll enhances.
    That rule is not in the committed data, so it is not asserted here."""
    piece = _Piece(5, 0, [
        {"stat": "FIGHT_PROP_CRITICAL", "value": 0.031, "rolls": 1},
        {"stat": "FIGHT_PROP_ATTACK_PERCENT", "value": 0.047, "rolls": 1},
    ])

    potential = potential_of(piece)

    assert potential.substats == ("FIGHT_PROP_CRITICAL", "FIGHT_PROP_ATTACK_PERCENT")


def test_a_malformed_substat_does_not_stop_the_count() -> None:
    """`substats` is a JSONB column with no schema behind it. A row that cannot list its
    substats can still say how many rolls it has left, and refusing to answer either would
    lose the useful half with the useless one."""
    piece = _Piece(5, 0, [{"value": 0.031}, None, "nonsense"])

    potential = potential_of(piece)

    assert potential.rolls_remaining == 5
    assert potential.substats == ()


@pytest.mark.parametrize(("stars", "level"), [(3, 20), (4, 17), (5, 21), (5, -1)])
def test_a_level_the_rarity_cannot_reach_is_refused(stars: int, level: int) -> None:
    """A 3-star cannot be +20. Returning zero rolls for one would be a plausible number for
    an impossible piece — `artifact_rolls_remaining` raises for exactly that reason, and this
    does not paper over it."""
    from app.data.snapshot import SnapshotUnavailableError

    with pytest.raises(SnapshotUnavailableError):
        potential_of(_Piece(stars, level))


def test_an_unknown_rarity_is_refused_rather_than_guessed() -> None:
    from app.data.snapshot import SnapshotUnavailableError

    with pytest.raises(SnapshotUnavailableError):
        potential_of(_Piece(9, 0))


def test_the_schedule_is_read_not_restated() -> None:
    """Deleting a rarity from the snapshot must fail this rather than fall back to a
    hardcoded five. That is the whole reason G.9 stayed blocked until the table was derived.
    """
    from app.data import snapshot

    snapshot._load.cache_clear()
    original = snapshot._load

    def without_five(name: str) -> dict:
        data = original(name)
        if name != "artifact_roll_schedule":
            return data
        return {
            **data,
            "schedules": {k: v for k, v in data["schedules"].items() if k != "5"},
        }

    snapshot._load = without_five
    try:
        from app.data.snapshot import SnapshotUnavailableError

        with pytest.raises(SnapshotUnavailableError):
            potential_of(_Piece(5, 0))
    finally:
        snapshot._load = original
        snapshot._load.cache_clear()
