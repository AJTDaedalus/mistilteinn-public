"""Task 3, docs/TASKS_move_key_resolution.md — L4 end-to-end against the real seeded DB.

Reproduces the current move-key-resolution inventory (docs/DESIGN_move_key_resolution.md
§1.1, as progressively retired by Tasks 4-7) by running scripts.validate_kits.check_l4
(equivalently, scripts.audit_agent_data_binding.run_audit, which it wraps) against the
real seeded app DB. The exact counts below are a living snapshot, not a fixed target —
each of Tasks 4-7 retires part of the inventory and must update both this test and
known_issues.json's waivers together (a finding that stops firing without its waiver
being removed is a STALE WAIVER error). Requires the SEEDED PRODUCTION DB, not the
isolated test DB — run manually:

    docker compose exec backend python -m pytest \
        tests/integration/test_move_key_resolution.py -v

Skips automatically when the seeded data is absent.

check_l4 manages its own event loop internally (asyncio.run over run_audit). Calling it
more than once per process reuses the shared SQLAlchemy engine's connection pool across
separate, now-closed event loops and breaks ("RuntimeError: Event loop is closed") — so,
unlike the DB-free unit tests, this module calls it exactly once via a module-scoped
fixture and both tests read the same result, matching test_validate_kits_l0.py's
`corpus`/`findings` fixture pattern.
"""

from __future__ import annotations

import asyncio

import pytest

from app.database import engine
from scripts import validate_kits
from scripts.audit_agent_data_binding import (
    DOCUMENTED_DEVIATIONS,
    BuildupDrift,
    DatabaseNotSeededError,
    audit_buildup_drift,
)
from scripts.validate_kits import GATED_WAIVER_CLASS, Finding, check_l4, load_waivers


@pytest.fixture(scope="module")
def findings() -> list[Finding]:
    result = check_l4([])
    if not validate_kits.L4_STATUS["db_reachable"]:
        pytest.skip("App DB not reachable or not seeded — seeded DB required for L4")
    return result


def test_l4_reproduces_known_inventory(findings: list[Finding]) -> None:
    """L4 must find exactly the current inventory: no more, no fewer.

    Post-Task-7 (Norma/Velina retired, the last waiver): 0 findings, was 12 at the
    start of this branch (docs/DESIGN_move_key_resolution.md §1.1). The whole known
    inventory is now closed — a nonzero count here means either a regression in
    already-fixed data, or a genuinely new defect that needs its own waiver (or fix)
    before this test's assertion changes again.
    """
    assert findings == [], [f"{f.code} {f.source_file}[{f.index}]" for f in findings]


def test_l4_every_finding_is_waived_branch_debt(findings: list[Finding]) -> None:
    """Every current L4 finding must have a known_issues.json branch_debt waiver.

    Guards against a finding silently going unwaived (which would fail `--no-waivers`
    for a reason nobody explains) and against a waiver going stale once its owning task
    lands — the harness's own stale-waiver check (scripts.validate_kits.main) covers
    that half; this half pins that every *current* finding is accounted for.
    """
    waivers = load_waivers()

    unwaived = [f for f in findings if f.key not in waivers]
    assert unwaived == [], f"L4 finding(s) with no known_issues.json waiver: {unwaived}"

    for f in findings:
        assert waivers[f.key]["class"] == GATED_WAIVER_CLASS


@pytest.fixture(scope="module")
def drifts() -> list[BuildupDrift]:
    """Curated buildups that disagree with their move's DB row sum, real seeded DB.

    Same one-call-per-module discipline as `findings` above: audit_buildup_drift opens
    the shared engine, so a second asyncio.run would inherit a pool bound to a closed
    loop.
    """

    async def _collect() -> list[BuildupDrift]:
        # `check_l4` above already ran the shared engine on a now-closed loop, and its
        # pooled asyncpg connections stay bound to it ("attached to a different loop").
        # Drop the pool without touching those dead connections so this loop opens its
        # own; without this the audit fails and, worse, the failure looks like an
        # unreachable DB and silently skips.
        await engine.dispose(close=False)
        return await audit_buildup_drift()

    try:
        return asyncio.run(_collect())
    except DatabaseNotSeededError as exc:
        pytest.skip(f"App DB not reachable or not seeded — seeded DB required: {exc}")


def test_no_undocumented_buildup_drift(drifts: list[BuildupDrift]) -> None:
    """Every curated buildup matches its DB row sum, or says why it must not.

    Issue #82 closed a 15-entry backlog of curated `buildup` values that silently
    disagreed with their move's rows — round-number placeholders, first-row-only sums,
    and one value copied from an unrelated move. These feed anomaly buildup, so they
    move trigger timing and damage.

    A new entry here is not automatically a bug in the JSON: the DB row set is the
    convention, not an oracle. But it must be *explained* — either the curated number
    is wrong, or the row set is not the move (a `potential` pair, mutually exclusive
    variants), in which case it belongs in DOCUMENTED_DEVIATIONS with its sources.
    """
    undocumented = [
        f"{d.agent_name} — {d.key}: curated {d.spec_buildup} vs DB sum {d.db_sum} "
        f"over {d.db_rows} {d.hit_mode} row(s)"
        for d in drifts
        if d.documented_reason is None
    ]
    assert undocumented == []


def test_every_documented_deviation_still_fires(drifts: list[BuildupDrift]) -> None:
    """A DOCUMENTED_DEVIATIONS entry cannot outlive the defect it describes.

    Mirrors known_issues.json's stale-waiver rule: once the row set is fixed (issue #85
    teaches the nanoka importer about `potential`), Jane's curated 51232 will equal the
    DB sum, the drift stops firing, and the entry must be deleted rather than left to
    quietly bless a number nobody re-checked.
    """
    firing = {(d.agent_name, d.key) for d in drifts}
    stale = sorted(set(DOCUMENTED_DEVIATIONS) - firing)
    assert stale == [], f"DOCUMENTED_DEVIATIONS entries that no longer drift: {stale}"
