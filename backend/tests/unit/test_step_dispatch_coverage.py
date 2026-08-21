"""Every damage-step type must be handled at every dispatch site.

There are three independent places that switch on step type, each with its own
`isinstance` chain ending in `raise TypeError`:

* `damage_dag_service.evaluate_steps_total` — the baseline / current-damage path
* `disc_optimizer.optimize_discs` — the optimizer's per-frame context builder
* `disc_scorer.score_disc_potential` — the ranker's per-disc scorer

They are wired independently, so adding a step type wires one and forgets the
others. That is not hypothetical: `RefringeCreditStep` (#160) was added to the
first two, and the third raised `TypeError` on every rank request with a Lumiflux
agent on the team until this test was written.

The `raise TypeError` guards (E-8 acceptance item 4) turn that into a loud
failure rather than a silent zero, which is right — but they only fire when a
request actually produces the step, i.e. in production, on the teams that use the
mechanic. This test moves the discovery to commit time.

Deliberately a source-level check rather than an end-to-end one: constructing a
real `BuildSnapshot` + `EnemySnapshot` + registry for three call sites would test
the arithmetic (already covered elsewhere) at the cost of not actually asserting
the thing that breaks, which is *coverage of the union*.
"""

from __future__ import annotations

import inspect

import pytest

from app.services import combo_types, damage_dag_service, disc_optimizer, disc_scorer


def _union_member_names(union: object) -> set[str]:
    """Class names in a `Union[...]`, tolerating forward references."""
    return {
        arg.__forward_arg__ if hasattr(arg, "__forward_arg__") else arg.__name__
        for arg in union.__args__  # type: ignore[attr-defined]
    }


DAMAGE_STEPS = _union_member_names(combo_types.DamageStep)

_DISPATCHERS = [
    pytest.param(damage_dag_service.evaluate_steps_total, id="evaluate_steps_total"),
    pytest.param(disc_optimizer.optimize_discs, id="optimize_discs"),
    pytest.param(disc_scorer.score_disc_potential, id="score_disc_potential"),
]


def test_the_union_is_not_empty() -> None:
    """Guards the guard — a broken introspection helper would vacuously pass."""
    assert DAMAGE_STEPS
    assert "ComboStep" in DAMAGE_STEPS
    assert "AnomalyStep" in DAMAGE_STEPS


@pytest.mark.parametrize("dispatcher", _DISPATCHERS)
def test_dispatcher_handles_every_damage_step_type(dispatcher) -> None:
    source = inspect.getsource(dispatcher)
    missing = sorted(name for name in DAMAGE_STEPS if name not in source)
    assert not missing, (
        f"{dispatcher.__name__} does not mention {missing}. "
        "Every DamageStep member needs an explicit branch here — the trailing "
        "`raise TypeError` means an unwired type takes out live requests for "
        "exactly the teams that use the mechanic."
    )


@pytest.mark.parametrize("dispatcher", _DISPATCHERS)
def test_dispatcher_still_rejects_unknown_types(dispatcher) -> None:
    """The strict tail must survive; a fall-through `else` would score zero.

    Silent zeros are the failure mode E-8 added these guards against, and the one
    `aftershock`/`abloom`/`sweeping`/`kit_formula` still exhibit on the event side
    (#163).
    """
    source = inspect.getsource(dispatcher)
    assert "TypeError" in source, (
        f"{dispatcher.__name__} lost its unhandled-step-type guard; a new step "
        "type would now be scored as zero instead of failing loudly."
    )
