# DESIGN: the optimizer surface

**Companion:** `docs/TASKS_optimizer.md`
**Tier:** Planner (Opus). Implementation is Worker.
**Follows:** `docs/TASKS_multipliers.md` (complete) — which removed the last blocker.

## Branch policy

Per-task branches off `dev`, named `feat/<task>` or `fix/<task>`, merged to `dev` by PR after
review. **No direct commits to `dev` or `main`.** O.1 and O.2 gate O.3; O.4 needs O.3's
result. Task 0 of `docs/TASKS_optimizer.md` is the branch-setup gate.

---

## 1. What is already built, and why none of it is reachable

`frontend/src/app/sim/` is a working optimizer:

| | |
|---|---|
| `damage.ts` | the chain, verified against the Python oracle to 1e-6 |
| `search.ts` | Pareto prefilter + exhaustive walk, pinned against `artifact_optimizer.optimize` |
| `damage.wgsl` / `gpu.ts` | the same arithmetic on the GPU, gated in CI |

**Nothing imports any of it.** Four CI gates run it as scripts; no page does. That is the "a
library no page calls" shape `app.routes.spec.ts` was written to catch, one level below
routes — the guard checks every *route* is linked, and this is a module with no route at all.

It has been unreachable because `SearchContext` requires a `hit`, and until M.2 nothing could
supply one without a user typing `1.2091`. That is fixed. This chunk is what remains.

## 2. The one thing the browser cannot work out for itself

`search()` takes candidates whose `stats` are keyed by **kernel quantity** — `atk_pct`,
`crit_rate`, `elemental_mastery`. The API returns artifacts keyed by the source's
**`FIGHT_PROP_*`** vocabulary. The translation between them is
`stat_calculator._quantity_for_prop`, and it is backend-private for good reason: it decides
what every stat *means*, and it refuses rather than guessing on a prop it does not know.

**Reimplementing it in TypeScript would be a second definition of that mapping.** This repo's
most frequent finding is "two copies, and the duplicate was the broken one" — and the failure
here is silent: a mis-mapped substat produces a build that is optimal for a stat the character
does not have, presented as the answer.

So the same answer as `/rotations/options`, `/builds/options` and `/artifacts/options`: **the
server publishes what the client needs, and the client does not re-derive it.**

### 2.1 Where each half comes from

- **The inventory** already has a home. `GET /artifacts/inventory` exists *specifically* for
  the client-side search — its docstring answers OQ-S3 with "the browser holds the inventory
  and revalidates it", and it is ETag'd so an unchanged account revalidates for free. It
  should therefore carry **kernel-ready** candidates rather than `ArtifactRead`: id, slot,
  set id, and `stats` already translated. That is *smaller* than what it returns today, and
  it is what its only intended consumer needs.
- **Everything else** is per-build and per-hit, so it is a second endpoint:
  `POST /builds/{id}/search-context`. Base contributions from `build_assembler`, set bonuses
  from the same, the target, the character level, the damage-bonus quantity, and **the hit
  resolved from a named talent** (M.2).

Both are the server's existing computations, published rather than reimplemented.

## 3. What the page does with them

Pick a build, pick a hit, run the search **in the browser**, show the top N.

Then — and this is the part that makes it checkable — **explain the winner.**
`POST /builds/{id}/explain` already accepts `artifact_ids`, so the winning five can be handed
straight back for a full derivation. A ranking whose winner cannot be explained is a ranking
nobody can verify, which is why M.3 came first.

### 3.1 The search runs client-side, and that was decided

`RESEARCH_gcsim_embed.md` §6 and the client-optimizer plan settled this: gcsim is ~430×
too slow to be an inner loop, the Chunk F chain stays, and the search runs in the browser so a
user's inventory is searched on their own machine. Nothing here reopens it.

### 3.2 What the result must not claim

`SearchResult.isExact` says whether the answer is the true optimum **over the inventory as
given**. The page must show it. A top-10 list that is actually the top 10 of a pruned subset,
presented without saying so, is the "confident number computed for something else" failure at
the scale of a whole feature.

Likewise `paretoRemoved` and `evaluated`: a search that considered 40 combinations and one
that considered 4 million look identical when only the winner is shown.

## 4. Testing strategy

| task | what proves it |
|---|---|
| O.1 | the context matches what `/explain` computes for the same build and hit — *the same server, asked twice, must not disagree with itself* |
| O.2 | every artifact's translated stats round-trip against `_quantity_for_prop`; a prop it refuses is reported, not silently dropped |
| O.3 | the page runs the real kernel over a known inventory and picks the known winner; `isExact` and the counts are displayed |
| O.4 | the explained winner's damage equals the search's damage for that combination |

O.4 is the one worth naming. **Two implementations of the chain now meet on one screen** —
the browser kernel's f32 arithmetic and the backend's f64 — and C.2 measured their divergence
at up to 3.4e-07. The test asserts agreement *within that tolerance*, and a mismatch outside
it is a real disagreement rather than a rounding artefact.

## 5. Non-goals

- **No rotation optimization.** Still `DESIGN_rotation.md` §3.5's open question, and you asked
  for a design pass on it as its own piece of work.
- **No constraint editing** — minimum ER, forced sets, locked slots. `OptimizerConstraints`
  exists server-side and the kernel does not take them yet; adding a UI for constraints the
  kernel ignores would be worse than not having one.
- **No GPU path in the page.** `gpu.ts` is gated in CI and needs a WebGPU adapter; the CPU
  search is fast enough for one build and the fallback question is its own task.
- **No saving a search result.** The run corpus keys *simulations*, not searches.

## 6. Open questions

- **OQ-O1 — does the inventory snapshot keep returning `ArtifactRead`?** *Answered: no.* Its
  documented purpose is the client-side search, nothing consumes it yet, and kernel-ready
  candidates are both smaller and the thing its consumer needs. `GET /artifacts` remains the
  UI list.
- **OQ-O2 — what happens when an artifact carries a prop the mapping refuses?** *Answered:
  reported, never dropped.* A silently omitted piece is an inventory the user cannot see is
  incomplete, and a search over it recommends the best of what it was shown while looking like
  the best of what they own. The snapshot already carries `truncated` for the analogous case.
- **OQ-O3 — how many results?** *Answered: the kernel's `topN`, defaulting to 10.* Not one:
  a single answer hides how close the runner-up was, and near-ties are exactly where f32
  ordering is least trustworthy.
