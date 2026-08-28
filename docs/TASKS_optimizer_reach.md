# TASKS — optimizer reach

**Status: none started.** Plan is `docs/DESIGN_optimizer_reach.md`; the three owner rulings it
was revised for are in `docs/DECISIONS.md` (2026-08-28).

Track **A** is throughput. Track **B** is optional 2+2 coverage. Do Task 1 first regardless —
it shrinks the default scope of every run, which makes the rest cheaper to measure.

---

## Task 0 — branch setup gate

Branch `feat/optimizer-reach` off `dev`. No commits to `dev`/`main`.
**Acceptance:** `git branch --show-current` is `feat/optimizer-reach`; `npm test` green before
anything changes, so a later red suite is attributable.

## Task 1 — the set filter defaults to nothing selected

Owner ruling 3. Today `selectedSets = null` means "untouched, therefore all"; invert it so a run
requires an explicit pick. `Search rotation` is disabled until at least one set is chosen, and
says why.

**Why first:** it is the change that makes "only complete calculations" affordable, and it is
small. Every measurement below is taken against the scope a real run will actually have.
**Acceptance:** a fresh page has nothing selected and cannot start a search; picking one set
enables it; the calibration count shown before the run matches what the run performs.

---

## Track A — throughput

### A.1 — measure the cost, per state, split baseline vs probe

Instrument `calibrateAll` for per-state wall time and the baseline/probe split; run it against
the real 2,370-artifact export; write the table into `docs/RESEARCH_calibration_cost.md`.

**Acceptance:** a committed table over ≥10 real states. The total reconciles with the ~3.8 min
already measured, or the discrepancy is explained. **A.4 is gated on this** — it is only worth
doing if the probe is genuinely half.

### A.2 — drive calibration one state at a time

Lift the per-state loop so states can be calibrated individually; keep the all-states call as a
thin wrapper.

**Acceptance:** one-at-a-time plus merge returns **exactly** what the batch call returns over
the real inventory. `recipe-search.spec.ts` stays green untouched.

### A.3 — parallel calibration in Web Workers

N workers, gcsim instance each, **reused across states**, starting at 4.

**Acceptance:** identical results to serial over the real inventory; measured speedup and peak
memory recorded in `RESEARCH_calibration_cost.md`. **If the wasm load dominates per worker, keep
serial and say so** — this task is allowed to conclude "not worth it", and that conclusion must
be written down rather than quietly abandoned.

### A.4 — probe once, only if provably invariant

Probe every state, assert resolved conversions are equal, collapse only then.

**Acceptance:** the assertion runs over real states in CI-able form. **If conversions differ
anywhere, stop and report it** — a conditional set bonus feeding a conversion is a finding worth
more than the speedup.

### A.5 — pin that no partial ranking can render

Owner ruling 2. The current code already sets `result` only after every state finishes; this
task makes that a property rather than an accident.

**Acceptance:** a test fails if a ranking renders while a state is still calibrating. Progress
reporting is unaffected — progress is not a result.

---

## Track B — optional 2+2

### B.1 — pass `setBonuses` into the recipe search

`runRotation()` builds `{ recipes, fourPieceSets }` and no `setBonuses`. Wire it from the same
search context the single-hit path already reads.

**Acceptance:** a 2+2 build scores **differently** with and without the bonuses — a test that
passes when the wiring is dead is not a test. 4-piece results unchanged (a 4-piece state leaves
one spare piece, which grants nothing).

### B.2 — derive the conditional 2-piece sets from the data

The nine with no static `add_props`. Computed, never hardcoded.

**Acceptance:** the list is derived at runtime and matches the nine known at 7.0.51 — Gambler,
Golden Troupe, Long Night's Oath, Marechaussee Hunter, Martial Artist, Noblesse Oblige, Obsidian
Codex, Scroll of the Hero of Cinder City, Tiny Miracle — without naming them in source.

### B.3 — calibrate a 2-piece state

Owner ruling 1, and a **prerequisite** for B.4 rather than a follow-up: 2+2 must not ship
offering a set whose bonus it scores as zero. Extend the calibration request to equip two pieces
of a named set.

**Acceptance:** a Noblesse Oblige 2-piece calibration produces a recipe whose burst hits carry
the +20 %, verified against a gcsim run that equipped it. **Not derived from `param_list`.**

### B.4 — enumerate a 2+2 pair as a set configuration

User names a pair (A, B). Walk 2 slots of A, 2 of B, one free, partitioned by slot assignment.
The existing bound applies unchanged.

**Acceptance:** an exhaustive reference over a capped inventory matches the bounded walk's top
10 **and** `boundPruned > 0`, so the comparison cannot be vacuous. No combination appears twice
— assert on distinct artifact-id sets, not on a count.

### B.5 — retire `includeNoFourPiece`'s unbounded walk

It is 99.97 % of the space, it does not finish, and B.4 covers what it was for.

**Acceptance:** removed, with `docs/FINDINGS_shakedown.md` updated to say why rather than
leaving a reader to wonder where it went.

### B.6 — the pair picker, behind a toggle

Rare, so opt-in: a collapsed control, not a third of the page.

**Acceptance:** hidden by default; selecting a pair shows the added calibration count **before**
the run starts — including the extra state a conditional set costs — since that is what the user
is agreeing to.

---

## Sequencing

`0 → 1 → A.1 → A.2 → A.3 → A.4 → A.5` then `B.1 → B.2 → B.3 → B.4 → B.5 → B.6`.

A.3 and A.4 are independent of each other and of Track B; either may be deferred without
blocking anything, and A.3 is explicitly allowed to conclude "not worth it". **B.3 gates B.4**
by ruling 1 — that is the one ordering here that is not a preference.
