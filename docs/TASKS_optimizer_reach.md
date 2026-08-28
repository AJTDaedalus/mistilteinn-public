# TASKS — optimizer reach

**Status: none started.** Plan is `docs/DESIGN_optimizer_reach.md`. Read it first; the two
tracks are sequenced, not parallel.

Track **A** is what every user feels on every first run. Track **B** is a coverage gap for a
minority of builds and is **opt-in by owner ruling**. Do A first — B's search is additive on
top of A's streaming surface and is unpleasant without it.

---

## Task 0 — branch setup gate

Branch `feat/optimizer-reach` off `dev`. No commits to `dev`/`main`.
**Acceptance:** `git branch --show-current` is `feat/optimizer-reach`; `npm test` green before
anything changes, so a later red suite is attributable.

---

## Track A — calibration throughput

### A.1 — measure the cost, per state, split baseline vs probe

Instrument `calibrateAll` to record per-state wall time and the baseline/probe split; run it
against the real 2,370-artifact export and write the table into
`docs/RESEARCH_calibration_cost.md`.

**Why first:** every task below is judged against this. "~6 s per state" is R.1's figure
divided out of a total, not a measurement of the split, and A.3 is only worth doing if the
probe is genuinely half.
**Acceptance:** a committed table with per-state times over ≥10 real states; the total matches
the ~3.8 min already measured, or the discrepancy is explained.

### A.2 — merge the top-N across states in the caller

Lift the per-state loop out of `searchRecipe` so a caller can drive one state at a time and
merge results, keeping the current all-states call working as a thin wrapper.

**Acceptance:** driving states one-by-one and merging returns **exactly** what the current
single call returns, over the real inventory. Existing `recipe-search.spec.ts` stays green
untouched.

### A.3 — stream results as each state lands

Search each state as its calibration completes; the leaderboard updates progressively.

**Acceptance:** a state landing later can displace an earlier winner (test it explicitly); the
UI labels a partial run as partial; the final result equals the batch result.

### A.4 — stop early, and say what was searched

A run stopped after *k* of *n* states reports the best of those *k*, labelled, and lists the
states not searched — the `uncoveredSets` discipline.

**Acceptance:** a stopped run never presents itself as the best overall; the unsearched states
are named.

### A.5 — parallel calibration in Web Workers

N workers, gcsim instance each, **reused across states**. Start at 4 and measure; 41 MB of wasm
per worker is the ceiling.

**Acceptance:** identical results to serial calibration over the real inventory; measured
speedup and peak memory recorded in `RESEARCH_calibration_cost.md`. If the wasm load dominates
per worker, say so and keep serial — a slower correct answer beats a faster one nobody measured.

### A.6 — probe once, only if provably invariant

Probe every state, assert the resolved conversions are equal across all of them, and collapse to
one probe **only** if they are.

**Acceptance:** the assertion runs over real states in CI-able form. **If conversions differ
anywhere, stop and report it** — that finding outranks the speedup, because it means a
conditional set bonus is feeding a conversion and the recipe model needs to know.

---

## Track B — optional 2+2

### B.1 — pass `setBonuses` into the recipe search

`runRotation()` builds `{ recipes, fourPieceSets }` and no `setBonuses`. Wire it from the same
search context the single-hit path already reads.

**Acceptance:** a 2+2 build scores **differently** with and without the bonuses — a test that
passes when the wiring is dead is not a test. Existing 4-piece results are unchanged (a
4-piece state has one spare piece, which grants nothing).

### B.2 — report 2-piece bonuses that are not stat pools

Nine of sixty. Carry them out of the search the way `uncoveredSets` is carried, named.

**Acceptance:** selecting Noblesse Oblige surfaces it as unmodelled; nothing silently
contributes zero. The list is derived from the data (`add_props` all `FIGHT_PROP_NONE`), not
hardcoded — a hardcoded list goes stale on the next patch.

### B.3 — enumerate a 2+2 pair as a set configuration

User names a pair (A, B). Walk 2 slots of A, 2 of B, one free, partitioned by slot assignment
so nothing is double-counted. The existing bound applies unchanged.

**Acceptance:** an exhaustive reference over a capped inventory matches the bounded walk's
top-10 **and** `boundPruned > 0`, so the comparison cannot be vacuous. No combination appears
twice — assert on distinct artifact-id sets, not on the count.

### B.4 — retire `includeNoFourPiece`'s unbounded walk

Once B.3 lands, the "search every no-4-piece build" option has no reason to exist: it is 99.97 %
of the space, it does not finish, and the pair picker covers what it was for.

**Acceptance:** removed, with the findings doc updated to say why rather than leaving a reader
to wonder where it went.

### B.5 — the pair picker, behind a toggle

Rare, so opt-in: a collapsed control, not a third of the page.

**Acceptance:** hidden by default; selecting a pair shows the added calibration count **before**
the run starts, since that is the cost the user is agreeing to.

### B.6 — calibrate a 2-piece state for the conditional nine *(optional, owner call)*

Let gcsim apply what we will not derive. One extra calibration per conditional set selected.

**Acceptance:** a Noblesse Oblige 2+2 scores its burst bonus, verified against a gcsim run that
equipped it. **Do not derive it from `param_list`** — `docs/DECISIONS.md` rejected exactly that
reasoning for weapon passives, and it is the failure fairy actually shipped.

---

## Sequencing

`0 → A.1 → A.2 → A.3 → A.4 → A.5 → A.6` then `B.1 → B.2 → B.3 → B.4 → B.5 → (B.6)`.

A.5 and A.6 are independent of each other and of Track B; either can be deferred without
blocking anything. **B.6 is gated on an owner decision (OQ-R1)** and is the only task here that
changes what a number *means* rather than how fast it arrives.
