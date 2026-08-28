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

### [x] R.0 — Branch setup **(gate)**
- **Do:** branch `feat/recipe-surface` off `dev`.
- **Accept:** `git branch --show-current` is not `dev` or `main`.

### [x] R.1 — How many calibrations does a real inventory need? **[Planner]** — **done: S = 35, 36 calibrations, ~3.8 min**
- **Do:** against a real GOOD import, count the sets with **≥4 pieces** — that is `S`, and the
  calibration count is `S + 1` plus any of the 9 conditional-2-piece sets present.
- **Accept:** a number in `docs/LOG_mistilteinn.md`, with the inventory size it came from.
  **OQ-R1.**
- **Count reachable 4-piece sets, not sets with ≥4 pieces.** Four pieces spread across four
  distinct slots yields exactly one combination; four pieces where two share a slot yields
  none. Counting the latter as `S` inflates the calibration budget with states no combination
  can reach.
- **Why first:** the whole design rests on `S + 1` being small. If a real account has 40 sets
  with four pieces, two minutes becomes seven and the interaction changes.

### [x] R.2 — Is a 2-piece bonus really kernel-representable? **[Planner]** — **done**
- **Do:** for a sample of sets, calibrate with and without the set and compare. A difference
  that is a plain stat delta means the kernel already has it.
- **Accept:** the finding recorded, and `DESIGN_recipe_surface.md` §2's table either confirmed
  or corrected. **Do not inherit it** — *having a static prop* is not the same as *having no
  conditional part*, and a tier could carry both.

### [x] R.2a — Find each recipe's minimum ER **[Planner]** — **done** (+30 % measured)
- **Do:** sweep artifact-borne ER and find the lowest value at which burst count reaches the
  calibration's own value with `sd == 0`. That is the recipe's **minimum ER**.
- **Accept:** one number per recipe, carried on it. About ten `sample()` runs, ~30 s.
- **A number, not a dimension.** An earlier draft made this "discover the plateau boundaries"
  and keyed recipes by plateau, multiplying the budget by `P`. **Owner decision: a build below
  the minimum is flagged, not scored against a degraded recipe** — the same principle as
  `DECISIONS.md` (2026-08-25), *rotations are authored, never optimized*. The budget stays
  `S + 1`.

## Phase 1 — calibration

### [x] R.3 — Emit calibration configs — **done** (config emission *and* the endpoint)
- **Do:** an endpoint that emits, for a build and rotation: a calibration config with a chosen
  4-piece set equipped and **an ER the rotation can actually be performed at**, and a **probe**
  config at a perturbed stat.
- **Accept:** the config carries `add set="x" count=4` and `add stats er=<value>`, **and no
  other stat**; it round-trips through `validateConfig`. A build with no rotation is a 422.
- **ER is not zero, and this is the correction.** `DESIGN_gcsim_optimizer.md` §3.1 said
  "zero artifact stats"; ER is an artifact stat, and a zero-ER calibration produced **2 burst
  instances against a real candidate's 3** (`RESEARCH_recipe_risks.md` §1). ER is
  **structural**: baked into the calibration, and a candidate's own ER is used only to check it
  clears the recipe's minimum — **never added as a damage stat**.
- **`_artifact_lines` currently derives both from the equipped artifacts** — the set counts and
  the stat totals come from the same loop. Splitting them is the work.

### [x] R.4 — Calibrate in the browser — **done** (OQ-R2 answered)
- **Do:** run `sample()` for baseline and probe, `parseSample`, `resolveConversions`, cache the
  result client-side (**OQ-R2** for the key and invalidation).
- **Accept:** a calibration survives a page reload; a gcsim pin change invalidates it. **A
  cache that cannot be invalidated is a stale golden fixture with extra steps.**

## Phase 2 — the search

### [x] R.4a — Do not add a bonus the calibration already holds — **done**
- **Do:** when scoring a combination against a recipe calibrated with set X, **omit X's set
  bonuses** from the kernel's stat pools. Other sets in the combination still contribute.
- **Accept:** a test that a 2-piece bonus is applied **exactly once**. Measured: calibrating
  with `Blizzard Strayer` puts `cryo% 0.27` in the recipe against `0.12` without — the 0.15
  difference is its 2-piece, and `searchRecipe` would add it again
  (`RESEARCH_recipe_risks.md` §2).
- **This makes `DESIGN_recipe_surface.md` §2 conditional:** "2-piece bonuses stay kernel stat
  pools" is true only of the sets the calibration does **not** hold.

