"""The production image can actually build the pinned gcsim.

**Three deploys failed in a row and every local gate was green.** The 2026-08-31 re-pin moved
to a gcsim whose `go.mod` says `go 1.27.0`, while `frontend/Dockerfile.prod` still built the
browser wasm on `golang:1.25-alpine` with `GOTOOLCHAIN=local`:

    go: go.mod requires go >= 1.27.0 (running go 1.25.14; GOTOOLCHAIN=local)

Nothing caught it because `scripts/ci_local` does not build the production image, and the host
that runs the gates had a newer Go than the container. The pin, the toolchain it needs, and
the image that provides it are three facts that must agree, and only two of them lived
anywhere a check could read.

So the required version is a row in the pin table — the same document that owns the commit —
and this compares it against the Dockerfile. Offline, because the unit lane has no network and
a gate that needs one is a gate that gets skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CROSSVAL_DOC = REPO / "docs" / "CROSSVAL_gcsim.md"
DOCKERFILE = REPO / "frontend" / "Dockerfile.prod"


def _required() -> tuple[int, int]:
    """The Go version the pinned gcsim needs, from the pin table."""
    row = re.search(r"^\| \*\*Go toolchain\*\* \| `(\d+)\.(\d+)`", CROSSVAL_DOC.read_text(), re.M)
    assert row, "docs/CROSSVAL_gcsim.md no longer carries a `**Go toolchain**` row"
    return int(row.group(1)), int(row.group(2))


def _image() -> tuple[int, int]:
    """The Go the production image provides."""
    tag = re.search(r"^FROM golang:(\d+)\.(\d+)", DOCKERFILE.read_text(), re.M)
    assert tag, "frontend/Dockerfile.prod no longer builds on a pinned golang image"
    return int(tag.group(1)), int(tag.group(2))


def test_the_pin_table_names_a_go_version() -> None:
    """A missing row would make the comparison below pass by reading nothing."""
    assert _required() >= (1, 0)


def test_the_production_image_is_new_enough_for_the_pin() -> None:
    """`GOTOOLCHAIN=local` means the container cannot fetch a newer Go to rescue itself."""
    assert _image() >= _required(), (
        f"frontend/Dockerfile.prod builds on Go {'.'.join(map(str, _image()))}, but the pinned "
        f"gcsim needs {'.'.join(map(str, _required()))}. The wasm build will fail at deploy "
        f"time, not here — bump the image in the same commit as the pin."
    )
