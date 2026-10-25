# TASKS — Artifacts follow-ups

*Design: `docs/DESIGN_artifacts_followups.md`. Log: `docs/LOG_mistilteinn.md`. Order: F1 → F4
→ F2 → F3, one PR per part. Each PR is gated by `cd backend && python -m scripts.ci_local` on
its exact head.*

**Status: F1 built and verified, PR pending. F2–F4 planned. Owner rulings OQ-F1–F4 have recommended defaults
(DESIGN §5).**

---

## F1 — one build-state setup (`refactor/ranking-setup`)

### F1.0 Branch — **done**
`refactor/ranking-setup` off `dev` @ `bbb04af`.

### F1.1 Characterisation spec — before any refactor — **done**
- **Files:** new `frontend/src/app/pages/artifacts/artifact-ranking.service.spec.ts`.
- Stub `OptimizeService` (`inventory`, `artifactSets`), `ArtifactsService.list` and
  `RecipeOptimizeService.calibrateAll`. Use synthetic recipes from `sim/upgrade-fixtures.ts`.
  The fixture is a five-piece worn build with a 4-piece set, plus a few unworn pieces.
- Pin `rank` (baseline and per-row deltas), `outcomesFor` (distribution summary), `upgradeEstimate`
  (per-slot `pBeat`, median) and `deepDive` (`before`, `after`, `gain`) to values printed from the
  current code.
- **Accept:** green on the unrefactored code.

### F1.2 The refusal spec — red first — **done**
- Same file. The worn set's recipe is missing from the stub's `byFourPieceSet`. All of `rank`,
  `outcomesFor`, `upgradeEstimate`, `deepDive` and `sweepBestBuilds` must reject with one
  message naming the set.
- Cheap refusals: a missing `fresh_drop` (Upgrade) and an unknown artifact id (outcomes, dive)
  reject **without** calling `calibrateAll`.
- **Accept:** failing on the old code for `outcomesFor`, `deepDive` and `sweepBestBuilds` only.
  Record that in the log.
- **As built:** five failed on the old code. `upgradeEstimate` refused with a different message,
  and `deepDive` calibrated before refusing an unknown id. The red tests were committed with the
  fix, not before it, so every commit stays buildable.

### F1.3 `buildState` and the four migrations — **done**
- **Files:** `artifact-ranking.service.ts`.
- Add `buildState(request, { check, shouldCancel })` per DESIGN §1.3. Migrate `rank`,
  `upgradeEstimate`, `outcomesFor` and `diveContext`. `diveContext` keeps only `all`.
- Keep every caller-specific comment that explains a decision. Move the shared ones onto
  `buildState`.
- **Accept:** F1.1 unchanged and green. F1.2 green. `npm run verify` green. The service file is
  shorter.

### F1.4 Planted faults — **done**
- Each of these must be caught by the spec:
  - remove refusal step 4;
  - restore `?? noFourPiece` inside `buildState`;
  - evaluate the baseline under `noFourPiece`;
  - drop the `check` callback call.
- **Accept:** 4/4 caught, recorded in the log.

### F1.5 Drive and gate — **driven: identical on `dev` and the branch**; gate pending
- Drive Rank, an outcome card, Optimal build and Upgrade on the owner's Skirk build. Compare
  against the same views on `dev`.
- `ci_local`, then PR, merge and deploy confirmation.
- **Accept:** same figures; 26/26 (or the current count) on the PR head; the deploy has landed.

---

## F4 — Strongbox crafts (`feat/upgrade-strongbox`)

### F4.0 Branch
Off `dev` after F1 merges.

### F4.1 Data and backend
- **Files:** `app/data/external/artifact_draw_model.json` (`strongbox` block: `four_line_share`,
  `pieces_per_craft`, `slot_and_main_stat` marked ASSUMED, `excluded_sets` per OQ-F4, each with
  a source), `app/data/external.py` (validated loader, refuses a missing source),
  `app/services/artifact_potential.py`, `app/schemas/artifact.py` (`FreshDropInputs.strongbox`,
  optional).
- Regenerate `frontend/openapi.json` in-process. The diff must be purely additive.
- **Accept:** unit tests for the loader, including the refusal; integration inventory test sees
  the block; `test_openapi_contract_is_current` green.

