"""`total_damage` means TEAM damage; the target's share is recoverable (A3).

The credits (#160) attribute the part of a teammate's damage the target's stats
move. The remainder is still team damage and was simply absent from the reported
total, which made `total_damage` neither the target's damage nor the team's.

A `TeammateDamageStep` carries that remainder as one constant per step list. It
cannot affect ranking — no candidate changes it by a point — so this is a
reporting fix, not a scoring one, and the two properties below are what make it
safe.
"""

from __future__ import annotations

import pytest

from app.schemas.optimizer import OptimizerDiscBuildSchema
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep, TeammateDamageStep
from app.services.damage_dag_service import evaluate_steps_total
from app.services.modifiers import ActiveConditions, AttackScope


def _build():
    return BuildSnapshot(
        agent_element="physical", agent_level=60, agent_base_atk=1000, modifiers=[]
    )


def _enemy():
    return EnemySnapshot(level=60, base_def=50, element_res=0)


def _hit():
    return ComboStep(
        label="Hit", attack_id="hit", attack_name="Hit", scope=AttackScope.ALL, multiplier=5000
    )


def _constant(value=12345.0):
    return TeammateDamageStep(
        label="Teammate damage (not attributable)",
        attack_id="tc",
        frozen_damage=value,
    )


class TestItIsAdditiveAndConstant:
    def test_the_total_grows_by_exactly_the_constant(self) -> None:
        args = {"build": _build(), "enemy": _enemy(), "conditions": ActiveConditions()}
        without = evaluate_steps_total(steps=[_hit()], **args)
        with_ = evaluate_steps_total(steps=[_hit(), _constant()], **args)
        assert with_ - without == pytest.approx(12345.0)

    def test_it_does_not_depend_on_the_build(self) -> None:
        """The ranking-safety property, asserted rather than argued.

        A term that varied with the build would reorder candidates; this one is
        frozen teammate damage, so two very different builds must see the same
        contribution from it.
        """
        weak = BuildSnapshot(
            agent_element="physical", agent_level=60, agent_base_atk=100, modifiers=[]
        )
        strong = BuildSnapshot(
            agent_element="physical", agent_level=60, agent_base_atk=9000, modifiers=[]
        )
        conds, enemy = ActiveConditions(), _enemy()
        delta_weak = evaluate_steps_total(
            build=weak, enemy=enemy, steps=[_hit(), _constant()], conditions=conds
        ) - evaluate_steps_total(build=weak, enemy=enemy, steps=[_hit()], conditions=conds)
        delta_strong = evaluate_steps_total(
            build=strong, enemy=enemy, steps=[_hit(), _constant()], conditions=conds
        ) - evaluate_steps_total(build=strong, enemy=enemy, steps=[_hit()], conditions=conds)
        assert delta_weak == pytest.approx(delta_strong)

    def test_zero_is_representable_and_inert(self) -> None:
        args = {"build": _build(), "enemy": _enemy(), "conditions": ActiveConditions()}
        assert evaluate_steps_total(steps=[_hit(), _constant(0.0)], **args) == pytest.approx(
            evaluate_steps_total(steps=[_hit()], **args)
        )


class TestTheShareIsRecoverable:
    def test_subtracting_the_field_gives_the_attributed_share(self) -> None:
        schema = OptimizerDiscBuildSchema(
            total_damage=100_000.0,
            teammate_unattributed_damage=40_000.0,
            disc_ids=[],
            set_counts={},
        )
        assert schema.total_damage - schema.teammate_unattributed_damage == 60_000.0

    def test_the_field_defaults_so_old_payloads_validate(self) -> None:
        schema = OptimizerDiscBuildSchema(total_damage=1.0, disc_ids=[], set_counts={})
        assert schema.teammate_unattributed_damage == 0.0
