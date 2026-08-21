"""Task 36 / escalation E-8 — how a `LuminizeStep` is scored against a candidate.

These are the three properties the E-8 resolution named as acceptance criteria
beyond "a step reaches the mapping", plus the unhandled-step-type guard. Each
pins a specific way the obvious implementation goes wrong:

1. **The naked-DPS regression** — scoring must rise with the scored build's
   gear. If a future refactor carries the simulation's frozen numbers instead of
   rescoring, this goes flat, because the optimizer simulates a *disc-stripped*
   build and those frozen numbers are zero-disc numbers (E-8 Finding 2).
2. **Wrong-agent mitigation** — Luminize is computed in Remielle's context, so
   DEF-ignore, RES shred, vulnerability and AnomalyBoostArea are hers. The
   anomaly DAG node reads all four from the registry, which here holds the
   *scored* build, and those are ``"sum"`` reads — so a corrective entry would
   add to the wrong agent's value rather than replace it. Reusing
   ``build_anomaly_step_context`` would pass every other test in this file
   (E-8 Amendment 2).
3. **Provenance** — a support-captured Voidflare is a constant; a DPS-captured
   one is not. Getting this backwards is silent.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.services.build_damage_service import (
    BuildSnapshot,
    EnemySnapshot,
    resolve_build_stats,
)
from app.services.combo_types import LuminizeStep
from app.services.damage_calculator import calculate_luminize_damage
from app.services.damage_dag_service import (
    build_luminize_owner_scaled_context,
    build_luminize_step_context,
    calculate_build_anomaly_dag,
    compute_luminize_with_disc_overlay,
    evaluate_steps_total,
)
from app.services.modifiers import (
    ActiveConditions,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)

_GEAR = [
    {"main_stat_type": "atk_pct", "main_stat_value": 3000},
    {"main_stat_type": "anomaly_proficiency", "main_stat_value": 300},
    {"main_stat_type": "pen_ratio", "main_stat_value": 1000},
]


def _enemy() -> EnemySnapshot:
    return EnemySnapshot(level=60, base_def=50, element_res=0, stun_dmg_mult=10000)


def _build(disc_stats: list[dict] | None = None, modifiers: list[Modifier] | None = None):
    return BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_source_id="burnice",
        agent_specialty="anomaly",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=115,
        agent_anomaly_mastery=100,
        disc_stats=disc_stats or [],
        modifiers=modifiers or [],
    )


def _step(**overrides) -> LuminizeStep:
    kwargs = {
        "label": "Luminize (fire)",
        "attack_id": "luminize_fire_1.0",
        "voidflare_element": "fire",
        "effective_mult_bp": 20_000,
        "def_ignore": 0,
        "constant_factor": 1.5,
        "frozen_damage": None,
    }
    kwargs.update(overrides)
    return LuminizeStep(**kwargs)


def _score(build: BuildSnapshot, step: LuminizeStep) -> float:
    ctx = build_luminize_step_context(
        build=build,
        enemy=_enemy(),
        step=step,
        conditions=ActiveConditions(),
    )
    return compute_luminize_with_disc_overlay(ctx, build.disc_stats)


def _self_modifier(stat: str, value: int) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.CORE_SKILL,
        source_label=f"test {stat}",
        target=ModifierTarget.SELF,
        conditions=[Condition.ALWAYS],
    )


class TestScalesWithTheScoredBuild:
    """E-8 Finding 2. The optimizer hands `simulate()` a disc-stripped build, so
    a Voidflare captured from it froze zero-disc ATK / DMG% / PEN / AP. Carrying
    those numbers forward would score the step as though the build wore nothing.
    """

    def test_geared_scores_higher_than_stripped(self) -> None:
        step = _step()
        stripped = _score(_build(), step)
        geared = _score(_build(disc_stats=_GEAR), step)
        assert stripped > 0
        assert geared > stripped, (
            "the Luminize step did not scale with the scored build's discs — it is "
            "being carried as a frozen value, which in the optimizer is the "
            "disc-stripped (naked) value"
        )

    @pytest.mark.parametrize(
        "disc",
        [
            {"main_stat_type": "atk_pct", "main_stat_value": 3000},
            {"main_stat_type": "anomaly_proficiency", "main_stat_value": 300},
            {"main_stat_type": "pen_ratio", "main_stat_value": 1000},
            {"main_stat_type": "fire_dmg", "main_stat_value": 3000},
        ],
    )
    def test_each_live_term_moves_the_score(self, disc: dict) -> None:
        """All four DPS-derived zones must actually be wired to the registry.

        A node that dropped, say, BoostArea would still pass the test above on
        the strength of ATK alone.
        """
        step = _step()
        assert _score(_build(disc_stats=[disc]), step) > _score(_build(), step)


class TestMitigationComesFromRemielleNotTheScoredBuild:
    """E-8 Amendment 2. Six of Luminize's inputs belong to Remielle. The four
    below are registry-backed in the anomaly node, so reusing that node would
    read them off the scored build instead — silently, and in a direction that
    grows with the scored build's own buffs.
    """

    @pytest.mark.parametrize(
        "stat",
        ["def_ignore", "res_reduction", "res_ignore", "vulnerability", "anomaly_dmg_bonus"],
    )
    def test_control_these_modifiers_do_reach_the_anomaly_path(self, stat: str) -> None:
        """Guards the test below from going vacuous.

        ``test_scored_builds_own_mitigation_is_ignored`` asserts a *non*-effect,
        so it would keep passing if these modifiers stopped being routed at all
        (a rename, a changed `ModifierTarget`, a dropped combat-bonus bucket).
        This pins that they genuinely bite on the ordinary anomaly path, which
        is the node Luminize must NOT be scored by.
        """
        plain = calculate_build_anomaly_dag(
            build=_build(disc_stats=_GEAR),
            enemy=_enemy(),
            anomaly_type="burn",
            conditions=ActiveConditions(),
        ).total
        buffed = calculate_build_anomaly_dag(
            build=_build(disc_stats=_GEAR, modifiers=[_self_modifier(stat, 5000)]),
            enemy=_enemy(),
            anomaly_type="burn",
            conditions=ActiveConditions(),
        ).total
        assert buffed > plain

    @pytest.mark.parametrize(
        "stat",
        ["def_ignore", "res_reduction", "res_ignore", "vulnerability", "anomaly_dmg_bonus"],
    )
    def test_scored_builds_own_mitigation_is_ignored(self, stat: str) -> None:
        step = _step()
        plain = _score(_build(), step)
        with_own_buff = _score(_build(modifiers=[_self_modifier(stat, 5000)]), step)
        assert with_own_buff == pytest.approx(plain), (
            f"the scored build's own {stat} changed the Luminize result; that zone "
            "belongs to the Lumiflux agent and must come from the step's baked "
            "constants, not from the registry"
        )

    def test_the_steps_def_ignore_is_applied(self) -> None:
        """The mirror of the above: Remielle's DEF-ignore *must* reach DEFArea.

        It cannot fold into ``constant_factor`` because DEFArea subtracts it from
        the scored build's PEN before taking a ratio, so it is the one
        Remielle-side term that has to travel as its own field.
        """
        build = _build(disc_stats=_GEAR)
        assert _score(build, _step(def_ignore=5000)) > _score(build, _step(def_ignore=0))

    def test_the_constant_factor_is_applied_linearly(self) -> None:
        build = _build(disc_stats=_GEAR)
        assert _score(build, _step(constant_factor=3.0)) == pytest.approx(
            2 * _score(build, _step(constant_factor=1.5))
        )


class TestProvenanceSplit:
    """E-8 Finding 1 / question 1. One Voidflare store, keyed by the Lumiflux
    agent, can hold captures from several teammates. They score differently.
    """

    def test_frozen_damage_is_carried_verbatim_and_does_not_scale(self) -> None:
        step = _step(frozen_damage=12_345.0)
        stripped = evaluate_steps_total(
            build=_build(), enemy=_enemy(), steps=[step], conditions=ActiveConditions()
        )
        geared = evaluate_steps_total(
            build=_build(disc_stats=_GEAR),
            enemy=_enemy(),
            steps=[step],
            conditions=ActiveConditions(),
        )
        assert stripped == pytest.approx(12_345.0)
        assert geared == pytest.approx(12_345.0), (
            "a support-captured Voidflare was rescored against the candidate; "
            "supports are never disc-stripped, so its frozen value is already exact"
        )

    def test_live_step_is_rescored_by_evaluate_steps_total(self) -> None:
        step = _step()
        stripped = evaluate_steps_total(
            build=_build(), enemy=_enemy(), steps=[step], conditions=ActiveConditions()
        )
        geared = evaluate_steps_total(
            build=_build(disc_stats=_GEAR),
            enemy=_enemy(),
            steps=[step],
            conditions=ActiveConditions(),
        )
        assert geared > stripped > 0


class TestParityWithTheProceduralCalculator:
    """The factoring is only safe if it reproduces `calculate_luminize_damage`.

    E-8 ruled that the chain separates into four live terms times one constant
    ``K = RES x Vuln x Stun x Level x AnomalyBoost``, with ``def_ignore`` carried
    apart because DEFArea subtracts it from the scored build's PEN. This checks
    that claim end to end rather than trusting the algebra: resolve a real
    build's stats, feed them to the procedural calculator as a Voidflare, then
    score the equivalent step against that same build and compare.

    This is DESIGN §13.5's "optimizer total matches simulate()'s luminize term
    for the equipped set", reduced to the one step that carries it.
    """

    @pytest.mark.parametrize("def_ignore", [0, 3000])
    @pytest.mark.parametrize("discs", [[], _GEAR])
    def test_scored_step_matches_calculate_luminize_damage(
        self, discs: list[dict], def_ignore: int
    ) -> None:
        build = _build(disc_stats=discs)
        stats = resolve_build_stats(build, ActiveConditions())

        # Remielle-side and enemy-side inputs, chosen non-neutral so a dropped
        # zone shows up as a mismatch rather than cancelling out.
        remielle_anomaly_dmg_bonus = 4000
        enemy_res = -1000
        vulnerability = [1500]

        expected = calculate_luminize_damage(
            voidflare_atk=stats.atk,
            voidflare_dmg_bonus_bp=0,
            voidflare_pen_ratio_bp=stats.pen_ratio,
            voidflare_pen_flat=stats.pen_flat,
            voidflare_anomaly_proficiency=stats.anomaly_proficiency,
            luminize_mult_bp=20_000,
            attacker_level=60,
            remielle_anomaly_proficiency=0,
            ap_bonus_per_point_bp=0,
            remielle_anomaly_dmg_bonus=remielle_anomaly_dmg_bonus,
            enemy_base_def=50,
            enemy_level=60,
            def_ignore=def_ignore,
            enemy_res=enemy_res,
            vulnerability_bonuses=vulnerability,
        )

        # The mapping builds `constant_factor` from exactly these AnomalyResult
        # fields — see the `luminize` event detail in anomaly_simulator.py.
        constant_factor = (
            (expected.res_mult / 10000)
            * (expected.vulnerability_mult / 10000)
            * (expected.stun_mult / 10000)
            * (expected.level_mult / 10000)
            * (expected.anomaly_boost_mult / 10000)
        )
        step = _step(
            effective_mult_bp=expected.effective_mult_bp,
            def_ignore=def_ignore,
            constant_factor=constant_factor,
        )
        enemy = EnemySnapshot(
            level=60, base_def=50, element_res=enemy_res, stun_dmg_mult=10000
        )
        ctx = build_luminize_step_context(
            build=build, enemy=enemy, step=step, conditions=ActiveConditions()
        )
        actual = compute_luminize_with_disc_overlay(ctx, build.disc_stats)

        # The DAG stays in float where the procedural path floors at every zone,
        # so parity is ~1% — the tolerance the DAG service documents.
        assert actual == pytest.approx(expected.total, rel=0.01)


class TestUnhandledStepTypeIsLoud:
    """E-8 acceptance item 4. The dispatch sites used to fall through to an
    `else` that assumed `ComboStep` and read `step.multiplier`. A new step type
    reaching one of them died with an AttributeError pointing at the consumer
    rather than at the type nobody wired up — or, worse, would score as zero if
    the attribute happened to exist.
    """

    def test_evaluate_steps_total_raises_on_an_unknown_step(self) -> None:
        class _MysteryStep:
            label = "?"

        with pytest.raises(TypeError, match="unhandled step type _MysteryStep"):
            evaluate_steps_total(
                build=_build(),
                enemy=_enemy(),
                steps=[_MysteryStep()],
                conditions=ActiveConditions(),
            )


class TestOwnerScaledLuminize:
    """P-F2 / hardening Task 15 — the Lumiflux agent is herself the optimized DPS.

    That case inverts everything above. She can never capture a Voidflare from
    herself (`_resolve_refringe` no-ops on a Lumiflux acting agent), so every
    Luminize event names a support as its source and takes the frozen branch --
    and the frozen number embeds HER disc-stripped AP inside `effective_mult_bp`
    and her Anomaly DMG% inside `constant_factor`.

    The result was that AP discs, her single most important stat, showed **zero**
    marginal value on the largest part of her own damage, and the optimizer
    ranked her builds on her direct hits alone.
    """

    _AP_ONLY: ClassVar[list[dict]] = [
        {"main_stat_type": "anomaly_proficiency", "main_stat_value": 300}
    ]

    def _owner_step(self, **overrides) -> LuminizeStep:
        kwargs = {
            "frozen_damage": 10_000.0,
            # 200% base, folded at her stripped AP of 115 with 20 bp/AP:
            # 20000 * (10000 + 20*115) // 10000 = 20000 * 12300 // 10000 = 24600
            "effective_mult_bp": 24_600,
            "owner_base_mult_bp": 20_000,
            "owner_ap_bonus_bp": 20,
        }
        kwargs.update(overrides)
        return _step(**kwargs)

    def _score_owner(self, build: BuildSnapshot, step: LuminizeStep) -> float:
        ctx = build_luminize_owner_scaled_context(
            build=build,
            enemy=_enemy(),
            step=step,
            conditions=ActiveConditions(),
        )
        return compute_luminize_with_disc_overlay(ctx, build.disc_stats)

    def test_the_step_reports_itself_as_owner_scaled(self) -> None:
        assert self._owner_step().is_owner_scaled
        assert not _step(frozen_damage=1.0).is_owner_scaled
        assert not _step().is_owner_scaled

    def test_ap_discs_now_move_the_score(self) -> None:
        """The defect, inverted. Pre-fix both of these were 10_000.0."""
        stripped = self._score_owner(_build(), self._owner_step())
        with_ap = self._score_owner(_build(disc_stats=self._AP_ONLY), self._owner_step())
        assert with_ap > stripped

    def test_the_stripped_score_reproduces_the_frozen_damage_exactly(self) -> None:
        """The rescale must be an identity at the AP the simulation used --
        otherwise it silently re-bases every Luminize in the rotation."""
        assert self._score_owner(_build(), self._owner_step()) == pytest.approx(10_000.0)

    def test_the_rescale_is_the_hand_derived_ratio(self) -> None:
        """Absolute pin, derived by hand rather than from the implementation.

        Base AP 115 + 300 from the disc main stat = 415.
        Live fold  = 20000 * (1 + 20*415/10000) = 20000 * 1.83  = 36_600
        Stripped   = 24_600 (the step's `effective_mult_bp`)
        Expected   = 10_000 * 36_600 / 24_600 = 14_878.048...
        """
        scored = self._score_owner(_build(disc_stats=self._AP_ONLY), self._owner_step())
        assert scored == pytest.approx(10_000.0 * 36_600 / 24_600)

    def test_a_non_ap_disc_does_not_move_it(self) -> None:
        """Control: only her AP enters the rescaled half. ATK% belongs to the
        captured teammate, whose contribution is frozen and must stay frozen."""
        atk_only = [{"main_stat_type": "atk_pct", "main_stat_value": 3000}]
        assert self._score_owner(
            _build(disc_stats=atk_only), self._owner_step()
        ) == pytest.approx(self._score_owner(_build(), self._owner_step()))


class TestOwnerScaledAnomalyDmgBonus:
    """P-F2's second Remielle-owned frozen term, and the one with teeth.

    `constant_factor` bakes AnomalyBoostArea (10000 + her Attribute Anomaly
    DMG%) at simulation time — and the optimizer simulates a build stripped of
    both disc stats AND disc-set modifiers (`_strip_disc_contribution` filters
    `_DISC_SET_SOURCES`). So Feathered Fate's 4pc +15% Attribute Anomaly DMG was
    invisible on Luminize: the optimizer under-valued her SIGNATURE set on the
    damage source that dominates her kit.

    Unlike the AP fold this is not a per-candidate quantity — her Anomaly DMG%
    varies only with the disc SET distribution, which the optimizer already
    resolves once per frame. So it rides as a constant and the node stays linear.
    """

    _AP_ONLY: ClassVar[list[dict]] = [
        {"main_stat_type": "anomaly_proficiency", "main_stat_value": 300}
    ]

    def _step(self, **overrides) -> LuminizeStep:
        kwargs = {
            "frozen_damage": 10_000.0,
            "effective_mult_bp": 24_600,
            "owner_base_mult_bp": 20_000,
            "owner_ap_bonus_bp": 20,
            # The simulation's disc-stripped run saw 0% Anomaly DMG.
            "owner_anomaly_boost_mult": 10_000,
        }
        kwargs.update(overrides)
        return _step(**kwargs)

    def _four_pc(self, value: int = 1500) -> Modifier:
        return Modifier(
            stat="anomaly_dmg_bonus",
            value=value,
            source=ModifierSource.DISC_SET_4PC,
            source_label="4pc: Attribute Anomaly DMG",
            target=ModifierTarget.SELF,
            conditions=[Condition.ALWAYS],
        )

    def _score(self, build: BuildSnapshot, step: LuminizeStep) -> float:
        ctx = build_luminize_owner_scaled_context(
            build=build, enemy=_enemy(), step=step, conditions=ActiveConditions()
        )
        return compute_luminize_with_disc_overlay(ctx, build.disc_stats)

    def test_a_four_piece_anomaly_dmg_bonus_now_moves_the_score(self) -> None:
        """The defect, inverted. Pre-fix both of these were 10_000.0."""
        plain = self._score(_build(), self._step())
        with_4pc = self._score(_build(modifiers=[self._four_pc()]), self._step())
        assert with_4pc > plain

    def test_the_bonus_applies_at_exactly_its_stated_size(self) -> None:
        """+15% Attribute Anomaly DMG must scale Luminize by exactly 1.15 --
        AnomalyBoostArea is a linear zone, so anything else is a wiring error."""
        plain = self._score(_build(), self._step())
        with_4pc = self._score(_build(modifiers=[self._four_pc(1500)]), self._step())
        assert with_4pc == pytest.approx(plain * 1.15)

    def test_it_composes_with_the_ap_rescale_rather_than_replacing_it(self) -> None:
        """The two frozen terms are independent; fixing one must not shadow the
        other. 1.4878... (AP) x 1.15 (boost) applied to the same base."""
        base = self._score(_build(), self._step())
        ap_only = self._score(_build(disc_stats=self._AP_ONLY), self._step())
        both = self._score(
            _build(disc_stats=self._AP_ONLY, modifiers=[self._four_pc()]), self._step()
        )
        assert both == pytest.approx(ap_only * 1.15)
        assert both == pytest.approx(base * (ap_only / base) * 1.15)

    def test_a_step_without_the_frozen_boost_is_left_alone(self) -> None:
        """Back-compat: `owner_anomaly_boost_mult=None` must be a no-op, so a
        step built before this field existed scores exactly as it used to."""
        step = self._step(owner_anomaly_boost_mult=None)
        assert self._score(
            _build(modifiers=[self._four_pc()]), step
        ) == pytest.approx(self._score(_build(), step))

    def test_a_nonzero_frozen_boost_is_divided_out_not_double_counted(self) -> None:
        """If the simulation already saw some Anomaly DMG% (a W-Engine, say),
        the live value replaces it rather than stacking on top."""
        # Sim froze 20% (Ode R1); frame resolves that same 20% and nothing else.
        step = self._step(owner_anomaly_boost_mult=12_000)
        build = _build(modifiers=[self._four_pc(2000)])
        assert self._score(build, step) == pytest.approx(10_000.0)
