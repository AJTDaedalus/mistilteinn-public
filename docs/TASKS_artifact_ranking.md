# TASKS: ranking one artifact

**Companion:** `docs/DESIGN_artifact_ranking.md` — read **§2** (what already exists), **§7**
(the closed cost question) and **§8** (the 2026-09-05 replan) before starting.
**Issue:** [#291](https://github.com/AJTDaedalus/mistilteinn/issues/291).
**Decisions:** `DECISIONS.md` §22 (2026-08-29) and §33 (2026-09-05).
**Prior reading:** `RESEARCH_fribbels_hsr.md`, `AUDIT_fribbels_handson.md`,
`RESEARCH_genshin_optimizer_scoring.md`, `AUDIT_fribbels_parity.md` §§2 and 5.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each: tick it here, append to `docs/LOG_mistilteinn.md`,
**stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

> **Status: Phase 1 in progress.** Written 2026-09-05. **A.0 and A.1 done.** A.1 found that
> GO states the one-artifact-at-a-time limitation in its own UI, which turns
> `DESIGN_artifact_ranking.md` §8.2 from an inference into a citation —
> `docs/AUDIT_go_handson.md`, reproducible with
> `cd backend && python -m scripts.audit_genshin_optimizer`.

**Branch policy.** All work on `feat/artifact-ranking`, off `dev`, never on `dev` or `main`.
A.0 is the gate. **One PR per phase**, not per task — five PRs, not seventeen.

---

## Standing rules for this chunk

- Verify `git branch --show-current` before every commit.
- **`cd backend && python -m scripts.ci_local`, exit 0 over every job, on the exact commit that
  is the PR head**, before any merge to `dev`. `--list` prints the plan; `--job <id>` is for
  iterating and never clears a merge.
- Any API change regenerates `frontend/openapi.json` in-process (`create_app().openapi()`) and
  leaves `test_openapi_contract_is_current.py` green. Run `npm run codegen` after.
- `npm run verify` is the frontend typecheck. `npx tsc -p tsconfig.app.json` skips specs and
  `tsconfig.json` is vacuous; neither clears anything. `npm test` is `ng test`.
- `npm run check:tokens` after any stylesheet change. An undefined custom property fails silently.
- **A number this feature prints must be able to say where it came from.** That is the standing
  architecture constraint (`CLAUDE.md` §Architecture) and it is the whole point of a score.
- **Do not write a substat weight, a roll tier, or a main-stat probability from memory.** §8.3
  establishes that these are *not* in the pinned game data and must carry a named source.
- **Drive the feature.** #237 shipped a weapon picker whose two weapons returned the same number
  to the decimal with every test green. A score column that renders is not a score column that
  is right: take a screenshot, and check one piece's number by hand against `/explain`.

---

# Phase 1 — the data, and where it is allowed to come from

*One PR. Backend only. Nothing here needs the frontend to exist.*

### [x] A.0 — Branch setup **(gate)**
- **Do:** branch `feat/artifact-ranking` off an up-to-date `dev`.
- **Accept:** `git branch --show-current` is `feat/artifact-ranking`; `git status --porcelain`
  clean.

### [x] A.1 — **[Planner]** Drive Genshin Optimizer, and screenshot what it shows
- **Why:** `RESEARCH_genshin_optimizer_scoring.md`'s own honesty note says *"I did not run GO or
  view its UI. Statements about what the user sees are read off the JSX."* We are copying its
  distribution display; a plan for a chart nobody has looked at is the failure this repo names
  most often. The owner has confirmed GO has *"some nice statistics plots"*.
- **Do:** drive GO headless with Playwright at 1440×1000, import
  `references/genshin_export_2026-08-28_11-07.json` (2,370 artifacts, the owner's own), open the
  Upgrade Opt tab for a real build, and screenshot: the distribution chart, its two headline
  numbers, the per-artifact card, and any sort/filter surface. `scripts/shoot.py` is the harness.
- **Accept:** `docs/AUDIT_go_handson.md` exists, every claim cites a screenshot filename under
  `screenshots/go/`, and anything not reached is listed as not reached — the shape
  `AUDIT_fribbels_handson.md` already uses. **A page that could not be opened is recorded as
  such, never inferred from the JSX.**
- **Escalate if:** the export will not import or the tab needs a live account. Do not substitute
  a reading of the source for a screenshot and call the task done.

### [x] A.2 — The substat draw constants, as a cited external snapshot
- **Why:** §8.3 — the weights are **not** in `ReliquaryAffixExcelConfigData` (350 rows at
  `5445617e33b2`: `id / propType / group_id / propValue / depotId`, no weight) and main-stat
  probabilities are not in `ReliquaryMainPropExcelConfigData`. `ReliquaryExcelConfigData.weight`
  exists and is an **item-drop weight**; taking it because the key matched would be confidently
  wrong.
- **Do:** add `backend/app/data/external/artifact_draw_model.json` — substat appearance weights
  and per-slot main-stat probabilities — with a provenance block naming
  `genshin-optimizer/libs/gi/upopt/src/consts.ts` at a pinned commit **and** the fandom
  *Artifact/Distribution* page that file's own comment cites. Precedent for shipping a named
  secondary source openly: `gcsim_config.ENERGY_DRIP`.
- **Accept:** a loader beside `app/data/snapshot.py`; `tests/unit/test_artifact_draw_model.py`
  asserts every weight against the committed file and that the provenance block is non-empty and
  names both sources. **Directory is `external/`, not `yuanshen/snapshot/`** — a file that is not
  derived from the pinned capture must not sit where every other file is.
- **Do not:** put it under `yuanshen/snapshot/` or let `build_snapshot.py` regenerate it.

### [x] A.3 — Measure the owner's export against those weights, and record that it cannot ground them
- **Why:** the export is the obvious place to derive weights from and it does not work. Measured
  2026-09-05 on flowers at +0 (319 pieces, 1,061 lines): `eleMas` w=4 at 13.29%, `critDMG_` w=3 at
  12.25%, `atk` w=6 at 11.97%, `def_` w=4 at 7.82%. Inclusion probability under a weighted draw
  without replacement is **monotone in weight** — not proportional, which is why a naive
  percentage test is the wrong one, but the ordering is forced — and w=3 above w=6 violates it.
- **Do:** `backend/scripts/measure_substat_frequencies.py`, conditioning on slot and main stat so
  the pool is right. Write findings to `docs/RESEARCH_substat_draw_weights.md`: the numbers, the
  monotonicity argument, and the two candidate explanations (survivorship in a kept inventory; a
  wrong published table) with no claim about which.
- **Accept:** the script runs `python -m scripts.measure_substat_frequencies` against a path and
  reproduces the figures above; the doc states plainly that **this corpus is not a source for the
  weights** and A.2's file is.
- **Do not:** "fix" the weights to match the export.

### [x] A.4 — Expose what the client needs to project a piece
- **Do:** the client scorer needs, per artifact: decomposed rolls (`substat_rolls`, already
  built), `rolls_remaining` / `gains_a_substat` (`artifact_potential`, already built), the roll
  tier values for its rarity, and the draw model from A.2. Extend the inventory payload rather
  than adding a per-piece round trip — the column scores 2,370 pieces at once.
- **Accept:** `GET /artifacts/inventory` carries them; a piece whose rolls did **not** decompose
  carries `null`, not zero (`UpgradePotentialRead`'s existing rule); contract regenerated;
  `npm run codegen` run; the 401 sweep covers any new route.
- **Prove the negative:** `python -m scripts.inject` on the null path. A test that cannot tell an
  undecomposable piece from a zero-roll one is the `isExact` flag thrown away at the last step.

---

# Phase 2 — the fast column

*One PR. This is the sortable, whole-inventory half. It ships useful on its own.*

### [x] A.5 — `sim/artifact-projection.ts` — a piece at max level, four ways
- **Do:** pure TS, no rendering, no network. From rolls remaining, tier values and the draw
  model, produce four stat pools for one piece: **current**, **average**, **best**, **worst**
  (§5). Follow `futureScore.ts`'s shape (`RESEARCH_fribbels_hsr.md` §4.5) — mid-tier spread
  evenly for average; every remaining roll on the best-scoring line at top tier for best — and
  charge a missing fourth line the average contribution across the lines that could still appear.
- **Accept:** unit tests over hand-worked examples, including a 5★ +0 with three substats (five
  upgrades, one of which creates the line) and a 5★ +0 with four (five that all deepen). A 3★
  caps at +12 and gets three. **Offline and deterministic** — this task touches no recipe.

### [x] A.6 — Five numbers per piece, and the three refusals
- **Do:** join A.5's projections to the existing `scoreForSlot`. Report per piece: current,
  average, best, worst, and the **signed delta vs. what is equipped** — the column
  `AUDIT_fribbels_handson.md` names as the one that makes the list decidable. Add letter grades
  (OQ-A3) on `scoreFormatting.ts`'s 5% steps.
- **Accept:** §6's three refusals are behaviour, not prose: an undecomposable piece reports **no
  score**; a wrong main stat is reported as a **separate fact**, not a low comparable number; a
  build whose recipe carries `unmodelled_passives` propagates that caveat onto every score
  derived from it. Each has a test that fails when the refusal is removed.
- **Label the bound:** a single-slot delta is a **lower bound** on the pinned re-search (§8.1).
  The number ships as *"at least +N%"*, not as *"+N%"*.

### [x] A.7 — `/artifacts` gets a build picker and a calibration
- **Do:** OQ-A7. A build/team selector on the inventory page; on selection, resolve the recipe
  through `recipe-cache.ts` and only calibrate what is missing. Calibration is **a job with
  progress, never a request that blocks** — `RESEARCH_recipe_cost.md`'s standing ruling.
- **Accept:** with a warm cache the column appears without a gcsim run; cold, the user sees
  progress and can leave. `npm run check:tokens` green. Reuse `shared/{icon,token,element,combobox}`
  rather than deciding again — `FINDINGS_frontend_validation.md`'s lesson.

### [x] A.8 — The columns: sort, filter, heat shading
- **Do:** the five numbers as sortable columns on the existing card/list, heat-shaded so the
  shape reads before the numbers do (`AUDIT_fribbels_handson.md` §2). Respect the existing
  120-piece render cap and "show more" — the page held all 2,370 in the DOM once already.
- **Accept:** screenshot at 1440×1000 with the real 2,370-piece export loaded, and **one piece's
  number checked by hand against `/explain`**. Sorting by delta descending puts a plausible
  upgrade at the top; sorting a fresh +0 by *best* does not bury it. Closes
  `AUDIT_fribbels_parity.md` §2's last open row.

### [x] A.9 — On-demand calibration for a set the build does not wear
- **Found while driving A.8, and it is bigger than the task title:** `rank()` currently
  calibrates **only the no-4-piece baseline**, so a build that is itself wearing a 4-piece set is
  scored under a recipe that omits its own bonus — every number understated, and not uniformly,
  because a set bonus interacts with the stats rather than adding to them. So A.9 covers three
  states, not one: the build's **current** 4-piece (the honest baseline), **no** 4-piece (what a
  set-breaking swap actually produces), and a **different** 4-piece a candidate would complete.
  `scoreForSlot`'s `recipeAfterSwap` exists for exactly this and is still unused.
- **Do:** OQ-A8. A candidate that would complete a different 4-piece is scored under **its own**
  recipe — `scoreForSlot` already takes `recipeAfterSwap` for exactly this. Where that recipe is
  absent, show *"needs calibration"* and a button, never a number computed under the wrong one.
- **Accept:** a test proves a cross-set piece scored under the build's own recipe and under its
  correct one give **different** numbers, and that the UI never shows the first.

---

# Phase 3 — the deep dive, which is what #291 asked for

*One PR. Measure before building — A.10 gates A.11.*

### [x] A.10 — **[Planner]** What does a pinned re-search actually cost?
- **Why:** OQ-A9. `COMBINATION_BUDGET_SECONDS = 5` is the *ordinary* search's budget over 2,370
  pieces; pinning one slot removes a factor and constrains the 4-piece state, and nobody has
  measured what is left. `FINDINGS_shakedown.md` F2 has the unpinned figures (4.26e10 raw, 1e5
  with a set pinned).
- **Do:** measure, warmed, against the committed browser build and the real export: combinations
  after Pareto with one slot forced, wall time, and how it moves with the piece's set.
- **Accept:** numbers in `docs/RESEARCH_pinned_search_cost.md`, five runs, reproducible command
  recorded. **Do not infer this from the unpinned figure** — §7's cost note is in the DESIGN
  because the escalation before it did exactly that and was wrong by a factor of thirty.
- **Escalate if:** it is not interactive even as a job with progress. That changes the shape of
  A.12 and is a Planner call.

### [x] A.11 — Pin a slot in `searchRecipe`
- **Do:** the smallest change that expresses "this piece is in this slot": restrict that slot's
  bucket to one candidate before the Pareto filter, leaving the other four buckets whole. The
  4-piece state walk already handles the set consequences, which is why this is the honest engine
  for #291's *"assume you can move other artifacts"* and the slot swap is not.
- **Accept:** a pinned search over a build's own equipped piece reproduces that build's damage;
  pinning a piece the unpinned winner already contains returns the same winner. Tests, not a
  screenshot, for both.

### [x] A.12 — "Best build with this piece" — the panel, and the % gain
- **Do:** on a piece, a deliberate action that runs A.11 **at the piece's projected max-level
  stats** and reports the resulting best build against the current one. This is #291's headline
  sentence and the number it names.
- **Accept:** OQ-A10 is settled in the UI, not left implicit: the percentage is **against the
  build as currently equipped** and the label says so. Where the current build is not optimal —
  which for a piece someone is asking about is most of the time — *against the best build without
  this piece* is a different number, and if both are shown they are labelled apart. The result
  names which four neighbours moved, because a build that changed four slots is a different
  recommendation from one that changed one.
- **Drive it:** screenshot a real run end to end. A flat result across two pieces is #240's
  failure and is what this task is most likely to reproduce.

---

# Phase 4 — the distribution

*One PR. Last, per §5, and the only part with no crossvalidation oracle behind it.*

### [x] A.13 — The draw model, pure
- **Do:** `RESEARCH_genshin_optimizer_scoring.md` §2, which distinguishes two mechanisms GO does
  not mix up: **which substats the piece has** is a weighted draw *without replacement* excluding
  the main stat and existing lines; **which line each upgrade enhances** is **uniform over the
  four**, independent per roll. Roll quality is four tiers at 70/80/90/100% of max, uniform;
  `expandRollsLevel` enumerates the *sum* of n tiers with quadrinomial coefficients (OEIS
  A008287), collapsing 4ⁿ orderings into 3n+1 totals.
- **Accept:** probabilities sum to 1 across every enumerated case; a hand-computed two-roll case
  matches; the 3-vs-4 initial split is applied. Pure and offline.

### [ ] A.14 — The distribution over damage, and its verification
- **Do:** GO's shape — delta method at the coarse levels, **exact enumeration at the leaves**, no
  Monte Carlo. §5's "apparent conflict" section is the argument that our objective qualifies:
  closed-form, deterministic, ~0.05 µs/hit, smooth except for the `min(max(cr,0),1)` clamp whose
  kink location is known.
- **Accept:** **the mean of the distribution equals A.5's `average` to within a stated
  tolerance**, and that equivalence is the verification — §5 requires the two cannot disagree,
  and this is the only oracle available. Where they differ, the *average* becomes the
  distribution's mean and A.5's rule is retired, not both kept.
- **Name the approximations** the way `RESEARCH_genshin_optimizer_scoring.md` §2 names GO's,
  in the module, not in a doc.

### [ ] A.15 — The plot
- **Do:** the chart from A.1's screenshots, on the piece's panel. Theme-aware, both palettes.
- **Accept:** screenshot in light and dark; `npm run check:tokens` green; the two headline
  numbers are labelled with what they mean rather than left to be guessed.

---

# Phase 5 — close it out

### [ ] A.16 — Sweep and hand back
- **Do:** delete `artifact-score.ts`'s "no caller, delete me" header now that it has callers.
  Update `AUDIT_fribbels_parity.md` §§2 and 5, `DESIGN_artifact_ranking.md`'s status banner,
  `DECISIONS.md`, and `CLAUDE.md`'s plan table. Append the chunk to `docs/LOG_mistilteinn.md`.
- **Accept:** `rg "TODO\(chunk-" backend/app backend/tests frontend/src` still counts zero.
  Issue #291 closed **by a merge into `dev`** — GitHub honours `Closes #N` only on the default
  branch, which is why #292 closed none of its 23. Re-derive the suite counts rather than quoting
  the ones in `CLAUDE.md`.
- **Confirm the deploy:** `gh run list --branch dev`, then a request against
  `https://mistilteinn.aetherus.dev`. A merge and a deploy are two events.

---

## Open questions carried by this plan

| | |
|---|---|
| **OQ-A9** | ~~Does a pinned re-search stay interactive over the whole inventory?~~ **Answered: no, not uncapped** — 300 s without finishing. The dive searches the best 24 per slot, keeps the pin regardless, and says so on screen. `RESEARCH_pinned_search_cost.md`. |
| **OQ-A10** | "% gain" against the current build, or against the best build without this piece? A.12 implements the first and labels it; the second is defensible and diverges exactly when the current build is not optimal. |
