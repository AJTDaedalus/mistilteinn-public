"""There is **one** gcsim pin, and `docs/CROSSVAL_gcsim.md` owns it.

Three things now depend on which gcsim commit this project means: the crossval fixtures
(`sim_version` is asserted against it), the browser WASM build the frontend serves, and every
formula citation that names a file and line range.

Two pins that can drift apart are two definitions of what "correct" means — and this repo
already knows the failure, because `tests/crossval` asserts a fixture's `sim_version` for
exactly that reason. A second pin sitting in a build script would let the browser run one
gcsim while the oracle asserts another, and the numbers would diverge with nothing to say why.

So the build script *reads* the pin rather than declaring one, and this test asserts that
nothing else declares one either.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CROSSVAL_DOC = REPO / "docs" / "CROSSVAL_gcsim.md"
BUILD_SCRIPT = REPO / "frontend" / "scripts" / "build-gcsim-wasm.sh"
#: Every other file that builds the wasm and therefore has to know which gcsim to build.
#:
#: **The production image was a second reader and this test did not cover it.** It reads the
#: pin correctly, but `DECISIONS.md` §28 claimed the invariant was *guarded* here — and a
#: hard-coded SHA in the Dockerfile would have passed green. A test named for an invariant it
#: does not actually hold is worse than no test: it is the claim without the check.
PIN_READERS = (
    BUILD_SCRIPT,
    REPO / "frontend" / "Dockerfile.prod",
)

#: A 40-character hex string that is not obviously something else.
_SHA = re.compile(r"\b[0-9a-f]{40}\b")


def _declared_pin() -> str:
    row = re.search(r"^\| \*\*Commit\*\* \| `([0-9a-f]{40})`", CROSSVAL_DOC.read_text(), re.M)
    assert row, "docs/CROSSVAL_gcsim.md no longer declares a `**Commit**` row"
    return row.group(1)


def test_the_doc_declares_the_pin():
    assert len(_declared_pin()) == 40


@pytest.mark.parametrize("reader", PIN_READERS, ids=lambda p: p.name)
def test_everything_that_builds_the_wasm_reads_the_pin_rather_than_repeating_it(
    reader: Path,
) -> None:
    """A hard-coded SHA in any of them is the drift this test exists to prevent."""
    text = reader.read_text()

    assert "CROSSVAL_gcsim.md" in text, (
        f"{reader.name} builds the wasm without reading the pin from docs/CROSSVAL_gcsim.md"
    )
    hard_coded = _SHA.findall(text)
    assert not hard_coded, (
        f"{reader.name} hard-codes {hard_coded}. It must read the pin from "
        f"docs/CROSSVAL_gcsim.md so a re-pin cannot leave the browser running one gcsim "
        f"while the crossval oracle asserts another."
    )


def test_every_pin_reader_exists():
    """A path that has moved would make the check above pass by reading nothing."""
    for reader in PIN_READERS:
        assert reader.is_file(), f"{reader} is listed as a pin reader and does not exist"


def test_the_crossval_fixtures_were_produced_by_the_pinned_commit():
    """The fixtures already carry `sim_version`; this ties it to the same single pin."""
    import json

    pin = _declared_pin()
    fixtures = sorted((REPO / "backend" / "tests" / "fixtures" / "crossval").glob("*.json"))
    assert fixtures, "no crossval fixtures found"
    for fixture in fixtures:
        recorded = json.loads(fixture.read_text()).get("sim_version")
        assert recorded == pin, (
            f"{fixture.name} was produced by gcsim {recorded}, but the pin is {pin}. "
            f"Regenerating a fixture is a new claim about what is correct and should arrive "
            f"as a reviewed diff — see that directory's PROVENANCE.md."
        )


def test_ci_builds_and_verifies_the_browser_wasm():
    """The verifier is only a gate if something runs it.

    `npm test` does not: it is a standalone Node script, deliberately, because it needs the
    real WebAssembly host and Go's JS runtime rather than Angular's test environment. So one
    deleted CI step would leave the browser build unverified while everything stayed green —
    the shape `test_ci_runs_the_perf_gate.py` already guards for the backend.
    """
    import yaml

    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "test.yml").read_text())
    runs = [
        str(step.get("run", ""))
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
    ]

    assert any("gcsim:build" in r for r in runs), "no CI step builds the gcsim browser wasm"
    assert any("gcsim:verify" in r for r in runs), (
        "no CI step verifies the gcsim browser build against the oracle. Building it and "
        "never checking it agrees is how a silently different simulator ships."
    )
    assert any("gcsim:verify-config" in r for r in runs), (
        "no CI step checks that gcsim accepts the configs this repo emits. String tests "
        "pin the emitter's decisions; only gcsim can say the result is a config."
    )
    assert any("emit_sample_configs" in r for r in runs), (
        "nothing generates the configs the validator reads, so it would exit on an empty "
        "directory — which it does deliberately, rather than passing on nothing."
    )


def test_the_browser_verifier_uses_the_deterministic_case():
    """gcsim **rolls** crit, so a live re-run is not reproducible.

    `verify-gcsim-wasm.mjs` re-runs the browser build on every CI job. Pointed at
    `ayaka_normal_1.txt` it passed five runs and then returned 40.894 against an expected
    21.706 — a ratio of 1.884, which is exactly `1 + Ayaka's crit DMG at 90/6`. It had rolled
    a crit.

    A gate that fails 5% of the time is worse than no gate: it teaches people to re-run CI,
    and the day it fails for a real reason nobody believes it. The `_nocrit` variant clamps
    crit rate to zero and is reproducible — verified by forcing the opposite (`cr=1`), which
    returns 204.471 on 40 runs out of 40 against the no-crit 108.530.
    """
    verifier = (REPO / "frontend" / "scripts" / "verify-gcsim-wasm.mjs").read_text()

    assert "ayaka_normal_1_nocrit.txt" in verifier, (
        "the browser verifier no longer uses the no-crit case. Anything that re-runs gcsim "
        "and compares to a recorded number is flaky, because gcsim rolls crit."
    )
    assert (REPO / "backend" / "tests" / "fixtures" / "crossval"
            / "ayaka_normal_1_nocrit.txt").exists()
