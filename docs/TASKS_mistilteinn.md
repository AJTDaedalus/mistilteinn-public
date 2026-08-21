# TASKS: mistilteinn — ZZZ strip-out and Genshin domain rebuild

**Companion:** `docs/DESIGN_mistilteinn.md` (read §1 amendments and §3 chunk plan first)
**Tier:** Worker (Sonnet) unless a task is marked **[Planner]** or **[Owner]**
**Cadence:** one task at a time. After each: update this file's status column, append to
`docs/LOG_mistilteinn.md`, **stop and report**. Do not start the next task without confirmation.

**Status key:** ` ` todo · `~` in progress · `x` done · `!` blocked (escalation in LOG)

**Standing rules for every task in this file**
- Verify `git branch --show-current` before every commit. Never commit to `dev` or `main`.
- `ruff check app/` and the relevant tests pass before each commit.
- Deleted code is recoverable from `/root/fairy` and `fairy@76909c4`. Deletion commit messages
  must name the original path.
- Never search `backend/build/` (stale shadow copy). Use `rg`, or scope to `backend/app backend/tests`.
- Run scripts as `cd backend && python -m scripts.<name>`, never by file path.

---

## Chunk A — Identity, topology, and CI

### [x] A.0 — Branch setup **(gate: nothing else starts until this is done)**
- **Do:** create `dev` from `main`; create `feat/genshin-domain` from `dev`; push neither.
- **Files:** none.
- **Accept:** `git branch` shows `main`, `dev`, `docs/port-plan`, `feat/genshin-domain`;
  `git branch --show-current` is `feat/genshin-domain`.
- **Tests:** none.

### [x] A.1 — Rename project identifiers (backend)
- **Do:** `fairy` → `mistilteinn` in `backend/pyproject.toml` (name, scripts, tool sections) and
  `backend/alembic.ini`. Update `backend/CLAUDE.md` prose that names fairy as *this* project
  (keep references that name fairy as the *upstream* — those are provenance, not stale).
- **Files:** `backend/pyproject.toml`, `backend/alembic.ini`, `backend/CLAUDE.md`.
- **Accept:** `pip install -e "backend/.[dev]"` succeeds; `rg -i fairy backend/pyproject.toml backend/alembic.ini` returns nothing.
- **Tests:** `pytest tests/unit -x -q` no worse than before (suite is expected red per fork state — record the count, do not fix).

### [x] A.2 — Rename project identifiers (frontend)
- **Do:** `fairy` → `mistilteinn` in `frontend/package.json`, `frontend/angular.json`,
  `frontend/eslint.config.js`, `frontend/CLAUDE.md`. Do **not** hand-edit
  `frontend/openapi.json` (generated — regenerate in A.9) or `frontend/package-lock.json`
  beyond the name field.
- **Files:** as listed.
- **Accept:** `npm ci && npm run build` in `frontend/` succeeds.
- **Tests:** `npm test -- --watch=false` result recorded (may be red; do not fix ZZZ specs).

### [x] A.3 — Delete stale scan artifact
- **Do:** delete `security/zap/zap-baseline-prod.html` (105 fairy references; a captured scan of
  fairy's production host, meaningless here).
- **Accept:** file gone; `rg -il fairy` no longer lists it.

### [x] A.4 — Repoint at the shared Postgres server
- **Do:** per DESIGN §A3 — remove the `db` service and its bind mounts/healthcheck from
  `docker-compose.yml`; point `backend` at the fairy stack's Postgres (external network or host
  gateway, whichever the fairy compose file makes available — **inspect it, do not assume**);
  remove `depends_on: db`.
- **Files:** `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example`.
- **Accept:** `docker compose config` valid; `.env.example` documents that the DB is external and
  that `mistilteinn` / `mistilteinn_test` must pre-exist.
- **Tests:** none yet (DB does not exist until A.6).

### [x] A.5 — Remap host ports
- **Do:** backend `8000:8000` → `8001:8000`; frontend `4200:4200` → `4201:4200`. Update
  `CORS_ORIGINS` default in `backend/app/config.py` and the frontend API base URL.
- **Files:** `docker-compose.yml`, `backend/app/config.py`, `frontend/src/app/api/api.client.ts`.
- **Accept:** with the fairy stack running, `docker compose up -d backend` starts with no port
  conflict; `curl localhost:8001/api/v1/health` answers.

