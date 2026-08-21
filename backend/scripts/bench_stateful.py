"""Task 14 — Benchmark stateful simulator cost (OQ4 input).

Measures:
  1. Single simulate() call time for a realistic Yanagi combo (~30 steps).
  2. 2-AM-variant loop cost (the inner loop in resolve_stateful_am_step_lists).
  3. Projected cost of running the stateful path for N optimizer candidates.

Run inside Docker:
  docker compose exec backend python -m scripts.bench_stateful
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from statistics import mean, stdev

sys.path.insert(0, "/app")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data.loaders.moves import load_agent_moves
from app.models.enums import PotentialVariant
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, EnemyProfileRepository
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.optimizer_pipeline import _make_am_variant
from app.services.snapshot_builder import build_snapshot_from_db

YANAGI_BUILD_ID = "019e673e-357f-78d3-b44a-60aad6ac60d3"
ENEMY_ID = "019e4c7f-9e26-7c52-b224-bf241759d08d"

# Typical optimizer candidate counts we want to stress-test
CANDIDATE_COUNTS = [100, 500, 1_000, 5_000, 10_000]

# Reps for timing (more = tighter estimate)
REPS = 50

# Threshold above which projected wall-time is reported in minutes instead of seconds
SECONDS_PER_MINUTE = 60


def _make_combo_steps(attacks_by_name: dict, n: int = 30) -> list:
    """Build a synthetic n-step combo cycling through Yanagi's moves."""
    # Typical Yanagi rotation: Basic × 2, Special, EX Special, repeat
    rotation = [
        "Basic Attack",
        "Basic Attack",
        "Special Attack: Gekka",
        "EX Special Attack: Gekka Ruten",
    ]
    steps = []
    for i in range(n):
        move = rotation[i % len(rotation)]
        # Fall back to first available move if exact name not found
        atk_list = attacks_by_name.get(move) or next(iter(attacks_by_name.values()), [])
        steps.append(
            SimulatedAttackStep(
                agent_id="dps",
                move_name=move,
                attacks=atk_list,
                conditions=[],
            )
        )
    return steps


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        br = BuildRepository(session)
        ar = AttackRepository(session)
        er = EnemyProfileRepository(session)

        print("Loading build + enemy from DB...")
        yanagi_db = await br.get_by_id(YANAGI_BUILD_ID)
        yanagi_ag = yanagi_db.agent
        enemy = await er.get_by_id(ENEMY_ID)  # ORM model; simulate() uses getattr

        snap = build_snapshot_from_db(yanagi_db, yanagi_ag)

        # Load Yanagi attacks grouped by name
        # Benchmark harness: takes the build's own rank, like the calc path it times.
        all_attacks = await ar.get_by_agent(
            str(yanagi_ag.id), PotentialVariant.for_rank(yanagi_db.potential_rank)
        )
        attacks_by_name: dict[str, list] = {}
        for atk in all_attacks:
            attacks_by_name.setdefault(atk.name, []).append(atk)

        moves_db = load_agent_moves()

        steps = _make_combo_steps(attacks_by_name, n=30)
        builds = {"dps": snap}

        print(f"Combo: {len(steps)} steps | Reps: {REPS}\n")

        # ─── 1. Single simulate() timing ────────────────────────────────────────
        times_single: list[float] = []
        for _ in range(REPS):
            t0 = time.perf_counter()
            simulate(builds, steps, enemy, moves_db)
            times_single.append((time.perf_counter() - t0) * 1000)

        p50_single = sorted(times_single)[len(times_single) // 2]
        avg_single = mean(times_single)
        sd_single = stdev(times_single) if len(times_single) > 1 else 0.0

        print("=== 1. Single simulate() call ===")
        print(f"  avg   {avg_single:.2f} ms   p50 {p50_single:.2f} ms   sd {sd_single:.2f} ms")

        # ─── 2. Two-variant loop (mirrors resolve_stateful_am_step_lists) ───────
        times_2var: list[float] = []
        for _ in range(REPS):
            t0 = time.perf_counter()
            for am_idx in range(2):
                extra_am = 60 if am_idx == 1 else 0
                variant = _make_am_variant(snap, extra_am)
                simulate({"dps": variant}, steps, enemy, moves_db)
            times_2var.append((time.perf_counter() - t0) * 1000)

        p50_2var = sorted(times_2var)[len(times_2var) // 2]
        avg_2var = mean(times_2var)

        print("\n=== 2. 2-AM-variant loop (per-candidate cost) ===")
        print(f"  avg   {avg_2var:.2f} ms   p50 {p50_2var:.2f} ms")

        # ─── 3. Projected full-search times ──────────────────────────────────────
        print("\n=== 3. Projected optimizer search (stateful path, 2 AM variants) ===")
        print(f"  {'Candidates':>12}   {'Wall-time':>10}")
        for n in CANDIDATE_COUNTS:
            proj_s = n * avg_2var / 1000
            unit = "s" if proj_s < SECONDS_PER_MINUTE else "min"
            val = proj_s if proj_s < SECONDS_PER_MINUTE else proj_s / SECONDS_PER_MINUTE
            print(f"  {n:>12,}   {val:>8.1f} {unit}")

        print()
        print("OQ4 input: see docs/LOG_anomaly_fixes.md for recorded results.")


if __name__ == "__main__":
    asyncio.run(main())
