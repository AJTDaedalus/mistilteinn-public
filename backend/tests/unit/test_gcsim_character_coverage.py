"""Which seeded characters gcsim can actually simulate — the successor to L6.

`.github/workflows/test.yml` carried a **disabled** `kit-validation` job from fairy, whose
level **L6** was *"every seeded character has a kit entry"*. Chunk S superseded the corpus
that job validated: gcsim already implements the kits, so there is no corpus to curate and
the job would never have been restored as written.

But L6's *question* survived the corpus it was asked about. It is now: **every seeded
character resolves to a gcsim key, or is on a reviewed list of ones that do not.** A character
that cannot be keyed cannot be simulated in the browser and cannot be crossvalidated, and
finding that out from a user's failed search is the shape this repo keeps refusing.

The list is committed rather than computed-and-trusted, so:

- a **re-pin that implements** one of these shows up as a diff someone reads;
- a character that **stops** resolving fails here rather than in a search;
- and the count of what the product cannot do is a number, not a feeling.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.gcsim_keys import GcsimKeyError, character_key, pinned_commit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COVERAGE = FIXTURES / "gcsim_character_coverage.json"
CHARACTERS = FIXTURES / "nanoka_gi" / "character.json"


def _seeded() -> dict[str, dict]:
    return json.loads(CHARACTERS.read_text())


def _unimplemented() -> list[dict]:
    """Every seeded character that does not resolve to a gcsim key, recomputed."""
    out = []
    for nanoka_id, body in sorted(_seeded().items()):
        try:
            character_key(nanoka_id, body.get("en", ""), body.get("element"))
        except GcsimKeyError:
            out.append({
                "nanoka_id": nanoka_id,
                "name": body.get("en", ""),
                "element": body.get("element"),
            })
    return out


def test_the_committed_coverage_matches_what_actually_resolves():
    """The list is the claim; this is the check.

    A drift in either direction matters. **New entries** mean the catalogue moved ahead of
    the pin and those characters silently became unsimulatable. **Missing entries** mean a
    re-pin implemented someone, which is good news that should still be reviewed rather than
    absorbed.
    """
    committed = json.loads(COVERAGE.read_text())
    actual = _unimplemented()

    committed_ids = {entry["nanoka_id"] for entry in committed["unimplemented"]}
    actual_ids = {entry["nanoka_id"] for entry in actual}

    newly_broken = sorted(actual_ids - committed_ids)
    newly_working = sorted(committed_ids - actual_ids)
    assert not newly_broken, (
        f"these seeded characters no longer resolve to a gcsim key: {newly_broken}. They "
        f"cannot be simulated or crossvalidated — regenerate the coverage fixture only if "
        f"that is intended."
    )
    assert not newly_working, (
        f"these characters now resolve and the fixture still lists them as unimplemented: "
        f"{newly_working}. A re-pin implemented them; update the fixture."
    )


def test_the_coverage_is_recorded_at_the_pin():
    assert json.loads(COVERAGE.read_text())["pinned_commit_sha"] == pinned_commit()


def test_the_seeded_total_is_current():
    """A stale total would make the coverage ratio quietly wrong."""
    assert json.loads(COVERAGE.read_text())["seeded_total"] == len(_seeded())


def test_most_of_the_roster_is_simulatable():
    """The product claim behind the pivot: gcsim covers substantially the whole roster.

    Chunk S measured 106 characters and used that to supersede the kit corpus. If coverage
    ever fell far below that, the argument for not curating a corpus would weaken — so the
    floor is asserted rather than assumed, and it is deliberately loose: this guards against
    a collapse, not against ordinary drift as new characters release.
    """
    seeded = len(_seeded())
    unimplemented = len(_unimplemented())
    assert seeded - unimplemented >= 100, (
        f"only {seeded - unimplemented} of {seeded} seeded characters resolve. Chunk S "
        f"superseded the kit corpus on the strength of gcsim's coverage; a collapse here "
        f"reopens that decision."
    )


def test_the_unimplemented_are_mostly_newer_than_the_pin():
    """Sanity on *why* they are missing: released after the pin, not broken keys.

    A key that fails for a character gcsim *does* implement would be a bug in
    `gcsim_keys.normalise`, and it would hide in this list looking like a release-date gap.
    """
    committed = json.loads(COVERAGE.read_text())["unimplemented"]
    ids = [entry["nanoka_id"] for entry in committed]
    # nanoka ids are ascending by release; the pin predates the 10000100+ block.
    late = [i for i in ids if int(i.split("-")[0]) >= 10000100]
    travelers = [i for i in ids if i.split("-")[0] in {"10000005", "10000007"}]
    assert len(late) + len(travelers) == len(ids), (
        f"unexpected unimplemented characters that predate the pin: "
        f"{sorted(set(ids) - set(late) - set(travelers))}. That points at a key-normalisation "
        f"bug rather than a release-date gap."
    )