### [x] A.6 — Create the mistilteinn databases
- **Do:** in the running fairy Postgres container, `CREATE DATABASE mistilteinn;` and
  `CREATE DATABASE mistilteinn_test;` owned by the mistilteinn role (create the role if absent).
  Record the exact commands in `docs/LOG_mistilteinn.md` — this is manual, one-time infra.
- **Accept:** `psql -l` shows four databases (`fairy`, `fairy_test`, `mistilteinn`,
  `mistilteinn_test`); `DATABASE_URL` connects.

### [x] A.7 — Backend boot-time connect retry
- **Do:** the DB is no longer a `depends_on` we control, so add a bounded retry-with-backoff
  around initial engine connect. Fail loudly after the budget — never fall through to a
  half-started app.
- **Files:** `backend/app/database.py`, `backend/app/main.py`.
- **Accept:** backend started before the DB is reachable retries and then serves; started after,
  connects immediately.
- **Tests:** unit test on the retry helper with a mocked connect that fails N times.

### [x] A.8 — Wordmark, title, favicon → mistilteinn placeholder
- **Do:** `<title>Fairy</title>` → `mistilteinn`; brand wordmark → `mistilteinn`; sub-wordmark
  `ZZZ Optimizer` → `Genshin Optimizer`; remove the `fairy-emblem.webp` favicon link and delete
  the asset. **Leave `frontend/src/styles/_tokens.scss` untouched** — the Fairy palette stays
  until Chunk J supplies a Mitya-derived one (DESIGN §A4).
- **Files:** `frontend/src/index.html`, `frontend/src/app/app.html`,
  `frontend/public/fairy-emblem.webp` (delete).
- **Accept:** no rendered string says "Fairy"; no 404 for the favicon.

### [x] A.9 — Regenerate `frontend/openapi.json`
- **Do:** regenerate from the running backend rather than editing by hand.
- **Accept:** diff shows only the identifier/title change.

### [x] A.10 — Retarget CI
- **Do:** in `.github/workflows/test.yml`, drop the `validate_kits.py` invocations (the data they
  read was stripped) and the ZZZ-specific jobs. **Leave the job stanza in place, disabled, with
  a `TODO(chunk-H)` comment naming exactly which levels must be restored** — a silently removed
  gate is the failure mode this repo's CLAUDE.md calls out by name. Update the Postgres service
  credentials to the mistilteinn ones.
- **Files:** `.github/workflows/test.yml`.
- **Accept:** workflow YAML parses (`actionlint` or a push to the branch); the disabled gate is
  visible in the file with its restore condition written down.

### [x] A.11 — Gate the ZAP scan
- **Do:** `security/zap/` targets `mistilteinn.aetherus.dev`, which does not resolve. Add an
  explicit opt-in guard so the scan cannot report a false pass against a nonexistent host.
- **Files:** `security/zap/*`, `.github/workflows/security.yml`.
- **Accept:** scan is skipped-by-default and the skip is *reported as a skip*, not a pass.

### [x] A.12 — Chunk A close-out
- **Do:** `rg -il fairy --glob '!docs/**'` and confirm every remaining hit is deliberate
  provenance. Record the surviving list in `docs/LOG_mistilteinn.md`.
- **Accept:** backend boots on 8001 against the shared DB; `ruff check app/` clean; commit.

---

## Chunk B — Demolition

Each task below is **one commit**. Commit message form:
`refactor: delete ZZZ <group> (was fairy@76909c4:<path>) — replaced by <chunk>`

### [x] B.1 — Stage the port-reference set
- **Do:** move the six PORT-marked services into `backend/app/services/_ported/` and exclude that
  directory from `ruff`, from `pytest` collection, and from any runtime import:
  `optimizer_pipeline.py`, `disc_optimizer.py`, `damage_dag_service.py`, `rank_pipeline.py`,
  `build_damage_service.py`, `modifiers.py` + `buff_resolver.py`.
  Add `_ported/README.md` stating these are read-only porting source, which chunk consumes each,
  and that each file is **deleted when its port lands**.
- **Accept:** `rg -n "services\._ported" app/` returns only the README; ruff excludes it.

