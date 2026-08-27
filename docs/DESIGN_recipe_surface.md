# DESIGN: making the recipe optimizer reachable, and right about sets

**Companion:** `docs/TASKS_recipe_surface.md`.
**Predecessor:** `docs/TASKS_gcsim_optimizer.md` (G.0–G.8, complete). This is the chunk that
makes its work reach a user, and fixes the gap that measuring it exposed.
**Evidence:** `docs/RESEARCH_conditional_sets.md`, `RESEARCH_calibration_cache.md`,
`RESEARCH_gcsim_calibration.md`, `RESEARCH_recipe_cost.md`.

## Branch policy

Per-task branches off `dev`, `feat/<task>` or `fix/<task>`, merged to `dev` by PR after review.
**No direct commits to `dev` or `main`.** **`gh pr merge --delete-branch` checks out `dev`** —
branch immediately after a merge, before anything else. **Task R.0 is the branch-setup gate.**

---

## 1. Two problems, and the second is bigger than the first

**Reachability.** `searchRecipe` exists, is gated, and **nothing calls it**. The optimize page
calls `search`. A kernel nobody reaches changes no answer a user sees — the same failure
`CLAUDE.md` records from Chunk J, when there was a verified optimizer that nothing imported.

**Correctness.** Measuring what a calibration must contain turned up something worse:
**every 4-piece bonus in the game is conditional — 60 of 60 — and the kernel scores every one
as zero**
(`RESEARCH_conditional_sets.md`). A conditional affix's props are all `FIGHT_PROP_NONE`, so
`_bonus_stats` skips them — correctly, since inventing a quantity would be worse — and the
search then ranks four-piece sets as though their headline effect did not exist.

**A recipe can hold what the kernel cannot**, because gcsim applies the bonus and the
calibration bakes in the result. That is available *only* to a search scoring against a recipe,
which makes reachability and correctness the same job.

## 2. The calibration set, and why it is small

Naively, keying calibration by "set combination" means `S²/2 + 2S + 1` states. The measurement
removes the square term: **51 of 60 two-piece bonuses are plain static stats**, which the
kernel already models correctly as stat pools. Only the 4-piece tier must be inside a
calibration, and a five-piece combination has **at most one** 4-piece set.

| state | calibrations |
|---|---|
| a 4-piece of set *X* | one per set with ≥4 pieces in the inventory |
| no 4-piece | one |

**S + 1**, at ~3.2 s each plus a probe. A dozen viable sets is under two minutes, once per
`(team, rotation, weapon, ER plateau)` — and `RESEARCH_calibration_cache.md` measured a plateau
at **60 ER points wide**, so that key changes rarely.

**The 9 sets with a conditional 2-piece are the exception and must be handled, not assumed
away** — they need their own states on top. The five `Prayers` circlets have **no multi-piece
tier at all** and belong in no state.

## 3. Shape

```
  calibrate (once per set state)              search (per combination)
  ──────────────────────────────              ────────────────────────
  server emits configs:                       candidate's 5 pieces
    · zero artifact stats                       ↓
    · the 4-piece set equipped                setCounts → pick the recipe
    · a probe at a perturbed stat               ↓
        ↓                                     evaluate that recipe   (~0.02 µs/hit)
  browser: sample() ×2                          ↓
        ↓                                     Σ → rotation damage
  parseSample + resolveConversions
        ↓
  Recipe, cached client-side
```

**The search selects a recipe by the combination's `setCounts`.** That is the only structural
change to `searchRecipe`: today it takes one recipe; it needs a small map from 4-piece set id
to recipe, with a fallback for combinations that reach no 4-piece.

### 3.1 The Pareto layer is the risk

`liveQuantitiesFor` derives the live set from **one** recipe. With several, the live set must
be the **union** — a piece dominated under one recipe may be the winner under another, and
pruning it makes the lossless layer silently lossy. **This is the one place a bug here
produces a wrong answer rather than a slow one.**

### 3.2 Verify the 2-piece assumption rather than trusting it

*Having a static prop* is not the same as *having no conditional part*. The probe technique
applies to sets as well as stats: calibrate with and without a set and compare. If the
difference is a plain stat delta, the kernel already has it and no calibration is needed. If
it is not, that set needs a state. **R.2 measures this rather than inheriting §2's table.**

## 4. What is deliberately not fixed

**Snapshotted conversions.** Noelle's burst snapshots DEF at cast, so a two-point probe cannot
resolve it and those hits stay frozen — ~21 % out on the fixture. `staleConversions` reports
it, and **the page must surface that**, because an optimizer that is confidently wrong in the
case it was built to fix is worse than one that says it does not know.

**The single-hit search.** It stays and stays reachable. It answers a different question in
microseconds, and OQ-W4 settled the principle: deleting a fast honest answer because a slow
better one exists is a downgrade.

## 4a. Three corrections from measuring before building

`docs/RESEARCH_recipe_risks.md`. All three were in **this design**, not in the code, and all
three would have produced numbers that looked entirely reasonable.

1. **ER is an artifact stat, so "calibrate at zero artifact stats" calibrates the wrong
   rotation.** A zero-ER calibration produced **2 burst instances against a real candidate's
   3**. ER is **structural**: baked into the calibration at a plateau-representative value, and
   a candidate's own ER picks a plateau rather than being added as a damage stat.
2. **Calibrating with a set bakes in its 2-piece**, which the kernel would then add again —
   measured as an exact 0.15 double-count on `Blizzard Strayer`. §2's "2-piece bonuses stay
   kernel stat pools" holds only for sets the calibration does **not** hold.
3. **A build that cannot execute the rotation is flagged, not scored.** Candidates within one
   search reach different burst counts, and an earlier draft concluded recipes must be keyed
   by ER plateau — multiplying the budget by `P`. **Owner decision: no.** Each recipe carries
   a **minimum ER**, and a build below it is reported as unable to perform the rotation. Same
   principle as `DECISIONS.md` (2026-08-25): *rotations are authored, never optimized* — a
   build that cannot burst on cue is not performing that rotation, and silently scoring it
   against a degraded variant substitutes a rotation nobody wrote. **The budget stays
   `S + 1`.**

## 5. Open questions

- **OQ-R1 — how many calibrations does a *real* inventory need?** §2 says S+1, where S is the
  sets with ≥4 pieces. **Measure S against a real GOOD import** rather than assuming a dozen.
- **OQ-R2 — when is a calibration invalidated?** The key is `(team, rotation, weapon, 4-piece
  set, ER plateau, gcsim pin)`. A pin change invalidates everything; an ER move invalidates
  only if it crosses a plateau, which `stabilityFrom` detects. Where that check lives is open.
- **OQ-R3 — what does the page do while calibrating?** Two minutes is a job, not a spinner. It
  needs progress, and it needs to be interruptible without losing what is already calibrated.
- **OQ-R4 — does the fast tier stay the default?** A user who wants an answer now versus one
  who wants the right answer is a product question, not a technical one.
