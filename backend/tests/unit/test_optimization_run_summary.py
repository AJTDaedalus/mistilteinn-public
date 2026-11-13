"""A saved formula estimate says what it is in the list row (math-fallback P1, task 8).

`DESIGN_team_math_fallback.md` §2.5: a formula result is labelled wherever it is shown,
including a stored one. The list's `summary` is what a row reads without loading the run, so
it carries the flag, and it does not invent an energy model for a run that simulated nothing.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.v1.optimization_runs import _summary


def test_a_formula_estimate_is_flagged_and_has_no_energy_model():
    run = SimpleNamespace(objective={
        "kind": "formula-estimate", "artifact_set_ids": [15003], "wait_for_energy": False,
    })
    summary = _summary(run)
    assert summary["formula_estimate"] is True
    assert summary["energy_model"] is None
    assert summary["sets"] == [15003]


def test_a_gcsim_run_is_not_flagged_and_keeps_its_energy_model():
    run = SimpleNamespace(objective={"wait_for_energy": True})
    summary = _summary(run)
    assert summary["formula_estimate"] is False
    assert summary["energy_model"] == "waiting"


def test_a_run_with_no_objective_is_not_a_formula_estimate():
    assert _summary(SimpleNamespace(objective=None))["formula_estimate"] is False
