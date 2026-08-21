# Optimizer validation fixtures (real data)

DB-free, committed fixtures for the math checkpoints in
`docs/DESIGN_optimizer_granularity.md` ("Validation fixtures & math
checkpoints"). Captured from the 2026-06-30 prod incident so the bounded-
error optimizer math can be re-checked on demand without prod or a seeded
DB. See `scripts/capture_optimizer_fixture.py`.

## Provenance
- **Source job:** `019f162b-74a8-75d0-a5d6-a75287889d96` (status `failed`,
  cancelled by backend restart after 9+ min at 0/0/0 progress).
- **Owner:** `019e5510-5be0-74b3-a76b-b64dd3560515` (owner).
- **Team:** `019f104e-0815-72d3-9447-2f3c2ffc661d`; agent **Ye Shunguang**,
  enemy "Ye Shiyuan the Thrall", combo **Twst1**.
- **Frame:** `{32700: 2, 33500: 4}` — 2pc Branch & Blade Song +
  4pc White Water Ballad.

## Files
- **`owner_twst1_discs.json`** — the run's exact candidate pool: 595
  `DiscCandidate`-shaped discs (`disc_id, slot, set_id (hakushin), main_stat_*,
  substats`). `disc_ids` is the *search pool* (`optimizer_pipeline.py:455`).
- **`owner_twst1_buckets.json`** — per-`(set_id, slot)` counts of the
  in-frame discs, derived from the pool above.

## Ground-truth numbers (the locked targets)
Of the 595 candidates, only **128 are in the two frame sets**
(32700 ×76, 33500 ×52). In-frame per-slot buckets:

| set | s1 | s2 | s3 | s4 | s5 | s6 |
|---|--|--|--|--|--|--|
| 32700 Branch & Blade Song (2pc) | 3 | 18 | 19 | 18 | 6 | 12 |
| 33500 White Water Ballad (4pc)  | 11 | 7 | 10 | 4 | 7 | 13 |

- **Exhaustive (frame):** 12,529,002 combos.
- Uniform K=7 → 989,898 · K=8 → 1,628,672 · K=12 → 6,405,984.

> NOTE: an earlier planning estimate of ~94.2B used the owner's *full*
> inventory (566 in-frame discs) rather than the submitted 595-disc pool.
> The pool is the real population — 12.5M. This correction is the first
> result of the math-checkpoint discipline.

## Payload fixtures (synthetic — read this before using CP7 numbers)
- **`owner_twst1_payload.json`** — build / enemy / Twst1 combo steps.
  **SYNTHETIC**: the prod source job is not in the local DB. Ye Shunguang
  stats queried from the local DB (L60-scaled: agent_base_atk=863,
  wengine_base_atk=743 Cloudcleave Radiance), enemy Ye Shiyuan the
  Thrall, simplified Twst1 combo at skill level 12. Produced by
  `scripts/capture_optimizer_fixture.py --payload`.
- **`owner_subframe_small.json`** — same payload + disc pool capped to
  ≤6 per `(set_id, slot)` bucket: 404 discs, 458,784 exhaustive frame
  combos. Tractable exhaustive ground truth for CP5/CP8.

> **CAVEAT:** the payload is a plain physical crit combo — no anomaly
> steps, no ER gating, no `event_log_by_am` fan-out. It exercises only
> the overlay fast path. Any throughput measured on it is
> `RATE_OVERLAY` ONLY — do not treat it as a universal combos/sec rate;
> the stateful anomaly path is orders of magnitude slower (this was the
> actual cost driver in the 2026-06-30 incident). See CP7 (amended) in
> `docs/DESIGN_optimizer_granularity.md`.
