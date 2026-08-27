# RESEARCH: how many calibrations does a search need? (OQ-G1, OQ-G3)

**Question:** a recipe is calibrated per `(team, rotation, weapons, artifact-set combination,
ER bucket)`. `RESEARCH_er_bucketing.md` bucketed ER in 5 % steps. **How many of those buckets
actually need their own calibration, and where do the recipes live?**

**Answer: far fewer than one per bucket. The unit is the *plateau*, and a plateau measured 60
percentage points wide — twelve 5 % buckets.**

## 1. The measurement

Solo Ayaka, the committed `rotation_gated.txt`, ER swept in 10-point steps, 120 iterations
each. `Soumetsu (Bloom)` is the burst; its instance count is what a recipe's structure hangs
on.

| ER total | bursts | sd | DPS | |
|---|---:|---:|---:|---|
| 100 % | 2.00 | 0.000 | 3410 | stable |
| 110 % | 2.17 | 0.382 | 3564 | **transition** |
| 120 % | 2.74 | 0.440 | 3865 | **transition** |
| 130 % | 2.98 | 0.129 | 3979 | **transition** |
| **140 %** | **3.00** | **0.000** | 3996 | **stable** |
| 150–200 % | 3.00 | 0.000 | 3990–4050 | **stable** |
| 210 % | 3.01 | 0.091 | 3973 | **transition** |
| 220 % | 3.18 | 0.389 | 4132 | **transition** |

**Wide stable plateaus separated by narrow transition bands.** That is the same shape
`RESEARCH_er_bucketing.md` found — *"burst count is a step, not a slope"* — seen from the axis
that matters for calibration rather than for error.

## 2. What that changes

**A recipe calibrated at ER 160 % is valid from 140 % to 200 %.** Calibrating every 5 % bucket
would produce **twelve identical recipes** for that span, at ~3.2 s each.

So the cache key is **not** the bucket. It is *"which plateau is this build on"*, and a build
that is not on one has **no valid recipe at all** — which `stabilityFrom` already reports, from
the same `sd` this table is built on. **The detection and the cache key are the same
measurement.**

### On a plateau, ER stops mattering

DPS across 140–200 % is 3990–4050, a **1.5 % spread over 120 iterations** — the Monte Carlo
noise floor, not a trend. Ayaka has no ER-scaling effect, and once the burst count stops
changing, extra ER buys nothing.

**That is not universal and the cache must not assume it.** `Emblem of Severed Fate` converts
ER into burst damage, and `Engulfing Lightning` converts it into ATK — for those, damage keeps
climbing across a plateau even though the *structure* does not change. The recipe still holds
(the structure is what it encodes); it is `staleConversions` that has to say the conversion is
baked in, and **OQ-G5 records that a percentage-term conversion like Engulfing's is not yet
detected**.

## 3. Resolution, stated

Measured in **10-point steps**, so the plateau spans *at least* 140–200 % and its exact edges
sit somewhere in 130–140 % and 200–210 %. Locating them to the point would need a finer sweep,
and it is not worth it: a caller does not need the edge, it needs to know whether the build it
has is on a plateau, and `stabilityFrom` answers that directly for the build in hand.

**Do not read this table as the answer for every rotation.** It is one solo rotation; a
four-character team has four bursts with four thresholds, so its plateaus will be narrower and
more numerous. The method transfers; the numbers do not.

## 4. OQ-G3 — where recipes live

| | size |
|---|---|
| the `sample()` payload | 1.3 MB |
| the `calc`+`damage` events kept | 234–600 KB |
| **the parsed recipe** | **30–70 KB** (94–221 hits) |

**Recommendation: cache client-side first, and do not add a server surface yet.**

- A recipe costs **~3.2 s** to regenerate, in the browser, where it is already produced.
- 30–70 KB is comfortable for browser storage; the 1.3 MB sample never needs keeping.
- A server cache means an API, tenancy, invalidation on re-pin, and a second copy of something
  derivable — for a saving of 3.2 s.

`sim_runs` stays what it is: **a corpus of gcsim runs**, keyed by `context_key` + `er_bucket`.
A recipe is a *derivative* of a run, and storing derivatives beside sources is how the two
drift. Revisit if recipes need to be shared between a user's devices, which is a product
question rather than a performance one.
