"""L4 (per-agent move-key resolution) validator tests — Task 3,
docs/TASKS_move_key_resolution.md.

L4 asks: does every attack-name key in every per-agent JSON under moves/agents/ and
skill_overrides/ resolve to an attack *owned by that agent*? It reuses
scripts.audit_agent_data_binding's classification directly rather than re-deriving it,
so these tests drive that shared classification with synthetic DB state — no real DB,
no fixture, matching L0's DB-free style. The end-to-end pass against the real seeded DB
(and the DB-unseeded skip) is covered by the integration test,
tests/integration/test_move_key_resolution.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.audit_agent_data_binding import DatabaseNotSeededError, classify_key
from scripts.audit_agent_data_binding import Finding as BindingFinding
from scripts.validate_kits import _L4_CODE_BY_CLASSIFICATION, Finding, check_l4

if TYPE_CHECKING:
    import pytest


def test_synthetic_wrong_agent_key_flagged_foreign() -> None:
    """The Grace class: a key that resolves, but to a different agent's attack."""
    finding = classify_key(
        key="Basic Attack: Swiftedge",
        directory="moves",
        source_file="grace.json",
        agent_name="Grace",
        owned_names=["Basic Attack: High-Pressure Spike"],
        norm_name_to_agent_id={"Basic Attack: Swiftedge": "ye-shunguang-id"},
        id_to_name={"ye-shunguang-id": "Ye Shunguang"},
    )
    assert finding is not None
    assert finding.classification == "FOREIGN"
    assert "Ye Shunguang" in finding.detail


def test_synthetic_correct_key_passes() -> None:
    """A key that exactly matches an attack this agent owns resolves clean."""
    finding = classify_key(
        key="Basic Attack: High-Pressure Spike",
        directory="moves",
        source_file="grace.json",
        agent_name="Grace",
        owned_names=["Basic Attack: High-Pressure Spike"],
        norm_name_to_agent_id={},
        id_to_name={},
    )
    assert finding is None


def test_synthetic_dead_key_flagged() -> None:
    """A key that resolves to no attack at all, for any agent."""
    finding = classify_key(
        key="Ultimate: Nonexistent Move",
        directory="moves",
        source_file="aria.json",
        agent_name="Aria",
        owned_names=["Basic Attack: Perfect Pitch"],
        norm_name_to_agent_id={},
        id_to_name={},
    )
    assert finding is not None
    assert finding.classification == "DEAD"


def test_synthetic_nbsp_key_flagged() -> None:
    """A key that resolves to an owned attack only after whitespace normalisation."""
    finding = classify_key(
        key="EX Special Attack: Really Heavy",  # plain space
        directory="moves",
        source_file="piper.json",
        agent_name="Piper",
        owned_names=["EX Special Attack:\xa0Really Heavy"],  # NBSP escape avoids ambiguous literal
        norm_name_to_agent_id={},
        id_to_name={},
    )
    assert finding is not None
    assert finding.classification == "NBSP"


def test_pseudo_key_never_flagged() -> None:
    """stun_onset_abloom is not an attack name — allowlisted, not a finding."""
    finding = classify_key(
        key="stun_onset_abloom",
        directory="moves",
        source_file="nangong_yu.json",
        agent_name="Nangong Yu",
        owned_names=[],
        norm_name_to_agent_id={},
        id_to_name={},
    )
    assert finding is None


def test_code_map_covers_every_classification() -> None:
    """Every classification scripts.audit_agent_data_binding emits has an L4 waiver code."""
    assert set(_L4_CODE_BY_CLASSIFICATION) == {"BIND", "FOREIGN", "DEAD", "NBSP"}


