"""M.4 — our parsed multipliers against gcsim's, from committed files only.

`app/services/talent_scaling.py` decides which rows are damage by asking whether the label
contains `DMG`. That is a heuristic over English text, and this is what stops it being taken
on trust: gcsim implements the same characters from the same source independently, so
agreement turns the heuristic into a checked claim.

**No database and no clone.** The nanoka payloads and gcsim's tables are both committed, so
this runs in any lane and cannot skip — which matters more here than usual, because a crossval
that quietly stops comparing is the exact shape fairy shipped a stale golden fixture behind.

The richer run is `python -m scripts.gcsim.crossval_multipliers` against a seeded database:
**105 characters, 18,611 hits, 0 mismatches** as of this commit. This file is the part that
runs every time.
"""

from __future__ import annotations

import pytest

from scripts.gcsim.crossval_multipliers import (
    CharacterRows,
    Report,
    compare,
    from_fixtures,
    load_snapshot,
)


@pytest.fixture(scope="module")
def report() -> Report:
    return compare(from_fixtures(), load_snapshot())


def test_our_multipliers_agree_with_gcsim(report: Report) -> None:
    assert report.mismatches == [], report.summary()
    assert report.refusals == [], report.summary()


def test_the_comparison_actually_compared_something(report: Report) -> None:
    """The clause that makes the test above mean anything.

    A crossval matching zero rows passes every assertion about disagreement. Measured at
    **180 hits over 1 character** from the committed fixtures; the floor is under that so
    adding a payload does not fail this, and a fixture directory that stopped loading drops
    straight through it.
    """
    assert report.characters >= 1, report.summary()
    assert report.matched >= 150, report.summary()
    assert report.ok


def test_a_disagreement_would_fail(report: Report) -> None:
    """Proves the comparison can go red.

    Everything above asserts an absence, and an absence is what a comparison that silently
    matched nothing also produces. This feeds a character whose multipliers are deliberately
    wrong and checks it is reported — the negative case, which for a crossval matters more
    than for an ordinary test.
    """
    real = from_fixtures()
    assert real, "no fixture characters — the rest of this file proves nothing"

    tampered = [
        CharacterRows(
            gcsim_key=character.gcsim_key,
            name=character.name,
            rows=tuple(
                (action, level, labels, [value * 1.5 for value in (params or [])])
                for action, level, labels, params in character.rows
            ),
        )
        for character in real
    ]

    spoiled = compare(tampered, load_snapshot())

    assert spoiled.mismatches, "a 50% error in every multiplier went unnoticed"
    assert not spoiled.ok


def test_the_snapshot_is_the_pinned_gcsim(report: Report) -> None:
    """A snapshot built from a different commit would compare against another game version,
    and would look exactly like this one."""
    import json

    from app.services.gcsim_keys import pinned_commit
    from scripts.gcsim.crossval_multipliers import SNAPSHOT

    assert json.loads(SNAPSHOT.read_text())["pinned_commit_sha"] == pinned_commit()


def test_a_report_that_compared_nothing_is_not_ok() -> None:
    """The clause that turns "no disagreements" into "agreement".

    A run matching zero rows satisfies every assertion about mismatches, which is the
    green-by-absence failure this whole file exists against. Tested directly, because with
    real fixtures `matched` is 180 and the clause never bites.
    """
    assert not Report().ok
    assert not Report(characters=5).ok, "characters seen is not hits compared"
    assert Report(matched=1).ok


def test_the_comparison_keys_on_the_action_not_only_the_label() -> None:
    """Rosaria's skill and burst are **both** labelled `Skill DMG`.

    gcsim has four tables under that label — 0.584 and 1.36 for the skill, 1.04 and 1.52 for
    the burst. A comparison keyed on the label alone would happily check one against the
    other and call it agreement.

    Both directions are asserted because the buggy version picks whichever table it finds
    first: exactly one of these two would then falsely match, and which one is not something
    a test should depend on.
    """
    snapshot = load_snapshot()
    skill_params = [0.584, 1.36]
    burst_params = [1.04, 1.52]
    row = ["Skill DMG|{param1:P}+{param2:P}"]

    for action, params in (("burst", skill_params), ("skill", burst_params)):
        muddled = [
            CharacterRows(
                gcsim_key="rosaria", name="Rosaria", rows=((action, 1, row, params),),
            ),
        ]

        assert compare(muddled, snapshot).mismatches, (
            f"{action} compared against the other talent's table and agreed"
        )


def test_the_tolerance_cannot_hide_a_real_error() -> None:
    """A **0.1%** error, not the 50% the tamper test uses.

    Multipliers are published to six decimals, so a disagreement that mattered would be in
    the third decimal. A tolerance loose enough to swallow that would let this whole file
    pass over a parser that was quietly wrong — which is why the damage-chain crossval has
    the same test.
    """
    real = from_fixtures()
    assert real, "no fixture characters"

    nudged = [
        CharacterRows(
            gcsim_key=character.gcsim_key,
            name=character.name,
            rows=tuple(
                (action, level, labels, [value * 1.001 for value in (params or [])])
                for action, level, labels, params in character.rows
            ),
        )
        for character in real
    ]

    assert compare(nudged, load_snapshot()).mismatches, "a 0.1% error went unnoticed"
