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

### The shape of the cost

Each state is **two gcsim samples** (baseline + probe), and the states are already ordered by
how much of each set the user owns — R.1 chose that ordering *"so an interrupted run has
calibrated the ones most likely to matter"*. Nothing yet takes advantage of it.

### A1. Stream results per state (first, and cheapest)

Search each state **as its calibration lands** rather than after all 36. The leaderboard fills
progressively, the user can stop when they have seen enough, and the existing ordering finally
pays off.

This does not reduce total work. It removes the blocking wait, which is the thing the root
`CLAUDE.md` already says the design implies: *"a job with progress, never a request that
blocks."* It is also the prerequisite for Track B being tolerable, since a 2+2 pair search is
additive on top.

**Correctness note:** the top-N must merge across states rather than reset, and a state landing
later must be able to displace an earlier winner. That is exactly what `searchRecipe`'s `best`
array already does across its state loop — streaming moves the loop outward, into the caller,
so the merge has to move with it.

### A2. Parallel calibration in Web Workers

N workers, each with its own gcsim instance. The wasm is 41 MB, so memory is `41 MB × N` and
the ceiling is real; 4 workers is the starting point, not 16.

**Measure before committing.** Two risks: the wasm load may dominate per worker (it is the
slow first step the R.8 progress reporting already calls out separately), and browsers throttle
background workers. If load cost dominates, workers must be **reused across states**, not
spawned per state.

### A3. Probe once, if it is provably invariant

Half of all calibration is the probe, which exists to measure conversions. If a build's
conversions do not depend on which artifact set is equipped, the probe is being paid 36 times
for one answer.

**This is a question, not a plan.** A conditional 4-piece bonus that converts a stat into
damage would make the probe state-dependent, and the whole point of the 4-piece work is that
those bonuses are opaque. The gate: probe every state once, assert the resolved conversions are
equal across states, and only then collapse it. If they differ anywhere, the finding is worth
more than the speedup.

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

### B4. Two ways to handle those nine, and the cheap one is wrong

**Derive them from `param_list` and the description.** This is the fabricated-citation failure
fairy actually suffered, and `docs/DECISIONS.md` already rejected exactly this reasoning for
weapon passives (2026-08-26). Not doing it.

**Calibrate them, like a 4-piece.** A "2-piece of set X" calibration state lets **gcsim** apply
the real bonus, reusing every piece of machinery that already exists. Costs one extra
calibration per conditional set the user selects — at most nine, and only when opted in.

This is the same answer the 4-piece work arrived at, for the same reason: the authority on what
a conditional bonus does is the simulator, not our reading of the tooltip.

---

## Testing strategy

- **A1** — a state landing later displaces an earlier winner; stopping early yields the best of
  what was searched, labelled as such, never presented as the best overall.
- **A2** — identical results to serial calibration; worker count is configuration, not
  correctness.
- **A3** — the invariance assertion **is** the test; it must run over real states, not a fixture.
- **B1** — the same equivalence discipline the bound got: a 2+2 search against an exhaustive
  reference over a capped inventory, asserting the prune fired (`boundPruned > 0`) so the
  comparison cannot be vacuous. That check caught a bound comparing two empty lists once already.
- **B2** — a 2+2 build scored with and without `setBonuses` must differ, or the wiring is dead.
- **B3** — the nine conditional 2-piece sets are **named** in the result when selected, with the
  count, and never silently contribute zero.

## Open questions for the owner

- **OQ-R1** Should a 2+2 pair search offer the 9 conditional sets at all before B4 lands? The
  honest interim is to list them as selectable but flagged, the way `weapon_comparison` reports
  `unmodelled_passives` rather than publishing a ranking it cannot stand behind.
- **OQ-R2** Is "stop early and take the best so far" a button, or does closing the page do it?
  The first needs a partial-result contract; the second does not.
