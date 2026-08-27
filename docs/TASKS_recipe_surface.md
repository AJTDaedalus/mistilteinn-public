# TASKS: making the recipe optimizer reachable, and right about sets

**Companion:** `docs/DESIGN_recipe_surface.md` — read §1 (why reachability and correctness are
one job) and §3.1 (the Pareto layer is the risk) before starting.
**Evidence:** `docs/RESEARCH_conditional_sets.md`.
**Predecessor:** `docs/TASKS_gcsim_optimizer.md`, complete.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each: tick it here, append to `docs/LOG_mistilteinn.md`,
**stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

**Standing rules**

- Verify `git branch --show-current` before every commit. **`gh pr merge --delete-branch`
  checks out `dev`** — branch immediately after a merge.
- **Run each gate standalone and check its exit code.** Not chained behind `&&`, not piped
  through `tail`.
- Lint with **CI's own argument list** — copy the `run:` line out of `.github/workflows/test.yml`.
- Prove the negative with `python -m scripts.inject`. **A surviving mutation means the test is
  wrong until proven otherwise** — that held five times in the last chunk, twice for bugs that
  were invisible against a fixture with nothing to find.
- **Never emit `swap_delay=0`**; **check `simulate()`'s return value**, which is a string on
  failure; **take every gcsim key through `gcsim_keys`**.
- **A new fixture must exercise something the existing ones do not**, and `PROVENANCE.md` must
  say what. Two bugs last chunk survived because the first fixture had nothing to find.

---

## Phase 0 — measure before building

### [ ] R.0 — Branch setup **(gate)**
- **Do:** branch `feat/recipe-surface` off `dev`.
- **Accept:** `git branch --show-current` is not `dev` or `main`.

### [ ] R.1 — How many calibrations does a real inventory need? **[Planner]**
- **Do:** against a real GOOD import, count the sets with **≥4 pieces** — that is `S`, and the
  calibration count is `S + 1` plus any of the 9 conditional-2-piece sets present.
- **Accept:** a number in `docs/LOG_mistilteinn.md`, with the inventory size it came from.
  **OQ-R1.**
- **Why first:** the whole design rests on `S + 1` being small. If a real account has 40 sets
  with four pieces, two minutes becomes seven and the interaction changes.

### [ ] R.2 — Is a 2-piece bonus really kernel-representable? **[Planner]**
- **Do:** for a sample of sets, calibrate with and without the set and compare. A difference
  that is a plain stat delta means the kernel already has it.
- **Accept:** the finding recorded, and `DESIGN_recipe_surface.md` §2's table either confirmed
  or corrected. **Do not inherit it** — *having a static prop* is not the same as *having no
  conditional part*, and a tier could carry both.

## Phase 1 — calibration

### [ ] R.3 — Emit calibration configs
- **Do:** an endpoint that emits, for a build and rotation: a **zero-artifact-stat** config with
  a chosen 4-piece set equipped, and a **probe** config at a perturbed stat.
- **Accept:** the emitted config has **no `add stats` line**, carries `add set="x" count=4`,
  and round-trips through `validateConfig`. A build with no rotation is a 422, not a guess.
- **`_artifact_lines` currently derives both from the equipped artifacts** — the set counts and
  the stat totals come from the same loop. Splitting them is the work.

### [ ] R.4 — Calibrate in the browser
- **Do:** run `sample()` for baseline and probe, `parseSample`, `resolveConversions`, cache the
  result client-side (**OQ-R2** for the key and invalidation).
- **Accept:** a calibration survives a page reload; a gcsim pin change invalidates it. **A
  cache that cannot be invalidated is a stale golden fixture with extra steps.**

## Phase 2 — the search

### [ ] R.5 — Select a recipe per 4-piece state
- **Do:** `searchRecipe` takes a map from 4-piece set id to recipe, plus a fallback for
  combinations reaching no 4-piece.
- **Accept:** a combination with 4 pieces of set X scores against X's recipe; one with 2+2
  scores against the fallback. A missing recipe is **reported, never silently substituted** —
  scoring a Blizzard Strayer build against the no-set recipe is exactly the wrong answer this
  chunk exists to stop.

### [ ] R.6 — The Pareto layer takes the union **(the risky one)**
- **Do:** `liveQuantitiesFor` over several recipes returns the **union** of their live sets.
- **Accept:** a test where a quantity live under only one recipe still prevents pruning.
  **Mutate it**: intersecting instead of unioning must be caught.
- **This is the one place a bug produces a wrong answer rather than a slow one.** A piece
  dominated under one recipe may win under another, and pruning it makes a layer that
  advertises itself as lossless silently lossy.

### [ ] R.7 — Prove a 4-piece bonus is now visible
- **Do:** a test that a conditional 4-piece set changes the ranking.
- **Accept:** it **fails against `search`** and passes against `searchRecipe`. 60 of 65 sets
  score their 4-piece as zero today; this is the test that says they no longer do.

## Phase 3 — the page

### [ ] R.8 — Wire the optimize page
- **Do:** offer the recipe objective, with calibration progress (**OQ-R3**) and the fast tier
  still reachable (**OQ-R4**).
- **Accept:** a user can run a rotation-scored search end to end. Interrupting calibration does
  not lose what is already done.

### [ ] R.9 — Surface what the recipe does not know
- **Do:** show `staleConversions` and `stable` on the result.
- **Accept:** a build with an unresolved conversion says so, and a build off an ER plateau says
  **its ranking is not a result**. Same rule as `isExact` and W.5's separability.
- **Non-negotiable:** the snapshotted-conversion gap is ~21 % on the Noelle/Redhorn fixture.
  **An optimizer confidently wrong in the case it was built to fix is worse than one that says
  it does not know.**

---

## Open questions

**OQ-R1** real calibration count (R.1) · **OQ-R2** cache key and invalidation (R.4) ·
**OQ-R3** what the page shows while calibrating (R.8) · **OQ-R4** which tier is the default
(R.8).

## Not in this chunk

- **Resolving snapshotted conversions.** A two-point probe cannot separate a cast-time snapshot
  from a hit-time one. It needs per-ability snapshot grouping — `calc` publishes `src_frame`,
  so the data is there, but it is a chunk of its own. **R.9 surfaces it; nothing here fixes
  it.**
- **Percentage-term conversions** (OQ-G5). `Engulfing Lightning` converts ER into ATK%, and a
  character has base ER regardless, so a non-zero test fires on every recipe.
- **Server-side recipe storage.** `RESEARCH_calibration_cache.md` settled OQ-G3: client-side
  first, because a recipe is 30–70 KB and costs 3.2 s to regenerate where it is produced.
