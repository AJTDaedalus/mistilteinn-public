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

### [~] A.3 — Catalogue pages against the real API
- **Do:** the read surface G.6a shipped — characters, weapons, artifact sets, enemies — as
  simple list/detail pages, replacing the deleted ZZZ ones so the app is not an empty shell.
- **Accept:** each page renders from `/api/v1/...` with no hand-written types; `npm run codegen`
  is the only source of API types.
- **Characters done.** Weapons, artifact sets and enemies follow the same shape —
  `CatalogueService` already has their methods.

### [x] A.4 — Re-enable the frontend test lane **(done with A.2 — the tests already passed once the ZZZ pages were gone)**
- **Do:** CI runs `npm test` — currently a disabled step with a `TODO(chunk-J)`.
- **Accept:** the step runs and is required. A skipped check is not a pass.

---

## Chunk B — gcsim in the browser

### [x] B.1 — ~~Vendor~~ **build** the gcsim WASM from the pin **[snapshot discipline]**
- **Revised during execution: the artifact is *not* committed.** It is **40 MB** (7 MB
  gzipped, and `-ldflags="-w -s"` saves ~1 MB at a documented performance cost), so
  committing it would add a multi-megabyte blob on every re-pin, permanently. Two precedents
  in this repo point the other way — the crossval `PROVENANCE.md` (*"gcsim is not vendored:
  it is a 35 MB Go binary"*) and `app/data/yuanshen/`, whose 54 MB TextMap lives only in the
  gitignored cache. **The pin and the recipe are committed; the artifact is built.**
- **Done:** `scripts/build-gcsim-wasm.sh`, `frontend/gcsim/PROVENANCE.md`, gitignored
  artifacts, and CI builds it. The script **reads** the pin out of `CROSSVAL_gcsim.md`;
  `test_gcsim_pin_is_single.py` fails on a hard-coded SHA anywhere, because two pins that can
  drift are two definitions of correct.

### [x] B.2 — Run one simulation in the browser build
- **Done, and it agrees:** driven through upstream's own JS bindings
  (`initializeAggregator` → `initializeWorker` → `simulate` → `aggregate` → `flush`) the
  browser build returns **21.706079870465302** — the committed fixture's value, the native
  binary's, and the WASI probe's, **to the last digit**. Four independent paths.
- `scripts/verify-gcsim-wasm.mjs` is a standalone Node gate (it needs the real WebAssembly
  host, not Angular's test environment) and CI runs it; a guard test fails if that step goes
  away. Checked by pointing it at a wrong expectation and watching it exit 1.
- **Measured:** instantiate 0.09 s; **31.35 ms per Monte Carlo iteration** single-threaded on
  a two-character 90-second rotation. See the DESIGN §3.5 correction this forced.

### [x] B.3 — Config generation from a build
- **Done**, and `RESEARCH_gcsim_embed.md` §5 was **wrong about the keys**. It read gcsim's
  *directory* names and concluded the surname is dropped (`ayaka`). The authority is
  `pkg/core/keys/*.dm.go`, and the real keys are the **full** names — `kamisatoayaka`,
  `kaedeharakazuha`, `raidenshogun`. So there is no surname alias table at all.
- What the unmatched 45 actually are: **28 Traveler variants** (structured — body id +
  element → `aetherpyro`, `luminehydro`; gcsim has **six** elements, no Cryo Traveler) and
  **17 characters newer than the pin**. The second group is refused, correctly: gcsim cannot
  simulate what it does not implement.
- `app/data/gcsim/keys.json` is the committed derivation (`scripts/gcsim/build_key_snapshot.py`),
  and CI feeds emitted configs to **gcsim's own `validateConfig`** — the only authority on
  whether the text is a config.

### [x] B.4 — Context runs, bucketed by ER
- **Done:** `sim_runs` (migration `c0318f0bbead`), `sim_context.context_key`,
  `SimRunRepository`. A repeat lookup hits; a different pin, ER bucket or rotation misses.
- **The key is a hash, not a row of columns**, because a cache key must be all-or-nothing —
  columns invite a lookup that matches a subset and returns a run for a different context
  while looking like a hit. The pin is inside the hash *and* in the lookup, so forgetting
  either still misses rather than serving a number from a different simulator.
- **A team is a set; a rotation is a sequence.** Reordering a team hits, reordering a
  rotation misses. Both asserted.
- **ER rounds down**, so a hit never claims uptime the build has not earned: 179% must not
  read a run from 180% that got its burst off.
- **Owner-scoped.** The browser produces these numbers, so a tampered client could submit
  anything; scoping limits that to poisoning its own cache. Sharing is a separate feature
  with its own threat model, and `owner_id` is nullable so a server-generated corpus can be
  shared explicitly rather than by accident.

---

## Chunk C — The kernel

### [x] C.1 — The differential-testing harness, **before the kernel** **[gate]**
- **Do:** a generator producing thousands of arbitrary build/hit cases and their expected
  values from the Python chain, committed as fixtures, with a sample confirmed by gcsim.
- **Why first:** DESIGN §6. A second damage chain without a test binding it to the first is
  the whole hazard, and building the kernel first means the harness gets shaped to fit
  whatever the kernel already does.
- **Done:** `scripts/kernel/generate_cases.py` sweeps the input surface into
  `tests/fixtures/kernel/cases.json` — **2,000 cases**, deterministic from a fixed seed.
- **Coverage is asserted, not assumed**: all 4 scaling stats, 8 channels, 7 scopes, all 4
  amplifying reactions plus none, 30% past the crit-rate cap, all three resistance branches
  including exactly 0.75, and 13% combining both enemy DEF mechanics.
- `test_kernel_cases.py` replays every case **from the JSON alone**, which is the harness's
  real failure mode: a fixture missing a field the chain reads would look like "the kernel is
  wrong" and the first thing anyone would do is change the kernel. Verified by corrupting 50
  cases and watching it fail.
- **Anchoring is transitive and that is written down.** A case is a synthetic stat bundle,
  and no gcsim config expresses one — gcsim simulates characters, not hypothetical stat
  vectors. So `tests/crossval` pins the chain to gcsim and the chain generates these. One
  link longer than DESIGN §6 implied; what keeps it honest is crossval running with
  `CROSSVAL_REQUIRE_DB=1` so the anchor cannot skip.

### [x] C.2 — Argue the f32 tolerance **[Planner]**
- **Do:** derive it from f32 precision compounded over the chain's operations, in writing, in
  `docs/CROSSVAL_gcsim.md`'s style. **Before the kernel is written.**
- **Done: `1e-6` relative**, argued in `docs/CROSSVAL_gcsim.md` and made executable in
  `tests/unit/test_f32_tolerance.py`. Both halves are **measured over the 2,000-case sweep**,
  not asserted:
  - f32 end-to-end divergence: median 6.78e-08, p95 1.91e-07, **max 3.51e-07**. So `1e-7`
    (the f64 chain's tolerance) would fail ~5% of cases for reasons that are not bugs, and
    `1e-6` is ~2.8x the measured maximum.
  - smallest plausible formula error: **206x** the tolerance (a forgotten crit clamp), then
    226x (DEF mechanics combined additively) and 1,500,000x (the RES boundary).
  - The constant is pinned **from both sides**: widening it to 1e-2 fails 5 tests, tightening
    it to 1e-9 fails 2. A tolerance that only resists widening is one that can quietly become
    unachievable slack.

### [x] C.3 — TypeScript CPU kernel: stats and one hit
- **Done:** `src/app/sim/damage.ts` matches the Python chain on **all 2,000 cases, worst
  3.379e-07** against the 1e-6 tolerance — landing almost exactly on the 3.51e-07 C.2's f32
  model predicted, which is independent confirmation both are right.
- **Every operation goes through `Math.fround`.** JavaScript is f64 and WGSL has no f64, so
  computing natively here would make this backend *more* accurate than the GPU one — and a
  user switching backends would watch their build's number change for no reason they could
  act on. Matching the GPU's precision is worth more than having more of it.
- The sweep is `scripts/verify-kernel.mjs`, a standalone Node gate (Node 24 strips types, so
  it imports the kernel source and there is no build artifact to go stale). CI runs it and a
  guard test fails if that step disappears.
- **Verified by injecting three real formula bugs**: a forgotten crit clamp (598 cases
  diverge), DEF mechanics added rather than multiplied (255), and gcsim's reading of the
  0.75 RES boundary (511).

### [x] C.4 — TypeScript CPU kernel: the five-slot search
- **Do:** the Cartesian product, the bounded top-N heap, and the lossless Pareto layer —
  algorithms ported from G.1/G.3, implementation new.
- **Done:** `src/app/sim/search.ts` picks the **same winner as the Python optimizer on all
  40 shared fixtures**, worst damage divergence 2.275e-07, and the lossless Pareto layer
  removes the same pieces — arithmetic, so it must agree exactly rather than approximately.
- **Budget-K deliberately did not port.** It exists in the Python optimizer because a server
  is slow; DESIGN §2 expects the GPU to search exhaustively, so a lossy layer would trade
  exactness for time that is not being spent. `isExact` is kept anyway — a flag that is
  always true today is still the flag that tells you about the day it is not.
- Verified by injecting three search bugs: Pareto losing its tie-break so identical pieces
  remove each other (2 cases), grouping by slot without set (35), and a top-N that keeps the
  worst (40).

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
