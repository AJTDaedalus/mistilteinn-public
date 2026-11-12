"""`scripts/ci_local.py` must run what CI runs — enforced, not remembered.

The local runner exists so that an unavailable Actions (billing, outage, offline) does not
mean merging unverified work. That only holds if it stays faithful to the workflows, and
"stays faithful" cannot be a habit: the gap between the two would be invisible, because
everything would pass.

The runner reads the YAML at run time, so it cannot drift by omission. What it *can* do is
grow an adaptation that quietly skips a real check — so these tests are about the adaptations,
which are the only place a gate can go missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.ci_local import _ADAPTATIONS, NOT_RUN_LOCALLY, WORKFLOWS, collect, workflows

REPO = Path(__file__).resolve().parents[3]


def _workflow_run_lines() -> set[str]:
    """Every command line CI would execute, from the YAML itself."""
    lines: set[str] = set()
    for workflow in WORKFLOWS:
        document = yaml.safe_load((REPO / ".github" / "workflows" / workflow).read_text())
        for job in document["jobs"].values():
            if job.get("if") is False:
                continue
            for step in job.get("steps", []):
                for line in (step.get("run") or "").splitlines():
                    if line.strip():
                        lines.add(line.strip())
    return lines


def test_every_workflow_command_is_either_run_or_explicitly_adapted():
    """Nothing may go missing silently. A skip needs a reason this test can see."""
    steps = collect()
    executed = {line.strip() for step in steps for line in step.command.splitlines()}
    adapted = {line for step in steps for line, _ in step.adaptations}

    for line in _workflow_run_lines():
        assert line in executed or line in adapted or any(
            a.substitute is not None and a.match in line for a in _ADAPTATIONS
        ), (
            f"CI runs `{line}` and the local runner neither runs it nor adapts it. Add an "
            f"adaptation with a reason, or let it run — but it cannot simply not happen."
        )


def test_every_adaptation_states_a_reason():
    """An unexplained skip is indistinguishable from a forgotten one."""
    for adaptation in _ADAPTATIONS:
        assert adaptation.reason.strip(), f"{adaptation.match!r} skips without saying why"
        assert len(adaptation.reason) > 20, (
            f"{adaptation.match!r} has a reason too short to be one: {adaptation.reason!r}"
        )


def test_every_skipping_adaptation_can_prove_its_justification():
    """A skip whose precondition is unchecked is a hole, not a skip.

    "The Vulkan driver is already installed" is only a valid reason to skip the install if
    the driver *is* installed — and if it is not, skipping turns the GPU gate into a silent
    no-op, which is precisely the shape OQ-S4 was written to prevent.
    """
    for adaptation in _ADAPTATIONS:
        if adaptation.replacement is None and adaptation.substitute is None:
            assert adaptation.precondition, (
                f"{adaptation.match!r} skips a CI step with nothing verifying that the thing "
                f"it provides is actually present here"
            )


def test_the_disabled_job_is_not_run_locally():
    """`if: false` is how this repo disables a gate. Running it here would report a pass CI
    does not give, which is the inverse of the skipped-check rule and just as wrong."""
    assert not any(step.job == "kit-validation" for step in collect())


def test_the_runner_covers_every_job_ci_defines():
    """A whole job going missing is the failure this is most worth catching."""
    enabled = set()
    for workflow in WORKFLOWS:
        document = yaml.safe_load((REPO / ".github" / "workflows" / workflow).read_text())
        enabled |= {
            job_id for job_id, job in document["jobs"].items() if job.get("if") is not False
        }
    assert {step.job for step in collect()} == enabled


@pytest.mark.parametrize("gate", [
    "pytest tests/unit",
    "pytest tests/integration",
    "pytest tests/crossval",
    "pytest tests/perf",
    "npm run kernel:verify-gpu",
    "npm test",
    "npm run typecheck",
    "bandit",
    "gitleaks",
])
def test_the_named_gates_actually_run(gate: str):
    """Spot-checks on the gates this project argued hardest for.

    Belt and braces over the coverage test: those arguments are in `docs/` and a future
    adaptation that skipped one would be a quiet reversal of a documented decision.
    """
    steps = collect()
    commands = "\n".join(step.command for step in steps)
    assert gate in commands, f"{gate!r} is not among the commands the local runner executes"


def test_every_workflow_is_either_run_here_or_listed_as_not_run():
    """A workflow that appears and is quietly ignored is a gate nobody notices losing.

    The runner reads the files it is told to read, so adding `deploy-prod.yml` to the repo
    changed nothing here and nothing failed — which is exactly the shape worth catching. It
    genuinely should not run locally, and now it says so.
    """
    on_disk = {p.name for p in (REPO / ".github" / "workflows").glob("*.yml")}
    accounted = set(WORKFLOWS) | set(NOT_RUN_LOCALLY)

    unaccounted = sorted(on_disk - accounted)
    assert not unaccounted, (
        f"these workflows are neither run by scripts.ci_local nor listed in "
        f"NOT_RUN_LOCALLY with a reason: {unaccounted}"
    )


def test_every_excluded_workflow_states_why():
    for name, reason in NOT_RUN_LOCALLY.items():
        assert len(reason) > 30, f"{name} is excluded without a real reason: {reason!r}"


def test_a_tool_without_its_workflow_refuses_to_run(tmp_path: Path) -> None:
    """The triage job lives in its own file so the public export can drop both together.

    In the private tree, deleting the file must not quietly delete the tool's 100-odd tests.
    """
    (tmp_path / "tools" / "discord-triage").mkdir(parents=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="discord-triage"):
        workflows(tmp_path)


def test_a_tree_without_the_tool_runs_without_its_workflow(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    assert "triage.yml" not in workflows(tmp_path)


def test_this_tree_runs_the_triage_workflow() -> None:
    assert "triage.yml" in WORKFLOWS
