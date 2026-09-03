"""Data the running app needs must be inside the production image.

**Written because it was not.** The teapot fixture was committed under `tests/fixtures/`,
`backend/.dockerignore` excludes `tests/`, and the first deploy of the tracker died on
`FileNotFoundError: /app/tests/fixtures/nanoka_gi/suite.json`. Every test passed, the image
built, and the failure was only visible on the deploy — the rollback put prod back.

A green suite could not have caught it, because the suite runs where `tests/` exists. What
catches it is asking the *packaging rules* whether a path survives them, which is what this
does.
"""
from __future__ import annotations

from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]

#: Paths a script or the app reads at run time, which must therefore be in the image.
#:
#: Add to this when a script starts reading a new committed file. The cost of forgetting is a
#: failed deploy, which is a slow and public way to find out.
SHIPPED = (
    "app/data/teapot/suite.json",
    "app/data/yuanshen/snapshot/artifact_main_stat_pools.json",
    "app/data/yuanshen/snapshot/growth_curves.json",
)


def _dockerignore_patterns() -> list[str]:
    text = (BACKEND / ".dockerignore").read_text(encoding="utf-8")
    return [
        line.strip().rstrip("/")
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]


@pytest.mark.parametrize("relative", SHIPPED)
def test_the_file_exists(relative: str) -> None:
    assert (BACKEND / relative).is_file(), f"{relative} is missing"


@pytest.mark.parametrize("relative", SHIPPED)
def test_dockerignore_does_not_exclude_it(relative: str) -> None:
    """The check that would have caught the failed deploy."""
    excluded = _dockerignore_patterns()
    parts = relative.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]

    hit = next((p for p in prefixes if p in excluded), None)
    assert hit is None, (
        f"{relative} is inside {hit!r}, which `.dockerignore` excludes — it will not be in "
        f"the production image, and the deploy will fail on it."
    )


def test_the_exclusion_check_catches_the_path_that_actually_failed() -> None:
    """**The guard on the guard.**

    `tests/fixtures/nanoka_gi/suite.json` is where this file lived when the deploy died. The
    check has to reject that exact path, or it is a rule that happens to be satisfied rather
    than one that is enforced.
    """
    excluded = _dockerignore_patterns()
    failed_path = "tests/fixtures/nanoka_gi/suite.json"
    parts = failed_path.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]

    assert any(prefix in excluded for prefix in prefixes), (
        "`.dockerignore` no longer excludes `tests/`, so this check would not have caught "
        "the deploy failure it was written for."
    )


def test_seed_teapot_reads_a_shipped_path() -> None:
    """Read off the script rather than restated here, so moving the file moves the test."""
    from scripts.seed_teapot import FIXTURE

    relative = FIXTURE.relative_to(BACKEND).as_posix()

    assert relative in SHIPPED, (
        f"`seed_teapot` reads {relative}, which is not in the shipped list. Either it belongs "
        f"there, or the data belongs somewhere the image carries."
    )
