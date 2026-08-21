"""Tests for Task 5e/5f — Pareto-dominance prefilter layer (P1d, P1d-2, lossless).

`_pareto_filter` drops any disc whose accumulated stat vector — projected onto the
payload's *effective* dimensions (`_effective_pareto_fields`, Task 5f, P1d-2) — is
weakly dominated by another disc in the same group. Every comparison dimension is
weakly monotone in damage, so this is lossless — unlike the budget-K prefilter, it
never needs an error bound. The full-vector comparator (`fields` left at its default)
is nearly inert on realistic inventories (see DESIGN P1d-2); projection onto the
probe-derived live dims is what makes it actually prune junk-stat discs.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import disc_optimizer as optimizer_module
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.damage_dag_service import build_damage_step_context
from app.services.disc_optimizer import (
    DiscCandidate,
    OptimizerConstraints,
    _pareto_filter,
    optimize_discs,
)
from app.services.modifiers import ActiveConditions, AttackScope

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "optimizer"
_SUBFRAME_FILE = _FIXTURE_DIR / "owner_subframe_small.json"


def _disc(
    disc_id: str,
    slot: int,
    *,
    set_id: int = 100,
    main_stat_type: str = "",
    main_stat_value: int = 0,
    substats: list[dict] | None = None,
) -> DiscCandidate:
    return DiscCandidate(
        disc_id=disc_id,
        slot=slot,
        set_id=set_id,
        main_stat_type=main_stat_type,
        main_stat_value=main_stat_value,
        substats=substats or [],
    )


def _empty_buckets() -> dict[int, list[DiscCandidate]]:
    return {s: [] for s in range(1, 7)}


def _crit_dps_build(**overrides: object) -> BuildSnapshot:
    """A plain physical ATK-scaling crit-DPS agent (no HP/DEF/ER involvement)."""
    return BuildSnapshot(
        agent_base_atk=1000, wengine_base_atk=500, agent_element="physical", **overrides
    )


def _crit_dps_enemy() -> EnemySnapshot:
    return EnemySnapshot(level=60, base_def=500, element_res=0)


def _crit_dps_combo() -> list[ComboStep]:
    return [
        ComboStep(
            label="BA1",
            attack_id="a1",
            attack_name="Basic 1",
            scope=AttackScope.BASIC,
            multiplier=10000,
            element="physical",
        ),
    ]


def _score_ctxs_for(
    base_build: BuildSnapshot,
    enemy: EnemySnapshot,
    combo_steps: list[ComboStep],
    conditions: ActiveConditions,
) -> list[list[tuple]]:
    """Build one probe-ready score-context list, mirroring what `_build_frame_contexts([])`
    builds inside `optimize_discs` — without needing a live inventory or the full
    optimizer entry point (Task 5f probe tests exercise `_effective_pareto_fields`
    directly)."""
    step_ctxs = [
        (
            1,
            optimizer_module._KIND_STANDARD,
            s.scope == AttackScope.EX_SPECIAL,
            build_damage_step_context(
                build=base_build,
                enemy=enemy,
                multiplier=s.multiplier,
                conditions=conditions,
                attack_scope=s.scope,
            ),
        )
        for s in combo_steps
    ]
    return [step_ctxs]


class TestDominatedRemoved:
    def test_dominated_removed(self):
        """B's stat vector is <= A's in every dim, < in one — B is redundant."""
        winner = _disc(
            "winner",
            slot=3,
            main_stat_type="crit_rate",
            main_stat_value=300,
            substats=[{"stat": "atk_pct", "value": 300}],
        )
        loser = _disc(
            "loser",
            slot=3,
            main_stat_type="crit_rate",
            main_stat_value=300,
            substats=[{"stat": "atk_pct", "value": 200}],
        )
        buckets = _empty_buckets()
        buckets[3] = [winner, loser]

        filtered, removed = _pareto_filter(buckets)

        assert removed == 1
        assert {d.disc_id for d in filtered[3]} == {"winner"}


class TestIncomparableKept:
    def test_incomparable_kept(self):
        """A wins on crit_rate, B wins on crit_dmg — neither dominates, both survive."""
        disc_a = _disc(
            "crit_rate_disc",
            slot=3,
            substats=[{"stat": "crit_rate", "value": 300}, {"stat": "crit_dmg", "value": 0}],
        )
        disc_b = _disc(
            "crit_dmg_disc",
            slot=3,
            substats=[{"stat": "crit_rate", "value": 0}, {"stat": "crit_dmg", "value": 300}],
        )
        buckets = _empty_buckets()
        buckets[3] = [disc_a, disc_b]

        filtered, removed = _pareto_filter(buckets)

        assert removed == 0
        assert {d.disc_id for d in filtered[3]} == {"crit_rate_disc", "crit_dmg_disc"}


class TestDifferentMainStatsNotCompared:
    def test_different_main_stats_not_compared(self):
        """Same slot/set_id but different main_stat_type — incomparable trade-offs.

        `worse` looks strictly weaker on every shared substat dimension, but a
        different main stat type puts it in a different group, so it is never
        compared against `better` and must survive.
        """
        better = _disc(
            "better",
            slot=3,
            main_stat_type="crit_rate",
            main_stat_value=300,
            substats=[{"stat": "atk_pct", "value": 300}],
        )
        worse = _disc(
            "worse",
            slot=3,
            main_stat_type="anomaly_mastery",
            main_stat_value=0,
            substats=[{"stat": "atk_pct", "value": 100}],
        )
        buckets = _empty_buckets()
        buckets[3] = [better, worse]

        filtered, removed = _pareto_filter(buckets)

        assert removed == 0
        assert {d.disc_id for d in filtered[3]} == {"better", "worse"}


class TestTiesKeepOne:
    def test_ties_keep_one(self):
        """Identical stat vectors cannot differ in damage — keep the lowest disc_id."""
        low = _disc(
            "a_low",
            slot=3,
            main_stat_type="crit_rate",
            main_stat_value=300,
            substats=[{"stat": "atk_pct", "value": 300}],
        )
        high = _disc(
            "b_high",
            slot=3,
            main_stat_type="crit_rate",
            main_stat_value=300,
            substats=[{"stat": "atk_pct", "value": 300}],
        )
        buckets = _empty_buckets()
        buckets[3] = [high, low]  # insertion order shouldn't matter

        filtered, removed = _pareto_filter(buckets)

        assert removed == 1
        assert {d.disc_id for d in filtered[3]} == {"a_low"}


class TestJunkStatDiscDominatedUnderProjection:
    """Task 5f (P1d-2): the full-vector comparator lets a dead junk-stat line (flat DEF,
    which never affects this ATK-scaling crit payload's damage) protect an otherwise
    dominated disc. Projecting onto the probe-derived live dims removes that protection.
    """

    @staticmethod
    def _pair() -> tuple[DiscCandidate, DiscCandidate]:
        god_roll = _disc(
            "god_roll",
            slot=3,
            substats=[
                {"stat": "crit_rate", "value": 300},
                {"stat": "crit_rate", "value": 300},
                {"stat": "crit_rate", "value": 300},
                {"stat": "crit_dmg", "value": 480},
            ],
        )
        junk_armored = _disc(
            "junk_armored",
            slot=3,
            substats=[
                {"stat": "crit_rate", "value": 300},
                {"stat": "crit_rate", "value": 300},
                {"stat": "def", "value": 50},  # substat key "def" -> DiscStats.flat_def
            ],
        )
        return god_roll, junk_armored

    def test_junk_stat_disc_dominated_under_projection(self):
        god_roll, junk_armored = self._pair()
        buckets = _empty_buckets()
        buckets[3] = [god_roll, junk_armored]
        score_ctxs = _score_ctxs_for(
            _crit_dps_build(), _crit_dps_enemy(), _crit_dps_combo(), ActiveConditions()
        )

        # Full-vector comparator: junk_armored's flat_def line makes it incomparable to
        # god_roll (0 < 50 on that dim) — this is exactly the P1d-2 problem statement.
        _, removed_full = _pareto_filter(buckets, optimizer_module._PARETO_STAT_FIELDS)
        assert removed_full == 0

        # Projected comparator: flat_def never moves this payload's damage, so it drops
        # out of the effective set — god_roll now dominates on crit_rate + crit_dmg alone.
        fields = optimizer_module._effective_pareto_fields(
            buckets, score_ctxs, OptimizerConstraints(), False
        )
        assert "flat_def" not in fields
        filtered, removed_proj = _pareto_filter(buckets, fields)
        assert removed_proj == 1
        assert {d.disc_id for d in filtered[3]} == {"god_roll"}


class TestConstraintStatAlwaysRetained:
    """Task 5f (P1d-2): a `min_stats` floor on a stat the probe would otherwise call dead
    must force that stat back into the effective set — the constraint invariant.
    """

    def test_constraint_stat_always_retained(self):
        god_roll, junk_armored = TestJunkStatDiscDominatedUnderProjection._pair()
        buckets = _empty_buckets()
        buckets[3] = [god_roll, junk_armored]
        score_ctxs = _score_ctxs_for(
            _crit_dps_build(), _crit_dps_enemy(), _crit_dps_combo(), ActiveConditions()
        )

        no_constraint_fields = optimizer_module._effective_pareto_fields(
            buckets, score_ctxs, OptimizerConstraints(), False
        )
        assert "flat_def" not in no_constraint_fields

        constrained_fields = optimizer_module._effective_pareto_fields(
            buckets, score_ctxs, OptimizerConstraints(min_stats={"defense": 100}), False
        )
        assert "flat_def" in constrained_fields
        assert "def_pct" in constrained_fields

        # Constraint invariant: junk_armored's flat_def line makes the pair incomparable
        # again — the disc that projection alone would prune now survives.
        _, removed = _pareto_filter(buckets, constrained_fields)
        assert removed == 0


class TestErGateRetainsEnergyRegen:
    """Task 5f (P1d-2): ER feasibility is applied outside the scoring function the probe
    uses, so a pure probe can never see `energy_regen` as live — the ER gate must force
    it in explicitly whenever the rotation-energy-cost gate is active.
    """

    def test_er_gate_retains_energy_regen(self):
        buckets = _empty_buckets()
        buckets[3] = [
            _disc("a", slot=3, substats=[{"stat": "energy_regen", "value": 300}]),
            _disc("b", slot=3, substats=[{"stat": "energy_regen", "value": 100}]),
        ]
        score_ctxs = _score_ctxs_for(
            _crit_dps_build(), _crit_dps_enemy(), _crit_dps_combo(), ActiveConditions()
        )

        gate_off = optimizer_module._effective_pareto_fields(
            buckets, score_ctxs, OptimizerConstraints(), False
        )
        assert "energy_regen" not in gate_off

        gate_on = optimizer_module._effective_pareto_fields(
            buckets, score_ctxs, OptimizerConstraints(), True
        )
        assert "energy_regen" in gate_on


class TestSheerPathKeepsHpDims:
    """Task 5f (P1d-2): the probe is scoring-function-agnostic — whatever
    `compute_damage_with_accumulated_disc` actually reads is what gets kept live.

    Mocked here because the disc-optimizer fast path's DAG context always scales off ATK
    (`Q_ATK_NODE`) regardless of `agent_specialty` — real Sheer/Rupture dispatch is a
    known, separate gap (see project memory ``project_sheer_damage.md``; Yixuan's kit
    JSON is tracked as wrong there), not something Task 5f fixes. This test instead
    proves the probe mechanism itself correctly keeps HP dims live when the reward is a
    (hypothetical) function of HP, independent of that gap.
    """

    def test_sheer_path_keeps_hp_dims(self):
        def _hp_scaled_damage(_ctx: object, disc: object) -> float:
            return float(disc.flat_hp) + float(disc.hp_pct) * 2.0

        buckets = _empty_buckets()
        buckets[3] = [
            _disc(
                "a",
                slot=3,
                substats=[
                    {"stat": "hp", "value": 500},  # substat key "hp" -> DiscStats.flat_hp
                    {"stat": "hp_pct", "value": 200},
                ],
            ),
            _disc("b", slot=3, substats=[{"stat": "hp", "value": 100}]),
        ]
        score_ctxs: list[list[tuple]] = [
            [(1, optimizer_module._KIND_STANDARD, False, object())]
        ]

        with patch.object(
            optimizer_module,
            "compute_damage_with_accumulated_disc",
            side_effect=_hp_scaled_damage,
        ):
            fields = optimizer_module._effective_pareto_fields(
                buckets, score_ctxs, OptimizerConstraints(), False
            )

        assert "flat_hp" in fields
        assert "hp_pct" in fields


class TestProbeTwoPointKeepsInteractionDim:
    """Task 5f (P1d-2): CritArea = 1 + CR*CD, so CD's marginal effect is exactly zero
    whenever CR=0. A single-point probe (others-at-base only) would wrongly call CD dead
    for an agent with no innate crit rate; the two-point check (others-at-base AND
    others-at-max) catches it via the others-at-max evaluation, where disc CR is nonzero.
    """

    def test_probe_two_point_keeps_interaction_dim(self):
        # No innate crit rate/DMG — total CR is 0 unless a disc supplies it, so CD is
        # genuinely dead at the others-at-base point (CR=0) for this build.
        base_build = _crit_dps_build(agent_crit_rate=0, agent_crit_dmg=0)
        buckets = _empty_buckets()
        buckets[3] = [
            _disc("cr_disc", slot=3, substats=[{"stat": "crit_rate", "value": 900}]),
            _disc("cd_disc", slot=3, substats=[{"stat": "crit_dmg", "value": 480}]),
        ]
        score_ctxs = _score_ctxs_for(
            base_build, _crit_dps_enemy(), _crit_dps_combo(), ActiveConditions()
        )

        fields = optimizer_module._effective_pareto_fields(
            buckets, score_ctxs, OptimizerConstraints(), False
        )

        assert "crit_rate" in fields
        assert "crit_dmg" in fields


class TestDeadMainDominatedAfterGroupCollapse:
    """Task 5f stage 2 (P1d-2): once the comparison is projected, a disc whose *main*
    stat is dead (e.g. an HP%-main slot for a crit-DPS payload) contributes nothing extra
    to its vector — so it becomes directly comparable to, and prunable against, a
    different-main disc in the same (slot, set_id) group.
    """

    def test_dead_main_dominated_after_group_collapse(self):
        # HP%-main is dead for this projected field set — its main contributes nothing,
        # leaving only its (weak) crit_rate substat line.
        dead_main = _disc(
            "dead_main_hp",
            slot=4,
            main_stat_type="hp_pct",
            main_stat_value=3000,
            substats=[{"stat": "crit_rate", "value": 100}],
        )
        # crit_rate-main contributes directly to the effective vector, plus a crit_dmg
        # substat line — strictly ahead of dead_main on every effective dim.
        live_main = _disc(
            "live_main_cr",
            slot=4,
            main_stat_type="crit_rate",
            main_stat_value=600,
            substats=[{"stat": "crit_dmg", "value": 200}],
        )
        buckets = _empty_buckets()
        buckets[4] = [dead_main, live_main]
        fields = ("crit_rate", "crit_dmg", "atk_pct")

        # Grouping unchanged (stage 1 only): different mains stay incomparable.
        _, removed_ungrouped = _pareto_filter(buckets, fields)
        assert removed_ungrouped == 0

        # Stage 2: grouping collapses to (slot, set_id) — dead_main is now dominated.
        filtered, removed_collapsed = _pareto_filter(buckets, fields, collapse_main=True)
        assert removed_collapsed == 1
        assert {d.disc_id for d in filtered[4]} == {"live_main_cr"}


class TestLiveMainTradeoffNotCollapsed:
    """Task 5f stage 2 (P1d-2): two mains that both project to nonzero, mutually
    incomparable vectors must survive the group collapse — collapsing grouping only
    removes discs that are genuinely weaker on every live dim, never a real trade-off.
    """

    def test_live_main_tradeoff_not_collapsed(self):
        atk_main = _disc(
            "atk_pct_main", slot=4, main_stat_type="atk_pct", main_stat_value=600
        )
        cd_main = _disc(
            "crit_dmg_main", slot=4, main_stat_type="crit_dmg", main_stat_value=600
        )
        buckets = _empty_buckets()
        buckets[4] = [atk_main, cd_main]
        fields = ("crit_rate", "crit_dmg", "atk_pct")

        filtered, removed = _pareto_filter(buckets, fields, collapse_main=True)

        assert removed == 0
        assert {d.disc_id for d in filtered[4]} == {"atk_pct_main", "crit_dmg_main"}


class TestExhaustiveResultsIdenticalWithPareto:
    """CP8 (re-scoped by Task 5f, P1d-2): exhaustive results with the identity filter,
    full-vector Pareto, and projected Pareto are all byte-identical top-N.

    Built from real `owner_subframe_small` disc records (two buckets with a known,
    verified dominance case each — see docs/LOG_optimizer_granularity.md Task 5e) plus
    one disc per remaining slot, so the full pipeline runs in milliseconds while still
    exercising real captured stat data end to end.
    """

    @pytest.fixture(scope="class")
    def fixture_data(self) -> dict:
        return json.loads(_SUBFRAME_FILE.read_text())

    @staticmethod
    def _pick(
        discs: list[dict], slot: int, set_id: int, main: str, n: int | None = None
    ) -> list[dict]:
        matches = [
            d
            for d in discs
            if d["slot"] == slot and d["set_id"] == set_id and d["main_stat_type"] == main
        ]
        return matches if n is None else matches[:n]

    def _build_inventory(self, fixture_data: dict) -> list[DiscCandidate]:
        discs = fixture_data["discs"]
        # (2, 33500, "atk"): 6 real discs, 1 provably dominated.
        # (5, 32700, "physical_dmg"): 3 real discs, 1 provably dominated.
        # One real disc per remaining slot keeps the combo count small (18 total).
        raw = (
            self._pick(discs, 2, 33500, "atk")
            + self._pick(discs, 5, 32700, "physical_dmg")
            + self._pick(discs, 1, 32700, "hp", n=1)
            + self._pick(discs, 3, 33500, "def", n=1)
            + self._pick(discs, 4, 33500, "crit_dmg", n=1)
            + self._pick(discs, 6, 33500, "atk_pct", n=1)
        )
        assert len(raw) == 13  # 6 + 3 + 1*4 — guards against fixture drift
        return [
            DiscCandidate(
                disc_id=d["disc_id"],
                slot=d["slot"],
                set_id=d["set_id"],
                main_stat_type=d["main_stat_type"],
                main_stat_value=d["main_stat_value"],
                substats=d["substats"],
            )
            for d in raw
        ]

    def test_exhaustive_identical_with_projected_pareto(self, fixture_data: dict):
        inventory = self._build_inventory(fixture_data)
        base_build = BuildSnapshot(**fixture_data["base_build"])
        enemy = EnemySnapshot(**fixture_data["enemy"])
        combo_steps = [
            ComboStep(
                label=s["label"],
                attack_id=s["attack_id"],
                attack_name=s["attack_name"],
                scope=AttackScope(s["scope"]),
                multiplier=s["multiplier"],
                element=s["element"],
            )
            for s in fixture_data["combo_steps"]
        ]
        # top_n=4: Task 5f's projection is aggressive enough on this small fixture that
        # only 4 non-dominated combos remain in the reduced (post-stage-1) search space
        # (2 surviving slot-2 candidates x 2 surviving slot-5 candidates) — top_n=5 would
        # legitimately return only 4 results there while the unfiltered variants still had
        # a 5th (now-provably-dominated) entry to pad out to 5. Capping at 4 keeps the
        # three variants' result counts comparable.
        constraints = OptimizerConstraints(required_sets={32700: 2, 33500: 4}, top_n=4)
        conditions = ActiveConditions()

        def _identity_filter(
            slot_candidates: dict[int, list[DiscCandidate]],
            *_args: object,
            **_kwargs: object,
        ) -> tuple[dict[int, list[DiscCandidate]], int]:
            return slot_candidates, 0

        def _run() -> optimizer_module.OptimizerResult:
            return optimize_discs(
                base_build=base_build,
                enemy=enemy,
                combo_steps=combo_steps,
                inventory=inventory,
                disc_set_modifiers={},
                constraints=constraints,
                conditions=conditions,
            )

        # (a) no Pareto layer at all — ground truth.
        with patch.object(optimizer_module, "_pareto_filter", side_effect=_identity_filter):
            no_pareto = _run()

        # (b) full-vector comparator (pre-5f behavior): every DiscStats field compared.
        with patch.object(
            optimizer_module,
            "_effective_pareto_fields",
            side_effect=lambda *a, **kw: optimizer_module._PARETO_STAT_FIELDS,
        ):
            full_vector = _run()

        # (c) projected comparator (Task 5f stage 1, the real default call path).
        projected = _run()

        # The layer must have actually engaged in both Pareto variants (else the
        # byte-identical comparison below is vacuous), and projection must remove
        # strictly more than the full-vector comparator — the whole point of P1d-2.
        assert no_pareto.pareto_removed == 0
        assert full_vector.pareto_removed > 0
        assert projected.pareto_removed > full_vector.pareto_removed

        top_no_pareto = [(b.disc_ids, b.total_damage) for b in no_pareto.builds]
        top_full_vector = [(b.disc_ids, b.total_damage) for b in full_vector.builds]
        top_projected = [(b.disc_ids, b.total_damage) for b in projected.builds]
        assert top_no_pareto == top_full_vector == top_projected
