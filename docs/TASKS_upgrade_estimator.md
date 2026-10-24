# TASKS: the upgrade estimator

**Companion:** `docs/DESIGN_upgrade_estimator.md`. Read §1 (what already exists), §4 (the closed
form) and §5 (the hard part) first. **Evidence:** `docs/RESEARCH_artifact_drop_model.md`.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each one: tick it here, append to `docs/LOG_mistilteinn.md`,
then **stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

> **Status: draft, 2026-10-24. Nothing started.** OQ-U1/U2/U5 answered (DESIGN §9.1): θ = 1%,
> no levelling cost, standard domains only. Phase 3's location waits on DESIGN §11 (tabbed
> `/optimize`). Task 1 is a measurement whose
> result can change §5. If it does, the DESIGN is amended before Task 4 starts.

**Branch policy.** `feat/upgrade-estimator`, off `dev`. **No direct commits to `dev`.** Task 0 is
the gate. **One PR per phase**, three PRs in total (`space-prs-further-apart`).

## Standing rules

- Verify `git branch --show-current` before every commit.
- **`cd backend && python -m scripts.ci_local` exits 0 over every job, on the exact PR head,
  before any merge.**
- **Do not write a drop rate, line-count share, weight or tier from memory.** Every one comes
  from `RESEARCH_artifact_drop_model.md` with its § and source carried into the data file.
- `npm run verify` is the typecheck; `npm test` is `ng test`. `npm run check:tokens` after any
  stylesheet change.
- **Drive the feature.** Take a screenshot, and check one slot's `q` by hand against the Monte
  Carlo script on a real build.

---

# Phase 1 — data and the measurement

### [ ] 0 — Branch setup **(gate)**
- **Do:** rename `docs/upgrade-estimator` to `feat/upgrade-estimator` and rebase it on an
  up-to-date `dev`.
- **Accept:** `git branch --show-current` is `feat/upgrade-estimator`; the RESEARCH and DESIGN
  commits are on it; `git status --porcelain` is clean.

### [ ] 1 — **[Planner]** Measure the exact pass's cost, and test monotonicity
- **Why:** DESIGN §5.1 reasons that brute force is ~10⁷ evaluations and that three reductions
  make it interactive. That is an inference, and `RESEARCH_pinned_search_cost.md` is this repo's
  record of an inferred cost being wrong by orders of magnitude.
- **Do:** a throwaway spec or script (not shipped) over the owner's real build and calibrated
  recipe (`reproduce-from-the-owners-own-data`). Four parts:
  1. Check monotonicity of `scoreForSlot` in each substat across a grid, ER included.
  2. Count cells surviving branch-and-bound for each slot × main stat, against the current piece
     and against a deliberately weak one.
  3. Count evaluations with and without dead-stat collapse and the frontier walk.
  4. Time it.
- **Accept:** `docs/RESEARCH_upgrade_estimator_cost.md` with a table of
  slot × main × {cells, evaluations, ms}, the monotonicity result per stat, and a verdict:
  main thread, Web Worker, or "exact is not affordable, re-plan §5". Commit the measurement
  command, not just the numbers.
- **Escalate if:** any stat is non-monotone, or the worst slot exceeds ~2 s in a worker.

### [ ] 2 — Extend the draw model with drop counts and line shares
- **Files:** `backend/app/data/external/artifact_draw_model.json`, `app/data/external.py`, its
  schema, unit tests.
- **Do:** add the following, each with the R§ and URL beside it:
  - `five_star_per_run: 1.065`, with the `N₅ = 1 + Bernoulli` shape marked `assumed: true`;
  - `four_line_share: {domain: 0.20}` — domain only in v1; other sources arrive with the
    Strongbox follow-up;
  - the daily resin regeneration constant, cited.

  Resin per run is **read from `planner_economy.json`**, not restated.
- **Accept:** the loader refuses a missing or out-of-range share. A test asserts every new entry
  carries a source. `DrawModel` in `api.types.ts` carries the new fields after
  `npm run codegen`, and the openapi diff is **purely additive**
  (`duplicate-pydantic-names-rename-both`).

### [ ] 3 — Domain → sets in the yuanshen snapshot
- **Files:** `scripts/yuanshen/build_snapshot.py`, a new
  `snapshot/artifact_domains.json`, `app/data/snapshot.py`, tests.
