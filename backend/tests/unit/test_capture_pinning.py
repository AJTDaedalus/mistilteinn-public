"""N.2 — the fixture capture pins to what is committed, not to what upstream calls latest.

`tests/fixtures/nanoka_gi/` is ground truth for every enum, column and mapping in this repo,
and those are only true of **one** version. A capture that follows `gi.latest` writes a
payload from a newer patch into a directory pinned to an older one, and nothing about the
result says so.

That happened: adding two characters pulled them at 7.0.52 while every other file was 7.0.51,
and rewrote three index files. These tests are what stops the natural invocation being the
dangerous one.
"""

from __future__ import annotations

import json

from scripts.capture_nanoka_fixtures import FIXTURE_DIR, MANIFEST_NAME, committed_version


def test_the_default_version_comes_from_the_committed_manifest() -> None:
    """Not from upstream. The committed file is what the pin means."""
    manifest = json.loads((FIXTURE_DIR / MANIFEST_NAME).read_text())

    assert committed_version() == manifest["gi"]["latest"]


def test_the_pin_matches_what_the_importer_and_verifier_assert() -> None:
    """Three places name the version and they must agree.

    `nanoka_transport.FIXTURE_VERSION` drives the offline test transport and
    `verify_seed.FIXTURE_VERSION` guards a seeded database; both are hand-maintained against
    the committed manifest. A capture that re-pinned silently would leave all three
    disagreeing, and the first symptom would be a seeded database failing verification for a
    reason that points nowhere near here.
    """
    from scripts import verify_seed
    from tests.unit import nanoka_transport

    assert (
        committed_version()
        == nanoka_transport.FIXTURE_VERSION
        == verify_seed.FIXTURE_VERSION
    )
