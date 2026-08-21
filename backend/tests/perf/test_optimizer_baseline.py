# ruff: noqa: E402, I001 — the module-level skip below runs before the imports it guards.
"""Performance baseline for optimize_discs — YSG realistic filtered inventory.

Run with:  pytest -x -m perf backend/tests/perf/test_optimizer_baseline.py
Skipped by default (no -m perf flag).

Build: Ye Shunguang (ice/attack) — 4pc White Water Ballad (33500) + 2pc Branch & Blade Song (32700).
Enemy: Ye Shiyuan the Thrall (level 60, ice-neutral).

Slot filters applied before the optimizer call (matching frontend filter behaviour):
  Slot 4 main stat: atk_pct | crit_rate | crit_dmg
  Slot 5 main stat: atk_pct only
  Slot 6 main stat: atk_pct only

Inventory is intentionally small (~3-4 per slot) so the test completes in seconds
even at the unoptimised rate.  The interesting signal is the RATIO between this
baseline and the post-A2 time, not the absolute number.

Expected combos: 3×3×3×4×3×3 = 972
Expected baseline time: ~2–5 s (unoptimised, ~2 ms/combo)
Expected post-A2 time: <0.5 s (overlay path, ~0.1-0.3 ms/combo)

**PORT STATE — SKIPPED, NOT DELETED (B.12).** Every import below points at a module the
demolition removed or staged: `build_damage_service` and `disc_optimizer` and `modifiers`
live in `app/services/_ported/`, `combo_types` is gone. The file is kept because **G.7
re-baselines `tests/perf` for the 5-slot Genshin search space** and this is the harness that
produced fairy's numbers — the structure (fixed inventory, slot filters, ratio-not-absolute
reasoning) ports; the ZZZ build and enemy do not.

The skip is module-level and unconditional. It is *not* a `-m perf` gate: this file cannot
even be imported today, and a collection error is not the same message as "not re-baselined
yet".
"""

import pytest

pytest.skip(
    "tests/perf is not re-baselined for Genshin yet — see G.7 and the module docstring.",
    allow_module_level=True,
)

# NOTE: `from __future__ import annotations` was removed here. Python requires it to be the
# first statement in the file, and the module-level `pytest.skip` above has to come first —
# the file would otherwise raise SyntaxError at *collection*, which is a hard error rather
# than a skip. Restore it at the top when G.7 restores the imports.

import time

import pytest

from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import AnomalyStep, ComboStep
from app.services.disc_optimizer import (
    DiscCandidate,
    OptimizerConstraints,
    SetFrame,
    optimize_discs,
)
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)

# ---------------------------------------------------------------------------
# Set IDs
# ---------------------------------------------------------------------------
WWB = 33500  # White Water Ballad
BBS = 32700  # Branch & Blade Song

# Repeats for the step-shape comparison; best-of-N, not mean (see `_time`).
_PERF_REPEATS = 3


# ---------------------------------------------------------------------------
# Set modifiers (always-on only; matches typical "all conditions active" run)
# ---------------------------------------------------------------------------


def _disc_mod(stat: str, value: int, source: ModifierSource) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=source,
        source_label=stat,
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


def _wwb_mods() -> list[Modifier]:
    return [
        _disc_mod("physical_dmg", 1000, ModifierSource.DISC_SET_2PC),  # 2pc +10%
        _disc_mod("crit_rate", 1000, ModifierSource.DISC_SET_4PC),  # 4pc +10% CR
    ]


def _bbs_mods() -> list[Modifier]:
    return [
        _disc_mod("crit_dmg", 1600, ModifierSource.DISC_SET_2PC),  # 2pc +16% CD
    ]


# ---------------------------------------------------------------------------
# Build — Ye Shunguang (ice, attack)
# ---------------------------------------------------------------------------


def _ysg_build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_atk=859,
        wengine_base_atk=594,
        agent_element="ice",
        modifiers=[
            _disc_mod("crit_rate", 3000, ModifierSource.CORE_SKILL),  # Core +30% CR
            _disc_mod("dmg_bonus", 2500, ModifierSource.CORE_SKILL),  # Core +25% DMG
        ],
    )