### [x] B.2 — Delete ZZZ services
- **Do:** delete all remaining `app/services/*.py` except `password.py`, `job_runner.py`,
  `__init__.py`, and `_ported/`. That includes `anomaly_simulator.py` (4,471 lines),
  `snapshot_builder.py`, `damage_calculator.py`, `combo_step_resolver.py`, `combo_types.py`,
  the `lumiflux*` trio, `disc_*`, `support_*`, `am_variants.py`, `channel_plan.py`,
  `resource_*`, `kit_formulas.py`, `modifier_loader.py`, `attribution.py`, `attributed_eval.py`,
  `stat_calculator.py`, `team_calculator.py`, `build_delta.py`, `buff_roster.py`,
  `rotation_cost.py`, `scorer_support.py`.
- **Accept:** `app/services/` contains only the keepers; no `app/` file imports a deleted module.

### [x] B.3 — Delete `app/formula/zzz/`
- **Do:** delete the directory (1,455 lines). Keep `formula/{__init__,builder,nodes,tags}.py`.
- **Accept:** `python -c "import app.formula"` succeeds; `app/pando/` still imports cleanly.

### [x] B.4 — Delete ZZZ models
- **Do:** delete `app/models/{agent,disc,w_engine}.py`; strip ZZZ members from
  `app/models/enums.py` (Element, Specialty, AttackType, Rarity, DiscSlot, StatType, the
  `*_ID_MAP`s, Potential*, HitMode) leaving only `UserStatus`; strip ZZZ columns/relationships
  from `app/models/build.py` (keep the `Build`/`EnemyProfile` skeletons for Chunk C to rewrite).
  Update `app/models/__init__.py`.
- **Accept:** `python -c "import app.models"` succeeds.

### [x] B.5 — Delete ZZZ schemas
- **Do:** delete `app/schemas/{agent,disc,w_engine,damage,optimizer,scorer,simulate,buff_preset,build}.py`.
  Keep `auth.py`, `common.py`, `optimization_job.py`, `team.py`. Update `__init__.py`.
- **Accept:** `python -c "import app.schemas"` succeeds.

### [x] B.6 — Delete ZZZ routes
- **Do:** delete `app/api/v1/{agents,discs,disc_sets,w_engines,damage,combos,simulate,scorer,optimizer,builds,buff_presets,enemies}.py`
  and their router registrations. Keep `auth.py`, `health.py`, `teams.py` (trim its ZZZ members).
- **Accept:** `uvicorn app.main:app` starts; `/docs` renders; `/api/v1/health` returns 200.

### [x] B.7 — Delete ZZZ repositories
- **Do:** delete `app/repositories/{agent,attack,disc,w_engine,buff_preset,build}.py`; trim
  `team.py`. Keep `base.py`, `optimization_job.py`, `session.py`, `user.py`.
- **Accept:** import clean; surviving repository tests pass.

### [x] B.8 — Delete the ZZZ data layer
- **Do:** delete every `app/data/importers/*.py` except `base_importer.py` (and strip
  `AnomalyStats` from it); delete `app/data/loaders/` entirely.
- **Accept:** `app/data/` holds `__init__.py`, `importers/{__init__,base_importer}.py`.

### [x] B.9 — Delete `scripts/dimbreath/` and the ZZZ scripts
- **Do:** delete `backend/scripts/dimbreath/` (Chunk E re-ports it from `/root/fairy`) and the
  ZZZ audit/backfill/icon/crossval scripts: `audit_*`, `backfill_*`, `bench_stateful.py`,
  `diag_ysg3.py`, `download_*_icons.py` (**note: these write into `/root/fairy/frontend/public/icons`
  — delete, never run**), `dump_crossval.py`, `inspect_monster.py`, `print_db_factions.py`,
  `refresh_kit_refs.py`, `scrape_nanoka_icons.py`, `seed_skill_overrides.py`,
  `snapshot_potential_deltas.py`, `sweep_nanoka_potential.py`, `sync_build_mindscapes.py`,
  `validate_kits.py`, `verify_mv_vs_nanoka.py`, `verify_zo_modifiers.py`.
  Keep `approve_user.py`, `set_password.py`, `bench_optimizer_checkpoints.py`; keep
  `seed_db.py` / `verify_seed.py` as **stubs to be rewritten in D.7/D.8**.
