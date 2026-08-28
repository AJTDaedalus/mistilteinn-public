# DESIGN — optimizer reach: calibration throughput, and optional 2+2

**Status: planned, nothing built.** Written 2026-08-28 after the shakedown
(`docs/FINDINGS_shakedown.md`) and the fixes in #119. Read that first — every number below
comes from it or from a measurement recorded here.

## Branch policy

Work happens on **`feat/optimizer-reach`**, branched from `dev`. **No direct commits to `dev`
or `main`**; `dev` is updated only by PR merge. Two tracks run in sequence, not parallel, so
one branch is enough — Track B depends on Track A's streaming surface to be usable at all.
`docs/TASKS_optimizer_reach.md` **Task 0** is the branch-setup gate.

## Where the optimizer stands

The search is **solved for builds holding a 4-piece set**, which is nearly every real build:
7.2 days → **1.8 s** for the largest set in a 2,370-piece inventory, exact, verified against an
exhaustive reference. Two things remain.

| | cost | who feels it |
|---|---|---|
| **A. Calibration** | ~6 s × 36 states = **~3.8 min** before any search starts | everyone, every first run |
| **B. No-4-piece builds** | unbounded; killed after an hour | rare, and by owner ruling **optional** |

**The bottleneck moved.** The search got fast enough that the wait is now upstream in gcsim.
That reorders the work: A is what a user experiences today, B is a coverage gap for a minority
of builds.

---

## Track A — calibration throughput

**Owner rulings 2 and 3 (2026-08-28, `docs/DECISIONS.md`) reshape this track.** Only complete
calculations are offered — no partial leaderboard, no early stop — and the set filter defaults
to nothing selected. Those two go together: scope is narrowed by the person who knows what they
want, instead of the wait being hidden behind streaming output.

The consequence is direct. **Throughput is the only lever left.** Parallel calibration and
probe-once were nice-to-haves in the first draft, when a streaming leaderboard would have
covered the wait; they are now the whole of the track.

### The shape of the cost

Each state is **two gcsim samples** (baseline + probe). With nothing preselected, a typical run
is a handful of states rather than 36 — three sets is four calibrations — so the absolute wait
is already far smaller than the ~3.8 min a full run costs. The work below is about the run that
is still large: a user comparing many sets deliberately.

### A1. Measure the baseline/probe split first

"~6 s per state" is R.1's total divided out, not a measurement of the split. **A3 is only worth
doing if the probe is genuinely half.**

### A2. Drive calibration one state at a time

Lift the per-state loop so a caller can calibrate states individually, with the current
all-states call preserved as a thin wrapper. This is the prerequisite for parallelism.

It was originally motivated by streaming; that motivation is gone and the task survives on the
other one. Worth stating so a later reader does not delete it as streaming's leftover.

### A3. Parallel calibration in Web Workers

N workers, a gcsim instance each, **reused across states**. The wasm is 41 MB, so memory is
`41 MB × N`; four workers is the starting point, not sixteen.

**Measure before committing.** If the wasm load dominates per worker, workers must be pooled
rather than spawned per state — and if pooling does not pay, say so and keep serial. A slower
correct answer beats a faster one nobody measured.

### A4. Probe once, if it is provably invariant

Half of all calibration is the probe, which measures conversions. If conversions do not depend
on the equipped set, that answer is being bought 36 times.

**A question, not a plan.** A conditional 4-piece that converts a stat into damage would make
the probe state-dependent, and the opacity of those bonuses is the entire premise of the
4-piece work. Gate: probe every state, assert the resolved conversions are equal, collapse only
then. **If they differ anywhere, stop and report** — that finding outranks the speedup, because
it means a conditional bonus feeds a conversion the recipe model does not know about.

### A5. Progress is reported; a result is not

Ruling 2 permits progress reporting — progress is not a result — and forbids showing a ranking
that a still-calibrating state could displace. The current code already sets `result` only
after every state completes, so this is a property to **pin**, not to build: it is one edit away
from being lost, and losing it would look like a feature.

---

## Track B — optional 2+2, which is not a smaller version of Track A's problem

By owner ruling (2026-08-28): **2+2 is valid for some characters but rare, so it is opt-in.**
Not a default, not a checkbox that quietly triples the wait.

### B1. Searching all no-4-piece builds is not the goal, and never was

