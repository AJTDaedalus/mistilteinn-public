r"""Mutation testing, with the failure modes this project actually hit built into it.

## Why this exists

Injection testing here means: break something on purpose, and check that a test notices.
It has caught real weak tests repeatedly — a guard that passes when removed is a guard
nothing is holding.

Done by hand it went wrong **twice in one session**, both times by reporting a result the run
did not produce:

- a revert chained after a `ruff check` that failed, so the backup was never taken, the first
  injection was never undone, the second landed on top of it, and both "results" described a
  file two mutations deep;
- an injection whose target string had drifted, which printed `TARGET NOT FOUND` and then ran
  the suite on the **unmodified** file, reporting a clean pass as though it were the
  injection's answer.

Neither was a bug in the code under test. Both were the *verification* being wrong, which is
worse: a broken test tells you nothing, but a broken harness tells you something false.

## The rule this encodes

**A result is only reported when the mutation provably applied and the source provably came
back.** Everything else exits non-zero with a reason. There is deliberately no path through
this module that prints a verdict on a run it cannot vouch for.

## The exit codes are inverted from the usual, on purpose

A mutation that the tests **catch** is the *good* outcome, so it exits `0`. A mutation that
**survives** means a guard nobody is holding, so it exits `1` — because the thing worth
failing a pipeline over is a test suite that did not notice.

| code | meaning |
|---|---|
| 0 | `CAUGHT` — the mutation applied and tests failed. The guard is real. |
| 1 | `SURVIVED` — the mutation applied and tests passed. **The guard is untested.** |
| 2 | `ERROR` — the harness cannot vouch for the run: target missing, ambiguous, or the
      suite was not green to begin with; or the source did not come back. |

## Usage

    python -m scripts.inject --file app/services/x.py \\
        --old 'if value < 0:' --new 'if False:' \\
        --tests tests/unit/test_x.py

    python -m scripts.inject --spec docs/injections/d5.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

#: Repo-root-relative paths are resolved against the backend directory, matching how every
#: other script here is run (`cd backend && python -m scripts.<name>`).
BACKEND = Path(__file__).resolve().parents[1]


#: Failing test names printed before the rest are summarised as a count.
_NAMES_SHOWN = 3


class Outcome(StrEnum):
    """What happened, and what it means about the test suite."""

    CAUGHT = "CAUGHT"
    SURVIVED = "SURVIVED"
    ERROR = "ERROR"

    @property
    def exit_code(self) -> int:
        """The process exit code for this outcome. See the module docstring on the inversion."""
        return {Outcome.CAUGHT: 0, Outcome.SURVIVED: 1, Outcome.ERROR: 2}[self]


class HarnessError(RuntimeError):
    """The harness cannot vouch for a run.

    Distinct from a mutation surviving. "The tests did not notice" is a finding about the
    tests; "I could not tell" is a finding about this program, and conflating them is how a
    harness starts reporting fiction.
    """


@dataclass(frozen=True, slots=True)
class Injection:
    """One mutation: a file, an exact string to replace, and what to replace it with."""

    file: str
    old: str
    new: str
    #: What to run. A path, a `-k` expression, whatever pytest accepts.
    tests: str
    #: Free text for the report — "reader builds the join key by hand". Optional, and worth
    #: writing: an injection nobody can describe is one nobody will re-aim when it drifts.
    describe: str = ""

    @property
    def path(self) -> Path:
        """Where the file actually lives."""
        return BACKEND / self.file


@dataclass(frozen=True, slots=True)
class Result:
    """What one injection proved."""

    injection: Injection
    outcome: Outcome
    #: Test node ids that failed under the mutation. Empty when it survived.
    failures: tuple[str, ...] = ()
    detail: str = ""

    def summary(self) -> str:
        """One line for a human, saying what the result means rather than only what it is."""
        what = self.injection.describe or f"{self.injection.old[:48]}…"
        if self.outcome is Outcome.CAUGHT:
            shown = self.failures[:_NAMES_SHOWN]
            names = ", ".join(f.rsplit("::", 1)[-1] for f in shown)
            hidden = len(self.failures) - len(shown)
            more = f" (+{hidden} more)" if hidden else ""
            return f"CAUGHT   {what} → {len(self.failures)} failed: {names}{more}"
        if self.outcome is Outcome.SURVIVED:
            return (
                f"SURVIVED {what} → the suite did not notice. Either the guard is untested, "
                f"or the mutation never reaches it."
            )
        return f"ERROR    {what} → {self.detail}"


def _pytest(tests: str) -> tuple[bool, tuple[str, ...]]:
    """Run pytest, returning (passed, failed node ids)."""
    # Args are constructed here, never passed to a shell.
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", tests, "-q", "--no-header", "-p", "no:randomly"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    # `removeprefix` first, *then* split. The other order takes the word "FAILED" as the
    # node id and strips a prefix that is no longer there, so every failure list came back
    # full of the string "FAILED" — caught by this module's own meta-tests, which is the
    # argument for a harness having them.
    failures = tuple(
        line.removeprefix("FAILED ").split(" ")[0].strip()
        for line in completed.stdout.splitlines()
        if line.startswith("FAILED ")
    )
    return completed.returncode == 0, failures


def run(injection: Injection, *, check_baseline: bool = True) -> Result:
    """Apply one mutation, run its tests, and put the file back.

    The file is restored in a `finally` and the restoration is **verified by comparing
    content**, not assumed from the fact that a write was issued. A harness that leaves a
    mutation behind poisons every run after it, and that is exactly how the first of the two
    incidents in the module docstring played out.
    """
    path = injection.path
    if not path.exists():
        return Result(injection, Outcome.ERROR, detail=f"no such file: {injection.file}")

    original = path.read_text()

    if injection.old not in original:
        # The single most important refusal in this module. A target that has drifted means
        # the mutation never applied, and any test result from that run describes untouched
        # code. Reporting it as an injection result is how a harness lies.
        return Result(
            injection,
            Outcome.ERROR,
            detail=(
                f"target string not found in {injection.file}. The mutation did not apply, "
                f"so nothing can be concluded from running the tests. Re-aim it."
            ),
        )

    occurrences = original.count(injection.old)
    if occurrences > 1:
        # Ambiguity is an error rather than a first-match: mutating a different occurrence
        # than intended produces a real result about the wrong thing.
        return Result(
            injection,
            Outcome.ERROR,
            detail=(
                f"target string appears {occurrences} times in {injection.file}; make it "
                f"unique so the mutation lands where it is meant to."
            ),
        )

    if check_baseline:
        baseline_green, _ = _pytest(injection.tests)
        if not baseline_green:
            # Otherwise a suite that is already red reads as CAUGHT, and the injection gets
            # credit for failures it had nothing to do with.
            return Result(
                injection,
                Outcome.ERROR,
                detail=(
                    f"{injection.tests} is not green before the mutation, so a failure "
                    f"afterwards would prove nothing. Fix the suite first."
                ),
            )

    try:
        path.write_text(original.replace(injection.old, injection.new, 1))
        passed, failures = _pytest(injection.tests)
    finally:
        path.write_text(original)
        if path.read_text() != original:
            # Nothing downstream can be trusted after this, including any other injection in
            # the same batch, so it is raised rather than returned.
            msg = (
                f"failed to restore {injection.file}. The working tree is now dirty and any "
                f"further result would be measured against mutated source."
            )
            raise HarnessError(msg)

    if passed:
        return Result(injection, Outcome.SURVIVED)
    return Result(injection, Outcome.CAUGHT, failures=failures)


def run_all(injections: list[Injection]) -> list[Result]:
    """Run a batch, each one independently restored before the next begins."""
    return [run(injection) for injection in injections]


def load_spec(path: Path) -> list[Injection]:
    """Read a JSON list of injections.

    A spec file makes a task's injections **reviewable data** rather than shell history: they
    land in the diff, they can be re-run by anyone, and a target that drifts is caught the
    next time the file runs rather than silently going stale.
    """
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        msg = f"{path} must contain a JSON list of injections"
        raise HarnessError(msg)
    out = []
    for index, entry in enumerate(raw):
        missing = sorted({"file", "old", "new", "tests"} - set(entry))
        if missing:
            msg = f"{path} entry {index} is missing {missing}"
            raise HarnessError(msg)
        out.append(Injection(
            file=entry["file"], old=entry["old"], new=entry["new"],
            tests=entry["tests"], describe=entry.get("describe", ""),
        ))
    return out


def main(argv: list[str] | None = None) -> int:
    """Run one injection or a spec file, and exit on what it proved."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--file", help="path, relative to backend/")
    parser.add_argument("--old", help="exact string to replace; must appear exactly once")
    parser.add_argument("--new", help="what to replace it with")
    parser.add_argument("--tests", help="what to run — a path or a pytest expression")
    parser.add_argument("--describe", default="", help="one line for the report")
    parser.add_argument("--spec", help="JSON file of injections, run in order")
    args = parser.parse_args(argv)

    if args.spec:
        injections = load_spec(Path(args.spec))
    elif args.file and args.old is not None and args.new is not None and args.tests:
        injections = [Injection(args.file, args.old, args.new, args.tests, args.describe)]
    else:
        parser.error("give --spec, or all of --file/--old/--new/--tests")

    results = run_all(injections)
    for result in results:
        print(result.summary())

    survived = [r for r in results if r.outcome is Outcome.SURVIVED]
    errored = [r for r in results if r.outcome is Outcome.ERROR]
    if errored:
        print(f"\n{len(errored)} injection(s) could not be vouched for. No verdict.")
        return Outcome.ERROR.exit_code
    if survived:
        print(f"\n{len(survived)} mutation(s) survived — those guards are not tested.")
        return Outcome.SURVIVED.exit_code
    print(f"\nAll {len(results)} mutations were caught.")
    return Outcome.CAUGHT.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