def test_check_l4_converts_binding_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_l4 wraps run_audit()'s output as L4 Finding objects, per-file indexed.

    Mocks run_audit so this stays DB-free like the rest of this file — the real
    end-to-end path (real DB, skip-if-unseeded) is the integration test's job.
    """
    synthetic = [
        BindingFinding(
            classification="FOREIGN",
            directory="moves",
            source_file="grace.json",
            agent_name="Grace",
            key="Basic Attack: Swiftedge",
            detail="resolves to an attack owned by a different agent: Ye Shunguang",
        ),
        BindingFinding(
            classification="DEAD",
            directory="moves",
            source_file="grace.json",
            agent_name="Grace",
            key="Special Attack: Enlightened Mind",
            detail="resolves to no attack for any agent",
        ),
    ]

    async def _fake_run_audit() -> list[BindingFinding]:
        return synthetic

    monkeypatch.setattr("scripts.validate_kits.run_audit", _fake_run_audit)

    result = check_l4([])

    assert [f.level for f in result] == ["L4", "L4"]
    assert [f.code for f in result] == ["foreign_move_key", "dead_move_key"]
    assert [f.source_file for f in result] == ["moves/grace.json", "moves/grace.json"]
    assert [f.index for f in result] == [0, 1]  # stable per-file position, not global
    assert all(isinstance(f, Finding) for f in result)


def test_check_l4_skips_cleanly_when_db_not_seeded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_run_audit() -> list[BindingFinding]:
        raise DatabaseNotSeededError("DB has no agents — seeded DB required")

    monkeypatch.setattr("scripts.validate_kits.run_audit", _fake_run_audit)

    result = check_l4([])

    assert result == []


# ---------------------------------------------------------------------------
# Buildup drift (informational; deliberately outside L4 and the merge gate)
# ---------------------------------------------------------------------------


def _drift_for(specs: dict, agg: dict, monkeypatch: pytest.MonkeyPatch) -> list:
    """Run audit_buildup_drift against synthetic specs + DB state, no real DB."""
    import asyncio

    from scripts import audit_agent_data_binding as mod

    async def _fake_state():
        return {"Tester": "agent-id"}, agg

    monkeypatch.setattr(mod, "load_buildup_state", _fake_state)
    monkeypatch.setattr(mod, "load_agent_moves", lambda _dir: specs)
    return asyncio.run(mod.audit_buildup_drift())


class _Spec:
    def __init__(self, agent_name: str, moves: dict) -> None:
        self.agent_name = agent_name
        self.moves = moves


class _Move:
    def __init__(self, buildup: int | None) -> None:
        self.buildup = buildup


def test_buildup_drift_flags_a_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A curated buildup that disagrees with its move's DB row sum is reported."""
    drifts = _drift_for(
        {"tester": _Spec("Tester", {"Basic Attack: Thing": _Move(9_598)})},
        {("agent-id", "Basic Attack: Thing"): (26_709, 2, "atomic")},
        monkeypatch,
    )
    assert len(drifts) == 1
    assert drifts[0].spec_buildup == 9_598
    assert drifts[0].db_sum == 26_709
    assert round(drifts[0].ratio, 2) == 0.36


def test_buildup_drift_ignores_matching_and_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A matching value is clean, and an omitted (None) one cannot drift.

    Since the omitted-buildup fix a `None` falls back to the DB rows at sim time, so
    reporting it as drift would be a false positive.
    """
    drifts = _drift_for(
        {
            "tester": _Spec(
                "Tester",
                {"Exact": _Move(500), "Omitted": _Move(None)},
            )
        },
        {
            ("agent-id", "Exact"): (500, 1, "atomic"),
            ("agent-id", "Omitted"): (12_345, 1, "atomic"),
        },
        monkeypatch,
    )
    assert drifts == []


def test_buildup_drift_handles_zero_db_sum(monkeypatch: pytest.MonkeyPatch) -> None:
    """Curated gauge where the DB reports none — Yuzuha's Hard Candy Shot class.

    `ratio` must not raise. That real case is closed (issue #82: nanoka and ZO both
    report attribute_infliction 0, so the entry now authors an explicit 0), but the
    shape it exposed is the reason drift is reported rather than auto-corrected — no
    "just use the DB sum" rule resolves a divide-by-zero.
    """
    drifts = _drift_for(
        {"tester": _Spec("Tester", {"Hard Candy Shot": _Move(12_000)})},
        {("agent-id", "Hard Candy Shot"): (0, 1, "atomic")},
        monkeypatch,
    )
    assert len(drifts) == 1
    assert drifts[0].ratio == float("inf")


def test_buildup_drift_is_unexplained_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A drift with no DOCUMENTED_DEVIATIONS entry reports no reason.

    The default has to be "unexplained": a deviation is only acceptable once someone
    writes down why the row set is not the move (issue #82).
    """
    drifts = _drift_for(
        {"tester": _Spec("Tester", {"Basic Attack: Thing": _Move(9_598)})},
        {("agent-id", "Basic Attack: Thing"): (26_709, 2, "atomic")},
        monkeypatch,
    )
    assert drifts[0].documented_reason is None


def test_buildup_drift_surfaces_a_documented_deviation(monkeypatch: pytest.MonkeyPatch) -> None:
    """A listed deviation still reports as drift, but carries its rationale.

    It must keep firing rather than being filtered out: the entry is retired by fixing
    the row set (issue #85's `potential` handling), and an entry that stopped firing
    silently would outlive the defect it describes — the failure mode
    known_issues.json's stale-waiver rule exists to prevent.
    """
    from scripts import audit_agent_data_binding as mod

    monkeypatch.setitem(
        mod.DOCUMENTED_DEVIATIONS, ("Tester", "Basic Attack: Thing"), "because reasons"
    )
    drifts = _drift_for(
        {"tester": _Spec("Tester", {"Basic Attack: Thing": _Move(9_598)})},
        {("agent-id", "Basic Attack: Thing"): (26_709, 2, "atomic")},
        monkeypatch,
    )
    assert len(drifts) == 1
    assert drifts[0].documented_reason == "because reasons"
