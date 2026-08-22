"""The workflow must run crossval **with the gate on**, and this notices if it stops.

Without `CROSSVAL_REQUIRE_DB=1` an unreachable database makes the crossval tests **skip**,
`pytest tests/crossval` exits 0, and the lane is green — the exact green-by-absence mode the
harness was built to prevent. Deleting two lines from the workflow would do it, and nothing
else in the repo would notice.

Same shape of guard as `test_openapi_contract_is_current.py`: a test whose whole job is to
see a configuration change that would otherwise be invisible.

**Parsed, not grepped.** The first draft searched the file for the variable name and was
satisfied by the *comment* that explains it — so a workflow that mentioned the gate while
not setting it would have passed. The step's `env` block is what matters, so the step's
`env` block is what gets read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "test.yml"

#: The command whose step must carry the gate.
CROSSVAL_COMMAND = "pytest tests/crossval"


@pytest.fixture(scope="module")
def crossval_step() -> dict[str, Any]:
    """The workflow step that runs the crossval suite."""
    if not WORKFLOW.exists():
        pytest.fail(f"{WORKFLOW} is missing; CI cannot be running anything")
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if CROSSVAL_COMMAND in str(step.get("run", ""))
    ]
    if not steps:
        pytest.fail(
            f"no CI step runs `{CROSSVAL_COMMAND}` — the gcsim comparison would exist in "
            f"the repo and never run",
        )
    return steps[0]


def test_ci_requires_a_database_for_crossval(crossval_step: dict[str, Any]):
    """The setting that turns a skip into a failure."""
    from tests.crossval.conftest import REQUIRE_DB_ENV

    value = str(crossval_step.get("env", {}).get(REQUIRE_DB_ENV, ""))

    assert value not in ("", "0", "false", "False"), (
        f"the crossval step does not set {REQUIRE_DB_ENV} to an enabling value (got "
        f"{value!r}), so an unreachable database would make it skip and the lane pass — "
        f"which is how fairy shipped a stale golden fixture. See tests/crossval/conftest.py."
    )


def test_the_harness_agrees_with_the_workflow_about_the_variables_name():
    """A rename on one side only would disable the gate without failing anything."""
    from tests.crossval.conftest import REQUIRE_DB_ENV

    assert REQUIRE_DB_ENV == "CROSSVAL_REQUIRE_DB"


def test_the_step_is_in_a_job_that_has_a_database(crossval_step: dict[str, Any]):
    """Requiring a database in a job that has none would make CI permanently red — which is
    loud rather than silent, but still not the intent."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    owning = [
        job
        for job in workflow["jobs"].values()
        if crossval_step in job.get("steps", [])
    ]

    assert owning, "could not find the job that owns the crossval step"
    assert "postgres" in owning[0].get("services", {}), (
        "the crossval step runs in a job with no Postgres service"
    )
