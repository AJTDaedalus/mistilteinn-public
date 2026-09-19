# TASKS — upstream bump, 2026-09

Status: **nothing started.** Design: `docs/DESIGN_upstream_bump_2026_09.md`. Owner decisions
D1–D5 are in its §5, and a task that waits on one names it. Gate for every PR:
`cd backend && python -m scripts.ci_local` exits 0 on the exact PR head (`--clean` for U).

## Chunk U — gcsim re-pin (`feat/gcsim-repin-v2.47.2`)

- [ ] **U.0 Branch.** `git switch dev && git pull && git switch -c feat/gcsim-repin-v2.47.2`.
  Accept: `git branch --show-current` names it.

- [ ] **U.1 Ship gcsim's licence notice with the wasm.** This is independent of the pin.
  Copy gcsim's `LICENSE` (MIT at the pin) into the build output from `build-gcsim-wasm.sh`,
  serve it next to `gcsim.wasm`, and record it in `frontend/gcsim/PROVENANCE.md`.
  - Files: `frontend/scripts/build-gcsim-wasm.sh`, `frontend/Dockerfile.prod`, PROVENANCE.
  - Accept: the prod image contains the notice; a unit test asserts the build script copies it.

- [ ] **U.2 Make the action list parser-derived.** Do this **before** the pin moves.
  - Extend `scripts/gcsim/build_key_snapshot.py` to record the parser's `actionKeys`
    (`pkg/gcs/ast/keys.go`) in `keys.json`.
  - `authorable_actions()` offers only enum ∩ parser.
  - New test: every offered action is a parser key.
  - Accept: a no-op at the current pin (snapshot diff is only the new field). Then plant
    `special_skill` in the enum list and confirm the test fails.

- [ ] **U.3 Move the pin** *(D1)*. Update the pin table in `docs/CROSSVAL_gcsim.md`: commit,
  date, title, "Pinned" note and Go row. Rebuild with `npm run gcsim:build`, then regenerate
  with `python -m scripts.gcsim.build_key_snapshot --src <clone>` and
  `... build_multiplier_snapshot --src <clone>`, and run `crossval_multipliers`.
  - Accept: `test_gcsim_pin_is_single`, `test_gcsim_keys`, `test_talent_multipliers`,
    `test_prod_go_satisfies_the_gcsim_pin` all pass. `special_skill` is **absent** from the
    offered actions and the OpenAPI enum. Multiplier crossval shows 0 mismatches.

- [ ] **U.4 Regenerate the pinned fixtures**, each with a PROVENANCE note explaining its diff:
  - crossval JSON: `sim_version` and `particle_element` change;
  - `gcsim_sample/skirk_team_calc.json`: 219→215 hits is expected;
  - the ER sweep;
  - the coverage fixture: 31→26 uncovered, using the new aliases;
  - `frontend/openapi.json`, then `npm run codegen`.
  - Accept: `npm run gcsim:verify`, `gcsim:verify-config`, `gcsim:verify-recipe`; both
    suites pass. The ER sweep's shape assertions hold, or the change is explained.

- [ ] **U.5 Treat `"none"` as unlabelled** in `frontend/scripts/verify-gcsim-recipe.mjs` (and
  anywhere else that tests `element === ''`). Accept: a test with a `"none"` event fails the
  way `''` used to.

- [ ] **U.6 Fix citation drift.** Work through the table in the gcsim RESEARCH doc §Citation
  drift. That covers the `damage.go` −4 shift, `element.go`, `attack.go`,
  `exec.go:151→156`, `sysfunc.go:472→491`, plus the three `damage.go` rows and the ER-sweep
  PROVENANCE that are already wrong. Accept: every cited line range, opened at the new pin,
  shows the cited code (checked by hand; list them in the LOG).

- [ ] **U.7 Cross-pin runs** *(D2)*. Implement whatever the owner rules for DECISIONS §26, and
  record the ruling there.

- [ ] **U.8 Drive it and document it.** In order:
  1. Build `Dockerfile.prod` locally.
  2. Run a real two-character rotation search in the browser (`scripts/shoot.py`).
  3. Add a CLAUDE.md note on the Traveler/Skirk story-buff gap *(D5)*.
  4. Run `ci_local --clean`, then open the PR.
  5. After the merge: `gh run list --branch dev`, and the served `BUILT_FROM` equals the pin.

## Chunk V — nanoka (`feat/nanoka-7.1`)

- [ ] **V.0 Branch** (only when V.2 is unblocked).

- [ ] **V.1 Archive the pinned payloads** *(D3)*. This is **time-critical**: capture all
  ~1,086 7.0.51 payloads before 7.1 goes live (inferred around 2026-09-22). Measure their
  size, store them per D3, and give the transport an archive source. Accept: `seed_db` and
  `verify_seed` succeed with nanoka unreachable (sockets blocked).

- [ ] **V.2 Bump to the 7.1 build** *(D4; blocked on nanoka publishing it)*.
  - Capture with `capture_nanoka_fixtures --version <v>`, passing the version explicitly.
  - Update the four pin sites (both `FIXTURE_VERSION`s, the `test_seed_db.py` literal,
    PROVENANCE).
  - Run `seed_db`, then `verify_seed`.
  - Move the YuanShen snapshot to the matching build.
  - Re-run `download_icons` for new art.
  - Accept: `test_capture_pinning` passes; `seed_runs` records the new version as succeeded
    with no prune refusal; the verify anchors pass (or were re-derived and explained);
    `/planner` has been driven for one character and one weapon.

- [ ] **V.3 Exaiphanes Blade's bill.** If 11521 still has zero ascension costs at 7.1, decide
  whether it is real (the planner shows zero) or a data defect (a curated override with a
  citation). Accept: the planner's figure for 11521 has a stated source.

- [ ] **V.4 Re-derive the coverage fixture** if V lands after U (DESIGN §4).
