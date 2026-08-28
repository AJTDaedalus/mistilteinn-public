# RESEARCH — what a calibration actually costs

**Task A.1 of `docs/TASKS_optimizer_reach.md`.** Measured 2026-08-28 against the owner's real
account (build: Skirk + Azurelight; rotation: a 5-step gated loop) and the committed browser
wasm at pin `3647a07`.

**Run in Node, against the same `gcsim.wasm` the browser loads.** A browser adds overhead this
does not capture, which matters for one conclusion below and is flagged where it does.

## The measurement

Thirteen real calibration states — the baseline plus the twelve sets the account owns most of —
each fetched from the live `POST /builds/{id}/calibrate` and timed as two `sample()` calls.

| state | baseline ms | probe ms | total ms |
|---|---|---|---|
| Brave Heart | 1483 | 1084 | 2567 |
| Instructor | 905 | 743 | 1648 |
| The Exile | 738 | 733 | 1471 |
| Blizzard Strayer | 764 | 761 | 1525 |
| Gladiator's Finale | 825 | 769 | 1594 |
| Viridescent Venerer | 912 | 978 | 1890 |
| Wanderer's Troupe | 787 | 837 | 1624 |
| Thundering Fury | 739 | 820 | 1559 |
| Noblesse Oblige | 739 | 811 | 1550 |
| Archaic Petra | 703 | 822 | 1525 |
| Tenacity of the Millelith | 731 | 820 | 1551 |
| Emblem of Severed Fate | 758 | 835 | 1593 |
| no 4-piece (baseline) | 817 | 809 | 1626 |

**mean baseline 839 ms · mean probe 832 ms · mean total 1671 ms**
The first row is warm-up; every subsequent state sits in a tight 1471–1890 ms band.

The wasm load is **583 ms, once**, shared by every state.

## Finding 1 — the probe is exactly half

**49.8 %.** A.4 (probe once, if provably invariant) would come close to halving calibration,
which is the largest single lever available. It was written as conditional on this measurement
and the condition is met.

It remains conditional on the *other* gate: conversions must be equal across states, or the
probe is measuring something state-dependent and cannot be collapsed. This finding says A.4 is
**worth attempting**, not that it is safe.

## Finding 2 — the ~3.8 min figure does not reproduce

At 1671 ms per state, **36 states is 60 s**, not 3.8 minutes. The plan, the findings doc and
`optimize.ts`'s own comments all carry ~3.8 min from R.1.

I cannot fully account for the gap, and would rather say so than pick a flattering explanation.
The candidates:

- **A double-counted probe.** `builds.py:calibrate_recipe` says *"a calibration is ~3.2 s of
  work per set"* — and 3.2 s is almost exactly **two** of my samples. If 3.2 s was later
  doubled for baseline-and-probe, 6.4 s × 36 ≈ 3.8 min falls straight out. This is the tidiest
  explanation and the one I would bet on, but it is inference about how a number was produced,
  not evidence.
- **A different machine.** These numbers are this box.
- **A browser, not Node.** `RESEARCH_gcsim_embed.md` records a large browser penalty on
  `simulate`; whether `sample` pays the same is unmeasured.

**What this does not license.** Nothing here proves 3.8 min was wrong in a browser, which is
where users are. Until someone measures `sample()` in a real browser tab, treat 60 s as the
floor and 3.8 min as an unrefuted ceiling.

## Finding 3 — rotation size barely moves it

| rotation | characters | one sample | a calibration |
|---|---|---|---|
| 5-step solo Skirk | 1 | 808 ms | 1.62 s |
| 4-character Skirk team (owner's real config) | 4 | 939 ms | 1.88 s |

Four characters cost **16 % more** than one, not four times. Cost tracks the **simulated
duration**, not the number of authored steps — which is what one would expect of a
frame-by-frame simulator, and matches `RESEARCH_gcsim_speed.md`'s finding that 86 % of an
iteration is the combat loop.

**Caveat that limits this row:** the team fixture's loop was cut to one iteration when it was
captured, so it is a *short* four-character rotation. It bounds the cost of adding characters,
not the cost of a long rotation.

## What this means for the plan

**A.4 (probe once) is promoted.** It is worth half of all calibration and the measurement that
gated it has come in.

**A.3 (parallel workers) is demoted, and should probably not be built yet.** Owner ruling 3
means a run is a handful of states, not 36 — three sets is four calibrations, about **7 s**.
Four workers would take that to ~4 s, saving three seconds for 41 MB × 4 of memory and a pool
to maintain. A.3 already permits the conclusion "not worth it"; this is the evidence for it.

**The one thing that would overturn this: a browser measurement.** If `sample()` in a tab is
several times slower than in Node, a full run returns to minutes and workers matter again. That
measurement is cheap and should happen before A.3 is either built or dropped — it is now the
open question, in place of the split A.1 was written to resolve.
