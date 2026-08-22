# TASKS: the client-side optimizer

**Companion:** `docs/DESIGN_client_optimizer.md` — read §2 (why the kernel is batched), §3.5
(why the corpus collapsed) and §6 (the gate) before starting anything.
**Tier:** Worker unless marked **[Planner]** or **[Owner]**.
**Cadence:** one task at a time. After each: update the status here, append to
`docs/LOG_client_optimizer.md`, **stop and report**.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

**Standing rules** — the same ones `TASKS_mistilteinn.md` carries, plus:
- Verify `git branch --show-current` before every commit. Never commit to `dev` or `main`.
- Frontend: `npx tsc --noEmit -p tsconfig.app.json` **and** `npm run lint` before every commit.
  **Not the root `tsconfig.json`** — it has `files: []` and compiles nothing, so it reports
  zero errors on a project with 147. That mistake was made and caught while writing this file;
  see A.1.
- Backend: `ruff check` and the full suite, as before.

---

## Chunk A — Make the frontend compile **(gate: nothing else starts)**

**This was discovered, not planned.** The DESIGN's kernel is TypeScript and lives in the
frontend, and the frontend does not compile: **147 errors** against endpoints and schemas B.6
deleted. A kernel cannot be added to a project where a type error is indistinguishable from
the 147 already there.

The errors are not scattered — they concentrate in fairy's ZZZ feature pages, which reference
`DiscSetSummary`, `WEngineSummary`, disc services and buff presets. **This is B.6's demolition
one layer up**, and it gets B.6's treatment: delete the ZZZ concepts rather than alias them.

### [ ] A.0 — Branch setup **(gate)**
- **Do:** create `feat/client-optimizer` from `dev`; sub-branches off it as the DESIGN's
  branch policy names them.
- **Accept:** `git branch --show-current` is `feat/client-optimizer`.

### [x] A.1 — Pin the real compile gate
- **Do:** a check that type-checks `tsconfig.app.json`, and CI runs it.
- **Why it is task one:** the root `tsconfig.json` has `files: []` and no `include`, so
  `npx tsc --noEmit -p tsconfig.json` exits 0 on a project with 147 errors. That reads as a
  green frontend. It was caught only by injecting a deliberate type error and noticing that
  it *also* passed — the same negative-case check this repo has needed repeatedly.
- **Accept:** the check fails today with 147 errors, and an injected error changes the count.
- **Tests:** a CI step, plus the equivalent of `test_ci_runs_the_perf_gate.py` proving the
  step exists and names `tsconfig.app.json`.

### [x] A.2 — Delete the ZZZ feature pages
- **Do:** delete `pages/{builds,rank,calculate,optimize,discs}` (~150 files) and the ZZZ
  `shared/` modules — `agent-picker`, `wengine-picker`, `disc-list`, `disc-rolls`,
  `stage-buffs`, `buff-context.store`, `buff-presets.service`, `custom-buff-id`. Drop their
  routes.
- **Revised during execution:** `teams` and `import` had to go too. Both import from the
  deleted `builds` module — `teams` for its build list and combo builder, `import` for the
  ZZZ disc scanner — so they were coupled to ZZZ concepts rather than merely adjacent. Their
  Genshin replacements are A.3's job (`teams` against `/api/v1/builds`, `import` against the
  GOOD endpoint G.6b shipped). `auth` and `landing` survive.
- **Commit message:** `refactor: delete ZZZ frontend pages (was fairy@76909c4:<path>)`,
  matching B.6's form.
- **Accept:** `tsc -p tsconfig.app.json` is **clean**; `npm run lint` clean; the app builds
  and the surviving routes render.

### [ ] A.3 — Catalogue pages against the real API
- **Do:** the read surface G.6a shipped — characters, weapons, artifact sets, enemies — as
  simple list/detail pages, replacing the deleted ZZZ ones so the app is not an empty shell.
- **Accept:** each page renders from `/api/v1/...` with no hand-written types; `npm run codegen`
  is the only source of API types.

### [x] A.4 — Re-enable the frontend test lane **(done with A.2 — the tests already passed once the ZZZ pages were gone)**
- **Do:** CI runs `npm test` — currently a disabled step with a `TODO(chunk-J)`.
- **Accept:** the step runs and is required. A skipped check is not a pass.

---

## Chunk B — gcsim in the browser

