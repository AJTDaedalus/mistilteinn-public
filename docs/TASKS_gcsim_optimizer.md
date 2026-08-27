# TASKS: a gcsim-based optimizer that runs in the browser

**Companion:** `docs/DESIGN_gcsim_optimizer.md` — read §2 (why this is transcription, not
re-derivation) and §4 (predict-then-verify) before starting.
**Evidence:** `docs/RESEARCH_gcsim_calibration.md`, `RESEARCH_recipe_cost.md`.
**Tier:** Worker unless marked **[Planner]**.
**Cadence:** one task at a time. After each: tick it here, append to `docs/LOG_mistilteinn.md`,
**stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

**Standing rules**

- Verify `git branch --show-current` before every commit. **`gh pr merge --delete-branch`
  checks out `dev`** — branch immediately after a merge, before anything else.
- **Run each gate standalone and check its exit code.** Not chained behind `&&`, not piped
  through `tail`.
- Lint with **CI's own argument list** — copy the `run:` line out of `.github/workflows/test.yml`.
- Prove the negative with `python -m scripts.inject`. **A surviving mutation means the test is
  wrong until proven otherwise.**
- **Never emit `swap_delay=0`.** It silently breaks every multi-character rotation.
- **`simulate()` reports failure by returning a string.** Check it; `flush()`'s error is a
  symptom, not a cause.
- **Take every gcsim key through `gcsim_keys`.** Directory names are not keys (`raiden` vs
  `raidenshogun`), and `validateConfig` accepts the wrong one.

---

## Phase 0 — clear the decks

### [x] G.0 — Branch setup **(gate)**
- **Do:** branch `feat/gcsim-optimizer` off `dev`.
- **Accept:** `git branch --show-current` is not `dev` or `main`.

### [x] G.1 — Repo cleanup **[Planner]** — **done**
- **Do:**
  1. **Rescope `TASKS_passive_port.md`.** P.3–P.5 were written on the premise that 237
     passives must be transcribed before a rotation can be scored.
     `RESEARCH_gcsim_calibration.md` §3 shows the calibration captures a passive's *effect*,
     so the port narrows to **passives whose amount depends on the candidate's own stats** —
     `Staff of Homa`, `Engulfing Lightning`, `Redhorn Stonethresher`,
     `Primordial Jade Cutter`, and whatever P.1's data shows joins them. Put a superseded
     banner at the top; do **not** silently renumber.
  2. **Retire `app/services/_ported/`** where the port has landed. Five ZZZ modules remain of
     eight; each was to be deleted when its port shipped. Check each against its README claim
     and delete what is done — leaving a module whose port landed is the same inventory rot
     `TASKS_loose_ends.md` cleaned up.
  3. **Re-derive `CLAUDE.md`'s numbers** — they moved again (1273 backend tests, 24 migrations
     check, path count). Run the derivations; do not edit from memory.
- **Accept:** `rg "TODO\(chunk-"` still zero; every TASKS file's banner matches its checkboxes;
  `_ported/README` describes what is actually there.
- **Why first:** every one of these is a claim a future reader will trust. This chunk adds
  four research documents on top of them.

## Phase 1 — the recipe

### [x] G.2 — Extract a recipe from `sample()` — **done**
- **Do:** `frontend/src/app/sim/recipe.ts` — parse a `sample()` payload into
  `{hits: RecipeHit[], meta}`, using `calc` events for the decomposition and `snapshot` for the
  stat vector.
- **Accept:** replaying the recipe against the calibration's **own** stats reproduces each
  hit's `avg_crit_dmg` to **1e-12**, over all 245 hits of a committed sample.
- **Two traps, both found by getting them wrong:** `bonus_dmg` **already includes** `ele_per`
  (adding it breaks 73 of 245 hits), and `damage_grp_mult` is **not** part of the pre-crit
  relation (including it makes 24 unlanded hits look like formula errors).
- **Use `avg_crit_dmg`, never `is_crit`.** gcsim rolls crit; this repo computes it, a
  documented divergence. A recipe carrying per-hit rolls imports Monte Carlo noise into a
  deterministic evaluator.

