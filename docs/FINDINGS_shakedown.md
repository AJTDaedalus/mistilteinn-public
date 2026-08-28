# Findings — running the app end to end against a real account

**Date:** 2026-08-28 · **Inventory:** the owner's GOOD export, 2,370 artifacts ·
**Build:** `dev` @ 068ec59, run locally (`:8001` / `:4201`) against the same code prod serves.

Run locally rather than on prod deliberately: identical code, no credentials in a transcript,
and no risk to a live service. Every number below was **measured**, not estimated; the two
that were estimated first are called out where the measurement moved them.

---

## What works

Recorded first, because a findings list that only lists faults misrepresents the state.

| step | result |
|---|---|
| GOOD import | **2,370 inserted, 0 rejected, 0.478 s** (`source: Irminsul`, `version: 3`) |
| `GET /artifacts/inventory` | **2,370 in 113 ms**, `truncated: false`, `unreadable: []` |
| calibration targets | **S = 35 → 36 calibrations**, live, matching the offline count exactly |
| `POST /rotations/{id}/compile` | 200, gated `while 1` loop as designed |
| `POST /builds/{id}/calibrate` | 200, baseline + probe |
| both emitted configs in gcsim | **216 landed hits each** — the live emitter's output runs |
| recipe parse | 216 hits, 10 distinct sources, 0 unresolved conversions, no stale terms |
| search correctness | ranks correctly on a small inventory; Pareto layer lossless |

The chain from *GOOD file* to *scored build* is connected end to end and each link is right.
What follows is about one link being the wrong **size**.

---

## F1 — The recipe search does not terminate at real inventory scale — **blocking**

2,370 artifacts, one live recipe (Skirk + Azurelight, 7 live quantities):

```
per slot          430 x 462 x 547 x 472 x 459
naive                                 2.354e+13 combinations
pareto (13 ms)    130 x 103 x 136 x 159 x 147   removed 1,695 of 2,370
after pareto                          4.256e+10 combinations
```

Measured throughput, timed on slices of the real buckets: **14.6 µs/combination**
(7,776 combos → 130 ms; 100,000 → 1,458 ms).

> **4.256e10 × 14.6 µs = 7.2 days.**

I had earlier carried 2.6 µs/combo as a working figure. It is **5.6× optimistic** — the
recipe replay does more per combination than the kernel it was extrapolated from. The honest
number is 14.6 µs, and it is what every estimate below uses.

### Root cause — a premise that was true of a different search

`sim/search.ts:17`:

> *"Budget-K is deliberately **not** here. It exists in the Python optimizer because a server
> is slow; **DESIGN §2 expects the GPU to search exhaustively**, so a lossy layer would give up
> exactness to save time that is not being spent."*

That reasoning is correct **for the kernel path it was written about**. `recipe-search.ts`
then reused the same structure — same `bucketBySlot`, same `paretoFilter`, same unbounded
`walk`, same hardcoded `isExact: true` — but it replays gcsim's arithmetic **on the CPU in
JavaScript**. The premise "time that is not being spent" does not survive the move off the
GPU, and nothing re-examined it when the code was reused.

This is not a bug in either search. It is a decision inherited across a boundary where its
justification stopped holding.

---

## F2 — There is no way to filter to a 4-piece set — **blocking, and the cheapest fix**

`optimize.html` contains no set control of any kind. Yet pinning the 4-piece set is what makes
the problem tractable, by three orders of magnitude:

| scope | combinations | time @ 14.6 µs |
|---|---|---|
| unfiltered | 4.256e+10 | **7.2 days** |
| pinned to one set — worst (15003) | 3.11e+6 | **45 s** |
| pinned to one set — median (15045) | 8.15e+4 | **1.2 s** |
| **every one of the 35 pinnable sets, exhaustively** | 1.094e+7 | **2.7 min** |

The last row is the striking one: searching *all thirty-five* 4-piece sets to exhaustion costs
**2.7 minutes** — comparable to the calibration that precedes it, and already the shape of a
job with a progress bar rather than a request that blocks.

### The part a set filter does **not** solve

Those 1.094e7 combinations are every build that **has** a 4-piece. The other **99.97%** of the
space is builds with no 4-piece — 2+2+1 and scattered. A user pinning "no 4-piece set" is back
to 4.26e10. So the filter alone is not sufficient, which is what makes F3 an independent fix
rather than an optimisation of the same one.