def _ye_shiyuan() -> EnemySnapshot:
    """Ye Shiyuan the Thrall — level 60 elite, ice-neutral RES."""
    return EnemySnapshot(level=60, base_def=50, element_res=0)


# ---------------------------------------------------------------------------
# Combo — Basic + EX Special (typical YSG test combo)
# ---------------------------------------------------------------------------


def _test_combo() -> list[ComboStep]:
    return [
        ComboStep(
            label="BA1",
            attack_id="att-ba1",
            attack_name="Basic 1",
            scope=AttackScope.BASIC,
            multiplier=10000,
            element="ice",
        ),
        ComboStep(
            label="EX",
            attack_id="att-ex",
            attack_name="EX Special",
            scope=AttackScope.EX_SPECIAL,
            multiplier=30000,
            element="ice",
        ),
    ]


def _team_rotation_combo() -> list[ComboStep | AnomalyStep]:
    """The post-Task-26 (issue #112) step shape: a full-team rotation.

    Before Task 26 the optimizer cut a team combo down to the target's own steps
    *before* simulating, so `/optimize` scored the 2-signature shape `_test_combo`
    above models. Now the whole team is simulated and the resulting events are
    filtered by ownership, which leaves the target with more steps AND — the part
    that costs — more **distinct signatures**: every cross-agent mechanic that was
    previously dead now varies `procs_override` per aura, and an `AnomalyStep`
    signature keys on it (`disc_optimizer.py:452`).

    Distinct signatures are what the per-candidate loop pays for: `sig_to_ctx`
    builds one context per signature per frame, and `sig_counts` then reuses it.
    Step *count* is nearly free by comparison. PR #113 reported this fixture's
    real-world analogue going 20 → 47 steps and 1 → 5 signatures, so that is what
    is modelled here: 47 steps over 5 signatures.

    The five signatures, and why a team rotation produces them:
      1. the target's own basic         (standard, BASIC)
      2. the target's own EX            (standard, EX_SPECIAL)
      3. burn ticks at neutral Refringe (aura fed before she banked a point)
      4. burn ticks at Refringed 1.04   (RefringeArea folded in — Task 35)
      5. burn ticks at a shared-aura buildup share (Task 26's fractional owner
         share, only producible once teammates are in the same rotation)
    """
    steps: list[ComboStep | AnomalyStep] = [
        ComboStep(
            label="BA1",
            attack_id="att-ba1",
            attack_name="Basic 1",
            scope=AttackScope.BASIC,
            multiplier=10000,
            element="ice",
        ),
        ComboStep(
            label="EX",
            attack_id="att-ex",
            attack_name="EX Special",
            scope=AttackScope.EX_SPECIAL,
            multiplier=30000,
            element="ice",
        ),
    ]
    # 45 anomaly ticks spread over the three distinct `procs_override` values.
    for i, scale in enumerate((1.0, 1.04, 0.25) * 15):
        steps.append(
            AnomalyStep(
                label=f"Anomaly Tick (ice) {i}",
                attack_id=f"anomaly_tick_ice_{i}",
                anomaly_type="shatter",
                element="ice",
                procs_override=scale,
            )
        )
    return steps


# ---------------------------------------------------------------------------
# Inventory — realistic post-filter size (3-4 per slot → ~972 combos)
# ---------------------------------------------------------------------------


def _d(
    disc_id: str,
    slot: int,
    set_id: int,
    main_stat_type: str,
    main_stat_value: int,
    substats: list[dict],
) -> DiscCandidate:
    return DiscCandidate(
        disc_id=disc_id,
        slot=slot,
        set_id=set_id,
        main_stat_type=main_stat_type,
        main_stat_value=main_stat_value,
        substats=substats,
    )