### [x] R.5 — Select a recipe per 4-piece state — **done**
- **Do:** `searchRecipe` takes a map from 4-piece set id to recipe, plus a fallback for
  combinations reaching no 4-piece.
- **A candidate below the recipe's minimum ER is flagged, not scored.** It cannot perform the
  rotation that was calibrated, and scoring it against a degraded variant would answer a
  question nobody asked. `RESEARCH_recipe_risks.md` §3.
- **Accept:** a combination with 4 pieces of set X scores against X's recipe; one with 2+2
  scores against the fallback. A missing recipe is **reported, never silently substituted** —
  scoring a Blizzard Strayer build against the no-set recipe is exactly the wrong answer this
  chunk exists to stop.

### [x] R.6 — The Pareto layer takes the union **(the risky one)** — **done**
- **Do:** `liveQuantitiesFor` over several recipes returns the **union** of their live sets.
- **Accept:** a test where a quantity live under only one recipe still prevents pruning.
  **Mutate it**: intersecting instead of unioning must be caught.
- **This is the one place a bug produces a wrong answer rather than a slow one.** A piece
  dominated under one recipe may win under another, and pruning it makes a layer that
  advertises itself as lossless silently lossy.

### [x] R.7 — Prove a 4-piece bonus is now visible — **done**
- **Do:** a test that a conditional 4-piece set changes the ranking.
- **Accept:** it **fails against `search`** and passes against `searchRecipe`. **Every 4-piece
  bonus in the game scores as zero today** — 60 of 60; this is the test that says they no
  longer do.
- **This is also where "60 of 60" gets its real size.** That figure counts tiers the kernel
  cannot *see*, not rankings it gets *wrong* — some conditional bonuses are healing, energy or
  shield effects that would contribute nothing to a damage ranking even if modelled. **Report
  how many of the 60 actually move a ranking**, and correct
  `RESEARCH_conditional_sets.md` if the answer is much smaller.

## Phase 3 — the page

### [x] R.8 — Wire the optimize page — **done**
- **Do:** offer the recipe objective, with calibration progress (**OQ-R3**) and the fast tier
  still reachable (**OQ-R4**).
- **Accept:** a user can run a rotation-scored search end to end. Interrupting calibration does
  not lose what is already done.

### [x] R.9 — Surface what the recipe does not know — **done**
- **Do:** show `staleConversions` and `stable` on the result.
- **Accept:** a build with an unresolved conversion says so, and **a build that cannot reach
  the recipe's minimum ER is flagged as unable to perform the rotation** — named, with the ER
  it has and the ER it needs, so the user can add ER or change the rotation. Same rule as
  `isExact` and W.5's separability.
- **The optimizer says which; it does not choose.** Silently ranking a build that cannot burst
  on cue is the optimizer substituting a rotation nobody wrote.
- **Non-negotiable:** the snapshotted-conversion gap is ~21 % on the Noelle/Redhorn fixture.
  **An optimizer confidently wrong in the case it was built to fix is worse than one that says
  it does not know.**

---

## Open questions

~~**OQ-R1** real calibration count~~ **answered in R.1**: `S = 35` against a 2,370-artifact account, so **36 calibrations and ~3.8 minutes**. Filtering by rarity or level barely helps (35 → 28). ·
~~**OQ-R2** cache key and invalidation~~ **answered in R.4**: keyed by gcsim pin, build,
rotation, 4-piece set, ER and seed, in browser storage; a refusal evicts and retries once, and
a cache that fails is a slow search rather than a broken page ·
~~**OQ-R3** what the page shows while calibrating~~ **answered in R.8**: progress per
4-piece state, with the 41 MB wasm load flagged separately because it is the slow first step
and looks like a hang otherwise ·
~~**OQ-R4** which tier is the default~~ **answered in R.8**: the single-hit objective, with
the rotation one a deliberate choice. Both stay reachable — OQ-W4's principle, that deleting a
fast honest answer because a slow better one exists is a downgrade.

## Not in this chunk

- **Resolving snapshotted conversions.** A two-point probe cannot separate a cast-time snapshot
  from a hit-time one. It needs per-ability snapshot grouping — `calc` publishes `src_frame`,
  so the data is there, but it is a chunk of its own. **R.9 surfaces it; nothing here fixes
  it.**
- **Percentage-term conversions** (OQ-G5). `Engulfing Lightning` converts ER into ATK%, and a
  character has base ER regardless, so a non-zero test fires on every recipe.
- **Server-side recipe storage.** `RESEARCH_calibration_cache.md` settled OQ-G3: client-side
  first, because a recipe is 30–70 KB and costs 3.2 s to regenerate where it is produced.