### F4.2 Share-safe cache
- **Files:** `sim/upgrade-estimate.ts`. Key `cellQuestions` by four-line share, or split it off
  (DESIGN §4.2).
- **Accept:** a spec runs a 0.20 and a 0.34 pass on one `BeatCache`, and each equals its uncached
  result. A planted fault (remove the share from the key) is caught.

### F4.3 The figures
- **Files:** `sim/resin-to-upgrade.ts` (`strongboxToUpgrade`: crafts quantiles, feedstock
  resin; `recyclingRate`: `q_domain + ½ q_box`), specs.
- **Accept:**
  - closed form within the sampler's 99.9% interval at a 0.34 share;
  - recycling within 1% of a literal renewal simulation for q ≤ 0.05;
  - Gladiator's Finale slot: domain unreachable, Strongbox finite.

### F4.4 Service and page
- **Files:** `artifact-ranking.service.ts` (Strongbox pass after the domain pass, reusing the
  cache), `pages/upgrade/*`.
- Add a "Strongbox crafts" column with feedstock, and a recycling toggle, off by default, whose
  label says which figure the table shows.
- **Accept:** page spec; driven at desktop and phone width with no horizontal scroll; console
  clean.

### F4.5 Gate, PR, deploy.

---

## F2 — one picker (`feat/artifacts-shared-picker`)

### F2.0 Branch, and owner rulings OQ-F1/OQ-F2 (or the defaults, stated in the PR).

### F2.1 Context grows
- **Files:** `artifacts-context.service.ts` and its spec.
- Add `teamId`, team-scoped rotations, build choices without a rotation, `readyFor(need)`,
  memory through `remembered.ts`'s existing keys, and memory cleared on account change.
- **Accept:** the spec cases in DESIGN §2.4.

### F2.2 `shared/artifacts-context-bar`
- A standalone component with three comboboxes, using `shared/combobox` and
  `[selected]` per option where a `<select>` remains.
- **Accept:** component spec; accessible names (lint); `npm run check:tokens`.

### F2.3 Rank and Upgrade use the bar
- **Files:** `artifacts.ts/html`, `pages/upgrade/*`.
- **Accept:** existing specs green after updating their stubs.

### F2.4 Optimize uses the bar
- **Files:** `optimize.ts/html`, `optimize.spec.ts`. Delete Optimize's own three signals. An
  `effect` on `context.buildId()` runs the old `selectBuild` body.
- **Accept:**
  - a spec that a new choice clears the previous result fails if the effect is removed;
  - the hit objective works with no rotation;
  - `remembered.spec.ts` is unchanged and green.

### F2.5 Drive, gate, PR, deploy
- Drive: choose, switch tabs, reload, sign out and in, with typed input rather than only `fill()`.

---

## F3 — Reshape, then Elixir (`feat/upgrade-reshape-elixir`)

### F3.0 Branch, and owner rulings OQ-F3/OQ-U4 (or the defaults).

### F3.1 Roll decomposition on the page payload
- Confirm `SubstatAnalysisRead` carries per-line tier multisets, and whether ambiguous lines
  carry weighted alternatives. If they do not, add that to the backend (`substat_rolls`), with
  tests.
- **Accept:** a written finding in the log either way.

### F3.2 Measure Definition's cost
- Bench: best main × 28 pairs × exact enumeration on the owner's recipe, per slot.
- **Accept:** a cost table in `docs/RESEARCH_upgrade_estimator_cost.md`. It decides whether
  F3.5 needs generator steps.

### F3.3 `sim/reshape.ts` plus a literal sampler
- Both mechanisms, initial-value exchangeability, and the 8-draw budget for 3-line-origin
  pieces.
- **Accept:**
  - enumeration inside the sampler interval for both mechanisms;
  - the Miyoushe-script rows (DESIGN §3.2) inside `[floor, resample]`, to within the script's sampling error, for their cases;
  - floor rows match GO's `rollCountProb` values (68.75/25/6.25, 50/31.25/15.6/3.1).

### F3.4 Reshape column, then PR 1 (gate, merge, deploy).

### F3.5 `sim/definition.ts` plus a literal sampler; 4-line share bracketed (0.20 and 0.34).

### F3.6 Elixir column, then PR 2 (gate, merge, deploy).
