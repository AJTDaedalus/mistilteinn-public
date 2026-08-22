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

### [x] C.5 — WGSL GPU backend behind the same interface
- **Do:** batch evaluation. Mind WGSL's limits (DESIGN §2): no f64, and a permutation id that
  needs 64-bit arithmetic emulated with 32-bit ints.
- **Done:** `damage.wgsl` + `gpu.ts` match the Python chain on all 2,000 cases (worst
  3.426e-07), and the gate also asserts the two backends agree with **each other** (1,291
  bit-identical, worst 4.244e-07).
- **OQ-S4 answered, and neither option it offered was needed.** CI installs
  `mesa-vulkan-drivers` (lavapipe); Dawn selects the software adapter; the WGSL path is
  genuinely exercised. No GPU hardware, no exemption. The gate fails rather than skips when
  no adapter exists.
- **The first answer was wrong in a way worth recording**: it generalised from a dev box that
  happened to have Mesa installed. Runners ship `libvulkan` and **no ICD**, so Dawn found no
  adapter at all and CI failed. "It works on my machine" applied to a *driver*.
- Verified by injecting the same three formula bugs the CPU gate catches — 598, 255 and 511
  cases, identical counts, which is itself evidence both backends read the same sweep.
- **Still to do:** the *search* on GPU. This lands the damage chain; C.4's search runs on the
  CPU backend, and porting the product loop to a compute shader is where DESIGN §2's billion
  permutations per second actually comes from.

### [!] C.6 — Delete the Python chain and optimizer **[DEFERRED — two reasons the plan did not foresee]**
- **Do:** only once C.3–C.5 pass. `formula/genshin/*`, `stat_calculator`,
  `damage_calculator`, `artifact_optimizer`, `artifact_prefilter`, `artifact_ranker`, and the
  server-side optimize/rank endpoints.
- **Why:** the rule `_ported/README.md` states — delete each file when its port lands.
- **Accept:** suite green without them; `optimization_jobs` retargeted to re-pin regeneration
  (DESIGN §5).

**Not done, and deliberately.** C.3–C.5 pass, which was the stated precondition. Two things
the plan could not have known then say to wait:

1. **Nothing in the UI reaches the client search yet.** `search.ts` is a library with gates;
   no page calls it. Deleting the server endpoints now would leave the product with **no
   reachable optimizer at all** — the server path removed and the client path not yet wired
   to anything. The order has to be: make the browser search user-reachable, *then* delete
   what it replaces.
2. **The Python chain generates the gates' own fixtures.** `scripts/kernel/generate_cases.py`
   and `generate_search_cases.py` import it to produce the 2,000 damage cases and the 40
   search cases that C.3, C.4 and C.5 all read. Deleting it freezes those fixtures: they stop
   being derived and become hand-maintained data, and a new mechanic (a transformative
   reaction, say) would have no way to produce expected values.

**What C.6 should become**, when it happens: delete the *production surface* — the
optimize/rank endpoints, their schemas, their DI wiring — and keep the chain as **test
infrastructure** feeding the generators, the way `bench_optimizer.py` and
`build_key_snapshot.py` are already tools rather than product. That is a smaller, safer claim
than "delete the chain", and it does not leave A6 violated: one implementation ships, the
other exists only to check it, which is what an oracle is.

**Unblocks when** a page uses `search.ts`. OQ-S3 is now answered (D.1) and the inventory
endpoint exists, so what remains is the page itself.

---

## Chunk D — Retrieval and explanation

### [x] D.1 — The run corpus: schema and write path — **done**

The schema landed early: G.12 built `sim_runs`, `SimRunRepository` and `sim_context`, keyed
`(owner_id, context_key, er_bucket, gcsim_pin)`. What D.1 added is the **write path** — three
routes under `/api/v1/sim-runs` — and the validation that makes a client-produced corpus
trustworthy, because the browser computes these numbers and every field crosses a trust
boundary:

- **A run from another gcsim is refused (409).** A stale browser WASM build would otherwise
  fill the corpus with a different simulator's runs, each looking like a hit. Checked
  *before* the database is touched, and there is a test for the ordering as well as the
  outcome — the outcome test passes either way, because `get_db` rolls back on any exception.