### [ ] B.1 — Vendor the gcsim WASM build **[snapshot discipline]**
- **Do:** build upstream's `cmd/wasm` at the pin in `CROSSVAL_gcsim.md` and commit the
  artifact plus `wasm_exec.js`, with a `PROVENANCE.md` naming the commit and the build
  command — the rule `app/data/yuanshen/` already follows. **Never a live fetch.**
- **Accept:** provenance records the pin; a test asserts the committed pin matches
  `CROSSVAL_gcsim.md`'s.

### [ ] B.2 — Run one simulation in the browser
- **Do:** load the module in a Web Worker, feed it the committed `ayaka_normal_1.txt`.
- **Accept:** it returns **21.706079870465302** — the value the native binary, the WASI probe
  and the committed fixture all agree on (`RESEARCH_gcsim_embed.md` §2). Anything else means
  the browser build and the oracle disagree, which is a blocker, not a rounding note.

### [ ] B.3 — Config generation from a build
- **Do:** emit gcsim config text from a stored build. Needs the character-key alias table
  (`RESEARCH_gcsim_embed.md` §5: 111 of 150 match naively; the rest are surname-prefixed).
- **Accept:** **refuses** an unmatched key naming it, exactly as `good_import_service`
  refuses an unknown `setKey`. A test asserts the alias table is injective.

### [ ] B.4 — Context runs, bucketed by ER
- **Do:** one run per ER bucket for a context (DESIGN §3.5), cached in Postgres, keyed by the
  gcsim pin.
- **Accept:** a repeat search does no new simulation; a pin change invalidates.

---

## Chunk C — The kernel

### [ ] C.1 — The differential-testing harness, **before the kernel** **[gate]**
- **Do:** a generator producing thousands of arbitrary build/hit cases and their expected
  values from the Python chain, committed as fixtures, with a sample confirmed by gcsim.
- **Why first:** DESIGN §6. A second damage chain without a test binding it to the first is
  the whole hazard, and building the kernel first means the harness gets shaped to fit
  whatever the kernel already does.
- **Accept:** the harness runs against the *Python* chain and passes, before any kernel
  exists.

### [ ] C.2 — Argue the f32 tolerance **[Planner]**
- **Do:** derive it from f32 precision compounded over the chain's operations, in writing, in
  `docs/CROSSVAL_gcsim.md`'s style. **Before the kernel is written.**
- **Accept:** a test proves the tolerance cannot hide a formula error — the property
  `tests/crossval` already asserts for the float64 chain.

### [ ] C.3 — TypeScript CPU kernel: stats and one hit
- **Accept:** passes C.1's harness within C.2's tolerance.

### [ ] C.4 — TypeScript CPU kernel: the five-slot search
- **Do:** the Cartesian product, the bounded top-N heap, and the lossless Pareto layer —
  algorithms ported from G.1/G.3, implementation new.
- **Accept:** same winners as the Python optimizer on shared fixtures.

### [ ] C.5 — WGSL GPU backend behind the same interface
- **Do:** batch evaluation. Mind WGSL's limits (DESIGN §2): no f64, and a permutation id that
  needs 64-bit arithmetic emulated with 32-bit ints.
- **Accept:** identical winners to C.4 on the same inputs; **OQ-S4** answered — either CI has
  a GPU or the exemption is recorded, because a check that cannot run is not a pass.

### [ ] C.6 — Delete the Python chain and optimizer
- **Do:** only once C.3–C.5 pass. `formula/genshin/*`, `stat_calculator`,
  `damage_calculator`, `artifact_optimizer`, `artifact_prefilter`, `artifact_ranker`, and the
  server-side optimize/rank endpoints.
- **Why:** the rule `_ported/README.md` states — delete each file when its port lands.
- **Accept:** suite green without them; `optimization_jobs` retargeted to re-pin regeneration
  (DESIGN §5).

---

## Chunk D — Retrieval and explanation

### [ ] D.1 — The run corpus: schema and write path
### [ ] D.2 — Retrieval by context key, **reporting its own error** (DESIGN §3)
### [ ] D.3 — "No retrievable neighbour" as a stated outcome, never a silent fallback
### [ ] D.4 — Explanation from contribution log + retrieved runs + catalogue text
### [ ] D.5 — Weapon comparison across N candidate weapons (DESIGN §3.5) — **v1**

---

## Open questions

- **OQ-S3** — browser holds the inventory vs fetches per search. Decide in D.1.
- **OQ-S4** — how the WebGPU path is tested in CI. Decide in C.5; it is a gate question,
  not a nicety.