- **Accept:** `ls backend/scripts` matches the keep list.

### [x] B.10 — Delete migration history
- **Do:** delete all 39 files in `backend/alembic/versions/`. Leave `alembic/env.py` and
  `script.py.mako`. There is no production database to preserve.
- **Accept:** `alembic history` is empty; `alembic heads` reports none.

### [x] B.11 — Delete orphaned root-level ZZZ artifacts
- **Do:** delete `backend/all_multi_moves.txt`, `backend/inspect_multi_hits.py`, and root
  `create_user.py` / `set_pw.py` if they duplicate `scripts/` equivalents (**check first**).
- **Accept:** no untracked-purpose files left at `backend/` root.

### [x] B.12 — Triage the test suite
- **Do:** delete every test whose subject was deleted in B.2–B.11 (expect ~270 of ~304 files).
  **Preserve:** auth (`test_auth_*`), sessions, users, teams (trimmed), optimization jobs,
  repository base/owner-scoping, middleware (`test_rate_limit`, `test_body_size_limit`),
  `test_orphan_sweep`, `test_models` (rewritten in C), the `test_pando_*` set, and the
  formula-core tests. `tests/perf` is kept but marked skip until Chunk G re-baselines it.
- **Accept:** surviving suite is ~30–40 files; `pytest` collection reports no import errors.

### [x] B.13 — Chunk B exit gate **(hard gate)**
- **Do:** run the full surviving suite against `mistilteinn_test`, plus `ruff check app/`.
- **Accept:** **`pytest` green**, `ruff` clean, `uvicorn app.main:app` serves `/api/v1/health`
  and the auth endpoints. A red suite here blocks Chunk C — this is the point where "the tests
  are expected to fail" stops being true (DESIGN §3, Chunk B exit).
- **Do also:** update `CLAUDE.md`'s "Fork state" section — most of its warnings are now
  historical and a stale warning is worse than none.

---

## Chunk C — Genshin domain models, enums, initial migration

### [x] C.1 — Capture the enum ground truth
- **Do:** fetch and commit a sample of `character.json`, `weapon.json`, `artifact.json` (index
  level) under `backend/tests/fixtures/nanoka_gi/`, with the version and fetch date recorded.
  Derive the distinct `element` / `weapon` / `rank` value sets from the committed files, not from
  a live call.
- **Accept:** fixture files committed; a short note in the DESIGN or LOG lists the observed value
  sets, including `WEAPON_CROSSBOW` and the literal `"None"` element.

### [x] C.2 — `app/models/enums.py` rewrite
- **Do:** write `Element` (7 visions, Physical **excluded**), `DamageType`, `WeaponType` (6,
  including crossbow), `Rarity` (with the character `QUALITY_*` ↔ weapon integer-`rank` split
  normalized), `ArtifactSlot` (5-member `StrEnum`), `TalentType`, `StatType` from the observed
  `FIGHT_PROP_*` vocabulary. Every map carries a provenance comment naming the endpoint and
  version it was read from.
- **Accept:** unit tests assert each enum's membership against the committed fixture; an
  unmapped key produces a warning, never a silent drop.

### [x] C.3 — `characters` model
- **Do:** new `app/models/character.py` — `Character`, `Talent`, `TalentScaling`,
  `Constellation`, `AscensionPassive`, per DESIGN §2.5. **New file, new class names; do not
  edit the deleted `agent.py` back into existence.**
- **Accept:** import clean; type hints on all public members; `ruff` clean.

### [x] C.4 — `weapons` model
- **Do:** new `app/models/weapon.py` — `Weapon` with `weapon_type`, rarity, base ATK, sub-stat
  type/value, refinement rows R1–R5.

### [x] C.5 — `artifacts` model
- **Do:** new `app/models/artifact.py` — `ArtifactSet` (with the `need: [2,4]` piece thresholds
  and per-rank affix text observed in the payload) and `Artifact` (slot, main stat, substats,
  level, owner, build binding).
- **Accept:** slot→allowed-main-stat table lives here as data, not as `if` branches.

### [x] C.6 — `build` / `enemy_profile` rewrite
- **Do:** rewrite `app/models/build.py` for Genshin: 5 artifact slots, weapon FK, talent levels,
  constellation level. `EnemyProfile`: level and per-element RES; **no daze/anomaly columns**.

