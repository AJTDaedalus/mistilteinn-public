# TASKS: the upgrade estimator

**Companion:** `docs/DESIGN_upgrade_estimator.md`. Read §1 (what already exists), §4 (the closed
form) and §5 (the hard part) first. **Evidence:** `docs/RESEARCH_artifact_drop_model.md`.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each one: tick it here, append to `docs/LOG_mistilteinn.md`,
then **stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG) · `-` removed

> **Status: built, 2026-10-24, on `feat/upgrade-estimator`.** Tasks 0–8 done, 3 removed by the
> owner, 9 is this close-out. Six departures from the plan as written, each recorded at its
> task and in `docs/LOG_mistilteinn.md`: Task 1 measured *after* Tasks 4–6 (a measurement needs
> the code it measures); GO's `freshArtifact` crossval replaced by a hand-worked cell plus the
> sampler; yielding instead of a Web Worker (38 ms worst block, measured); the sampler's
> no-page-imports guard is a grep, not a spec; mutations ran through a scratch harness because
> `scripts.inject` drives pytest only; and the tabs landed on this branch rather than first on
> their own, with Optimize keeping its own pickers.

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

### [x] 0 — Branch setup **(gate)**
- **Do:** rename `docs/upgrade-estimator` to `feat/upgrade-estimator` and rebase it on an
  up-to-date `dev`.
- **Accept:** `git branch --show-current` is `feat/upgrade-estimator`; the RESEARCH and DESIGN
  commits are on it; `git status --porcelain` is clean.

### [x] 1 — **[Planner]** Measure the exact pass's cost, and test monotonicity
- **Done:** `docs/RESEARCH_upgrade_estimator_cost.md`, `frontend/scripts/bench-upgrade-estimate.mjs`.
  0.1–0.9 s per slot on a 245-hit recipe; 10³–10⁵ evaluations, not 10⁷; monotone in every
  stat. Verdict: yield on the main thread, no worker.
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

### [x] 2 — Extend the draw model with drop counts and line shares
- **Files:** `backend/app/data/external/artifact_draw_model.json`, `app/data/external.py`, its
  schema, unit tests.
- **Do:** add the following, each with the R§ and URL beside it:
  - `five_star_per_run: 1.065`, with the `N₅ = 1 + Bernoulli` shape marked `assumed: true`;
  - `four_line_share: {domain: 0.20}` — domain only in v1; other sources arrive with the
    Strongbox follow-up;
  - `set_share_in_domain: 0.5` (R§1.3) — the σ = ½ of DESIGN §4.1.

  Resin per run is **read from `planner_economy.json`**, not restated.
- **Accept:** the loader refuses a missing or out-of-range share. A test asserts every new entry
  carries a source. `DrawModel` in `api.types.ts` carries the new fields after
  `npm run codegen`, and the openapi diff is **purely additive**
  (`duplicate-pydantic-names-rename-both`).

### [-] 3 — ~~Domain → sets~~ **removed** (owner, 2026-10-24: no domains; DESIGN §4.1)

*PR 1 here: data only, backend only.*

---

# Phase 2 — the math, client-side, with its oracle

### [x] 4 — The fresh-drop prior
- **Done:** `sim/fresh-drop.ts`. **Deviation:** no GO capture — GO is not runnable offline here.
  The spec instead checks one cell against an independent permutation sum, equal weights
  against `1/C(n,4)`, and the whole prior is judged by the Task 5 sampler.
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

### [x] 5 — The literal Monte Carlo oracle
- **Files:** `frontend/src/app/sim/fresh-drop-sampler.ts` (test-only, never imported by a page) +
  spec.
- **Do:** generate an artifact the way the game does (R§§2–4, one line at a time, upgrade by
  upgrade) with a seeded RNG, and score it with the injected evaluator. Share **no code** with
  Task 4 except the data file and the evaluator.
- **Accept:** on a toy linear evaluator where `P(beat)` has a closed form, the sampler's estimate
  falls inside its 99.9% binomial interval.

### [x] 6 — **[Planner]** `P(beat | slot, main)`: exact with the three reductions, plus the Gaussian fast pass
- **Done:** `sim/upgrade-estimate.ts`. Exact inside the sampler's interval on four slots of a
  synthetic recipe **and on the owner's real Skirk recipe** (flower: exact 5.30e-4, sampled
  [4.54e-4, 5.75e-4], 1.5M draws). Five planted faults all caught. **No Gaussian fast pass**:
  the exact pass is already interactive, and a Gaussian tail is wrong where this feature lives.
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

### [x] 7 — Per drop → resin
- **Files:** `frontend/src/app/sim/resin-to-upgrade.ts` + spec.
- **Do:** implement DESIGN §4:
  - `q(s)` with σ = ½ for a set slot and 1 for the off-piece (§4.1), `r` from `N₅`, then the
    geometric quantiles, mean and PMF, in resin, with θ defaulting to 1%.
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

### [x] 8 — The Upgrade tab at `/artifacts/upgrade` (DESIGN §11; needs the tabs refactor merged)
- **Done:** `pages/upgrade/`, `/artifacts` shell with Inventory · Optimize · Rank · Upgrade,
  redirects from `/inventory` and `/optimize`. Driven on the owner's Skirk build at 1440 and
  375 px; four visual defects found by looking and fixed (see LOG). **Not done:** a shared
  context bar for Optimize — Rank and Upgrade share their choice, Optimize keeps its own.
- **Do:**
  - **Per slot:** median, P25–P75, P90 in resin, and the per-drop `1 in N`.
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

### [!] 9 — Close-out — **blocked on the npm audit gate, not on this feature**
- **Gate, 2026-10-24, on `58b3f43`:** `ci_local` **25/26**. Every backend, integration, crossval,
  frontend, typecheck, lint and security job passed; `frontend-security/npm audit` failed on
  **47 advisories published since the allowlist's last review (2026-09-19)** — zod, Angular
  tooling and others. `package-lock.json` is byte-identical to `origin/dev`, so `dev` fails
  the same gate today. Rule 1 says a red gate blocks, so this does not merge until a
  dependency-patch branch clears it. Docs, banners and LOG are done.
- **Do:** update this file's banner, DESIGN status, `CLAUDE.md`'s plan table and
  `docs/LOG_mistilteinn.md`. Record what driving it found that no test did.
- **Accept:** `ci_local` is green on the PR head; merged; the deploy confirmed by
  `gh run list --branch dev` plus a lazy-chunk grep
  (`verify-a-frontend-deploy-by-grepping-the-lazy-chunk`).

*PR 3 here.*
