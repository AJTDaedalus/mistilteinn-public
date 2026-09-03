# DESIGN — waiting for energy, as an option

**Status:** built and merged 2026-09-02 (#242). `wait_for_energy` reaches the compiler and
`energy_drip` the config; the option is on the optimize page, **off by default**, and the two
models cannot share a cache entry. **OQ-E2 is answered below** — the waiting ladder is strictly
monotone. OQ-E1 (per search or per rotation) and OQ-E3 (showing both curves) remain open.

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

**OQ-E2 — what does waiting do to the energy ladder? — ANSWERED 2026-09-02, and the risk runs
the other way.** Both models were swept over `ENERGY_LADDER`'s own six rungs at
`ENERGY_LADDER_RUNS = 60`, same rotation, same team, the two configs differing only in the gate
and the drip:

| artifact ER | 0.20 | 0.30 | 0.45 | 0.60 | 0.80 | 1.00 |
|---|---|---|---|---|---|---|
| **waiting** DPS | 199,535 | 220,191 | 245,580 | 259,226 | 269,221 | 276,824 |
| waiting duration | 160.9 s | 149.7 s | 136.1 s | 128.0 s | 119.6 s | 113.9 s |
| **skipping** DPS | 267,640 | 267,100 | 265,796 | 266,297 | 267,316 | 267,701 |

Waiting is **strictly monotone across the whole ladder, +38.7 %**, the duration falling at every
rung. Skipping spans **+0.0 %** with two reversals of −0.20 % and −0.49 %.

The concern was that a duration moving with ER makes DPS climb for two reasons at once and so
voids the monotonicity argument. That is true about the mechanism and **backwards about the
risk**: a running maximum is dangerous over a flat noisy curve, where the peak it keeps is
noise — which is the *skipping* ladder above — and has nothing to do over the waiting one,
where no rung is ever below the one before it. `dpsAt` is safe under waiting for the reason it
was written, and safer than under the model it was justified for.

**What this does not settle** is the tripwire on extending `ENERGY_LADDER` past ~1.5; that
hazard is about a peak no candidate can reach and belongs to both models unchanged.

**A first attempt measured the wrong thing and said so loudly**, which is worth recording. Run
against the team's *current* rotation — 16 steps, replaced since — the duration was **10.8 s at
every rung**, identical to a tenth of a second. Under waiting that is impossible if anyone is
ever waiting, and the reason is that the rotation contains one burst per character, all paid
out of gcsim's starting energy. ER was not weakly measured there; it was **structurally
unmeasurable**, and a ladder run against it would have reported ±1 % of noise as a verdict.

**A user-authored energy guard is this same choice, made locally.** `.energy >= 30` on a block
tells the sim to skip rather than wait inside that block, so a guarded rotation prices ER lower
even when the run as a whole is waiting — measured at +8.8 % against +23.5 % on the owner's own
config (`DESIGN_conditional_steps.md`, OQ-C2). The two models are therefore not a global switch
over an otherwise-neutral rotation; a rotation can contain the other one.

**OQ-E3 — is the comparison a first-class feature?** Running both and showing two ER curves is
the honest way to present a 70 % disagreement. It is also twice the compute, and the owner's
own framing is that most searches compare one or two things.
