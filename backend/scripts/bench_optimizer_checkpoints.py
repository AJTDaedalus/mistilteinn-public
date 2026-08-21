"""Task 6b — run the math checkpoints (CP1-CP8) from DESIGN_optimizer_granularity.md.

DB-free: reads only the Task 6a fixtures under
``tests/fixtures/optimizer/``. Numbers get hand-copied into
``docs/LOG_optimizer_granularity.md``; this script is the reproducible
source of truth for re-running them later (per the DESIGN's circle-back
protocol — CP1-CP6 whenever the prefilter/union/damage DAG changes).

Run (DB-free, from ``backend/``):

    python -m scripts.bench_optimizer_checkpoints [--skip-slow]

``--skip-slow`` skips CP2/CP4/CP5 (the real ``optimize_discs`` runs on the
full 595-disc pool / subframe, several minutes each) and only runs the
cheap checkpoints (CP1, CP3, CP6, CP7's tiny-inventory timing, CP8 via
pytest). Results are written incrementally to ``--out`` (default:
``./bench_6b_results.json``) so a partial run is recoverable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from itertools import product as iproduct
from pathlib import Path

from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.damage_dag_service import (
    build_damage_step_context,
    compute_anomaly_with_accumulated_disc,
    compute_damage_with_accumulated_disc,
)
from app.services.disc_optimizer import (
    _ELEMENT_DMG_FIELDS,
    COMBO_BUDGET,
    PREFILTER_EXACT,
    UNION_PRODUCT_CAP,
    UNION_STAT_KEEP,
    DiscCandidate,
    OptimizerConstraints,
    SetFrame,
    _build_ref_disc_stats,
    _estimate_combo_count,
    _extract_bucket_sizes,
    optimize_discs,
)
from app.services.modifiers import ActiveConditions, AttackScope
from app.services.stat_calculator import accumulate_disc_stats

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "optimizer"
_FRAME = {32700: 2, 33500: 4}
_DEFAULT_OUT = Path.cwd() / "bench_6b_results.json"

# CP1's locked ground-truth targets (DESIGN_optimizer_granularity.md, owner_twst1_buckets).
_EXPECTED_EXHAUSTIVE = 12_529_002
_EXPECTED_K7 = 989_898
_EXPECTED_K8 = 1_628_672

_MIN_BUCKET_GROUP = 2  # smallest group size worth ranking for CP3
_STABLE_FROM_K = 10  # CP4: top1/top5 must be stable at every K >= this
_MAX_DELTA_PCT = 0.5  # CP5 pass threshold
_TINY_INVENTORY_COMBOS = 2**6  # CP7's 2-discs/slot inventory, 6 slots


def _combo_steps_from(steps_json: list[dict]) -> list[ComboStep]:
    return [
        ComboStep(
            label=s["label"],
            attack_id=s["attack_id"],
            attack_name=s["attack_name"],
            scope=AttackScope(s["scope"]),
            multiplier=s["multiplier"],
            element=s["element"],
        )
        for s in steps_json
    ]


def _inventory_from(discs_json: list[dict]) -> list[DiscCandidate]:
    return [
        DiscCandidate(
            disc_id=d["disc_id"],
            slot=d["slot"],
            set_id=d["set_id"],
            main_stat_type=d["main_stat_type"],
            main_stat_value=d["main_stat_value"],
            substats=d["substats"],
        )
        for d in discs_json
    ]


def _solo_score_ext(
    candidate_stat_dict: dict,
    step_ctxs: list[list[tuple]],
    ref_dicts: list[dict] | None = None,
) -> float:
    """Reimplements `_solo_score` (a disc_optimizer closure) from exported pieces only."""
    dicts = [candidate_stat_dict]
    if ref_dicts:
        dicts.extend(ref_dicts)
    disc = accumulate_disc_stats(dicts)
    best = 0.0
    for ctxs in step_ctxs:
        tot = 0.0
        for count, is_standard, _is_ex, ctx in ctxs:
            if is_standard:
                tot += count * compute_damage_with_accumulated_disc(ctx, disc)
            else:
                tot += count * compute_anomaly_with_accumulated_disc(ctx, disc)
        best = max(best, tot)
    return best


def _base_step_ctxs(
    base_build: BuildSnapshot, enemy: EnemySnapshot, combo_steps: list[ComboStep]
) -> list[list[tuple]]:
    conditions = ActiveConditions()
    step_ctxs = [
        (
            1,
            True,
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


# ─── CP1 — Estimator ────────────────────────────────────────────────────────


def cp1() -> dict:
    print("=== CP1: Estimator ===", flush=True)
    inv = [
        DiscCandidate(f"s{s}_{sid}_{i}", slot=s, set_id=sid)
        for s in range(1, 7)
        for sid in (1, 2)
        for i in range(3)
    ]
    slot_cands = {s: [d for d in inv if d.slot == s] for s in range(1, 7)}
    sizes = _extract_bucket_sizes(slot_cands)
    brute = sum(1 for _ in iproduct(*(slot_cands[s] for s in range(1, 7))))
    est_uncapped = _estimate_combo_count(sizes, None, {}, k=None)
    synthetic_ok = brute == est_uncapped == 6**6

    buckets = json.loads((_FIXTURE_DIR / "owner_twst1_buckets.json").read_text())
    bucket_sizes = {(b["slot"], b["set_id"]): b["count"] for b in buckets["buckets"]}
    frames = [SetFrame(_FRAME)]
    uncapped = _estimate_combo_count(bucket_sizes, frames, _FRAME, k=None)
    k7 = _estimate_combo_count(bucket_sizes, frames, _FRAME, k=7)
    k8 = _estimate_combo_count(bucket_sizes, frames, _FRAME, k=8)
    real_ok = uncapped == _EXPECTED_EXHAUSTIVE and k7 == _EXPECTED_K7 and k8 == _EXPECTED_K8

    result = {
        "synthetic_brute": brute,
        "synthetic_estimate": est_uncapped,
        "synthetic_pass": synthetic_ok,
        "real_uncapped": uncapped,
        "real_k7": k7,
        "real_k8": k8,
        "real_pass": real_ok,
        "pass": synthetic_ok and real_ok,
    }
    print(f"  synthetic: brute={brute} estimate={est_uncapped} pass={synthetic_ok}")
    print(f"  real: uncapped={uncapped:,} k7={k7:,} k8={k8:,} pass={real_ok}")
    return result


# ─── CP2 — No-op invariant ──────────────────────────────────────────────────


def cp2() -> dict:
    print("=== CP2: No-op invariant (full twst1 pool) ===", flush=True)
    payload = json.loads((_FIXTURE_DIR / "owner_twst1_payload.json").read_text())
    discs = json.loads((_FIXTURE_DIR / "owner_twst1_discs.json").read_text())
    base_build = BuildSnapshot(**payload["base_build"])
    enemy = EnemySnapshot(**payload["enemy"])
    combo_steps = _combo_steps_from(payload["combo_steps"])
    conditions = ActiveConditions()
    inv = _inventory_from(discs)

    def run(prefilter_top_k: int) -> tuple:
        constraints = OptimizerConstraints(
            required_sets=_FRAME,
            allowed_frames=[SetFrame(_FRAME)],
            top_n=5,
            prefilter_top_k=prefilter_top_k,
        )
        t0 = time.perf_counter()
        res = optimize_discs(
            base_build=base_build,
            enemy=enemy,
            combo_steps=combo_steps,
            inventory=inv,
            disc_set_modifiers={},
            constraints=constraints,
            conditions=conditions,
        )
        return res, time.perf_counter() - t0

    res_exact, dt_exact = run(PREFILTER_EXACT)
    print(f"  exact (Pareto-only): evaluated={res_exact.evaluated} time={dt_exact:.1f}s")
    # K=16 is >= every post-Pareto bucket size on this fixture (verified max=11) => no-op.
    res_noop, dt_noop = run(16)
    print(f"  K=16 (no-op expected): evaluated={res_noop.evaluated} time={dt_noop:.1f}s")

    ids_match = [b.disc_ids for b in res_exact.builds] == [b.disc_ids for b in res_noop.builds]
    dmg_match = [b.total_damage for b in res_exact.builds] == [
        b.total_damage for b in res_noop.builds
    ]
    return {
        "exact_evaluated": res_exact.evaluated,
        "exact_time_s": dt_exact,
        "noop_evaluated": res_noop.evaluated,
        "noop_time_s": dt_noop,
        "disc_ids_match": ids_match,
        "damage_match": dmg_match,
        "pass": ids_match and dmg_match,
    }


# ─── CP3 — Scoring bias is real ─────────────────────────────────────────────


def cp3() -> tuple[dict, dict, list[list[tuple]]]:
    print("=== CP3: Scoring bias (base vs full baseline) ===", flush=True)
    payload = json.loads((_FIXTURE_DIR / "owner_twst1_payload.json").read_text())
    discs = json.loads((_FIXTURE_DIR / "owner_twst1_discs.json").read_text())
    base_build = BuildSnapshot(**payload["base_build"])
    enemy = EnemySnapshot(**payload["enemy"])
    combo_steps = _combo_steps_from(payload["combo_steps"])
    step_ctxs = _base_step_ctxs(base_build, enemy, combo_steps)

    inv = _inventory_from([d for d in discs if d["set_id"] in _FRAME])
    slot_cands = {s: [d for d in inv if d.slot == s] for s in range(1, 7)}
    ref_dicts = _build_ref_disc_stats(slot_cands)

    diffs: dict = {}
    for slot in range(1, 7):
        for sid in _FRAME:
            group = [d for d in slot_cands[slot] if d.set_id == sid]
            if len(group) < _MIN_BUCKET_GROUP:
                continue
            base_rank = sorted(
                group, key=lambda d: -_solo_score_ext(d.to_stat_dict(), step_ctxs)
            )
            full_rank = sorted(
                group,
                key=lambda d: -_solo_score_ext(d.to_stat_dict(), step_ctxs, ref_dicts),
            )
            k = min(7, len(group))
            base_topk = {d.disc_id for d in base_rank[:k]}
            full_topk = {d.disc_id for d in full_rank[:k]}
            if base_topk != full_topk:
                diffs[(slot, sid)] = {
                    "group_size": len(group),
                    "k": k,
                    "swapped_in": full_topk - base_topk,
                    "swapped_out": base_topk - full_topk,
                }

    print(f"  buckets checked: {sum(1 for s in range(1,7) for sid in _FRAME)}")
    print(f"  buckets with membership change (base vs full): {len(diffs)}")
    for (slot, sid), d in diffs.items():
        print(
            f"    slot={slot} set={sid} k={d['k']}/{d['group_size']}: "
            f"swapped_in={sorted(d['swapped_in'])} swapped_out={sorted(d['swapped_out'])}"
        )

    result = {
        "n_buckets_checked": sum(1 for s in range(1, 7) for sid in _FRAME),
        "n_buckets_differ": len(diffs),
        "buckets": {
            f"{slot}:{sid}": {
                "swapped_in": sorted(d["swapped_in"]),
                "swapped_out": sorted(d["swapped_out"]),
            }
            for (slot, sid), d in diffs.items()
        },
        "pass": len(diffs) > 0,  # CP3 pass = at least one bucket demonstrates the bias
    }
    return result, diffs, slot_cands


# ─── CP4 — Convergence ──────────────────────────────────────────────────────


def cp4() -> dict:
    print("=== CP4: Convergence (K in {7,10,12,16}) ===", flush=True)
    payload = json.loads((_FIXTURE_DIR / "owner_twst1_payload.json").read_text())
    discs = json.loads((_FIXTURE_DIR / "owner_twst1_discs.json").read_text())
    base_build = BuildSnapshot(**payload["base_build"])
    enemy = EnemySnapshot(**payload["enemy"])
    combo_steps = _combo_steps_from(payload["combo_steps"])
    conditions = ActiveConditions()
    inv = _inventory_from(discs)

    per_k = {}
    for k in (7, 10, 12, 16):
        constraints = OptimizerConstraints(
            required_sets=_FRAME,
            allowed_frames=[SetFrame(_FRAME)],
            top_n=5,
            prefilter_top_k=k,
        )
        t0 = time.perf_counter()
        res = optimize_discs(
            base_build=base_build,
            enemy=enemy,
            combo_steps=combo_steps,
            inventory=inv,
            disc_set_modifiers={},
            constraints=constraints,
            conditions=conditions,
        )
        dt = time.perf_counter() - t0
        per_k[k] = {
            "top1_ids": res.builds[0].disc_ids,
            "top1_dmg": res.builds[0].total_damage,
            "top5_id_sets": [tuple(sorted(b.disc_ids)) for b in res.builds],
            "evaluated": res.evaluated,
            "time_s": dt,
        }
        print(
            f"  K={k}: evaluated={res.evaluated} time={dt:.1f}s "
            f"top1_dmg={res.builds[0].total_damage:.1f}"
        )

    ks = sorted(per_k)
    top1_stable = all(
        per_k[k]["top1_ids"] == per_k[12]["top1_ids"] for k in ks if k >= _STABLE_FROM_K
    )
    top5_stable = all(
        set(per_k[k]["top5_id_sets"]) == set(per_k[12]["top5_id_sets"])
        for k in ks
        if k >= _STABLE_FROM_K
    )
    return {
        "per_k": per_k,
        "top1_stable_from_k10": top1_stable,
        "top5_stable_from_k10": top5_stable,
        "pass": top1_stable,
    }


# ─── CP5 — Absolute delta ───────────────────────────────────────────────────


def cp5() -> dict:
    print("=== CP5: Absolute delta (subframe) ===", flush=True)
    subframe = json.loads((_FIXTURE_DIR / "owner_subframe_small.json").read_text())
    base_build = BuildSnapshot(**subframe["base_build"])
    enemy = EnemySnapshot(**subframe["enemy"])
    combo_steps = _combo_steps_from(subframe["combo_steps"])
    conditions = ActiveConditions()
    inv = _inventory_from(subframe["discs"])

    def run(prefilter_top_k: int) -> tuple:
        constraints = OptimizerConstraints(
            required_sets=_FRAME,
            allowed_frames=[SetFrame(_FRAME)],
            top_n=5,
            prefilter_top_k=prefilter_top_k,
        )
        t0 = time.perf_counter()
        res = optimize_discs(
            base_build=base_build,
            enemy=enemy,
            combo_steps=combo_steps,
            inventory=inv,
            disc_set_modifiers={},
            constraints=constraints,
            conditions=conditions,
        )
        return res, time.perf_counter() - t0

    truth, dt_truth = run(PREFILTER_EXACT)
    print(f"  truth (Pareto-only, exact): evaluated={truth.evaluated} time={dt_truth:.1f}s")

    results = {}
    for k in (3, 7):
        approx, dt = run(k)
        top1_match = approx.builds[0].disc_ids == truth.builds[0].disc_ids
        delta = abs(approx.builds[0].total_damage - truth.builds[0].total_damage) / (
            truth.builds[0].total_damage or 1.0
        )
        print(
            f"  K={k}: evaluated={approx.evaluated} time={dt:.1f}s "
            f"top1_match={top1_match} delta={delta * 100:.3f}%"
        )
        results[k] = {
            "evaluated": approx.evaluated,
            "time_s": dt,
            "top1_match": top1_match,
            "delta_pct": delta * 100,
        }

    return {
        "truth_evaluated": truth.evaluated,
        "truth_time_s": dt_truth,
        "truth_top1_ids": truth.builds[0].disc_ids,
        "truth_top1_dmg": truth.builds[0].total_damage,
        "per_k": results,
        "pass": all(
            r["top1_match"] and r["delta_pct"] <= _MAX_DELTA_PCT for r in results.values()
        ),
    }


# ─── CP6 — Union effectiveness ──────────────────────────────────────────────


def cp6(
    cp3_diffs: dict,
    slot_cands: dict,
    step_ctxs: list[list[tuple]],
    agent_element: str,
    ref_dicts: list[dict],
) -> dict:
    """Replicates `_prefilter`'s union keep (top-K_dmg ∪ top-m/stat) under both baselines.

    "base" mirrors the CURRENTLY SHIPPED default (PREFILTER_BASELINE="base") — both the
    K_dmg ranking AND each union stat sort use the bare candidate score, so ties within a
    stat field break on bucket-iteration order.
    "full" mirrors the config this task is gating (PREFILTER_BASELINE="full", Task 5c) —
    both the K_dmg ranking and the union stat sort's tie-break use the F-a reference score,
    so ties resolve toward the disc F-a actually favors. CP6's pass criterion is evaluated
    against "full" because that's the pipeline this checkpoint run unblocks (Sequencing:
    "PREFILTER_BASELINE='full' default on 6b passing (CP3+CP4)") — "base" numbers are kept
    only as a documented before/after data point.
    """
    print("=== CP6: Union effectiveness ===", flush=True)
    if not cp3_diffs:
        print("  no CP3-flagged buckets to check (CP3 found no scoring-bias buckets)")
        return {"n_checked": 0, "pass": None}

    # Mirrors the real `_prefilter`'s union_fields (Task 5b + 5d): crit_rate/crit_dmg
    # always, plus the agent-element DMG% stat when known. energy_regen/anomaly_proficiency
    # are omitted here — this fixture's combo has no ER gating and no anomaly steps, matching
    # the real call site's conditional inclusion.
    union_fields = ["crit_rate", "crit_dmg"]
    element_field = f"{agent_element}_dmg"
    if agent_element and element_field in _ELEMENT_DMG_FIELDS:
        union_fields.append(element_field)
    print(f"  union_fields={union_fields}")

    def _kept_set(group: list, k: int, ref: list[dict] | None) -> set[str]:
        acc = {d.disc_id: accumulate_disc_stats([d.to_stat_dict()]) for d in group}
        scores = {d.disc_id: _solo_score_ext(d.to_stat_dict(), step_ctxs, ref) for d in group}
        by_dmg = sorted(group, key=lambda d: -scores[d.disc_id])
        kept = {d.disc_id for d in by_dmg[:k]}
        for stat_field in union_fields:
            by_stat = sorted(
                group,
                key=lambda d, f=stat_field: (
                    -getattr(acc[d.disc_id], f),
                    -scores[d.disc_id],
                ),
            )
            kept.update(d.disc_id for d in by_stat[:UNION_STAT_KEEP])
        return kept

    results = {}
    for (slot, sid), diff in cp3_diffs.items():
        group = [d for d in slot_cands[slot] if d.set_id == sid]
        k = diff["k"]
        kept_base = _kept_set(group, k, None)
        kept_full = _kept_set(group, k, ref_dicts)
        swapped_in = diff["swapped_in"]
        retained_base = swapped_in <= kept_base
        retained_full = swapped_in <= kept_full
        results[(slot, sid)] = {
            "swapped_in": sorted(swapped_in),
            "retained_base": retained_base,
            "retained_full": retained_full,
        }
        print(
            f"  slot={slot} set={sid}: swapped_in={sorted(swapped_in)} "
            f"retained_base={retained_base} retained_full={retained_full}"
        )

    return {
        "n_checked": len(results),
        "buckets": {f"{slot}:{sid}": v for (slot, sid), v in results.items()},
        "all_retained_base": all(r["retained_base"] for r in results.values()),
        "all_retained_full": all(r["retained_full"] for r in results.values()),
        "pass": all(r["retained_full"] for r in results.values()),
    }


# ─── CP7 — Throughput ────────────────────────────────────────────────────────


def _tiny_pareto_safe_inventory() -> list[DiscCandidate]:
    """2 non-dominated discs/slot (crit_rate-leaning vs crit_dmg-leaning) — both survive
    Pareto so evaluated combo count stays exactly 2**6 = 64 regardless of n_ctx."""
    inv = []
    for s in range(1, 7):
        inv.append(
            DiscCandidate(
                f"cr{s}",
                slot=s,
                set_id=100,
                substats=[{"stat": "crit_rate", "value": 300}, {"stat": "crit_dmg", "value": 0}],
            )
        )
        inv.append(
            DiscCandidate(
                f"cd{s}",
                slot=s,
                set_id=100,
                substats=[{"stat": "crit_rate", "value": 0}, {"stat": "crit_dmg", "value": 300}],
            )
        )
    return inv


def _combo_n_steps(n: int) -> list[ComboStep]:
    return [
        ComboStep(
            label=f"s{i}",
            attack_id=f"a{i}",
            attack_name=f"Atk{i}",
            scope=AttackScope.BASIC,
            multiplier=10000 + i * 137,  # distinct multipliers => no signature consolidation
            element="physical",
        )
        for i in range(n)
    ]


def cp7() -> dict:
    print("=== CP7: Throughput (per-context rate fit) ===", flush=True)
    base_build = BuildSnapshot(agent_base_atk=900, wengine_base_atk=600, agent_element="physical")
    enemy = EnemySnapshot(level=60, base_def=500, element_res=0)
    conditions = ActiveConditions()
    inv = _tiny_pareto_safe_inventory()

    def measure(n_ctx: int, reps: int = 15) -> tuple[float, int]:
        combo_steps = _combo_n_steps(n_ctx)
        constraints = OptimizerConstraints(top_n=5, prefilter_top_k=PREFILTER_EXACT)
        times = []
        evaluated = 0
        for _ in range(reps):
            t0 = time.perf_counter()
            res = optimize_discs(
                base_build=base_build,
                enemy=enemy,
                combo_steps=combo_steps,
                inventory=inv,
                disc_set_modifiers={},
                constraints=constraints,
                conditions=conditions,
            )
            times.append(time.perf_counter() - t0)
            evaluated = res.evaluated
        return sum(times) / len(times), evaluated

    points = []
    for n_ctx in (1, 6, 24):
        t_avg, evaluated = measure(n_ctx)
        assert evaluated == _TINY_INVENTORY_COMBOS, (
            f"expected {_TINY_INVENTORY_COMBOS} combos (Pareto no-op), got {evaluated}"
        )
        per_combo = t_avg / evaluated
        points.append((n_ctx, per_combo))
        print(
            f"  n_ctx={n_ctx}: avg_time={t_avg * 1000:.2f}ms /{_TINY_INVENTORY_COMBOS} combos "
            f"-> {per_combo * 1e6:.2f} us/combo"
        )

    # OLS fit: time_per_combo = a + b * n_ctx
    n = len(points)
    xbar = sum(x for x, _ in points) / n
    ybar = sum(y for _, y in points) / n
    ss_xy = sum((x - xbar) * (y - ybar) for x, y in points)
    ss_xx = sum((x - xbar) ** 2 for x, _ in points)
    b = ss_xy / ss_xx if ss_xx else 0.0
    a = ybar - b * xbar
    ss_tot = sum((y - ybar) ** 2 for _, y in points)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in points)
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0

    rate_ctx = 1 / b if b else float("inf")
    print(f"  fit: time/combo ~= {a * 1e6:.2f}us + {b * 1e6:.3f}us * n_ctx  (R^2={r2:.4f})")
    print(f"  RATE_CTX = 1/b = {rate_ctx:.1f} ctx-evals/sec; overhead a = {a * 1e6:.2f}us")

    return {
        "points": points,
        "a_overhead_s": a,
        "b_s_per_ctx": b,
        "rate_ctx": rate_ctx,
        "r2": r2,
        "combo_budget_current": COMBO_BUDGET,
        "union_product_cap": UNION_PRODUCT_CAP,
    }


# ─── CP8 — Pareto losslessness (delegated to the existing regression test) ──


def cp8() -> dict:
    print("=== CP8: Pareto losslessness (delegated to pytest) ===", flush=True)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-v",
            "tests/unit/test_disc_optimizer_pareto.py::TestExhaustiveResultsIdenticalWithPareto",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    passed = proc.returncode == 0
    print(proc.stdout[-2000:])
    if not passed:
        print(proc.stderr[-2000:])
    return {"pass": passed, "returncode": proc.returncode}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-slow", action="store_true", help="skip CP2/CP4/CP5 (real optimize_discs runs)"
    )
    parser.add_argument("--out", default=str(_DEFAULT_OUT))
    args = parser.parse_args()

    out_path = Path(args.out)
    results: dict = {}

    def _dump() -> None:
        out_path.write_text(json.dumps(results, indent=2, default=str))

    results["cp1"] = cp1()
    _dump()

    if not args.skip_slow:
        results["cp2"] = cp2()
        _dump()

    cp3_result, cp3_diffs, slot_cands = cp3()
    results["cp3"] = cp3_result
    _dump()

    payload = json.loads((_FIXTURE_DIR / "owner_twst1_payload.json").read_text())
    step_ctxs = _base_step_ctxs(
        BuildSnapshot(**payload["base_build"]),
        EnemySnapshot(**payload["enemy"]),
        _combo_steps_from(payload["combo_steps"]),
    )

    if not args.skip_slow:
        results["cp4"] = cp4()
        _dump()
        results["cp5"] = cp5()
        _dump()

    ref_dicts = _build_ref_disc_stats(slot_cands)
    results["cp6"] = cp6(
        cp3_diffs, slot_cands, step_ctxs, payload["base_build"]["agent_element"], ref_dicts
    )
    _dump()

    results["cp7"] = cp7()
    _dump()

    results["cp8"] = cp8()
    _dump()

    print("\n=== Summary ===")
    for name, r in results.items():
        status = r.get("pass") if isinstance(r, dict) else None
        print(f"  {name}: pass={status}")
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