---

## F3 — Nothing excludes an artifact that cannot improve the build in any configuration

The Pareto layer is the only prune, and in 7 dimensions it is weak: it removed **1,695 of
2,370 (28.5%)**, leaving 675. That is not a defect — the layer is exactly as lossless as it
claims — but with seven live quantities, one extra point of a near-dead stat makes two pieces
incomparable, so incomparability dominates and the layer cannot carry the search on its own.
`search.ts:93` already says this about `artifact_prefilter`; the measurement confirms it at
scale.

What is missing is an **admissible upper bound**: at each depth of the walk, complete the
partial combination optimistically (per remaining slot, the maximum of each live quantity
still available), score that, and prune the whole subtree when it cannot beat the current
top-N threshold. This is exact — it can only discard combinations provably unable to win —
so `isExact` stays honestly `true`, and it is the standard technique for this search.

Note the two fixes compose rather than compete: the bound prunes hardest exactly where the set
filter helps least, because a no-4-piece search has the loosest set constraints and therefore
the widest gap between the optimistic completion and the real one.

---

## F4 — The "Not exact" warning is unreachable today

`optimize.html:108-114` renders:

> *"top 10 of a pruned subset, shown without saying so, is a confident answer to a…"*
> **"Not exact** — pruning bounded this search, so a better set may exist."*

Both searches hardcode `isExact: true`, so this branch cannot render. It is dead UI **and it
is precisely the affordance F3's bound would need** — so it should be wired up when the bound
lands, not deleted. Worth stating plainly: an exact branch-and-bound would keep `isExact:
true`, and this warning stays dark. It earns its keep only if a genuinely lossy layer is ever
added.

---

## F5 — A new account cannot get in without database access

`POST /auth/register` returns `{"status": "pending"}` and login then returns **403 pending**.
There is no self-serve approval path and no admin endpoint I could find. Getting in required:

```sql
update users set status = 'approved', approved_at = now() where email = '...';
```

For a single-owner deployment this may well be the intent — but it is undocumented, and
`docs/DEPLOY.md` does not mention that a freshly deployed instance has no way to admit its
first user. At minimum that belongs in the runbook; a `scripts/approve_user.py` would be
better than a hand-written `UPDATE` against prod.

---

## F6 — The rotation model cannot express a real config

The owner supplied a working 4-character Skirk / Furina / Yelan / Escoffier gcsim config. The
authoring surface cannot represent it. Missing:

- `+params` on an action (`skirk skill +hitlag=...`)
- `for` loops
- `energy every ...`
- custom target params
- `swap_delay` (the config sets 12; we deliberately never emit it — see the `swap_delay=0`
  note in the root `CLAUDE.md`, which is a *different* problem with the same field)

The owner's ruling stands that **rotations are authored, never optimised** — this is not an
argument against that. It is that the thing a user authors elsewhere cannot be brought here,
so the rotation surface is expressive enough for rotations we compose and not for rotations
that already exist.

---

## F7 — Every compiled step is `.ready`-gated, including `attack` and `dash`

```
if .skirk.attack.ready { skirk attack:5; }
if .skirk.dash.ready { skirk dash; }
```

The gate is **load-bearing on burst and skill** and must stay — an ungated action deadlocks
`while 1`, which is the silent failure the compiler exists to prevent. But normal attacks and
dash are effectively always ready, so the gate is noise there, and it makes the emitted config
read unlike anything a person would write. Low severity; worth a look only because the
compiled output is something users read when a rotation misbehaves.

---

## F8 — Unknown query parameters are silently ignored

`GET /characters?search=Skirk` returns an **unfiltered first page**, 200. The parameter is
`?name=`. FastAPI ignores unrecognised query params by default, so a typo in a filter reads as
"no matches for that filter" rather than "that filter does not exist" — during this run it
led me to build Skirk against *Aino + The Catch* before I noticed.

My mistake, not a defect. But it is the kind of mistake the API could refuse to accept, and
a user hand-driving the API will make it too.

---

## Suggested order

1. **F2** — the 4-piece set filter. Largest win per unit of work; makes the common case 1–45 s.
2. **F3** — the branch-and-bound upper bound. Makes the no-4-piece case tractable and is the
   half a filter cannot cover. Exact, so no honesty cost.
