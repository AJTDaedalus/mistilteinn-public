"""Baseline and candidate scoring must agree on the same discs (C3, numeric half).

The UI's improvement figure divides `total_damage` — produced by the optimizer's
per-candidate overlay path — by `current_build_damage`, produced by
`evaluate_steps_total`. If the two disagree on the same disc set, the reported Δ%
is wrong even when both numbers are individually plausible.

`test_damage_dag_overlay.py` already pins overlay-vs-full-DAG parity for standard
and anomaly steps. This covers the whole step LIST, and specifically the kinds
added for #160, which had none: both credit steps strip the build's discs when
building their context and rely on the caller to overlay them back. A context
built without the strip, or a caller that forgets the overlay, produces a number
that is wrong in one path and right in the other — exactly the shape that
corrupts a delta while leaving both totals believable.
"""

from __future__ import annotations

import pytest

from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import (
    AnomalyStep,
    ComboStep,
    LuminizeStep,
    RefringeCreditStep,
    SquadAtkCreditStep,
)
from app.services.damage_dag_service import (
    build_refringe_credit_context,
    build_squad_atk_credit_context,
    compute_luminize_with_accumulated_disc,
    compute_luminize_with_disc_overlay,
    evaluate_steps_total,
)
from app.services.modifiers import ActiveConditions, AttackScope
from app.services.stat_calculator import accumulate_disc_stats

# Real disc shape: main_stat_type/main_stat_value plus substats. A flat-key dict
# accumulates to nothing, which would make every parity assertion below pass
# vacuously — `test_the_discs_actually_move_the_number` exists to catch exactly
# that, and did.
_DISCS = [
    {
        "main_stat_type": "anomaly_proficiency",
        "main_stat_value": 92,
        "substats": [
            {"stat": "atk_pct", "value": 2400},
            {"stat": "crit_rate", "value": 960},
        ],
    },
    {
        "main_stat_type": "atk",
        "main_stat_value": 316,
        "substats": [{"stat": "crit_dmg", "value": 1440}],
    },
]


def _build(disc_stats):
    return BuildSnapshot(
        agent_element="physical",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=120,
        disc_stats=disc_stats,
        modifiers=[],
    )


def _enemy():
    return EnemySnapshot(level=60, base_def=50, element_res=0)


def _credit_steps():
    return [
        RefringeCreditStep(
            label="Refringe credit",
            attack_id="rc",
            frozen_tick_damage=5000.0,
            refringe_mult_at_stripped_ap=11224,
            refringe_ap_ratio_bp=2,
            refringe_flat_bonus_bp=2000,
        ),
        SquadAtkCreditStep(
            label="Squad ATK credit",
            attack_id="sac",
            frozen_teammate_damage=5000.0,
            teammate_atk_at_sim=3000,
            grant_rows=((240, 600), (1120, 2800)),
        ),
    ]


@pytest.mark.parametrize(
    ("step", "builder"),
    [
        pytest.param(_credit_steps()[0], build_refringe_credit_context, id="refringe_credit"),
        pytest.param(_credit_steps()[1], build_squad_atk_credit_context, id="squad_atk_credit"),
    ],
)
class TestCreditStepsScoreTheSameBothWays:
    def test_baseline_path_matches_the_candidate_overlay(self, step, builder) -> None:
        """`evaluate_steps_total` (baseline) vs the optimizer's overlay (candidate)."""
        geared = _build(_DISCS)
        baseline = evaluate_steps_total(
            build=geared,
            enemy=_enemy(),
            steps=[step],
            conditions=ActiveConditions(),
        )
        # The optimizer's shape: context off a disc-stripped build, discs overlaid
        # per candidate as an accumulated vector.
        ctx = builder(
            build=geared,
            enemy=_enemy(),
            step=step,
            conditions=ActiveConditions(),
        )
        candidate = compute_luminize_with_accumulated_disc(ctx, accumulate_disc_stats(_DISCS))
        assert baseline == pytest.approx(candidate)

    def test_the_discs_actually_move_the_number(self, step, builder) -> None:
        """Guards a false pass: two paths that both ignore discs also 'agree'."""
        bare = evaluate_steps_total(
            build=_build([]), enemy=_enemy(), steps=[step], conditions=ActiveConditions()
        )
        geared = evaluate_steps_total(
            build=_build(_DISCS), enemy=_enemy(), steps=[step], conditions=ActiveConditions()
        )
        assert geared > bare

    def test_the_raw_and_accumulated_overlays_agree(self, step, builder) -> None:
        ctx = builder(
            build=_build(_DISCS), enemy=_enemy(), step=step, conditions=ActiveConditions()
        )
        assert compute_luminize_with_disc_overlay(ctx, _DISCS) == pytest.approx(
            compute_luminize_with_accumulated_disc(ctx, accumulate_disc_stats(_DISCS))
        )


class TestMixedStepListsAreAdditive:
    def test_a_list_totals_its_parts(self) -> None:
        """Consolidation multiplies a context by an occurrence count, which is only
        exact if step scoring is a linear sum — assert that directly."""
        geared, enemy, conds = _build(_DISCS), _enemy(), ActiveConditions()
        steps = [
            ComboStep(
                label="Hit",
                attack_id="hit",
                attack_name="Hit",
                scope=AttackScope.ALL,
                multiplier=5000,
            ),
            AnomalyStep(
                label="Burn",
                attack_id="burn",
                anomaly_type="burn",
                element="fire",
                procs_override=1.0,
            ),
            *_credit_steps(),
        ]
        whole = evaluate_steps_total(build=geared, enemy=enemy, steps=steps, conditions=conds)
        parts = sum(
            evaluate_steps_total(build=geared, enemy=enemy, steps=[s], conditions=conds)
            for s in steps
        )
        assert whole == pytest.approx(parts)


