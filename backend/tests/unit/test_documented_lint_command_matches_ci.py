"""`backend/CLAUDE.md`'s lint command is the one CI runs.

That file says *"Run **exactly what CI runs**"* and then prints a command. It drifted anyway:
the block was three entries short — `scripts/inject.py`, `scripts/ci_local.py` and
`scripts/download_icons.py` — while the prose two paragraphs below claimed two of them were
in it. A developer following the documented command would have linted less than the gate and
seen "All checks passed".

This is the failure `scripts/ci_local.py` exists to prevent, one level up: *run what CI runs*
degrades into *run what I remember CI running*, and the gap is invisible because everything
passes. A warning in prose does not fix that. A test does.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[2]
WORKFLOW = BACKEND.parent / ".github" / "workflows" / "test.yml"
DOC = BACKEND / "CLAUDE.md"


def _targets(command: str) -> set[str]:
    """The paths a `ruff check ...` invocation lints, order and line breaks discarded."""
    flat = command.replace("\\\n", " ").split()
    assert flat[:2] == ["ruff", "check"], f"not a ruff invocation: {flat[:2]}"
    return {tok for tok in flat[2:] if not tok.startswith("-")}


#: The job this test is about. **Scoped, because CI now lints more than the backend.**
#:
#: It used to scan every job and assert exactly one `ruff check` step existed anywhere — which
#: was true until `tools/discord-triage` gained a lane of its own, and then this failed on a
#: branch that had not touched `backend/` at all. The assertion was a proxy for "find the
#: backend's ruff step" and it stopped meaning that the moment a second Python thing was
#: linted.
#:
#: Naming the job keeps the check exact rather than widening it: a third lane may lint whatever
#: it likes, and `backend/CLAUDE.md` still has to match **this** one.
BACKEND_JOB = "backend"


def _ci_lint_command() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"].get(BACKEND_JOB)
    assert job is not None, (
        f"no {BACKEND_JOB!r} job in the workflow — this test has drifted from CI's layout, "
        f"which is the exact failure it exists to catch"
    )
    found = [
        step["run"]
        for step in job.get("steps", [])
        if "run" in step and step["run"].strip().startswith("ruff check")
    ]
    assert len(found) == 1, (
        f"expected exactly one ruff step in the {BACKEND_JOB!r} job, found {len(found)}"
    )
    return found[0]


def _documented_lint_command() -> str:
    blocks = re.findall(r"```bash\n(.*?)```", DOC.read_text(encoding="utf-8"), re.DOTALL)
    found = [b for b in blocks if b.strip().startswith("ruff check")]
    assert len(found) == 1, f"expected one documented ruff command, found {len(found)}"
    return found[0]


def test_the_documented_command_lints_exactly_what_ci_lints() -> None:
    documented, ci = _targets(_documented_lint_command()), _targets(_ci_lint_command())
    assert documented == ci, (
        "backend/CLAUDE.md's lint command has drifted from .github/workflows/test.yml.\n"
        f"  only in the docs: {sorted(documented - ci) or 'none'}\n"
        f"  only in CI:       {sorted(ci - documented) or 'none'}\n"
        "Copy the workflow's `run:` line into the doc rather than editing it by hand."
    )


def test_both_commands_were_actually_found() -> None:
    """Two regexes and a YAML walk, any of which could match nothing and pass vacuously."""
    assert len(_targets(_ci_lint_command())) >= 8
    assert len(_targets(_documented_lint_command())) >= 8
