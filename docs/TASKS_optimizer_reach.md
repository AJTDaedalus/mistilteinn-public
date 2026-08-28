# TASKS — optimizer reach

**Status: Track A is closed as far as it can go** (2026-08-28). Task 0, Task 1, A.1 and A.5
are **done**; **A.4 is refused** on measurement; **A.3 is blocked** on a browser measurement and
**A.2 is moot until A.3 is decided**. Track B is next. Plan is
`docs/DESIGN_optimizer_reach.md`; the three owner rulings it was revised for are in
`docs/DECISIONS.md`.

**A.1's measurement moved two tasks.** `docs/RESEARCH_calibration_cost.md`: the probe is
**49.8 %** of a calibration, so **A.4 is promoted**; a state costs **1.67 s**, so a typical run
under ruling 3 is ~7 s and **A.3 is demoted and should probably not be built**. A.1 also found
the ~3.8 min figure does not reproduce — 36 states is 60 s here — and could not fully account
for the gap, so a **browser** measurement of `sample()` is now the open question in A.3's place.

**One bug fell out of A.1** and is fixed: every 4-piece calibration from the page 404'd, because
the inventory's `set_id` is the nanoka id and `/calibrate` resolves the catalogue uuid.

Track **A** is throughput. Track **B** is optional 2+2 coverage. Do Task 1 first regardless —
it shrinks the default scope of every run, which makes the rest cheaper to measure.

---

## Task 0 — branch setup gate

> **Done.** 385 tests green at the baseline.

Branch `feat/optimizer-reach` off `dev`. No commits to `dev`/`main`.
**Acceptance:** `git branch --show-current` is `feat/optimizer-reach`; `npm test` green before
anything changes, so a later red suite is attributable.

## Task 1 — the set filter defaults to nothing selected

> **Done.** Mutation-checked: an all-selected default, a gate ignoring the selection, and an add-only toggle are each caught.

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

> **Done** — `docs/RESEARCH_calibration_cost.md`, 13 real states.

Instrument `calibrateAll` for per-state wall time and the baseline/probe split; run it against
the real 2,370-artifact export; write the table into `docs/RESEARCH_calibration_cost.md`.

**Acceptance:** a committed table over ≥10 real states. The total reconciles with the ~3.8 min
already measured, or the discrepancy is explained. **A.4 is gated on this** — it is only worth
doing if the probe is genuinely half.

### A.2 — drive calibration one state at a time

> **Blocked, and possibly moot.** Its only surviving motivation is A.3, which is itself blocked
> on a browser measurement and demoted by A.1. Do not build this until A.3 is decided.

Lift the per-state loop so states can be calibrated individually; keep the all-states call as a
thin wrapper.

**Acceptance:** one-at-a-time plus merge returns **exactly** what the batch call returns over
the real inventory. `recipe-search.spec.ts` stays green untouched.

### A.3 — parallel calibration in Web Workers *(demoted by A.1 — measure a browser first)*

**Do not start this until `sample()` has been timed in a real browser tab.** A.1 makes a typical
run ~7 s in Node, which four workers would take to ~4 s for 41 MB × 4 of memory and a pool to
maintain. If a browser is several times slower the calculus flips; if it is not, this task's
right outcome is "not worth it, written down".

N workers, gcsim instance each, **reused across states**, starting at 4.

**Acceptance:** identical results to serial over the real inventory; measured speedup and peak
memory recorded in `RESEARCH_calibration_cost.md`. **If the wasm load dominates per worker, keep
serial and say so** — this task is allowed to conclude "not worth it", and that conclusion must
be written down rather than quietly abandoned.

### A.4 — probe once, only if provably invariant

> **Closed: REFUSED** (2026-08-28). Tested across 54 states with a build that actually has
> conversions (Noelle + Redhorn). **Four states differ** — Husk of Opulent Dreams, Ocean-Hued
> Clam, Echoes of an Offering, Song of Days Past. No *rate* ever disagreed; what varies is
> whether a conversion resolves, and it fails exactly where the set perturbs the term. Probing
> once would assert a stable conversion in the states that break it.
> `docs/RESEARCH_calibration_cost.md`.

Probe every state, assert resolved conversions are equal, collapse only then.

**Acceptance:** the assertion runs over real states in CI-able form. **If conversions differ
anywhere, stop and report it** — a conditional set bonus feeding a conversion is a finding worth
more than the speedup.

### A.5 — pin that no partial ranking can render

> **Done.** Mutation-checked: publishing a ranking from the progress callback — a streaming
> leaderboard, exactly what ruling 2 forbids — is caught.

Owner ruling 2. The current code already sets `result` only after every state finishes; this
task makes that a property rather than an accident.

**Acceptance:** a test fails if a ranking renders while a state is still calibrating. Progress
reporting is unaffected — progress is not a result.

---

## Track B — optional 2+2

### B.1 — pass `setBonuses` into the recipe search

> **Done.** Needed a new endpoint: `search-context` carries these but requires a *hit*, and
> the rotation objective has none. `GET /artifacts/set-bonuses` publishes them for owned sets,
> and the `add_props` → kernel-quantity conversion moved to `build_assembler.bonus_stats` so
> two routes share one implementation. Mutation-checked.

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

> **Backend done.** `Calibration.two_piece_set_keys` (at most two, mutually exclusive with a
> 4-piece) and `CalibrationRequest.two_piece_set_ids`. The frontend half needs
> `Recipe.meta.calibratedSetId` to become plural: a pair calibration bakes in **two** sets'
> bonuses, and `score` skipping only one would double-count the other.

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

---

## Later — not scheduled

### L.1 — per-character set recommendations as the default selection

**Owner idea, 2026-08-28: scrape keqingmains' per-character guides for the sets they list, and
preselect all of them.**

This aims squarely at the cost ruling 3 accepts — *"a user with no set in mind has no default to
lean on"*. A recommended shortlist is a better answer than either of the defaults that ruling
rejected: it is not all 35 (which is the 3.8-minute wait) and not nothing (which is the blank
page), and it is per character rather than one global guess.

**Why the citation rule does not block this, and where it would.** This repo's hardest lesson is
fabricated citations — deriving mechanics from community prose. A set *recommendation* is not a
mechanic: it preselects checkboxes and changes **which** states get calibrated, never what a
number means. gcsim still computes every score, and a bad recommendation costs a user one
unnecessary calibration, not a wrong ranking.

**That distinction is the whole safety argument, so it is also the boundary.** The moment
scraped text is used for what a bonus *does* rather than which set to try, it is the failure
`docs/DECISIONS.md` rejected for weapon passives. Recommendations select; they never score.

Open before this could be scheduled:

- **A committed snapshot, never a live fetch** — the convention every other external source in
  this repo follows, with a pinned capture date beside the patch it describes.
- **Staleness**: recommendations shift per patch, and a stale default is a silently worse
  starting point rather than an error anything can detect.
- **Attribution and terms** for redistributing a community site's curation.
- **Coverage**: what a character with no guide gets. Falling back to "nothing selected" is
  fine; falling back to "everything" would reintroduce the wait ruling 3 removed.
