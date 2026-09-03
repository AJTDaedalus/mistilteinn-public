# DESIGN — waiting for energy, as an option

**Status:** design, 2026-09-02. Nothing built.

## Branch policy

`feat/waiting-model`, off `dev`. **No direct commits to `dev` or `main`** — merged by PR after
review like every other feature.

## The ask

Owner, 2026-09-02, on why a starved Furina looked cheap:

> *"But without the ER% she doesn't burst on time making the DPS drop right?"*

and, choosing between the two models:

> *"Build waiting as an option."*

## The two models

When a character cannot fund a burst, the simulation can do one of two things.

**Skip** — what ships today. The burst is gated on `.ready`, gcsim does not attempt it, and the
rotation carries on. The cost is that burst's damage and its cast time.

**Wait** — what the owner's reading describes. The burst is ungated, gcsim holds the whole
simulation until the energy arrives, and *every other character stands still while it does*.
The cost is the delay, spread across the team.

They are not close. Measured on the owner's own team and rotation:

| | ER is worth |
|---|---|
| waiting, 2 passes | **+24.5 %** |
| waiting, 3 passes | **+42.4 %** |
| waiting, 5 passes | **+70.5 %** |
| skipping, 5 passes, below the cliff | **-0.3 % to +0.1 %** |

Waiting is arguably the better model of a person at a keyboard: they do not silently omit a
burst, they hold the rotation. Skipping is the one that runs.

## Why waiting needs the drip

**Ungated, gcsim has no watchdog.** `actionReadyCheckPhase` answers `ErrActionNotReady` with
`advanceFrames(1, actionReadyCheckPhase)` — retry, forever — and `stopCheck()` never consults
duration in damage mode. A burst nobody can fund blocks the sim, so nothing later runs, so no
particles drop, so the energy never comes. Measured: **2.4 GB and `fatal error: out of
memory`**, bisected to `escoffier burst` in the fourth cycle at `er=0.583`. The identical
config with her at `er=3.0` finishes in **0.03 s using 32 MB**.

An **energy drip** bounds the wait: a background trickle guarantees every burst eventually
becomes affordable, so the wait ends and its *length* is the ER penalty — which is exactly the
quantity the owner wants priced.

## The drip is cited, not chosen

This is the part that would otherwise be a number this repo invented, which `CLAUDE.md` names
as fairy's worst failure. It is not invented. **Five configs use the identical line**, four of
them committed here and one the owner's own:

```
energy every interval=480,720 amount=1;   # standard Energy drops
```

- `references/gcsim_db/clorinde-chevreuse-nicole-durin.txt:30` — comment: *standard Energy drops*
- `references/gcsim_db/mavuika-escoffier-citlali-bennett.txt:33` — same comment
- `references/gcsim_db/arlecchino-citlali-escoffier-bennett.txt:34`
- `references/gcsim_db/neuvillette-furina-citlali-escoffier.txt:32`
- `gcsim.app/db/bgHjR7MP7Fkn:36` — the owner's imported config, same comment

Three of the five call it *standard*. It is the community's own convention for the energy a
team collects from particles and enemy hits that a rotation does not itself generate, and it is
emitted **verbatim** with that provenance recorded beside it.

**It is still an assumption, and the UI says so.** A build ranked under the waiting model is
ranked against a stated rate of incoming energy; a team that plays around energy differently
gets a different answer. Stating that is the difference between a citation and a claim.

## Shape

- `build_config(..., energy_drip=False)` emits the line. Off by default, so nothing that runs
  today changes.
- The compiler emits **ungated** bursts when the waiting model is chosen — the gate is what
  turns waiting into skipping, and `_ENERGY_GATED_ACTION` already isolates that decision.
- The optimizer carries the choice into `context_key` and the recipe cache, because a recipe
  calibrated under one model is not the other's. **The lesson of #240**: a client-side option
  that never reaches the cache key produces two identical answers and reads as "the models
  agree".
- The result names which model produced it. A number whose meaning depends on an unstated
  assumption is the shape this repo refuses.

## Open questions

**OQ-E1 — does the toggle belong per search, or per rotation?** A rotation's author knows
whether they would wait; a searcher wants to compare. Leaning per search, so the two can be run
against the same rotation and compared, which is the owner's stated reason for wanting both.

**OQ-E2 — what does waiting do to the energy ladder?** The ladder varies ER and reads team DPS,
and under waiting the *rotation's duration* changes with ER as well. `dpsAt`'s running-maximum
argument rests on the ladder's range being monotone, which was measured under skipping.
Re-measure before trusting a waiting-model ladder.

**OQ-E3 — is the comparison a first-class feature?** Running both and showing two ER curves is
the honest way to present a 70 % disagreement. It is also twice the compute, and the owner's
own framing is that most searches compare one or two things.
