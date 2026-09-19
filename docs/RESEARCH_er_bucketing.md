# Is a 5% ER bucket safe? — measured, at the pin

**Date:** 2026-08-22 · **gcsim:** `3647a07a7cc3004bc1e79d9bb5f7444de20dceaa` (the one pin,
`docs/CROSSVAL_gcsim.md`) · **Data:** `backend/tests/fixtures/er_sweep/ayaka_er_sweep.json`

`DESIGN_client_optimizer.md` §3 states the assumption the whole retrieval layer rests on:

> **The load-bearing assumption** is that context is far less sensitive to marginal stat
> changes than damage is. That is plausible and it is not proven.

§3.5 then buckets energy recharge in whole 5% steps, because ER is the one artifact-borne
stat that changes *whether the rotation happens* rather than how hard it hits. D.2 is where
the retrieval layer is supposed to measure its own error, so the assumption was measured
before anything was built on it.

## Method

One character, one rotation, one target. **Only `er` varies** — 54 runs, one per whole ER
percent from 100 % to 153 %, 50 iterations each:

```
options iteration=50 duration=90 swap_delay=0;
energy every interval=300,600 amount=1;

kamisatoayaka char lvl=90/90 cons=0 talent=9,9,9;
kamisatoayaka add weapon="mistsplitterreforged" lvl=90/90 refine=1;
kamisatoayaka add set="blizzardstrayer" count=4;
kamisatoayaka add stats atk%=0.464 cd=0.62 er=<swept>;

target lvl=90 resist=0.1 pos=0,1;

active kamisatoayaka;
while 1 {
    if .kamisatoayaka.energy >= 80 { kamisatoayaka burst; }
    kamisatoayaka skill;
    kamisatoayaka attack:2;
}
```

Two details that took a wrong answer each to find, and that anyone re-running this needs:

- **A bare action list runs once.** `duration=90` with a flat list gave 1 burst, 1 skill and
  3 attacks over ninety seconds, and an ER sweep over it would have been 54 identical runs.
  It needs `while 1 { … }`.
- **`while 1` alone deadlocks.** gcsim *waits* for an unavailable action, so an ungated
  `burst` at the top of the loop waits for energy it can no longer generate. Still exactly
  one of everything. The `if .kamisatoayaka.energy >= 80` gate and `energy every` are what
  make the rotation actually execute.

## Result 1 — most of "context" is not ER-sensitive at all

| quantity | 100 % ER | 153 % ER |
|---|---|---|
| skill casts | 9.00 | 9.00 |
| attack casts | 18.0 | 18.0 |
| cryo aura uptime | 98.07 % | 98.07 % |

Identical to every digit gcsim prints, across a 53-point ER range. **For these, the §3
assumption does not merely hold — they are exactly invariant**, and retrieving them from a
neighbouring bucket costs nothing whatever.

## Result 2 — burst count is a step, not a slope

Burst casts sit flat at **2.00** from 100–115 %, climb steeply from **2.16 → 3.00** between
120 % and 137 %, and are flat at **3.00** from 137 % up. The ER coupling is real and it is
**concentrated in a narrow transition band**, not spread evenly.

## Result 3 — so bucket error is not uniform, and the fixed 5 % width does not survive

Spread of DPS *within* each 5 % bucket, against the Monte Carlo standard error of the runs
making it up:

| bucket | DPS spread | % | max se | ×se | burst range |
|---:|---:|---:|---:|---:|---|
| 100 | 77.5 | 3.9 % | 24.6 | 3.2 | 2.00–2.00 |
| 105 | 56.6 | 2.9 % | 23.7 | 2.4 | 2.00–2.00 |
| 110 | 39.6 | 2.0 % | 30.2 | 1.3 | 2.00–2.04 |
| 115 | 46.8 | 2.3 % | 37.2 | 1.3 | 2.02–2.14 |
| **120** | **279.1** | **13.3 %** | 47.6 | **5.9** | 2.16–2.60 |
| 125 | 133.6 | 5.8 % | 47.0 | 2.8 | 2.52–2.78 |
| 130 | 100.6 | 4.0 % | 39.1 | 2.6 | 2.88–2.98 |
| 135 | 63.7 | 2.5 % | 38.1 | 1.7 | 2.94–3.00 |
| 140 | 59.6 | 2.4 % | 28.6 | 2.1 | 3.00–3.00 |
| 145 | 85.1 | 3.4 % | 25.4 | 3.4 | 3.00–3.00 |
| 150 | 36.0 | 1.4 % | 28.3 | 1.3 | 3.00–3.00 |

> **Correction, 2026-09-19.** Every figure in this section was measured at **50
> iterations**, where a bucket's width is mostly noise about which runs land a third burst.
> Re-measured at 1,000 iterations during the v2.47.2 re-pin, the widest bucket is still
> **120** and its width is **7.3 %**, not 13.3 %; the settled top end is 0.3 %. The
> conclusion below holds — the buckets differ by an order of magnitude and a single constant
> error is indefensible — but the specific percentages here are an overestimate, and
> re-running the sweep at this doc's own pin reproduced neither the number nor the bucket.
> `backend/tests/fixtures/er_sweep/PROVENANCE.md` has the detail.

**Bucket 120 is 13.3 % wide in DPS** — the bucket straddling the steepest part of the climb.
Buckets away from the transition are at or near the noise floor.

A single global error figure would therefore be **wrong in both directions**: complacent at
120 %, alarmist at 145 %. This is the evidence for §3's actual instruction — *"a score built
on retrieved context ships with the measured error for its neighbourhood"* — being about a
**neighbourhood**, not a constant.

## Result 4 — and my own significance test misfired, which is the fourth finding

Bucket 145 is flagged `REAL` at 3.4× the standard error while burst count is **flat at 3.00**
across the whole bucket. With no context change there is nothing for a real divergence to
come from, so the flag is a false positive: the standard error is an underestimate here.

The reason is that DPS is not normally distributed in this experiment. Burst casts are
**discrete**, so the per-iteration DPS distribution is multi-modal — a mixture of "2 bursts
happened" and "3 bursts happened" — and `sd/√n` understates the spread of a mixture.

So the retrieval layer **must not adjudicate with a threshold**. It reports the divergence
*and* the noise floor and shows both, rather than pronouncing "significant" using a test that
produced a false positive on the first dataset it was applied to.

## What this means for D.2

1. **An exact bucket hit is not an exact answer.** A build sits *somewhere inside* its
   bucket, and the bucket was simulated at one point in it. Inside bucket 120 that point is
   worth ±13 %. Retrieval reports a divergence even for a distance-0 match.
2. **The error is measured from the corpus itself**, by comparing adjacent cached buckets —
   no extra simulation, and it is automatically per-context rather than a constant read off
   this one character.
3. **A divergence smaller than the runs' own noise is not a divergence**, and both numbers
   are reported rather than one verdict.
4. **The 5 % width is a starting point, not a guarantee.** Nothing here justifies changing it
   yet — one character, one rotation — but it does justify refusing to treat it as safe by
   construction.

## What this does not show

One character, one rotation, one weapon, one target, 50 iterations. It is enough to falsify
"5 % is uniformly safe" — one counterexample does that — and **not** enough to characterise
how wide the transition band is in general, or where it sits for a character with particles
from a teammate. Anything stated about *other* contexts must be measured in that context,
which is the point of computing divergence from the corpus rather than from this table.
