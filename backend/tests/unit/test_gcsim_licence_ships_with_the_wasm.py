"""The simulator we serve carries its licence notice, and so does Go's loader.

This site downloads `gcsim.wasm` and `wasm_exec.js` into every visitor's browser. That is
redistribution, and both licences require the notice to travel with the thing:

- gcsim's own — MIT at the pin (`LICENSE` in its tree). gcsim relicensed to **AGPLv3** on
  2026-09-19 (`05f01a733`), which is why `docs/CROSSVAL_gcsim.md` pins a release the MIT
  terms still cover; if that pin ever crosses the relicence, this file's premise changes and
  the notice that ships has to change with it.
- **Go's**, BSD-3-Clause. `wasm_exec.js` is copied out of `GOROOT`, not out of gcsim — it
  belongs to the Go distribution, and it was the easier of the two to overlook because
  nothing in this repo or gcsim's wrote it.

Asserted here rather than left to review because the failure is silent: the bundle builds,
the simulator runs, and nothing on screen looks different when a notice is missing.
`tests/unit/test_catalogue_art_is_not_committed.py` takes the same shape — ask the repo, not the
running system.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BUILD_SCRIPT = REPO / "frontend" / "scripts" / "build-gcsim-wasm.sh"
DOCKERFILE = REPO / "frontend" / "Dockerfile.prod"
ANGULAR = REPO / "frontend" / "angular.json"

NOTICES = ("gcsim.LICENSE.txt", "go.LICENSE.txt")


@pytest.mark.parametrize("notice", NOTICES)
def test_the_build_script_writes_the_notice(notice: str):
    assert notice in BUILD_SCRIPT.read_text(), (
        f"{BUILD_SCRIPT.name} no longer produces {notice}, so a local build serves the "
        f"simulator without its licence"
    )


@pytest.mark.parametrize("notice", NOTICES)
def test_the_production_image_writes_the_notice(notice: str):
    """The path that actually reaches users. The local script is the rehearsal."""
    assert notice in DOCKERFILE.read_text()


@pytest.mark.parametrize("notice", NOTICES)
def test_the_production_build_refuses_a_bundle_without_the_notice(notice: str):
    """A missing asset must fail the image, not ship quietly.

    The same assertion already guards the wasm itself, and it exists because an
    `angular.json` glob that matches nothing **succeeds**. That is how production served no
    simulator for a while, and it is how it would serve no notice.
    """
    check = next(
        line for line in DOCKERFILE.read_text().splitlines() if line.strip().startswith("for f in")
    )

    assert f"gcsim/{notice}" in check


def test_angular_copies_the_notices_into_the_bundle():
    assets = json.loads(ANGULAR.read_text())["projects"]["mistilteinn"]["architect"]["build"][
        "options"
    ]["assets"]
    globs = {a["glob"] for a in assets if isinstance(a, dict) and a.get("input") == "gcsim"}

    assert "*.LICENSE.txt" in globs, (
        "the notices are written into frontend/gcsim/ but nothing copies them into the "
        "bundle, so the deployed site would serve the simulator without them"
    )