### [x] C.7 — Initial migration
- **Do:** `alembic revision --autogenerate -m "initial genshin schema"`; review the generated
  SQL by hand (autogenerate misses server defaults and JSONB details).
- **Accept:** `alembic upgrade head` on an empty `mistilteinn` DB succeeds; `downgrade base`
  reverses cleanly; re-running `autogenerate` produces an empty diff.

### [x] C.8 — Model round-trip tests
- **Do:** integration tests creating and reading one row per table against `mistilteinn_test`,
  including cascade deletes.
- **Accept:** green; coverage on `app/models/` ≥ 90%.

### [x] C.9 — Chunk C close-out
- **Accept:** `rg -n "agent|disc|w_engine|anomaly|mindscape|specialty|stun" app/models app/schemas`
  returns nothing outside comments. Commit; report.

---

## Chunk D — nanoka GI importer + seed

*Sub-branch `feat/nanoka-gi-importer`. Parallel-safe with Chunk E.*

### [x] D.1 — Port the importer transport layer
- **Do:** new `app/data/importers/nanoka_gi_importer.py`. Copy the manifest-pin → index-fetch →
  detail-fetch → upsert → stale-prune skeleton from `/root/fairy`'s `nanoka_importer.py`;
  swap `zzz` for `gi` in the URL grammar. **Transport only — no field mapping yet.**
- **Accept:** a dry-run mode fetches all four indexes and reports counts without writing.

### [x] D.2 — Commit a detail-payload sample **(do this before writing any mapping)**
- **Do:** save one full character, weapon, artifact, and monster detail payload under
  `backend/tests/fixtures/nanoka_gi/detail/`. Write a short key-map note in the LOG.
- **Accept:** fixtures committed; the note names where ascension stats, talent tables, and
  constellations actually live in the payload. **Every mapping task below reads this note, not
  the ZZZ importer's assumptions.**

### [x] D.3 — Character mapping
### [x] D.4 — Weapon mapping
### [x] D.5 — Artifact-set mapping
### [x] D.6 — Monster / enemy-profile mapping
- **Do (each):** map the committed fixture to the Chunk C models; unit-test the mapping against
  the fixture with no network; then run it live against the full index.
- **Accept (each):** unit test green offline; live run upserts and re-runs idempotently.

### D.7 — `seed_db.py` rewrite
- **Do:** orchestrate the four passes; write a seed-provenance row recording the nanoka version
  pinned (`manifest.json → gi.latest`) and the run timestamp.
- **Accept:** `cd backend && python -m scripts.seed_db` fills a cold `mistilteinn`; a second run
  is a no-op diff.

### D.8 — `verify_seed.py` rewrite
- **Do:** per-table row counts asserted against the index lengths, plus a handful of hand-checked
  anchor values that fail loudly on drift.
- **Accept:** green against the seeded DB; **fails** when an anchor is deliberately corrupted
  (prove the gate can fail — a gate never observed failing is not a gate).

### D.9 — Chunk D close-out
- **Accept:** roster present and queryable; `docs/LOG_mistilteinn.md` records the pinned version.

---

## Chunk E — YuanShenResources snapshot toolkit

*Sub-branch `feat/yuanshen-snapshots`. Parallel-safe with Chunk D.*

### E.1 — Port `fetch.py` with a GitLab adapter (pinned SHA, byte cache)
### E.2 — Port the TextMap `base ⊕ overwrite` merge + anchor assertion
### E.3 — Build the table catalog from `ExcelBinOutput/` (do not guess table names)
### E.4 — Port `build_column_dicts.py` / `build_upstream_mv.py` to the Genshin tables
### E.5 — Commit the first snapshot (avatar / weapon / reliquary) + `provenance.json`
### E.6 — Assert no gate, test, or importer reaches the network at run time

- **Accept (chunk):** `python -m scripts.yuanshen.fetch --lang en --merge` works and asserts its
  anchor; snapshots committed; `pytest` passes with networking disabled.

---

## Chunk F — Stats and the damage chain

*Sub-branch `feat/genshin-damage`. **Read DESIGN §3 Chunk F before starting.***