3. **F5** — a user-approval script and a line in the runbook.
4. **F6** — expand the rotation grammar, or state in the UI what it cannot express.
5. **F4**, **F7**, **F8** — small, and none of them block a user.

F1 is not in this list because it is not a separate fix: it is what F2 and F3 together resolve.

---

# Update — what implementing F2 and F3 found

Written after the fixes landed. Three things changed the picture.

## F9 — the rotation objective had no UI at all — **the most important finding here**

`optimize.ts` has carried `objective`, `rotations`, `rotationId`, `calibrating`, `caveats` and
`runRotation()` since R.9, along with the whole `RecipeOptimizeService`. **No template
referenced any of them.** `grep -rn "runRotation\|objective" --include=*.html src` returned
nothing, and the page's only search button called `run()` — the single-hit search.

So the entire gcsim recipe optimizer — nine tasks, a calibration service, a recipe parser
verified exact to 2e-16, a bounded search — **was unreachable from the application**. Every
measurement in this document was taken by driving it from Node, which is why the gap survived
the shakedown's first pass: the engine answers correctly when you call it, and nothing calls
it.

This reframes F1. The search never terminating at real scale was not costing users anything
yet, because no user could start one.

## F3 — the bound is exact, and does not rescue the no-4-piece state

The bound works, and it is genuinely admissible — verified against the real inventory, a
1,248-combination exhaustive reference against the bounded walk's 446, **identical top 10 and
identical best damage**. Pinning the largest set in the inventory went from ~45 s to **1.8 s**,
with 61,243 subtrees pruned.

**It does not tame the no-4-piece state.** A search of that state alone was still running
after an hour and was killed. The reason is structural: at shallow depths the optimistic
completion takes the maximum of each quantity *independently* across every remaining slot, so
near the root the bound sits far above anything achievable and prunes nothing — while the tree
below it holds 4.26e10 leaves.

So the no-4-piece option ships **off by default**, with the page saying why. Making it
tractable needs the same trick that worked for 4-piece states — enumerate by set
configuration, here the 2+2 pairs — and that is its own chunk, not a tuning of this one.

## F2 — the filter cuts calibration too, which is the larger cost

Worth stating because the first design missed it: a set nobody selected is a set nobody has to
**calibrate**. Calibration is ~6 s per state and dominates a narrow search — 36 states is the
~3.8 minutes R.1 measured. The filter now gates both, so picking three sets is four
calibrations rather than thirty-six.

The baseline is calibrated either way. It is the reference every other recipe is measured
against, and `liveQuantitiesFor` needs it.

## A smaller one, fixed in passing

`CalibrationTarget.label` documents itself as *"for progress a user can read — 'Blizzard
Strayer', not a uuid"*, and it read `set 15003`. The inventory publishes `set_id` and no name;
names come from `/api/v1/artifact-sets`, joined on `nanoka_id` — the catalogue's own `id` is a
uuid and matches nothing in an inventory snapshot.

## F10 — the frontend container cannot start after `--renew-anon-volumes`

Found by trying to confirm the new UI in the running stack rather than only in a local build.
The container was **down**, crash-looping on:

```
Error: EACCES: permission denied, mkdir '/app/.angular/cache/21.2.20/mistilteinn/vite/deps_temp_...'
```

`docker-compose.yml` mounts anonymous volumes at `/app/node_modules` and `/app/.angular`.
Docker seeds a new anonymous volume from the image's copy of that path **and inherits its
ownership** — and when the path does not exist in the image, creates it root-owned. The image
runs as `USER node`. `node_modules` survives only by accident of `npm ci` creating it in the
image as `node`; `.angular` existed nowhere.

So `--renew-anon-volumes` — the exact recovery `frontend/CLAUDE.md` prescribes after a
dependency change — produced a cache directory `ng serve` could not write. Fixed with a
`RUN mkdir -p /app/.angular` after the `USER node` line.

A second, self-inflicted half worth recording: running `npm test` on the **host** regenerates
`src/app/api/api.types.ts` as root through the bind mount, and the container then cannot
overwrite it on its next `prestart`. Anything run on the host against this bind mount wants
`chown 1000:1000` afterwards.

## Still open

- **The no-4-piece state** — needs 2+2 configuration enumeration (above).
- **F5** the first-user approval path, **F6** the rotation grammar, **F7** the `.ready` gates,
  **F8** silently ignored query params. Untouched.
