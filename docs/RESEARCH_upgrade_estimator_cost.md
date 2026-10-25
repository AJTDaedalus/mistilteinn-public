# RESEARCH — what the upgrade estimator's exact pass costs, and whether it is right

**Date:** 2026-10-24. `docs/TASKS_upgrade_estimator.md` Task 1.
**Reproduce:** `cd frontend && node --import ./scripts/ts-resolve.mjs scripts/bench-upgrade-estimate.mjs`

## Why measured

DESIGN §5.1 reasoned that brute force is ~10⁷ evaluations per slot, and that three exact
reductions (dead-stat collapse, branch and bound, binary search on the last line) make it
interactive. That was an inference. `RESEARCH_pinned_search_cost.md` records an inferred cost in
this area that was wrong by orders of magnitude, so this one was measured before the surface
was built on it.

## Method

A 245-hit ATK-scaling Hydro recipe, the size `RESEARCH_gcsim_calibration.md` §2 measures for a
real rotation, built the way `bench-pinned-search.mjs` builds one. Four other pieces of a
plausible crit build, plus a mediocre CRIT DMG circlet. Real 5★ roll ladders, weights and
main-stat tables (`sim/upgrade-fixtures.ts`). θ = 1% (OQ-U1). Two references per slot:

- **as equipped**: beat the build by 1%;
- **strong**: beat it by 1% after a further 15%, standing in for a near-finished slot.

Node, not a browser: the hot loop is plain V8 arithmetic with no WASM and no DOM, the argument
`bench-search.mjs` makes. That makes this an order of magnitude, not a constant.

## Result

| reference | slot | P(beat \| slot drop) | questions | evaluations | exact | ±1 weights | Monte Carlo (40k, 99.9%) |
|---|---|---:|---:|---:|---:|---:|---|
| as equipped | flower | 1.250e-2 | 466 | 74,367 | 827 ms | +72 ms | 1.303e-2 [1.13e-2, 1.50e-2] ✓ |
| as equipped | sands | 1.439e-2 | 2,002 | 6,541 | 115 ms | +309 ms | 1.330e-2 [1.15e-2, 1.53e-2] ✓ |
| as equipped | goblet | 6.135e-3 | 5,264 | 19,785 | 362 ms | +1,013 ms | 6.325e-3 [5.15e-3, 7.77e-3] ✓ |
| as equipped | circlet | 1.482e-1 | 2,278 | 6,113 | 126 ms | +392 ms | 1.476e-1 [1.42e-1, 1.54e-1] ✓ |
| strong | flower | **0** (proved) | 466 | 466 | 14 ms | +55 ms | — |
| strong | sands | 2.359e-11 | 2,002 | 2,030 | 59 ms | +263 ms | — |
| strong | goblet | 4.385e-8 | 5,264 | 9,865 | 244 ms | +1,004 ms | — |
| strong | circlet | 1.621e-4 | 2,278 | 10,833 | 176 ms | +384 ms | — |

**Correctness.** Every case large enough to sample lies inside the literal sampler's 99.9%
interval. That sampler shares no code with the enumeration beyond the tables and the evaluator.
The "strong" probabilities are 10⁻⁴ to 10⁻¹¹. That is exactly the range a Monte Carlo cannot
see and a Gaussian tail would invent, which is the argument for exact enumeration.

**Cost.** A whole build (five slots, plume included) is about 1.5 s exact plus about 2 s for the
±1-weight sensitivity. Evaluations are 10³–10⁵ per slot, not 10⁷: the reductions buy two to
four orders of magnitude.

- **Dead-stat collapse** merges 2,520 goblet cells × 91 roll splits into 5,264 questions.
- **Branch and bound** answers most questions in two evaluations. It **proves** the strong
  flower unreachable in exactly one evaluation per question.
- **Sensitivity** is dominated by re-enumerating draw orders (`freshDropCells`), not by
  evaluation. The answers cache is weight-independent, so the twenty re-weightings evaluate
  nothing new.

## Monotonicity

The bounds rely on damage never falling as a substat rises. That held in a 300-trial randomised
check (`upgrade-estimate.spec.ts`), over every substat including ER. On this recipe ER is dead
(`liveQuantitiesFor` adds it only when the energy ladder varies), so ER's monotonicity under a
varying ladder is checked by construction, not by this fixture. `evaluateRecipe` scales by
`energyRatio`, which is non-decreasing in ER.

## Decision: yield, not a Web Worker

DESIGN §5.4 said to move to a Web Worker if the main-thread cost passed ~200 ms per slot. It
does in total, but the work is **hundreds to thousands of small units** (one cell merged, or one
question answered), so yielding between units bounds how long the thread is held. Measured with
GO's 12 ms budget, the **longest single block is 38 ms** (flower) and 13.5 ms (circlet). The
artifact ranker's distribution pass, which cannot yield inside a four-line piece, blocks for
223 ms.

The app has no worker infrastructure (no `webWorkerTsConfig`, no worker bundle, and specs run
in jsdom), and adding it would cost more than it buys at 38 ms. So
`slotBeatProbabilityAsync` yields and cancels, like `outcomeDistributionAsync`. If a future
recipe makes one question cost hundreds of milliseconds, the worker is the next step, and this
table is what to re-run.

## Mutation check

Five planted faults, each caught by the specs:

- the full-mass bound returns zero;
- a live stat treated as dead;
- the three-liner's roll budget off by one;
- the binary search off by one;
- the set factor ignoring 2-piece bonuses.

`scripts.inject` drives pytest only, so the run used a scratch harness that keeps its
refuse-rather-than-report rule: each target must match exactly once, the file is restored and
compared after each run, and the result is reported only after the restore.