### [x] G.3 — Commit a calibration fixture, and gate it — **done** (two fixtures)
- **Do:** commit one `sample()` payload plus the config and seed that produced it. Add a CI
  step that regenerates and compares.
- **Accept:** the gate fails if the pin moves and the payload does not. **A skipped check
  BLOCKS** — if the wasm is absent the gate exits non-zero with a reason, it does not pass.
- **Why:** the fixture is 1.3 MB of JSON that everything downstream trusts. fairy shipped a
  stale golden fixture for months; this is the guard that would have caught it.

## Phase 2 — evaluation

### [x] G.4 — Evaluate a recipe in the kernel — **done** (1.05× at H=17)
- **Do:** score a candidate combination against a recipe — aggregate stats once, then
  recompute each hit.
- **Accept:** a benchmark shows **≤1.3×** the current per-combination cost at H=17.
  `RESEARCH_recipe_cost.md` measured 1.15×; the margin is for the extra `sum()` calls distinct
  elements need.
- **Reuse `computeDamage`.** A second implementation of the chain is the thing DESIGN §1 A6
  forbids, and the differential gate exists because this repo already has two.

### [x] G.5 — Predict, then verify **(the real gate)** — **done** (1.986e-16)
- **Do:** build a recipe at one artifact set, predict a **different** set's rotation damage,
  then run gcsim on that set and compare.
- **Accept:** agreement inside a tolerance **argued from the measured Monte Carlo standard
  error**, not chosen. State the residual and what it is made of, as `CROSSVAL_gcsim.md` does.
- **This is the task that decides whether the chunk ships.** Self-consistency (G.2) proves
  transcription; only this proves fidelity. **A recipe that only reproduces its own
  calibration is a very expensive identity function.**

### [ ] G.6 — A recipe states its own validity
- **Do:** carry `stable` (burst-instance `sd == 0`), `staleModifiers` (stat-conversion
  passives present and unported), `erBucket`, `gcsimPin`, `seed`, `iterations`.
- **Accept:** a build inside an ER transition band comes back **`stable: false`**, and the
  optimizer surfaces that rather than ranking silently. Same rule as `isExact` and W.5.

## Phase 3 — the search

### [ ] G.7 — Calibration cache **[Planner]**
- **Do:** settle **OQ-G3** (where recipes live) and **OQ-G1** (which ER buckets to calibrate).
- **Accept:** OQ-G1 answered from a **measured** step location for a real rotation, not from
  `RESEARCH_er_bucketing.md`'s Ayaka sweep — that doc's own Result 3 shows real variation at
  flat burst count, so ER is not the only mover.

### [ ] G.8 — Swap the optimizer's objective
- **Do:** the search maximises recipe damage instead of one hit. Settle **OQ-G2**.
- **Accept:** a search for a `Redhorn Stonethresher` build **considers DEF pieces** — a test
  that fails against today's chain. **This is the task the whole plan is for**; everything
  before it changes no answer a user sees.
- **Keep the single-hit objective reachable.** It answers a different, legitimate question
  ("best for this hit") in microseconds, and OQ-W4 already settled the principle: deleting a
  fast honest answer because a slow better one exists is a downgrade.

---

## Open questions

**OQ-G1** which ER buckets (G.7) · **OQ-G2** re-rank all or re-score top N (G.8) ·
**OQ-G3** where recipes live (G.7) · **OQ-G4** whether `/compare-weapons`'s gcsim tier
collapses into this (after G.8).

## Not in this chunk

- **Tier 3 target-state passives.** `KernelTarget` cannot express aura, enemy type or weak
  spots — unaskable, not unported.
- **Making gcsim faster.** ~4× ceiling against a ~8,900× gap. The `CollectStats` config option
  noted in `RESEARCH_gcsim_calibration.md` remains unmeasured and is a *compare page* lever.
- **Rotation optimization.** Closed by owner decision, 2026-08-25.
