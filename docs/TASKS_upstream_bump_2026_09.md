# TASKS — upstream bump, 2026-09

Status: **Chunk U is done and merged (PR #323). V.1 is done and merged (PR #322).** Two
gate fixes came out of it and merged first (PR #321) — see the LOG. V.2 waits on nanoka
publishing 7.1. **W is done and merged (PR #325).** All owner decisions answered (`docs/DESIGN_upstream_bump_2026_09.md`
§5, 2026-09-19), so nothing here is blocked on a ruling. V.2 waits on nanoka publishing 7.1.
Gate for every PR: `cd backend && python -m scripts.ci_local` exits 0 on the exact PR head
(`--clean` for U, which changes the wasm build).

## Chunk U — gcsim re-pin to `v2.47.2` (`feat/gcsim-repin-v2.47.2`)

- [x] **U.0 Branch.** `git switch dev && git pull && git switch -c feat/gcsim-repin-v2.47.2`.
  Accept: `git branch --show-current` names it.

- [x] **U.1 Ship gcsim's licence notice with the wasm.** Independent of the pin; can land first.
  Copy gcsim's `LICENSE` from the build clone into the output of `build-gcsim-wasm.sh`, serve
  it beside `gcsim.wasm`, and record it in `frontend/gcsim/PROVENANCE.md`.
  - Accept: the notice is present in a built `frontend/gcsim/` **and** in the prod image; a
    unit test asserts the build script copies it.

- [x] **U.2 Every gcsim action is authorable or reviewed.** Do this **before** the pin moves.
  Owner ruling: a move gcsim implements cannot be silently dropped.
  - `build_key_snapshot` records the parser's `actionKeys` (`pkg/gcs/ast/keys.go`) beside the
    enum (`astr`) in `keys.json`.
  - Add a committed **reviewed non-authorable list**, each entry with a reason:
    `invalid`; `wait` / `delay` (sequencer constructs, not actions a step emits);
    `special_skill` (a cooldown bucket — no parser token exists, and the moves it tracks are
    authored as `skill`/`charge`, per `varka/charge.go:96` and `odette/skill.go:113`); `swap`
    (emitted implicitly, per the existing rotation rules).
  - A test fails on any enum entry that is neither a parser key nor on that list.
  - Accept: a no-op at the current pin (the snapshot diff is only the new field). Then plant a
    fake enum entry and confirm the test fails — a check that can only return one answer is
    not a check.

- [x] **U.3 Move the pin to `caf738dc8` (tag `v2.47.2`).** Update the pin table in
  `docs/CROSSVAL_gcsim.md` (commit, date, title, the "Pinned" note, the Go row — still 1.27).
  Rebuild with `npm run gcsim:build`; regenerate both snapshots with
  `python -m scripts.gcsim.{build_key_snapshot,build_multiplier_snapshot} --src <clone>`; run
  `crossval_multipliers`.
  - Accept: `test_gcsim_pin_is_single`, `test_gcsim_keys`, `test_talent_multipliers`,
    `test_prod_go_satisfies_the_gcsim_pin` pass; `special_skill` appears in the snapshot and
    **not** in the offered actions or the OpenAPI enum; multiplier crossval 0 mismatches.

- [x] **U.4 Drive the four new kits.** Iansan, Prune, Odette and Cryo Traveler. For each:
  author a rotation in our builder covering the kit's moves, compile it, and run it through
  gcsim. Check the condition vocabulary covers what the kit exposes (e.g. the Ifa/Ororon
  nightsoul conditions from `fd1699c4c`) or refuses it **by name**.
  - Accept: four configs validate and run; anything not expressible is written down in the LOG
    with what it would take. This is the task that answers "do we support all the moves".

- [x] **U.5 Regenerate the pinned fixtures**, each with a PROVENANCE note explaining its diff:
  crossval JSON (`sim_version`, `particle_element`); `gcsim_sample/skirk_team_calc.json`
  (219→215 hits is expected — frame-table fixes, `60894d7cb`); the ER sweep; the coverage
  fixture (31→26 uncovered, new aliases); `frontend/openapi.json` then `npm run codegen`.
  - Accept: `npm run gcsim:verify`, `gcsim:verify-config`, `gcsim:verify-recipe`; both suites
    pass; the ER sweep's shape assertions hold or the change is explained.

- [x] **U.6 Treat `"none"` as unlabelled** in `frontend/scripts/verify-gcsim-recipe.mjs` and
  anywhere else testing `element === ''` (`61f578730` renamed the empty element).
  - Accept: a `"none"` event fails the verifier the way `''` used to.

- [x] **U.7 Fix citation drift** — the table in `RESEARCH_gcsim_repin_2026_09.md` §Citation
  drift: the `damage.go` −4 shift, `element.go` (`ElementString` is gone), `attack.go`
  (delimiters dropped, `RelicSkill` added), `exec.go:151→156`, `sysfunc.go:472→491`, plus the
  three `damage.go` rows and the ER-sweep PROVENANCE already wrong at today's pin.
  - Accept: every cited range, opened at the new pin, shows the cited code. List them in the LOG.

- [x] **U.8 Record what the re-pin moves.** In `docs/DECISIONS.md`: §26 stands (D2) — saved
  runs from an older pin are still served — noting that this re-pin moved one vendored team by
  −8.2 %, so the premise is now known to be weaker than when it was written. Add a CLAUDE.md
  line on the Traveler/Skirk story-buff gap pointing at Chunk W.

- [x] **U.9 Drive it, gate it, deploy it.** Build `Dockerfile.prod` locally; run a real
  two-character rotation search in the browser (`scripts/shoot.py`); `ci_local --clean`; open
  the PR. After merge: `gh run list --branch dev`, and the served `BUILT_FROM` equals the pin.

## Chunk V — nanoka (`feat/nanoka-7.1`)

- [ ] **V.0 Branch** (when V.2 is unblocked).

- [x] **V.1 Make "reseed at the current version" true in the code** (D3). Today
  `verify_seed --live` and the prod `reseed` job read the committed `FIXTURE_VERSION`, which
  upstream deletes each cycle. Point them at the version nanoka publishes now, and say at each
  pin site that the committed fixtures are a snapshot of record, not a reseed source.
  - Accept: with the manifest reporting a version we do not pin, `verify_seed --live` and the
    reseed path both work; a test covers the version-resolution path.
  - This one does **not** wait for 7.1, and it is what stops the prod job breaking when 7.1 lands.

- [ ] **V.2 Bump to the 7.1 build** (blocked on nanoka publishing it; check the manifest, do
  not wait on the inferred date). Keep following `latest`, beta included (D4).
  - `capture_nanoka_fixtures --version <v>` — always pass it.
  - Update the four hand-written pin sites: both `FIXTURE_VERSION` constants, the literal in
    `test_seed_db.py`, `PROVENANCE.md`.
  - `seed_db`, then `verify_seed`; move the YuanShen snapshot to the matching build; re-run
    `download_icons`; `npm run codegen` if any schema moved.
  - Accept: `test_capture_pinning` passes; `seed_runs` shows the new version succeeded with no
    prune refusal; the verify anchors pass or were re-derived and explained; `/planner` driven
    for one character and one weapon.

- [ ] **V.3 Exaiphanes Blade (11521).** If it still has zero ascension cost at 7.1, decide
  whether that is real or a data defect, and carry a curated override with a citation if it is.
  - Accept: the planner's figure for 11521 has a stated source.

- [ ] **V.4 Re-derive the coverage fixture** if V lands after U (DESIGN §4).

## Chunk W — the Traveler's story buffs (`feat/traveler-story-buffs`, merged)

From D5: **match gcsim.** Done — `docs/LOG_mistilteinn.md` §W.

**All three buffs are the Traveler's**, including the one gcsim calls `skirk_story_buff`,
which is what the *Traveler* gets for finishing Skirk's story quest. Skirk has none, and no
character outside `internal/characters/traveler/` has one — which is smaller and clearer
than the scope written here before anybody read the source.

- [x] **W.1** Source the buff values and their conditions from gcsim at the pin, cited by file
  and line (the citation rule: never from memory).
- [x] **W.2** Apply them in the stat chain as data a shared evaluator reads (DESIGN §1 A6 —
  no per-character branches), default-on, and explainable in `/explain`.
- [x] **W.3** Prove it: a crossval case over a Traveler and a Skirk team agrees with gcsim
  inside a stated tolerance, with its own paragraph — do not widen an existing one.