def _build_inventory() -> list[DiscCandidate]:
    """
    Filtered inventory for 4pc WWB / 2pc BBS build.

    Slots 1-4: WWB discs  |  Slots 5-6: BBS discs.
    Slot 4 filtered to atk_pct / crit_rate / crit_dmg main stats only.
    Slot 5-6 filtered to atk_pct main stat only.

    3 candidates per unfiltered slot, 4 across slot-4 filters.
    """

    # Per-roll value helper (cycles so each disc is distinct).
    def r(base: int, seed: int) -> int:
        return base + (seed * base // 3) % (base * 2)

    return [
        # --- Slot 1 (WWB, HP main — unfiltered) ---
        _d(
            "wwb-s1-a",
            1,
            WWB,
            "hp",
            0,
            [
                {"stat": "crit_rate", "value": r(240, 1)},
                {"stat": "crit_dmg", "value": r(480, 2)},
                {"stat": "atk_pct", "value": r(300, 3)},
            ],
        ),
        _d(
            "wwb-s1-b",
            1,
            WWB,
            "hp",
            0,
            [
                {"stat": "crit_rate", "value": r(240, 4)},
                {"stat": "crit_dmg", "value": r(480, 5)},
                {"stat": "atk_pct", "value": r(300, 6)},
            ],
        ),
        _d(
            "wwb-s1-c",
            1,
            WWB,
            "hp",
            0,
            [
                {"stat": "crit_rate", "value": r(240, 7)},
                {"stat": "crit_dmg", "value": r(480, 8)},
                {"stat": "atk_pct", "value": r(300, 9)},
            ],
        ),
        # --- Slot 2 (WWB, ATK main — unfiltered) ---
        _d(
            "wwb-s2-a",
            2,
            WWB,
            "atk",
            0,
            [
                {"stat": "crit_rate", "value": r(240, 2)},
                {"stat": "crit_dmg", "value": r(480, 3)},
                {"stat": "atk_pct", "value": r(300, 4)},
            ],
        ),
        _d(
            "wwb-s2-b",
            2,
            WWB,
            "atk",
            0,
            [
                {"stat": "crit_rate", "value": r(240, 5)},
                {"stat": "crit_dmg", "value": r(480, 6)},
                {"stat": "atk_pct", "value": r(300, 7)},
            ],
        ),
        _d(
            "wwb-s2-c",
            2,
            WWB,
            "atk",
            0,
            [
                {"stat": "crit_rate", "value": r(240, 8)},
                {"stat": "crit_dmg", "value": r(480, 9)},
                {"stat": "atk_pct", "value": r(300, 1)},
            ],
        ),
        # --- Slot 3 (WWB, ATK main — unfiltered) ---
        _d(
            "wwb-s3-a",
            3,
            WWB,
            "atk",
            0,
            [
                {"stat": "crit_rate", "value": r(240, 3)},
                {"stat": "crit_dmg", "value": r(480, 4)},
                {"stat": "atk_pct", "value": r(300, 5)},
            ],
        ),
        _d(
            "wwb-s3-b",
            3,
            WWB,
            "atk",
            0,
            [
                {"stat": "crit_rate", "value": r(240, 6)},
                {"stat": "crit_dmg", "value": r(480, 7)},
                {"stat": "atk_pct", "value": r(300, 8)},
            ],
        ),
        _d(
            "wwb-s3-c",
            3,
            WWB,
            "atk",
            0,
            [
                {"stat": "crit_rate", "value": r(240, 9)},
                {"stat": "crit_dmg", "value": r(480, 1)},
                {"stat": "atk_pct", "value": r(300, 2)},
            ],
        ),
        # --- Slot 4 (WWB, filtered: atk_pct | crit_rate | crit_dmg) ---
        # One of each main stat type + one extra atk_pct (realistic: more ATK pieces in pool)
        _d(
            "wwb-s4-atk-a",
            4,
            WWB,
            "atk_pct",
            3000,
            [{"stat": "crit_rate", "value": r(240, 1)}, {"stat": "crit_dmg", "value": r(480, 2)}],
        ),
        _d(
            "wwb-s4-atk-b",
            4,
            WWB,
            "atk_pct",
            3000,
            [{"stat": "crit_rate", "value": r(240, 4)}, {"stat": "crit_dmg", "value": r(480, 5)}],
        ),
        _d(
            "wwb-s4-cr",
            4,
            WWB,
            "crit_rate",
            2400,
            [{"stat": "crit_dmg", "value": r(480, 3)}, {"stat": "atk_pct", "value": r(300, 6)}],
        ),
        _d(
            "wwb-s4-cd",
            4,
            WWB,
            "crit_dmg",
            4800,
            [{"stat": "crit_rate", "value": r(240, 7)}, {"stat": "atk_pct", "value": r(300, 8)}],
        ),
        # --- Slot 5 (BBS, filtered: atk_pct only) ---
        _d(
            "bbs-s5-a",
            5,
            BBS,
            "atk_pct",
            3000,
            [
                {"stat": "crit_rate", "value": r(240, 2)},
                {"stat": "crit_dmg", "value": r(480, 3)},
                {"stat": "pen_ratio", "value": r(240, 4)},
            ],
        ),
        _d(
            "bbs-s5-b",
            5,
            BBS,
            "atk_pct",
            3000,
            [
                {"stat": "crit_rate", "value": r(240, 5)},
                {"stat": "crit_dmg", "value": r(480, 6)},
                {"stat": "atk_pct", "value": r(300, 7)},
            ],
        ),
        _d(
            "bbs-s5-c",
            5,
            BBS,
            "atk_pct",
            3000,
            [
                {"stat": "crit_rate", "value": r(240, 8)},
                {"stat": "crit_dmg", "value": r(480, 9)},
                {"stat": "anomaly_proficiency", "value": r(9, 1)},
            ],
        ),
        # --- Slot 6 (BBS, filtered: atk_pct only) ---
        _d(
            "bbs-s6-a",
            6,
            BBS,
            "atk_pct",
            3000,
            [
                {"stat": "crit_rate", "value": r(240, 3)},
                {"stat": "crit_dmg", "value": r(480, 4)},
                {"stat": "pen_ratio", "value": r(240, 5)},
            ],
        ),
        _d(
            "bbs-s6-b",
            6,
            BBS,
            "atk_pct",
            3000,
            [
                {"stat": "crit_rate", "value": r(240, 6)},
                {"stat": "crit_dmg", "value": r(480, 7)},
                {"stat": "atk_pct", "value": r(300, 8)},
            ],
        ),
        _d(
            "bbs-s6-c",
            6,
            BBS,
            "atk_pct",
            3000,
            [
                {"stat": "crit_rate", "value": r(240, 9)},
                {"stat": "crit_dmg", "value": r(480, 1)},
                {"stat": "anomaly_proficiency", "value": r(9, 2)},
            ],
        ),
    ]


@pytest.mark.perf
def test_optimizer_baseline_timing() -> None:
    """Time optimize_discs on a filtered YSG inventory and print elapsed ms.

    This records the BEFORE number for A2's context-cache optimisation.
    Expected combos: 3×3×3×4×3×3 = 972.
    """
    inventory = _build_inventory()
    by_slot: dict[int, int] = {}
    for d in inventory:
        by_slot[d.slot] = by_slot.get(d.slot, 0) + 1
    print(f"\n[perf] Inventory per slot: {dict(sorted(by_slot.items()))}")

    expected_combos = 3 * 3 * 3 * 4 * 3 * 3  # 972
    print(f"[perf] Expected combos: {expected_combos}")

    start = time.perf_counter()
    result = optimize_discs(
        base_build=_ysg_build(),
        enemy=_ye_shiyuan(),
        combo_steps=_test_combo(),
        inventory=inventory,
        disc_set_modifiers={WWB: _wwb_mods(), BBS: _bbs_mods()},
        constraints=OptimizerConstraints(
            top_n=10,
            allowed_frames=[SetFrame({WWB: 4, BBS: 2})],
        ),
        conditions=ActiveConditions(),
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    print(
        f"[perf] optimize_discs BASELINE: {elapsed_ms:.1f} ms  "
        f"(evaluated={result.evaluated}, pruned_sets={result.pruned_sets}, "
        f"builds={len(result.builds)})"
    )

    assert result.evaluated > 0, "No combos evaluated — check inventory / set frame"
    assert len(result.builds) > 0
    assert result.builds[0].total_damage > 0


@pytest.mark.perf
def test_team_rotation_step_shape_timing() -> None:
    """Time the same inventory against the target-only vs full-team step shape.

    Task 26 (issue #112) changed what `/optimize` scores: the full team is now
    simulated and filtered by ownership, so a team combo's step list gains both
    steps and distinct signatures. PR #113's perf section argued from
    `simulate()` (1.06 → 4.20 ms, paid ≤4× per job, not per candidate) and from
    "the perf baseline is unchanged" — but the baseline above feeds a hand-built
    2-step list straight into `optimize_discs`, so it is unchanged *by
    construction* and says nothing about the shape that moved.

    This is the measurement that does. Same inventory, same frame, same build —
    only the step list differs, so the ratio isolates the per-candidate cost of
    the new shape. Prints rather than asserts a threshold: this file's own
    preamble says the interesting signal is the ratio, and absolute numbers are
    machine-dependent.
    """
    inventory = _build_inventory()
    common = {
        "base_build": _ysg_build(),
        "enemy": _ye_shiyuan(),
        "inventory": inventory,
        "disc_set_modifiers": {WWB: _wwb_mods(), BBS: _bbs_mods()},
        "constraints": OptimizerConstraints(
            top_n=10,
            allowed_frames=[SetFrame({WWB: 4, BBS: 2})],
        ),
        "conditions": ActiveConditions(),
    }

    target_only = _test_combo()
    full_team = _team_rotation_combo()

    # Warm up before timing anything. `optimize_discs`' inputs are all frozen
    # dataclasses and it holds no module-level cache, so the runs below cannot
    # contaminate each other — but the *first* call of either still absorbs
    # import and interpreter warmup, and that call would be the ratio's
    # denominator. Without this the baseline is inflated and the ratio
    # understates the real cost (measured: 4.4x unwarmed vs 5-7x warmed).
    optimize_discs(combo_steps=target_only, **common)

    def _time(steps: list) -> tuple[float, object]:
        """Best of `_PERF_REPEATS`. Noise on a shared runner is one-directional —
        it only ever adds time — so the minimum is the closest estimate of the
        real cost, and the mean would mostly measure whatever else the box was
        doing. Run-to-run spread on the raw single-shot numbers was ~35%.
        """
        best = float("inf")
        result = None
        for _ in range(_PERF_REPEATS):
            start = time.perf_counter()
            result = optimize_discs(combo_steps=steps, **common)
            best = min(best, (time.perf_counter() - start) * 1000)
        return best, result

    before_ms, before = _time(target_only)
    after_ms, after = _time(full_team)

    def _sigs(steps: list) -> int:
        standard = {(s.scope, s.multiplier) for s in steps if isinstance(s, ComboStep)}
        anomaly = {
            (s.anomaly_type, s.procs_override) for s in steps if isinstance(s, AnomalyStep)
        }
        return len(standard) + len(anomaly)

    print(
        f"\n[perf] target-only shape: {len(target_only)} steps, "
        f"{_sigs(target_only)} signatures → {before_ms:.1f} ms "
        f"(evaluated={before.evaluated}, {before_ms / before.evaluated:.3f} ms/candidate)"
    )
    print(
        f"[perf] full-team shape:   {len(full_team)} steps, "
        f"{_sigs(full_team)} signatures → {after_ms:.1f} ms "
        f"(evaluated={after.evaluated}, {after_ms / after.evaluated:.3f} ms/candidate)"
    )
    print(
        f"[perf] wall-clock {after_ms / before_ms:.2f}x  |  "
        f"per-candidate {(after_ms / after.evaluated) / (before_ms / before.evaluated):.2f}x  |  "
        f"candidates {after.evaluated / before.evaluated:.2f}x"
    )

    # The fixture only earns its keep if it actually models the shape change.
    assert _sigs(full_team) == 5, "fixture drifted from PR #113's reported 5 signatures"
    assert len(full_team) == 47, "fixture drifted from PR #113's reported 47 steps"
    # Not asserted equal, because they are not: the anomaly steps pull
    # `anomaly_proficiency` into the union keep-set (`disc_optimizer.py:692`), so
    # the full-team shape survives the prefilter with a wider candidate set. That
    # is the second, compounding half of the cost and the reason wall-clock moves
    # more than the per-candidate figure — both are printed above so a regression
    # in either is visible.
    assert after.evaluated >= before.evaluated
    assert after.builds[0].total_damage > 0
