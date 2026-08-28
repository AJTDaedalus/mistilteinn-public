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

---

# A.4 — the probe cannot be collapsed. Attempted, and refused.

A.4 was gated on two conditions: that the probe is worth enough to bother (A.1: **49.8 %**, yes)
and that resolved conversions are **equal across states**. The second was tested and **fails**.

## Method

The Skirk build resolves **zero** conversions, so it cannot answer this — the check would have
passed vacuously. Ran instead against **Noelle + Redhorn Stonethresher**, whose passive converts
DEF into damage, across **54 states**: the baseline plus every one of the 53 sets gcsim
implements at the pin. (Twelve of the 65 sets 422 — gcsim does not implement them; nine of those
are the one-piece "Prayers" circlets.)

Conversions are compared by **(ability, term) → the set of rates seen**, deliberately *not* by
hit index. The first version keyed by index, and Ocean-Hued Clam adds hits — 104 against the
baseline's 91 — which shifts every index and manufactured ~150 spurious differences. The
finding below survives that correction; the first output overstated it.

## Result

**50 of 54 states are identical**: 91 hits, 11 distinct conversion keys, 103 resolved, 0
unresolved, 0 stale. **Four differ**, and all four are sets that either move DEF during the run
or add damage sources:

| state | hits | resolved | unresolved | stale |
|---|---|---|---|---|
| *baseline and 49 others* | 91 | 103 | 0 | 0 |
| **Husk of Opulent Dreams** | 91 | 85 | 18 | 1 |
| **Ocean-Hued Clam** | 104 | 103 | 13 | 1 |
| **Echoes of an Offering** | 91 | 60 | 43 | 1 |
| **Song of Days Past** | 91 | 65 | 40 | 1 |

Husk loses its `flatAtk` conversions outright — six (ability, term) keys resolve to
`def@0.68` in the baseline and to **nothing** under Husk.

## The nuance that matters, and why it does not rescue A.4

**No rate ever disagreed.** There is no case of `def@0.68` in one state and `def@0.55` in
another. What varies is *whether a conversion resolves at all*.

That might look like an argument **for** probing once — import the baseline's rates and resolve
more. It is the opposite. Those four sets fail to resolve precisely **because the set itself
perturbs the term**: Husk's 4-piece stacks DEF% over the run, so DEF is not constant and a
single-stat probe cannot separate it. Importing the baseline's rate would assert a stable
conversion in exactly the states where the set makes it unstable — a recipe claiming a
resolution its own run refuses to support.

That is the failure this repo keeps legislating against, and the reason `staleConversions`
exists. **The current design is already honest here**: those four states report `stale: 1` and
their unresolved counts. A.4 would have replaced an honest "I could not resolve this" with a
confident wrong number.

## Ruling

**A.4 is closed as refused, not deferred.** The measurement is the answer, and it is the branch
the task specified: *"If conversions differ anywhere, stop and report it — that finding outranks
the speedup."*

## An unrelated finding from running this

`POST /builds/{id}/calibrate` is rate-limited at **60/minute per owner** (`WRITE_LIMIT`), and I
hit **429** repeatedly while calibrating 65 states back to back.

`calibrateAll` issues **one request per state with no pacing and no retry**. A 36-state run sits
just under the limit; two runs inside a minute, or a future 65-state one, do not — and a 429
mid-run aborts the whole calibration. The endpoint only *emits configs* (the simulation is the
browser's work), so the limit is conservative for what it guards. Worth either a client-side
retry with backoff or its own limit; recorded rather than fixed, because changing a rate limit
is the owner's call.
