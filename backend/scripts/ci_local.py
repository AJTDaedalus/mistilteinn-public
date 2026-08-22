"""Run what CI runs, here, and refuse to pretend when it cannot.

## Why

GitHub Actions is a convenience for this project, not the point of it — there is no
production target yet, so the pipeline's job today is *checking*, and checking can happen
anywhere. When Actions is unavailable (billing, an outage, working offline) the right
fallback is to run the same gates locally rather than to merge unverified work.

The wrong way to do that is from memory. "Run what CI runs" degrades within a week into "run
what I remember CI running", and the gap is invisible precisely because everything passes.

## So this reads the workflows rather than restating them

Every command comes from parsing `.github/workflows/*.yml` at run time. Add a step to CI and
it runs here on the next invocation, with no edit to this file. Delete one and it stops.
There is no second list to fall out of date.

## What is adapted, and why each adaptation is named

A handful of steps describe a *runner* rather than a check — installing Python, `apt-get`,
provisioning a Postgres service container. Those are adapted, and each adaptation carries its
reason in `_ADAPTATIONS` below. **Nothing is skipped silently**: a step that matches no
adaptation runs verbatim, and `tests/unit/test_ci_local_covers_the_workflows.py` fails if a
new step appears that this file has no answer for.

That inversion is the important part. The default is *run it*; skipping requires a stated
reason that a test can see.

## A number you did not run is a number you made up

The commit that introduced this file claimed "985 tests" in its message. The real figure was
**955**. Nothing had run `pytest -q`; the number was inferred from arithmetic on remembered
counts, in a commit whose entire subject is not doing that.

It is recorded here rather than quietly amended because the mistake is the argument for the
tool: `--list` and the per-step tally exist so that what ran is *read off a run*, never
reconstructed afterwards. Corrected in the following commit.

## What this cannot do, stated plainly

CI runs on a **clean checkout on a machine that is not mine**, and that has caught two real
bugs here that no local run would have:

- the WGSL gate passed locally because this box had `mesa-vulkan-drivers` and runners did
  not (`OQ-S4`);
- `npm run typecheck` passed locally against a **gitignored, stale** `api.types.ts` while CI,
  checking out fresh, failed.

`--clean` recovers most of that by running from a fresh `git clone` of HEAD into a temporary
directory, which restores the untracked-and-stale-artifact property. It does **not** restore
"a different machine", so a dependency that happens to be installed here and nowhere else
will still pass. That residue is a known, accepted risk while there is no deploy target — not
something this script has solved.

## Usage

    cd backend && python -m scripts.ci_local              # everything
    cd backend && python -m scripts.ci_local --list       # what would run, without running
    cd backend && python -m scripts.ci_local --job frontend
    cd backend && python -m scripts.ci_local --clean      # from a fresh clone of HEAD
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = ("test.yml", "security.yml")


@dataclass(frozen=True, slots=True)
class Adaptation:
    """One workflow step this machine handles differently, and the reason it must."""

    #: Substring matched against the step's `run` command, or the `uses` action id.
    match: str
    #: Whole-command replacement, used for a `uses:` action that maps to a local binary.
    #: `None` means the matched line is skipped entirely.
    replacement: str | None
    #: In-line substring substitution instead of skipping. Distinct from `replacement`
    #: because a `run:` block is a shell program, not a list of commands: replacing the whole
    #: line `if out=$(pip-audit --local); then` would delete the retry loop around it and
    #: leave a syntactically broken script that fails for a reason unrelated to the check.
    substitute: str | None = None
    reason: str = ""
    #: A command that must succeed first, proving the thing the skipped step provides is
    #: genuinely present. A skip with no such check is a skip that hides a missing dependency.
    precondition: str | None = None


#: Every adaptation, each with its justification. A step matching none of these runs verbatim.
_ADAPTATIONS: tuple[Adaptation, ...] = (
    Adaptation(
        match="pip install",
        replacement=None,
        reason="the backend is already installed in this environment",
        precondition="python -c 'import app'",
    ),
    Adaptation(
        match="apt-get",
        replacement=None,
        reason="the software Vulkan driver is installed on this machine",
        # Proves it rather than assuming: the whole point of the CI step is that a box
        # without an ICD reports `vkCreateInstance: Found no drivers!`, and skipping the
        # install on such a box would turn the GPU gate into a silent no-op.
        precondition="test -e /usr/share/vulkan/icd.d/lvp_icd.json",
    ),
    Adaptation(
        match="npm ci",
        replacement=None,
        reason="node_modules is already installed; --clean reinstalls it in the fresh clone",
        precondition="test -d node_modules",
    ),
    Adaptation(
        match="--local",
        replacement=None,
        substitute="backend",
        reason=(
            "--local audits the *environment*, and this box has 212 packages against the "
            "project's 20; CI installs into a clean venv, so the same flag means something "
            "different here. Auditing backend/ resolves the project's own declared tree "
            "instead. Not identical to CI, which audits the installed set including pinned "
            "transitives — closer than auditing 200 unrelated packages, and stated"
        ),
        precondition="pip-audit --version",
    ),
    Adaptation(
        match="gitleaks/gitleaks-action",
        replacement="gitleaks detect --source . --redact --no-banner",
        reason="the Action wraps the same binary; run it directly",
        precondition="gitleaks version",
    ),
)

#: Services a job declares, and how to satisfy them here. A job whose service cannot be
#: satisfied is reported as such rather than run against whatever happens to be listening.
_SERVICES: dict[str, tuple[str, str]] = {
    "postgres": (
        "docker exec fairy-db-1 pg_isready",
        (
            "Postgres must be reachable. `docker start fairy-db-1` — the database lives in "
            "the fairy stack (see the root CLAUDE.md)."
        ),
    ),
}


@dataclass
class Step:
    """One thing to run.

    `adaptations` is per **line**, not per step. A `run:` block can hold several commands —
    `.github/workflows/test.yml`'s "Emit sample gcsim configs" is `pip install -e .` followed
    by the emit itself — and matching an adaptation against the whole block skipped the emit
    along with the install. That is the exact failure this tool exists to prevent: a check
    quietly not running while the report says everything is fine. Caught by reading
    `--list` output, which is why `--list` exists.
    """

    job: str
    name: str
    command: str
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    #: What the workflow asked to run this under. `bash` is not `sh`: the pip-audit retry
    #: uses `set -o pipefail`, which dash rejects outright — running it under /bin/sh failed
    #: for a reason that had nothing to do with the check.
    shell: str = "bash"
    #: `(line, adaptation)` for lines this machine handles differently. A line with no entry
    #: runs verbatim.
    adaptations: tuple[tuple[str, Adaptation], ...] = ()

    @property
    def is_fully_adapted(self) -> bool:
        """True when nothing of this step is left to run here."""
        return not self.command.strip()


@dataclass
class Outcome:
    """What one step did."""

    step: Step
    passed: bool
    seconds: float
    output: str


def _adaptation_for(command: str) -> Adaptation | None:
    return next((a for a in _ADAPTATIONS if a.match in command), None)


def _adapt_lines(command: str) -> tuple[str, list[tuple[str, Adaptation]]]:
    """Apply adaptations line by line, returning what survives and what was changed."""
    kept: list[str] = []
    adapted: list[tuple[str, Adaptation]] = []
    for line in command.splitlines():
        if not line.strip():
            continue
        found = _adaptation_for(line)
        if found is None:
            kept.append(line)
        elif found.substitute is not None:
            kept.append(line.replace(found.match, found.substitute))
            adapted.append((line.strip(), found))
        elif found.replacement is None:
            adapted.append((line.strip(), found))
        else:
            kept.append(found.replacement)
    return "\n".join(kept), adapted


def collect(root: Path = REPO, *, include_disabled: bool = False) -> list[Step]:
    """Every step CI would run, in workflow order, read from the YAML itself."""
    steps: list[Step] = []
    for workflow in WORKFLOWS:
        document = yaml.safe_load((root / ".github" / "workflows" / workflow).read_text())
        for job_id, job in document["jobs"].items():
            # `if: false` is how this repo disables a job (the kit harness). Honour it —
            # running a deliberately-disabled gate locally would report a pass CI never gives.
            if job.get("if") is False and not include_disabled:
                continue
            working = (job.get("defaults") or {}).get("run", {}).get("working-directory", ".")
            job_env = dict(job.get("env") or {})
            for raw in job.get("steps", []):
                command = raw.get("run")
                adaptations: list[tuple[str, Adaptation]] = []
                if command is None:
                    uses = raw.get("uses", "")
                    adaptation = _adaptation_for(uses)
                    if adaptation is None or adaptation.replacement is None:
                        continue  # checkout/setup-* provision a runner; nothing to check.
                    command = adaptation.replacement
                else:
                    command, adaptations = _adapt_lines(command)
                # A step's own working-directory wins over the job default — the emit step
                # runs in `backend` inside a job defaulted to `frontend`.
                where = raw.get("working-directory", working)
                steps.append(Step(
                    job=job_id,
                    name=raw.get("name", command.splitlines()[0][:60] if command else "step"),
                    command=command,
                    cwd=root / where,
                    env={**job_env, **(raw.get("env") or {})},
                    shell=raw.get("shell", "bash"),
                    adaptations=tuple(adaptations),
                ))
    return steps


def _shell(
    command: str, cwd: Path, env: dict[str, str] | None = None, shell: str = "bash",
) -> tuple[bool, str]:
    """Run a command the way the workflow asked for it.

    `executable` matters: GitHub runs `run:` under bash by default, and this repo's steps use
    bash features. `subprocess(shell=True)` uses `/bin/sh`, which on Ubuntu is dash — where
    `set -o pipefail` is an error. A gate failing on its own shebang is not a gate result.
    """
    environment = {**os.environ, **(env or {})}
    environment["PATH"] = environment["PATH"] + ":/usr/local/go/bin"
    executable = shutil.which(shell) or "/bin/bash"
    completed = subprocess.run(  # noqa: S602 — commands come from the repo's own workflows
        command, shell=True, cwd=cwd, env=environment, executable=executable,
        capture_output=True, text=True, check=False,
    )
    return completed.returncode == 0, (completed.stdout + completed.stderr)


def _services_ready(steps: list[Step]) -> list[str]:
    """Which declared services are not available. Reported, never assumed."""
    document = yaml.safe_load((REPO / ".github" / "workflows" / "test.yml").read_text())
    jobs_running = {step.job for step in steps}
    problems = []
    for job_id, job in document["jobs"].items():
        if job_id not in jobs_running:
            continue
        for service in (job.get("services") or {}):
            check = _SERVICES.get(service)
            if check is None:
                problems.append(f"job {job_id} needs an unknown service {service!r}")
                continue
            ok, _ = _shell(check[0], REPO)
            if not ok:
                problems.append(f"job {job_id} needs {service}: {check[1]}")
    return problems


def run(steps: list[Step]) -> list[Outcome]:
    """Run every step, reporting each as it finishes."""
    outcomes: list[Outcome] = []
    for step in steps:
        failed_precondition = False
        for line, adaptation in step.adaptations:
            if adaptation.precondition is None:
                continue
            ok, output = _shell(adaptation.precondition, step.cwd)
            if not ok:
                # A skip whose justification cannot be verified is not a skip, it is a hole.
                print(f"  ✗ {step.job}/{step.name} — SKIP PRECONDITION FAILED")
                print(f"      skipped `{line}` because {adaptation.reason},")
                print(f"      but `{adaptation.precondition}` failed. Not safe to skip.")
                outcomes.append(Outcome(step, False, 0.0, output))
                failed_precondition = True
                break
        if failed_precondition:
            continue

        if step.is_fully_adapted:
            reasons = "; ".join(a.reason for _, a in step.adaptations)
            print(f"  - {step.job}/{step.name} — adapted: {reasons}")
            continue

        started = time.monotonic()
        ok, output = _shell(step.command, step.cwd, step.env, step.shell)
        elapsed = time.monotonic() - started
        mark = "✓" if ok else "✗"
        print(f"  {mark} {step.job}/{step.name} ({elapsed:.1f}s)")
        if not ok:
            tail = "\n".join(output.strip().splitlines()[-25:])
            print("\n".join(f"      {line}" for line in tail.splitlines()))
        outcomes.append(Outcome(step, ok, elapsed, output))
    return outcomes


def _git() -> str:
    """Absolute path to git, so the subprocess call names a real executable."""
    found = shutil.which("git")
    if found is None:
        msg = "git is not on PATH, so a clean clone is impossible"
        raise RuntimeError(msg)
    return found


def _clean_clone() -> Path:
    """A fresh clone of HEAD, so gitignored and untracked files cannot mask a failure.

    This is the half of CI's value that a working-tree run cannot give: `api.types.ts` is
    generated and gitignored, and a local typecheck once passed against a stale copy of it
    while CI, checking out fresh, failed.
    """
    target = Path(tempfile.mkdtemp(prefix="ci-local-"))
    subprocess.run(  # noqa: S603
        [_git(), "clone", "--quiet", "--depth", "1", f"file://{REPO}", str(target / "repo")],
        check=True, capture_output=True,
    )
    return target / "repo"


def _print_plan(steps: list[Step]) -> None:
    """Show what would run, so a reader can check the plan against the workflows."""
    for step in steps:
        print(f"{step.job}/{step.name}")
        for line, adaptation in step.adaptations:
            print(f"    - skipped: {line}   [{adaptation.reason}]")
        for line in step.command.splitlines():
            print(f"    $ {line}")


def _report(steps: list[Step], outcomes: list[Outcome]) -> int:
    """Print the tally and return the exit code."""
    failed = [o for o in outcomes if not o.passed]
    ran = len(outcomes)
    adapted = sum(len(s.adaptations) for s in steps)
    print(f"\n{ran - len(failed)}/{ran} passed, {adapted} adapted for this machine.")
    if failed:
        for outcome in failed:
            print(f"  FAILED {outcome.step.job}/{outcome.step.name}")
        return 1
    print(
        "All gates green locally. This is not the same as green in CI: a clean machine can "
        "still fail what this box passes."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the workflows' own steps locally and report honestly on what ran."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--job", help="run only this workflow job id")
    parser.add_argument("--list", action="store_true", help="print the steps and exit")
    parser.add_argument(
        "--clean", action="store_true",
        help="run from a fresh clone of HEAD, so untracked files cannot mask a failure",
    )
    args = parser.parse_args(argv)

    root = REPO
    scratch: Path | None = None
    if args.clean:
        clone = _clean_clone()
        scratch = clone.parent
        root = clone
        print(f"Running from a fresh clone of HEAD at {root}")

    try:
        steps = collect(root)
        if args.job:
            steps = [s for s in steps if s.job == args.job]
            if not steps:
                known = sorted({s.job for s in collect(root)})
                print(f"no job {args.job!r}; jobs are {known}")
                return 2

        if args.list:
            _print_plan(steps)
            return 0

        if args.clean:
            # The clone has no node_modules, so `npm ci` must actually run there.
            for step in steps:
                restored = [
                    line for line, a in step.adaptations if a.match == "npm ci"
                ]
                if restored:
                    step.adaptations = tuple(
                        (line, a) for line, a in step.adaptations if a.match != "npm ci"
                    )
                    step.command = "\n".join([*restored, step.command]).strip()

        problems = _services_ready(steps)
        if problems:
            print("Cannot run: a required service is unavailable.")
            for problem in problems:
                print(f"  - {problem}")
            # An unavailable service is a *could not check*, never a pass — the gate rule
            # this repo took from fairy, applied to its own local runner.
            return 2

        print(f"Running {len(steps)} steps from {len(WORKFLOWS)} workflows.\n")
        return _report(steps, run(steps))
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
