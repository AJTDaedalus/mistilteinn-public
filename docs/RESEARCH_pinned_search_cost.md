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

## The answer to OQ-A9: yes, and it is *better* than the free search, not merely cheaper

The page already ships a `COMBINATION_BUDGET_SECONDS = 5` walk, and `budgetK` trims buckets to fit
it. At ~1e-4 s per combination that budget buys about **50,000 evaluated combinations**.

The pinned walk scales cleanly as the fourth power of the bucket size — 20 → 28 is 1.4× per slot
and 1,608 → 6,114 is 3.8×, against 1.4⁴ = 3.84 — so 50,000 combinations is reached at roughly
**47 candidates per remaining slot**, against the free search's ~28 for the same money.

**So pinning does not make the search faster; it makes it deeper at the same budget.** That is the
useful framing for A.12: the deep dive is not a slower version of the optimizer, it is the same
five-second job asking a narrower question and therefore answering it better.

**It is still a job with progress, not a blocking request.** Five seconds is well past the
threshold where a frozen button is a bug, and `RESEARCH_recipe_cost.md`'s standing ruling —
*"a job with progress, never a request that blocks"* — applies unchanged.

## What this does not say

- **Node, not a browser.** `bench-search.mjs`'s argument carries over — this hot loop has no WASM,
  no DOM, and one small allocation per combination — but it is an argument, not a measurement, and
  the figures above should be read as an order of magnitude rather than pasted into a constant.
- **One pin position.** Every measurement pins the flower. A slot with a larger surviving bucket
  would show a larger ratio; the flower's 130 is the smallest of the five, so the numbers here are
  the *conservative* end.
- **Nothing about a whole-inventory sweep of pinned searches.** 2,370 pinned searches at five
  seconds each is three hours, which is why `DESIGN_artifact_ranking.md` §8.1 makes the deep dive
  a deliberate act on one piece and the column the thing that finds candidates for it.