The shipped `includeNoFourPiece` walks *every* combination without a 4-piece — 99.97 % of the
space, killed after an hour. That is the wrong shape. The right one is the trick that worked
for 4-piece states: **enumerate by set configuration.** The user names a pair (A, B); the walk
is 2 slots of A, 2 of B, one free, partitioned by slot assignment so nothing is counted twice.

Sizing, from the shakedown's own Pareto output — 675 survivors across 5 slots and 35 sets is
**~4 pieces per set per slot**:

```
one slot assignment:  4 x 4 x 4 x 4 x 135  ~ 3.5e4
x C(5,2) x C(3,2) = 30 assignments         ~ 1.0e6   -> ~15 s before the bound
```

Tractable for one chosen pair; hopeless for all `C(35,2) = 595` of them, which is precisely why
it is opt-in rather than a default.

### B2. The blocker nobody has hit yet: `setBonuses` is never passed

`runRotation()` builds its search context as `{ recipes, fourPieceSets }` — **no `setBonuses`
at all**. Harmless today, because a 4-piece state leaves one spare piece and a lone piece grants
nothing. The moment 2+2 exists, both 2-piece bonuses would be dropped silently, understating
every such build by exactly the thing the user selected it for.

### B3. Nine 2-piece bonuses are not stat pools

Queried against the seeded catalogue at 7.0.51, **not** inferred:

| tier | affixes | static `add_props` | conditional |
|---|---|---|---|
| 1-piece | 5 | 0 | 5 |
| 2-piece | 60 | **51** | **9** |
| 4-piece | 60 | 0 | 60 |

The nine: **Gambler**, **Golden Troupe**, **Long Night's Oath**, **Marechaussee Hunter**,
**Martial Artist**, **Noblesse Oblige**, **Obsidian Codex**, **Scroll of the Hero of Cinder
City**, **Tiny Miracle**.

Six of them are **ability-scoped DMG bonuses** — burst +20 %, normal/charged +15 %, skill
+20 %, plunging +25 %. A flat stat pool cannot express "only on burst hits". `Tiny Miracle` is
elemental RES and irrelevant to damage; the last two are genuinely state-conditional.

`artifact_optimizer.py` already documents this for the kernel path and **reports the count of
skipped conditional affixes** so *"why is my 4pc not showing up"* has an answer. The recipe path
has no equivalent, and needs one before 2+2 ships.

### B4. Those nine are calibrated, by ruling

**Deriving them from `param_list` and the description is rejected.** That is the
fabricated-citation failure fairy actually suffered, and `docs/DECISIONS.md` turned down exactly
this reasoning for weapon passives on 2026-08-26.

**Owner ruling 1 (2026-08-28): they are calibrated from the first version of 2+2** — not
offered-but-flagged, not excluded. A "2-piece of set X" calibration state lets gcsim apply the
real bonus, reusing machinery that already exists, at one extra calibration per conditional set
selected.

This moves what the first draft had as an optional last task into a **prerequisite**: 2+2 does
not ship offering a set whose bonus it silently scores as zero. The interim the draft proposed
never exists.

## Testing strategy

- **A2** — calibrating states one at a time and merging returns **exactly** what the batch call
  returns, over the real inventory.
- **A3** — identical results to serial calibration. Worker count is configuration, not
  correctness.
- **A4** — the invariance assertion **is** the test, over real states rather than a fixture.
- **A5** — no ranking renders while a state is still calibrating.
- **B1** — a 2+2 build scored with and without `setBonuses` must **differ**, or the wiring is
  dead and the test is decorative.
- **B3** — a Noblesse Oblige 2+2 scores its burst bonus, checked against a gcsim run that
  equipped it.
- **B4** — the same equivalence discipline the bound got: a 2+2 search against an exhaustive
  reference over a capped inventory, asserting `boundPruned > 0` so the comparison cannot be
  vacuous. That check caught a bound comparing two empty lists once already.
- **Set list** — the conditional nine are derived from the data (`add_props` all
  `FIGHT_PROP_NONE`), never hardcoded; a hardcoded list goes stale at the next patch.

## Resolved

All three open questions were settled by the owner on 2026-08-28 and are recorded in
`docs/DECISIONS.md`:

1. **The conditional 2-piece sets are calibrated from the start**, so no flagged-but-wrong
   interim exists.
2. **Only complete calculations are offered** — no partial leaderboard, no early stop. Throughput
   becomes the whole of Track A.
3. **The set filter defaults to nothing selected**, which is what makes (2) affordable. The
   accepted cost: a user without a set in mind has no default to lean on, mitigated only by the
   picker showing what they own, most-owned first.
