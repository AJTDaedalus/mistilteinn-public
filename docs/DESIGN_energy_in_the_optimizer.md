# DESIGN: weighing Energy Recharge in the optimizer

**Owner brief, 2026-09-01.** *"Ideal optimize behavior is that it'd weight ER alongside damage
stats. Obviously it doesn't do anything above the threshold where the character can burst on
time, but if they can't, the DPS gain from ER should be evaluated in whether or not the reduced
delay is 'worth' the cost of dropping dps stats for ER."*

## Branch policy

`feat/energy-in-the-optimizer`, sub-branches per chunk. **No direct commits to `dev` or
`main`**; `dev` moves only by reviewed PR. Task 0 of the TASKS file is the branch-setup gate.

## 1. What is wrong today, measured

`CandidateStats` has no ER field. `recipe-search.ts` and `recipe-eval.ts` contain no ER
handling at all. `Calibration`'s docstring states the design:

> ER is structural: baked in here, and a candidate's own ER is compared against the recipe's
> minimum rather than added as a damage stat.

So **an ER sands scores exactly zero improvement** and the search can never choose one. That is
defensible for a character already above threshold and wrong below it.

**The owner's own team, measured against the rotation gcsim's database page publishes:**

| | their build | owner's |
|---|---|---|
| duration | 124.6 s | **191.7 s** |
| Furina `insufficient_energy` | 0 | **67.1 s** |
| Furina artifact ER | 90.6 % | **27.9 %** |

Identical action counts on both runs — 189 attacks, 18 bursts, 6 charges, 53 dashes, 24 skills,
24 swaps. **Same actions, 54 % longer.** The optimizer cannot see any of it.

## 2. The approach is gcsim's, not ours

`pkg/optimization/opt_energy.go` solves this problem already, and the first draft of this
document proposed something worse — modelling `delay(ER)` as a curve and dividing damage by
duration. gcsim does not model the relationship at all. It **measures the requirement**:

1. Run with **`IgnoreBurstEnergy = true`** — the rotation executes as though energy were free,
   giving ideal timing.
2. Record, per character and per iteration, **how much additional ER they needed** to have
   burst on time.
3. Take the **80th percentile** of that distribution.
4. Convert to whole substat rolls, clamped to the roll limit.
5. **Fix ER there, then optimize every other substat.**

Three choices worth carrying, each of which the draft got wrong:

- **A distribution, not a point.** Energy generation varies per iteration; a mean would
  under-serve half the runs and a max would over-invest for all of them.
- **p80 is a stated risk posture**, not an accident — cover four runs in five.
- **Two phases, not joint.** ER is satisfied first and damage optimized after, which sidesteps
  trading them against each other combinatorially.

**`ignore_burst_energy` is a parseable config option** (`pkg/gcs/parser/parseOptions.go:104`),
so the counterfactual run is available to us exactly as it is to gcsim.

## 3. A second finding, unrelated to ER

`opt_damage.go` runs damage optimization under the same flag *"to remove noise from energy"*.
**Our calibration does not.** Every recipe's damage figures therefore carry energy timing folded
into them — which is worth investigating as a possible source of the instability
`meta.unstable` and `staleConversions` exist to report.

## 4. What this replaces

The energy warning shipped in #217 reports **teammates only**, because the calibration strips
the optimized character's own ER to zero, while `energyShortfall` covers only the optimized
character. Two mechanisms for one idea. Measuring the requirement directly collapses them into
one honest number for every character.

## 5. Open questions — the owner's, not the implementation's

| | |
|---|---|
| **OQ-E1** | **Risk posture.** p80 as gcsim uses, or higher? gcsim's own code carries `TODO: is ceil better than round? Maybe round with some kind of bias?`, so even upstream treats it as unsettled. |
| **OQ-E2** | **Two-phase or joint?** gcsim pins ER then optimizes damage. Joint is more correct in principle and much more expensive, and probably agrees nearly always — but "nearly always" is the kind of claim this repo measures rather than asserts. |