- **An unbucketed ER value is refused (422).** `er_bucket()` rounds down, so `179` is a key
  no reader ever generates; storing it fills a cache the writer cannot hit, and the miss
  looks like a cold context rather than a bug.
- **A `created` flag that is true.** Read from `xmax`, so a POST that replaced says `200`
  and `created: false` rather than claiming `201`.
- **A miss is a 404 naming the bucket**, which is the outcome D.3 turns into a stated one.

**OQ-S3 answered** — see the BRIEF. `GET /api/v1/artifacts/inventory` returns the whole
inventory with a version digest and answers `304` to `If-None-Match`. The deciding factor was
staleness, not transfer size.
### [x] D.2 — Retrieval by context key, **reporting its own error** (DESIGN §3) — **done**

`app/services/sim_retrieval.py` — a pure function over the runs cached for one context. It
returns the run **with** what was asked for, what was matched, how far that is, and how much
the substitution appears to cost. The HTTP surface is deliberately left to D.3, because
"retrieved" and "nothing retrievable" are two halves of one contract and shipping the first
shape now would mean reshaping it one task later.

**The assumption was measured before anything was built on it** —
`docs/RESEARCH_er_bucketing.md`, 54 gcsim runs at the pin, one per whole ER percent. Three
findings changed the design:

1. **Skill casts, attack casts and aura uptime are *exactly* invariant** across 100–153 % ER.
   The §3 assumption holds outright for most of what "context" means.
2. **A 5 % bucket is not uniformly safe.** Bucket 120 — the one straddling the burst-count
   climb — is **13.3 %** wide in DPS at 5.9× the runs' standard error, while buckets away
   from the transition sit at the noise floor. A single global error figure would be
   complacent at 120 % and alarmist at 145 %.
3. **The significance test misfired**, flagging a bucket where burst count was flat and no
   context change was possible. Burst casts are discrete, so per-iteration DPS is multi-modal
   and `sd/√n` understates it. `Divergence` therefore reports the delta **and** the noise
   floor rather than pronouncing on them.

And one more found by a test rather than by reading: **the nearest neighbour underestimates.**
For bucket 120 the nearest neighbour reports 3.7 % against a true within-bucket spread of
13.3 %, because the curve is steep in the half of the bucket that neighbour cannot see. The
reference is now the immediate neighbour that moved *most* (8.2 % there), and the docstring
says plainly that this is a lower bound — "the fastest the answer is moving nearby", not "the
most this can be wrong".
### [x] D.3 — "No retrievable neighbour" as a stated outcome, never a silent fallback — **done**

`GET /api/v1/sim-runs/retrieve` — the endpoint D.2 deliberately left unbuilt, landing both
halves of the contract at once.

**Always 200, never a 404.** `retrieved` is either present or explicitly null with
`not_retrieved_because` beside it. A 404 would be the wrong shape: "nothing close enough is
cached" is an *answer* — the caller acts on it by simulating — and dressing it as an error
invites the two reflexes an error provokes. Retrying wastes a round trip; catching it and
carrying on with whatever value was already in hand **is** the silent fallback DESIGN §3.5
forbids by name, and it is the one that would never appear in a log.

**Two absences, not one.** `cold` means nothing is cached for this context; `too_far` means
runs exist but the nearest is beyond `MAX_NEIGHBOUR_BUCKETS`. They call for different work —
simulate the set this search needs, or simulate this one bucket — so collapsing them would
leave the caller guessing how much it is in for, which is the difference between a stated
outcome and a shrug.
### [ ] D.4 — Explanation from contribution log + retrieved runs + catalogue text
### [ ] D.5 — Weapon comparison across N candidate weapons (DESIGN §3.5) — **v1**

---

## Open questions

- ~~**OQ-S3** — browser holds the inventory vs fetches per search.~~ **ANSWERED in D.1: it
  holds it and revalidates.** Not a latency question — ~234 KB gzipped for a large account
  either way — a staleness one. See `DESIGN_client_optimizer.md` §7.
- **OQ-S4** — how the WebGPU path is tested in CI. Decide in C.5; it is a gate question,
  not a nicety.
