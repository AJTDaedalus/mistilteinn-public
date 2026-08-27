# DESIGN: a gcsim-based optimizer that runs in the browser

**Companion:** `docs/TASKS_gcsim_optimizer.md`.
**Evidence:** `docs/RESEARCH_gcsim_calibration.md` (the decomposition), `RESEARCH_recipe_cost.md`
(the cost), `RESEARCH_damage_recipe.md` (ER stability), `RESEARCH_gcsim_speed.md` (why not just
make gcsim fast), `RESEARCH_er_bucketing.md` (the bucket width).

## Branch policy

Per-task branches off `dev`, `feat/<task>` or `fix/<task>`, merged to `dev` by PR after review.
**No direct commits to `dev` or `main`.** **`gh pr merge --delete-branch` checks out `dev`** —
branch immediately after a merge, before anything else; that is how W.6 landed unreviewed.
**Task G.0 is the branch-setup gate.**

---

## 1. The goal, and the one number that makes it possible

Today the optimizer maximises **one hit**. That is a proxy: the best five pieces for a single
Cutting DMG are not necessarily the best five for a rotation. Worse, the chain does not model
weapon passives, so for `Redhorn Stonethresher` it will **never consider DEF** and returns a
confident wrong answer.

The objective should be **the rotation's damage, as gcsim computes it**. gcsim cannot be the
inner loop — `RESEARCH_gcsim_embed.md` §6, ~8,900× — and making it faster tops out at ~4×
(`RESEARCH_gcsim_speed.md`).

**So gcsim runs once, and the loop replays its arithmetic.**

| | cost |
|---|---|
| fixed per combination (stat aggregation) | ~4.9 µs |
| **marginal per recipe hit** | **0.051 µs** |
| four-character team recipe | **17 sources** |

**≈1.15× today's cost, entirely client-side.**

## 2. Why this is not a re-derivation of gcsim

`sample(cfg, seed)` publishes **every term of the damage formula for every hit** — `talent`,
`total_scaling`, `bonus_dmg`, `cr`, `cd`, `def_mod`, `res_mod`, `flat_dmg`, `use_hp/def/em`,
the reaction terms. Recomposed across 245 hits, every relation is exact to **0.000e+00**
(`RESEARCH_gcsim_calibration.md` §2).

The recipe is therefore **transcribed, not modelled**. Nothing is fitted, no coefficient is
read off a tooltip, and no talent table is consulted. This is the citation rule satisfied by
construction: the number's provenance is a gcsim run, and the run is reproducible from a
committed config and seed.

## 3. Architecture

```
  calibrate (once)                          search (per combination)
  ─────────────────                         ────────────────────────
  gcsim sample() ─┐                         candidate's 5 pieces
                  ├─→  Recipe  ─────────→   + base + set bonuses
  gcsim aggregate ┘    (N hits)              ↓
    (instance counts,                       aggregate stats  (4.9 µs)
     stability)                              ↓
                                            for each hit: recompute  (0.051 µs)
                                             ↓
                                            Σ  → rotation damage
```

**Calibration is keyed by everything that changes the rotation or the baked-in buffs:**
`(team, rotation, weapons, artifact-set combination, ER bucket)` — the owner's own prediction,
before any of it was measured. `sim_runs` already exists and is already keyed by
`context_key` + `er_bucket`.

### 3.1 The calibration baseline

**Calibrate with the sets equipped but with zero artifact stats** — `add set="x" count=4` and
no `add stats` line. Then every stat in the published `final_stats` is character + weapon +
set-bonus + talent buff, which is exactly what the kernel already treats as `context.base`,
and the candidate's own artifact stats add on top.

This keeps **conditional set bonuses** (`Blizzard Strayer`'s crit rate against frozen) inside
the recipe, where they belong — they depend on the rotation, not on the candidate's substats.

### 3.2 What a recipe hit carries

`{ abil, attackTag, element, talent, scalingStat, flatDamage, baseBonusDmg, baseCritRate,
baseCritDmg, defMod, resMod, ampMultiplier, reactionTerms, instances }`

`instances` comes from the **aggregate**, not the sample: one seed's counts carry that seed's
jitter, and the aggregate's `sd` is what says whether the recipe is stable at all.

### 3.3 The gap the recipe cannot close by itself

A passive whose **amount is a function of the candidate's own stats** is baked in at
calibration and goes stale: `Staff of Homa` (ATK from max HP), `Engulfing Lightning` (ATK from
ER), `Redhorn Stonethresher` (flat damage from DEF), `Primordial Jade Cutter`.

**These are exactly the passives that change which artifacts win**, so they are the whole
remaining job — and `TASKS_passive_port.md` narrows to them from "44 + 14" to a handful.

## 4. Correctness strategy

**Self-consistency is not enough.** Replaying a recipe against the artifacts it was calibrated
with must reproduce gcsim's own number — but that only proves transcription, not fidelity.

**The real gate is predict-then-verify:** build a recipe at one artifact set, use it to predict
a *different* set's damage, then run gcsim on that set and compare. That is the crossval
discipline applied to the recipe, and it is what G.5 is for. A tolerance is argued from the
measured Monte Carlo standard error, not chosen.

**A recipe states its own validity**, like `isExact` and W.5's separability:
- `stable`: burst-instance `sd == 0` at this ER bucket
- `staleModifiers`: stat-conversion passives present and not yet ported
- `erBucket`, `gcsimPin`, `seed`, `iterations`

## 5. Open questions

- **OQ-G1 — how many ER buckets must be calibrated?** `RESEARCH_er_bucketing.md` measured
  bucket 120 at **13.3 %** DPS spread and others at the noise floor. Calibrating every bucket
  is wasteful; calibrating one is wrong. **Measure where the steps are for the actual rotation
  and calibrate the transitions.**
- **OQ-G2 — does the search need to re-rank by recipe, or only re-score the top N?** Scoring
  every combination at 1.15× is affordable, so re-ranking is the honest default; the cheaper
  two-stage option is a fallback if a real inventory says otherwise.
- **OQ-G3 — where does the recipe live?** `sim_runs` is the natural home and is already keyed
  correctly, but its `result` column holds a gcsim run, not a recipe. New column, new table, or
  a derived cache?
- **OQ-G4 — what happens to `/compare-weapons`?** A recipe per candidate weapon makes the
  gcsim comparison tier ~free. It may collapse into this.