- **Do:** derive each artifact domain's two 5★ sets from `DungeonExcelConfigData` +
  `RewardPreviewExcelConfigData` at the pinned commit. Take **membership only**, never counts
  (DESIGN §6, the planner's two-roll trap). Join set ids to the catalogue by game id, not by
  row id (`CLAUDE.md`: the KQM snapshot's 0-of-205 failure).
- **Accept:**
  - every domain has exactly two sets, or the build refuses;
  - every set id resolves against the seeded `artifact_sets`;
  - hand-read anchors for three domains, one of them the newest (7.0, Inverted Glacier,
    R§1.5);
  - an endpoint or field exposing the map, with an additive openapi diff.

*PR 1 here: data only, backend only.*

---

# Phase 2 — the math, client-side, with its oracle

### [ ] 4 — The fresh-drop prior
- **Files:** `frontend/src/app/sim/fresh-drop.ts` + spec.
- **Do:** enumerate (main, unordered 4-subset) cells with exact weights from `lineOutcomes`, plus
  the two roll budgets (DESIGN §3: 4-line → `1 + Multinomial(5, ¼)`, 3-line →
  `1 + Multinomial(4, ¼)`).
- **Accept:**
  - cell weights sum to 1 per slot (to 1e-12);
  - the subset marginals match `artifact_draw_model`'s main/sub tables;
  - **one cell's weight is checked by hand** in the spec comment;
  - a crossvalidation fixture against GO's `freshArtifact` (DESIGN §3), with numbers captured from
    GO at a pinned commit, matches to 1e-9.

### [ ] 5 — The literal Monte Carlo oracle
- **Files:** `frontend/src/app/sim/fresh-drop-sampler.ts` (test-only, never imported by a page) +
  spec.
- **Do:** generate an artifact the way the game does (R§§2–4, one line at a time, upgrade by
  upgrade) with a seeded RNG, and score it with the injected evaluator. Share **no code** with
  Task 4 except the data file and the evaluator.
- **Accept:** on a toy linear evaluator where `P(beat)` has a closed form, the sampler's estimate
  falls inside its 99.9% binomial interval.

### [ ] 6 — **[Planner]** `P(beat | slot, main)`: exact with the three reductions, plus the Gaussian fast pass
- **Files:** `frontend/src/app/sim/upgrade-estimate.ts` + spec. A worker wrapper only if Task 1
  said so.
- **Do:** per DESIGN §5.2:
  - branch-and-bound per cell, dead-stat collapse and the monotone frontier;
  - the existing `estimateOutcome` delta method, lifted to a cell mixture, as the fast pass;
  - a sensitivity pass that perturbs each weight ±1 and reports the spread of `q` (DESIGN §10).
- **Accept:**
  - **exact `q` lies inside the Task 5 sampler's 99.9% interval** on three real-recipe fixtures
    with `q ≥ 10⁻²`;
  - `q = 0` is returned, and proved by the bound, for a hand-built piece no drop can beat;
  - `scripts.inject` with one mutation per reduction (prune direction flipped, a dead stat that
    is not dead, an off-by-one budget) exits **0** for each, so each mutation is caught;
  - Task 1's time budget holds.

### [ ] 7 — Per drop → resin
- **Files:** `frontend/src/app/sim/resin-to-upgrade.ts` + spec.
- **Do:** implement DESIGN §4:
  - `q(s, D)` with set admissibility (§3.1), `r` from `N₅`, then the geometric quantiles, mean
    and PMF, in resin and days, with θ defaulting to 1%;
  - `q_any(D)` across slots.
  - **No Strongbox, no Stygian Onslaught** (DESIGN §9.1).
- **Accept:**
  - the quantile formula matches a brute-force cumulative sum;
  - `q = 0` yields "unreachable", never `Infinity` or `NaN` (`a-default-change-can-neuter-tests`:
    give the test a non-zero baseline too);
  - admissibility is tested for 4+1, 2+2+1 and rainbow builds;
  - one per-slot number is hand-checked in the spec comment against KQM's `E[N] = 1/p_tot`
    (R§7).

*PR 2 here: pure functions, all tested, nothing on screen.*

---

# Phase 3 — the surface

### [ ] 8 — The Upgrade tab (DESIGN §11; if the tabbed shell is declined, a panel on the build view)
- **Do:**
  - **Per slot:** median, P25–P75, P90 in resin and days, and the per-drop `1 in N`.
  - **Under the slots:** the domain ranking by `q_any`.
  - **Labels:** fast-pass numbers carry *Estimated* until the exact pass lands, then *Exact*.
  - **Captions that must not be dropped:**
    - "single-slot lower bound; the full search may find more";
    - "standard domain runs only; levelling cost not included";
    - the draw model's community-source caveat;
    - the sensitivity spread;
    - the recipe's `unstable` / `staleConversions` flags.
- **Accept:** `npm run verify`, `npm test` and `check:tokens` are green. **Driven** with
  `scripts/shoot.py` on the owner's build at desktop and phone width. One slot's `q` is
  hand-checked against the Task 5 sampler run on that same build. The DOM audit
  (`dom-audit-measures-what-screenshots-cannot`) shows no overflow at 375 px.

### [ ] 9 — Close-out
- **Do:** update this file's banner, DESIGN status, `CLAUDE.md`'s plan table and
  `docs/LOG_mistilteinn.md`. Record what driving it found that no test did.
- **Accept:** `ci_local` is green on the PR head; merged; the deploy confirmed by
  `gh run list --branch dev` plus a lazy-chunk grep
  (`verify-a-frontend-deploy-by-grepping-the-lazy-chunk`).

*PR 3 here.*