class TestOwnerScaledLuminizeIsRescaledNotFrozen:
    """The P-F2 shape must not be read as a plain constant (#169 follow-up).

    An owner-scaled `LuminizeStep` sets BOTH `is_owner_scaled` and
    `frozen_damage` — and there `frozen_damage` is the rescale BASE, computed
    against her DISC-STRIPPED snapshot, not the answer. `evaluate_steps_total`
    tested `frozen_damage` first and added that stale value, so her live Anomaly
    Proficiency moved her own Luminize by exactly zero on the baseline path while
    `optimize_discs` rescaled it correctly.

    That is worse than a wrong number: `current_build_damage` comes from this
    path, so the baseline understated precisely the build AP is supposed to
    scale, making AP look worthless in any measurement taken through it.
    """

    @staticmethod
    def _owner_scaled():
        return LuminizeStep(
            label="Luminize",
            attack_id="lum",
            voidflare_element="physical",
            effective_mult_bp=22060,   # the fold at her stripped AP
            def_ignore=0,
            constant_factor=1.0,
            frozen_damage=100_000.0,   # rescale BASE, not the answer
            owner_base_mult_bp=32000,
            owner_ap_bonus_bp=20,
            owner_anomaly_boost_mult=10000,
        )

    def test_her_ap_moves_her_own_luminize(self) -> None:
        step = self._owner_scaled()
        assert step.is_owner_scaled, "fixture broken: not the owner-scaled shape"
        args = {"enemy": _enemy(), "steps": [step], "conditions": ActiveConditions()}
        bare = evaluate_steps_total(build=_build([]), **args)
        geared = evaluate_steps_total(build=_build(_DISCS), **args)
        assert geared > bare, (
            "adding AP-bearing discs did not change her own Luminize — the "
            "baseline path is treating an owner-scaled step as a frozen constant"
        )

    def test_a_support_captured_voidflare_stays_constant(self) -> None:
        """The other shape must NOT be rescaled: a support's build is never
        stripped, so its frozen number is exact and discs must not touch it."""
        step = LuminizeStep(
            label="Luminize",
            attack_id="lum",
            voidflare_element="physical",
            effective_mult_bp=22060,
            def_ignore=0,
            constant_factor=1.0,
            frozen_damage=100_000.0,
        )
        assert not step.is_owner_scaled
        args = {"enemy": _enemy(), "steps": [step], "conditions": ActiveConditions()}
        assert evaluate_steps_total(build=_build(_DISCS), **args) == pytest.approx(
            evaluate_steps_total(build=_build([]), **args)
        )


class TestEquipperGatedSetBonusesSurviveTheOptimizerPath:
    """`applicable_set_modifiers` must resolve `equipper_is_*` (#171).

    `_strip_disc_contribution` removes every `_DISC_SET_SOURCES` modifier from
    the optimizer's base and `applicable_set_modifiers` re-adds them per frame.
    It did not resolve `equipper_is_*` gates, so any set row carrying one stayed
    inert for the entire search — while `snapshot_builder`, which the baseline
    uses, resolved them normally.

    A silent systematic under-score, not a crash: on the run that surfaced it the
    optimizer scored the *identical* disc set 51,657 below the baseline, exactly
    `luminize − luminize / 1.15` from Feathered Fate's dropped 4pc "+15%
    Attribute Anomaly DMG (Lumiflux equipper)".
    """

    FEATHERED_FATE = 34100

    def _mods(self):
        from app.services.modifier_loader import load_disc_set_modifiers

        return {self.FEATHERED_FATE: load_disc_set_modifiers(str(self.FEATHERED_FATE))}

    def test_a_lumiflux_equipper_keeps_the_gated_4pc(self) -> None:
        from app.services.snapshot_builder import applicable_set_modifiers

        out = applicable_set_modifiers(
            {self.FEATHERED_FATE: 4}, self._mods(),
            equipper_specialty="anomaly", equipper_element="lumiflux",
        )
        assert any(m.stat == "anomaly_dmg_bonus" for m in out), (
            "Feathered Fate's Lumiflux-gated 4pc was dropped for a Lumiflux "
            "equipper — equipper_is_* is not being resolved (#171)"
        )

    def test_a_non_lumiflux_equipper_does_not_get_it(self) -> None:
        """The gate must still gate — otherwise this trades an under-credit for
        an over-credit on every other agent wearing the set."""
        from app.services.snapshot_builder import applicable_set_modifiers

        out = applicable_set_modifiers(
            {self.FEATHERED_FATE: 4}, self._mods(),
            equipper_specialty="anomaly", equipper_element="fire",
        )
        assert not any(m.stat == "anomaly_dmg_bonus" for m in out)

    def test_ungated_rows_are_unaffected(self) -> None:
        from app.services.snapshot_builder import applicable_set_modifiers

        out = applicable_set_modifiers(
            {self.FEATHERED_FATE: 4}, self._mods(),
            equipper_specialty="anomaly", equipper_element="fire",
        )
        assert any(m.stat == "anomaly_proficiency_flat" for m in out), (
            "the 2pc/4pc AP rows carry no equipper gate and must always survive"
        )
