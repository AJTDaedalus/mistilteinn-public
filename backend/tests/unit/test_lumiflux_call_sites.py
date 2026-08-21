"""Task 32 — every production `simulate()` call site passes the Lumiflux kwargs.

Escalation E-5's failure mode was *a forgotten call site*: Refringe, Voidflare
capture, Luminize and Phase Flow were fully built, fully unit-tested, and inert
for every real request because nothing ever passed `lumiflux_specs`. Unit tests
that set the kwargs by hand cannot catch that — they are the seam.

So this test greps `app/` for `simulate(` and asserts each call passes
`lumiflux_specs=`, in the same spirit as Task 23's mechanism/policy purity test.
Adding a fifth un-wired call site fails CI. The allowlist is explicit and short;
adding to it is a deliberate, reviewable act.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

# Call sites that legitimately pass no Lumiflux arguments.
#
# `simulate_single_hit` evaluates one build against one enemy with no team and
# no rotation: there is no second agent to Refringe for, no swap to enter Phase
# Flow on, and its own docstring says it is not production traffic. Assembling
# inputs there would be dead weight, not safety.
EXEMPT: frozenset[tuple[str, str]] = frozenset(
    {
        ("services/anomaly_simulator.py", "simulate_single_hit"),
    }
)

REQUIRED_KWARGS = ("lumiflux_specs", "phase_flow_windows")


def _enclosing_function(tree: ast.Module, node: ast.AST) -> str:
    """Name of the innermost function containing `node`, or "<module>"."""
    best = "<module>"
    best_span = None
    for candidate in ast.walk(tree):
        if not isinstance(candidate, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end = getattr(candidate, "end_lineno", None)
        if end is None or not (candidate.lineno <= node.lineno <= end):
            continue
        span = end - candidate.lineno
        if best_span is None or span < best_span:
            best, best_span = candidate.name, span
    return best


def _simulate_calls() -> list[tuple[str, str, set[str]]]:
    """Every `simulate(...)` call under `app/`: (relpath, enclosing fn, kwargs)."""
    found: list[tuple[str, str, set[str]]] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "simulate":
                continue
            found.append(
                (
                    str(path.relative_to(APP_ROOT)),
                    _enclosing_function(tree, node),
                    {kw.arg for kw in node.keywords if kw.arg},
                )
            )
    return found


class TestEverySimulateCallSiteIsWired:
    def test_the_grep_finds_something(self) -> None:
        # A broken matcher would make every assertion below vacuously true.
        assert _simulate_calls(), "found no `simulate(` calls at all — matcher is broken"

    def test_all_three_production_entry_points_are_present(self) -> None:
        files = {rel for rel, _, _ in _simulate_calls()}
        assert {
            "api/v1/simulate.py",
            "services/optimizer_pipeline.py",
            "services/anomaly_simulator.py",
        } <= files
        sites = {(rel, fn) for rel, fn, _ in _simulate_calls()}
        assert ("services/anomaly_simulator.py", "simulate_combo_steps") in sites

    @pytest.mark.parametrize("call", _simulate_calls(), ids=lambda c: f"{c[0]}:{c[1]}")
    def test_call_site_passes_the_lumiflux_kwargs(self, call) -> None:
        rel, fn, kwargs = call
        if (rel, fn) in EXEMPT:
            pytest.skip(f"{rel}:{fn} is an allowlisted single-build call site")
        missing = [k for k in REQUIRED_KWARGS if k not in kwargs]
        assert not missing, (
            f"{rel}:{fn} calls simulate() without {missing}. Build them with "
            f"`lumiflux_assembly.assemble_lumiflux_inputs(builds, steps, moves_db)` "
            f"and pass both — a call site that forgets is exactly escalation E-5."
        )

    def test_every_exemption_still_corresponds_to_a_real_call_site(self) -> None:
        """A stale allowlist entry silently widens the hole it documents."""
        sites = {(rel, fn) for rel, fn, _ in _simulate_calls()}
        assert sites >= EXEMPT, f"stale exemptions: {sorted(EXEMPT - sites)}"


class TestStepMoveSpecCarriesTheLumifluxFields:
    """DESIGN §13.4 — the combo path synthesises its own move specs, so the
    fields the step loop reads have to be copied onto them."""

    def test_fields_exist_with_inert_defaults(self) -> None:
        from app.services.anomaly_simulator import _StepMoveSpec
        from app.services.modifiers import AttackScope

        spec = _StepMoveSpec(scope=AttackScope.ALL, element="fire")
        assert spec.triggers_luminize is False
        assert spec.luminize_mult_bp == 0
        assert spec.lumiflux_points == 0
        assert spec.phase_flow_entry is False

    def test_real_move_annotations_are_copied_by_attack_name(self) -> None:
        from app.services.anomaly_simulator import _lumiflux_move_fields

        fields = _lumiflux_move_fields("Remielle", "Ultimate: Dazzling Curtain Call")
        assert fields["triggers_luminize"] is True
        assert fields["luminize_mult_bp"] == 33600

        points = _lumiflux_move_fields("Remielle", "EX Special Attack: Ode to Dawn")
        assert points["lumiflux_points"] == 2
        assert points["phase_flow_entry"] is True

    def test_unknown_agent_or_move_yields_no_annotations(self) -> None:
        from app.services.anomaly_simulator import _lumiflux_move_fields

        assert _lumiflux_move_fields("Nobody At All", "Whatever") == {}
        assert _lumiflux_move_fields("Remielle", "Not A Real Move") == {}
