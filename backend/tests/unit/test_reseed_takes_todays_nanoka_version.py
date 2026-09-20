"""A prod re-seed takes the version nanoka publishes now, and verifies against it.

Owner ruling, 2026-09-19. The reasoning is upstream's retention, not a preference: nanoka
keeps only the current cycle — `gi/6.7` is already a 404 — and this repo commits 9 of the
~1,086 payloads a seed reads. So a pin the re-seed follows is a pin that stops working, and
the failure lands on the day someone needs to re-seed prod.

Two halves, and they have to move together:

- the re-seed resolves the manifest rather than reading `FIXTURE_VERSION`;
- `verify_seed` then runs `--live`, because the committed indexes describe 7.0.51 and the
  database no longer does. Offline mode would refuse, correctly, and that refusal would
  arrive as a red deploy job nobody could act on.

Asserted against the workflow file because that is where the behaviour lives. It is the same
shape as `test_prod_go_satisfies_the_gcsim_pin.py`: read what will actually run, rather than
trusting that the comment above it is still true.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-prod.yml"


def _job(name: str) -> dict:
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    assert name in jobs, f"deploy-prod.yml has no `{name}` job"
    return jobs[name]


def _script(job: str) -> str:
    """The job's shell, **without its comments**.

    The comments in these steps explain what was tried before and name the things being
    avoided — `FIXTURE_VERSION`, `--force-prune` — so a test grepping the raw text asserts
    the opposite of what it means and fails on a well-documented step.
    """
    lines = "\n".join(step.get("run", "") for step in _job(job)["steps"]).splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_the_reseed_does_not_pin_to_the_committed_fixture_version():
    """The line this task removed. It was right until upstream started deleting versions."""
    assert "FIXTURE_VERSION" not in _script("reseed"), (
        "the re-seed is pinned to the committed fixtures again. nanoka deletes old "
        "versions, so that pin stops resolving and prod cannot be re-seeded at all."
    )


def test_the_reseed_resolves_todays_version_from_the_manifest():
    """Through the one script that does it, so the resolution has a single home."""
    assert "scripts.nanoka_latest_version" in _script("reseed")


def test_the_reseed_still_passes_one_version_explicitly():
    """One pin per run is still the rule — that part of the old comment survives.

    The failure N.2 hit was a version nobody could name afterwards, not following upstream
    as such. `seed_db` is still handed a version rather than left to resolve its own.
    """
    script = _script("reseed")

    assert "seed_db --version" in script
    assert 'test -n "$VERSION"' in script, "an empty read must not pass as a successful pin"


def test_the_reseed_still_refuses_to_prune_on_its_own():
    """Unchanged, and worth holding down: a prune takes every user's builds with it."""
    assert "--force-prune" not in _script("reseed")


def test_verify_seed_checks_against_the_version_that_was_seeded():
    """`--live`, because the committed indexes no longer describe the database."""
    assert "verify_seed --live" in _script("verify-seed")


@pytest.mark.parametrize("job", ["reseed", "verify-seed"])
def test_the_job_still_runs_on_our_own_runner(job: str):
    """A guard on the surrounding change, not on this one.

    These jobs are the reason a failed Actions bill does not stop a deploy. Editing the
    script inside them should not quietly move them onto hosted minutes.
    """
    assert _job(job)["runs-on"] == ["self-hosted", "mistilteinn-prod"]
