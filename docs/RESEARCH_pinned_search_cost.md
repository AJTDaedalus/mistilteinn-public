# RESEARCH — what a pinned recipe search costs

**Date:** 2026-09-05. `docs/TASKS_artifact_ranking.md` A.10, answering **OQ-A9**.
**Reproduce:** `cd frontend && node --import ./scripts/ts-resolve.mjs scripts/bench-pinned-search.mjs [inventory.json]`
**Corpus:** the owner's own inventory as `GET /api/v1/artifacts/inventory` serves it — 2,369
pieces. A 245-hit recipe, the length `RESEARCH_gcsim_calibration.md` §2 measures on their real
rotation.

---

## The question

Issue #291 asks for *"the best build with this artifact levelled up"*, which A.11 implements by
**pinning** one slot and searching the other four around it. `DESIGN_artifact_ranking.md` §8.5
recorded the open question: does that stay interactive over a whole inventory?

It had to be measured rather than divided. §7 of the same document records a cost that was
**inferred and wrong by a factor of thirty**, and `bench-search.mjs` states the rule: *"a borrowed
timing is a fabricated measurement."*

## What the space looks like

After the Pareto filter, against the real inventory:

```
130 × 103 × 135 × 149 × 147  =  39,592,957,950 combinations
```

which independently reproduces `FINDINGS_shakedown.md` F2's 4.26e10 for the unrestricted space.
Pinning one slot removes that slot's factor: the pinned space is the product of the other four,
**~3.0e8** with the flower pinned.

## The measurement

Buckets capped per slot so the exhaustive walk finishes, both searches over the same subset:

| per slot | free: evaluated | pinned: evaluated | ratio |
|---:|---:|---:|---:|
| 12 | 1,092 | 196 | 5.6× |
| 20 | 10,244 | 1,608 | 6.4× |
| 28 | **60,465** | **6,114** | **9.9×** |

**The counts are exact and deterministic** — identical on every one of five runs. **The wall times
are not**, and that matters more than it usually would: the free search at 28 per slot measured
6.07 s, 6.10 s, 16.03 s, 6.21 s on an otherwise-busy box. So the ratio above is computed **from
the counts**, and the timings are reported only as an order of magnitude: roughly **1e-4 s per
evaluated combination** for a 245-hit recipe.

Two things worth reading off this rather than assuming:

- **The ratio is not the pinned slot's bucket size.** Raw, pinning 28 candidates down to 1 should
  be 28×; measured it is 9.9×. The bound-pruning layer is *less* effective when a slot is fixed —
  a forced piece weakens the partial-sum bound the walk prunes on — so pinning buys less than the
  arithmetic suggests. That gap is exactly what an inference would have got wrong.
- **`evaluated` is printed for a reason.** The first run of this script gave every synthetic piece
  `setId: 0`, so every combination formed a 4-piece of a set the recipe map had no entry for, and
  the walk evaluated **nothing** — while still reporting a perfectly plausible time. The script
  now exits non-zero rather than timing an empty loop.

## The answer to OQ-A9: **no, not uncapped** — and the first version of this section was wrong

**Measured: an uncapped pinned search over the real inventory does not finish in 300 seconds.**
`--full`, killed by its own timeout at exit 143. Pinning removes one slot's factor and leaves
~3.0e8 combinations, which is further than the branch-and-bound prunes.

### What the first draft of this document claimed, and why it was wrong

It said *"at the shipped 5-second budget a pinned search reaches ~47 candidates per remaining
slot"* — reasoning from `COMBINATION_BUDGET_SECONDS` and `budgetK`. **`searchRecipe` has no
budget layer.** It is exhaustive with branch-and-bound and says so in its own return value:
`isExact: true`, `effectiveK: null`, `prefiltered: 0`. The bound is what makes it tractable, not
a cap. So that paragraph described a mechanism this search does not have, and inferred an
interaction from it.

That is **the same mistake §7 of the DESIGN records** — a cost inferred from a measurement of
something adjacent rather than measured directly — made again, in the document written to avoid
it, two hours later. It was caught by driving the feature: the browser sat in the search for
seven minutes.

### What the deep dive does instead

Trim each slot to its best `DIVE_PER_SLOT` pieces **for this build** — the same single-slot swap
the column already computes, 12 µs a piece, ~28 ms for the whole inventory — and keep the pinned
piece regardless of where it ranks. Both searches run over that pool, and the **free** one
(`bestWithout`, OQ-A10's alternative reading) is the expensive half:

| per slot | free | pinned |
|---:|---:|---:|
| 20 | 0.93 s | 0.11 s |
| **24** | **3.31 s** | **0.21 s** |
| 28 | 5.40 s | 0.33 s |
| 40 | 28.4 s | 1.29 s |

**24 per slot**, so the pair costs ~3.5 s. They share a pool deliberately: `bestWithout` is only
comparable to `after` if both were chosen from the same candidates.

### What that costs in honesty, and how it is paid

The dive is now **the best build in a trimmed pool**, not a proof about the inventory.
`searchRecipe` still reports `isExact: true`, and that claim is true *of the pool* — so trimming
silently would convert it into a claim about the inventory that is false. `DeepDive` therefore
carries `searchedPerSlot` and `inventorySize`, and the panel says which.

**It remains a job with progress, not a blocking request** — `RESEARCH_recipe_cost.md`'s standing
ruling, unchanged.

## What this does not say

- **The trim is a heuristic.** Ranking by single-slot value is not a proof that the best
  five-piece build lives in the top 24 of each slot — a piece that is mediocre alone and
  excellent in a set could fall outside. It is the same shape of compromise `applyBudgetK` makes
  for the single-hit search, and it is stated rather than hidden.
- **Node, not a browser.** `bench-search.mjs`'s argument carries over — this hot loop has no WASM,
  no DOM, and one small allocation per combination — but it is an argument, not a measurement, and
  the figures above should be read as an order of magnitude rather than pasted into a constant.
- **One pin position.** Every measurement pins the flower. A slot with a larger surviving bucket
  would show a larger ratio; the flower's 130 is the smallest of the five, so the numbers here are
  the *conservative* end.
- **Nothing about a whole-inventory sweep of pinned searches.** 2,370 pinned searches at five
  seconds each is three hours, which is why `DESIGN_artifact_ranking.md` §8.1 makes the deep dive
  a deliberate act on one piece and the column the thing that finds candidates for it.
