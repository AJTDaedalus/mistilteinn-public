"""M.4 — our parsed multipliers against gcsim's, from committed files only.

`app/services/talent_scaling.py` decides which rows are damage by asking whether the label
contains `DMG`. That is a heuristic over English text, and this is what stops it being taken
on trust: gcsim implements the same characters from the same source independently, so
agreement turns the heuristic into a checked claim.

**No database and no clone.** The nanoka payloads and gcsim's tables are both committed, so
this runs in any lane and cannot skip — which matters more here than usual, because a crossval
that quietly stops comparing is the exact shape fairy shipped a stale golden fixture behind.

## What this file covers, exactly

**Three characters, 570 hits** — every nanoka character payload committed to
`tests/fixtures/`, and deliberately the three that matter:

* **Ayaka** — four skills, so talent type cannot be positional.
* **Venti** — `1-Hit DMG` is `{param1}+{param1}`, two arrows of one value. M.4 found the
  parser summing that into a single hit of double the multiplier.
* **Rosaria** — skill and burst are **both** labelled `Skill DMG`. M.4's first comparison
  keyed on the label alone, and was checking one against the other.

The last two were added in N.2 so **this file covers the bugs M.4 found**, rather than the
crossval having caught them once against a seeded database and then guarding nothing.

The richer run is `python -m scripts.gcsim.crossval_multipliers` against a seeded database:
**105 characters, 18,611 hits, 0 mismatches**. It is a manual gate; this file is the part that
runs every time, with no database and no clone.
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
    assert report.characters >= 3, report.summary()
    assert report.matched >= 500, report.summary()
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


# ── the two bugs M.4 found, now guarded by committed data ────────────────────


def test_the_committed_fixtures_contain_the_shapes_that_found_the_bugs() -> None:
    """Guards the guard.

    `test_our_multipliers_agree_with_gcsim` asserts an *absence*, and an absence is what a
    comparison over payloads that no longer contain the hard shapes also produces. This
    asserts the shapes are in there — so the sweep is exercising them rather than passing over
    three ordinary characters.
    """
    import json
    import re
    from pathlib import Path

    from scripts.gcsim.crossval_multipliers import FIXTURES

    repeated_param = shared_label = 0
    for path in Path(FIXTURES).glob("character_*.json"):
        payload = json.loads(path.read_text())
        labels_by_action: dict[str, set[str]] = {}
        for skill in payload.get("skills", []):
            promote = skill.get("promote") or {}
            icon = (promote.get("0") or {}).get("icon") or ""
            for row in promote.values():
                for entry in row.get("desc") or []:
                    if not entry or "DMG" not in entry:
                        continue
                    label, _, spec = entry.partition("|")
                    params = re.findall(r"\{param(\d+):", spec)
                    # Venti's shape: the *same* param referenced twice in one row.
                    if len(params) > 1 and len(set(params)) < len(params):
                        repeated_param += 1
                    labels_by_action.setdefault(icon[:8], set()).add(label)
        # Rosaria's shape: one label on two different talents of one character.
        seen: dict[str, int] = {}
        for labels in labels_by_action.values():
            for label in labels:
                seen[label] = seen.get(label, 0) + 1
        shared_label += sum(1 for count in seen.values() if count > 1)

    assert repeated_param > 0, "no `{paramN}+{paramN}` row — Venti's payload is missing"
    assert shared_label > 0, "no label shared across talents — Rosaria's payload is missing"


def test_a_summing_parser_would_fail_this_file() -> None:
    """The regression M.4 found, reproduced against the committed fixtures.

    Before N.2 this could only be shown against a seeded database. Venti's
    `{param1}+{param1}` is two arrows of 0.20382; summing gives 0.40764, and gcsim stores the
    per-hit figure — so a parser that sums disagrees, here, in CI, every run.
    """
    from app.services.talent_scaling import TalentHit

    def summing(desc: list[str], param: list[float]) -> list[TalentHit]:
        """`parse_talent_row` as it was before M.4 caught it: `A+B` folded into one hit."""
        from app.services import talent_scaling

        hits = talent_scaling.parse_talent_row(desc, param)
        folded: dict[tuple[str, bool], TalentHit] = {}
        for hit in hits:
            key = (hit.label, hit.exclusive)
            if key in folded:
                folded[key] = TalentHit(
                    label=hit.label,
                    multiplier=folded[key].multiplier + hit.multiplier,
                    hits=hit.hits,
                    exclusive=hit.exclusive,
                )
            else:
                folded[key] = hit
        return list(folded.values())

    import scripts.gcsim.crossval_multipliers as crossval

    original = crossval.parse_talent_row
    crossval.parse_talent_row = summing
    try:
        spoiled = compare(from_fixtures(), load_snapshot())
    finally:
        crossval.parse_talent_row = original

    assert spoiled.mismatches, "a summing parser agreed with gcsim — the shape is not covered"