### F.1 — `formula/genshin/tags.py` (scope/tag vocabulary)
### F.2 — `formula/genshin/stats.py` (stat graph feeding `app/pando`)
### F.3 — `stat_calculator.py` — base curves, ascension, weapon, artifacts, EM
### F.4 — `formula/genshin/sheets.py` + `damage.py`
### F.5 — `damage_calculator.py` — base × (1+DMG%) × crit × DEF term × RES term
### F.6 — Amplifying reactions only (vape/melt) — **no transformative, no additive**
### F.7 — gcsim crossval fixture harness with `CROSSVAL_REQUIRE_DB=1` from the first commit
### F.8 — First crossval case green within a written, justified tolerance

- **Hard rule, every task:** no multiplier, coefficient, or curve written from memory. Each
  constant cites gcsim / KQM / Amber **at the line that introduces it**. A task that cannot
  produce a citation is **blocked** (`!`) and escalated, not guessed.
- **Coverage:** 100% on damage calculation per CLAUDE.md.

---

## Chunk G — Artifact optimizer + GOOD import

*Sub-branch `feat/artifact-optimizer`.*

### G.1 — `disc_optimizer.py` → `artifact_optimizer.py` (5 slots, fixed flower/plume mains)
### G.2 — Per-slot main-stat pools as data
### G.3 — `optimizer_pipeline.py` port (top-K / Pareto / budget-K intact)
### G.4 — `rank_pipeline.py` port
### G.5 — `good_importer.py` — GOOD schema validation, reject-don't-coerce on unknown keys
### G.6 — Optimizer + builds + artifacts API surface restored
### G.7 — Re-baseline `tests/perf` for the 5-slot search space
### G.8 — Delete the consumed files from `app/services/_ported/`

---

## Chunk H — Kit corpus, modifier DSL, validation harness **[Planner: own DESIGN doc first]**

Sketch: retarget the modifier DSL scope vocabulary → define the Genshin kit-JSON schema →
port `validate_kits.py` L0–L2/L4–L6/LR/LU → **restore the CI gate disabled in A.10** →
rewrite `.claude/agents/kit-{curator,auditor}.md` and `.claude/skills/kit-curation/` for
Genshin talents/constellations → **[Owner]** approve the ~20–30 character MVP roster cut
(BRIEF constraint 4).

## Chunk I — Rotation / combo model **[Planner: own DESIGN doc first]**

Sketch: gcsim frame-data harvest as a committed snapshot (Chunk E pattern) → on-field/off-field
model → swap cooldowns → burst energy and particle economy. Blocked on **OQ-M2**.

## Chunk J — Frontend rewrite + Mitya visual identity **[deferred]**

Sketch: **[Owner]** supply Mitya reference art (**OQ-P1**) → derive `_tokens.scss` palette the
way fairy derived its own from `references/NPC_Fairy.webp` → new emblem asset → rewrite the
disc-shaped pages (`discs`, `disc-slot-picker`, disc filters) as artifact pages.

**Now also a blocking obligation, not just a polish pass.** The SPA has **161 TypeScript
errors** against endpoints and schemas deleted in B.6, so `npm test` and `npm run build` both
fail. It compiled only while `frontend/openapi.json` was stale (44 declared paths against 7
served); regenerating it in the PR #1 review made the breakage visible.

Chunk J must therefore **restore the `Unit tests` step in `.github/workflows/test.yml`'s
`frontend` job**, currently `if: false` with a `TODO(chunk-J)`. Until then CI runs `npm run
lint` only. Do not restore it by letting the contract rot again —
`backend/tests/unit/test_openapi_contract_is_current.py` will fail if the committed spec stops
matching the app.

## Chunk K — Deploy **[deferred]**

Sketch: re-author `deploy-prod.yml` against a mistilteinn target → DNS for
`mistilteinn.aetherus.dev` → tunnel config → **[Owner]** confirm co-hosting (**OQ-M3**,
now cheaper: one Postgres, two databases, one extra backend container).

---

## Escalation

Per the global collaboration guide: a task failing 2+ times, or revealing that this file's spec
is ambiguous or contradictory, gets an `## ESCALATION` block appended to
`docs/LOG_mistilteinn.md` and a **stop**. Recommend switching to Opus (Planner) — or to Fable
(Brain) if the blocker is strategic rather than structural.

**The most likely escalation in this plan is F.x with a missing citation.** That is working as
designed: the citation rule exists because fairy shipped fabricated ones.
