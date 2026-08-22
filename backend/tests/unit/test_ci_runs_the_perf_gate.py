"""The workflow must actually run the performance baseline, and this notices if it stops.

`tests/perf` carries `pytest.mark.perf`, and `pyproject.toml` deselects that marker by
default. So `pytest tests/unit` does not run it, `pytest` does not run it, and one deleted
CI step would leave the file in the repo, passing lint, referenced from TASKS, and never
executed — while the constant it guards (`SECONDS_PER_COMBINATION`) drifts.

That is precisely fairy's crossval failure: green by absence for months. Same shape of guard
as `test_ci_runs_the_crossval_gate.py`, and **parsed rather than grepped** for the same
reason — a workflow that merely *mentions* the perf suite in a comment would satisfy a
substring search.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "test.yml"

#: The marker `tests/perf` carries and `pyproject.toml` deselects by default.
PERF_MARKER = "perf"


def _steps_running_perf() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "tests/perf" in str(step.get("run", ""))
    ]


def test_a_ci_step_runs_the_perf_suite():
    if not WORKFLOW.exists():
        pytest.fail(f"{WORKFLOW} is missing; CI cannot be running anything")

    steps = _steps_running_perf()

    assert steps, (
        "no CI step runs tests/perf. The suite is marker-deselected by default, so nothing "
        "else would run it either — the baseline would exist and never execute, which is "
        "how a stale constant survives."
    )


def test_that_step_enables_the_marker_rather_than_relying_on_the_default():
    """`pytest tests/perf` alone collects nothing: `-m perf` is what selects it.

    A step missing the flag exits 0 having run zero tests, which reads as a pass.
    """
    for step in _steps_running_perf():
        command = str(step["run"])
        assert f"-m {PERF_MARKER}" in command, (
            f"the step running tests/perf does not pass `-m {PERF_MARKER}`, so it collects "
            f"nothing and exits 0 — a step that runs no tests and reports success."
        )


def test_the_marker_is_the_one_the_suite_actually_uses():
    """A rename on one side only would silently deselect everything."""
    import tests.perf.test_optimizer_baseline as baseline

    assert baseline.pytestmark.name == PERF_MARKER
