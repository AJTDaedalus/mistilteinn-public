# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mistilteinn is a Genshin Impact build optimizer + rotation simulator, forked from
[fairy](https://github.com/AJTDaedalus/fairy) (the ZZZ optimizer) and reusing its engine with a
rewritten domain layer.

**Read `docs/BRIEF_mistilteinn.md` and `docs/RESEARCH_genshin_port.md` first** — they are the
founding documents (goals, non-goals, approach, tool decisions, constraints handed to Planner)
and nothing in this repo overrides them.

## Repo state — read before trusting anything here

This tree is a fork of fairy `dev` @ 76909c4. **Chunks A, B, C, D and E of
`docs/TASKS_mistilteinn.md` are done:** the ZZZ domain layer is deleted, the infrastructure
core is green, the Genshin domain models exist, the nanoka GI importer seeds them, and the
committed YuanShenResources snapshot supplies what nanoka does not publish. **Chunk F — the
damage chain — is next, and is what all of that was for.**

- **The backend suite passes.** 437 tests, 1 skipped (`tests/perf`, awaiting G.7).
  `ruff check app/ tests/ scripts/seed_db.py scripts/verify_seed.py
  scripts/capture_nanoka_fixtures.py scripts/yuanshen/` is clean — that is CI's exact
  command — and
  `uvicorn app.main:app` serves `/api/v1/health`, `/docs`, and the auth and team endpoints.
  **A red backend suite is now a regression, not the size of the port** — that excuse
  expired at B.13.
- **The frontend does not compile, and that is the honest state.** 161 TypeScript errors
  against endpoints and schemas B.6 deleted. It was green until the PR #1 review only
  because `frontend/openapi.json` was stale — `npm run codegen` builds `api.types.ts` from
  that file, so the SPA type-checked against a contract describing 44 endpoints while the
  backend served 7. The contract is now regenerated and guarded by
  `backend/tests/unit/test_openapi_contract_is_current.py`. CI runs `npm run lint` only;
  `npm test` is a disabled step with a `TODO(chunk-J)`. **Chunk J is what makes it compile.**
- **The catalogue is seeded; the behaviour on top of it is not built.** 18 tables across six
  migrations — characters, talents, talent scalings, constellations, ascension passives,
  weapons, refinements, artifact sets, set affixes, artifacts, builds, enemy profiles, seed
  runs, plus the infrastructure core. `cd backend && python -m scripts.seed_db` fills them
  from nanoka GI **7.0.51** in ~10s (150 characters including all 28 Traveler variants, 260
  weapons, 65 artifact sets, 360 enemy profiles) and `python -m scripts.verify_seed` checks
  the result against the committed indexes and nine hand-read anchors. There is still **no
  damage chain and no optimizer**, and the API still serves seven paths — nothing in the
  seeded data is exposed over HTTP yet.
- **A seeded database says which patch it is.** `seed_runs` holds one append-only row per
  seed run: version pinned, per-entity counts, failed ids, and whether the run finished.
  `succeeded` is written `False` first and flipped at the end, so a run that died half way
  does not look complete. **Query it before trusting a stale checkout's database.**
- **A seed refuses to prune an implausible share of a table.** If an index comes back empty
  or truncated — a valid HTTP 200 that no retry can detect — deleting every row would take
  each user's builds with it through `ON DELETE CASCADE`. The pass reports `PRUNE REFUSED`,
  exits non-zero and deletes nothing; `python -m scripts.seed_db --force-prune` is the
  override for when a patch really did retract that much and someone has read the numbers.
- **Enemy base stats are curve bases, not level-90 stats.** A Hilichurl's `base_hp` is
  `13.584`; the growth curve is named in `enemy_profiles.stat_curves` and the curve table is
  `app/data/yuanshen/snapshot/growth_curves.json` (E.5). **Nothing applies them yet** —
  wiring base × curve into a stat is Chunk F. Anything that multiplies those numbers today
  and calls the result damage is wrong.
- **`app/models/artifact.py:MAIN_STAT_POOL` is populated from the committed snapshot** —
  `app/data/yuanshen/snapshot/artifact_main_stat_pools.json`, E.5. It is *derived*, and the
  derivation refuses to resolve anything it cannot pin: read
  `scripts/yuanshen/build_snapshot.py:derive_main_stat_pools` before touching it, and
  rebuild with `python -m scripts.yuanshen.build_snapshot` rather than editing the JSON.
  `main_stats_for()` still raises on an empty pool.
- **The YuanShen data is a committed snapshot, never a live fetch.** `app/data/yuanshen/`
  holds `schema/` (provenance + the 1,935-table catalog) and `snapshot/` (main-stat pools,
  artifact value tables, growth curves); `cache/` is the gitignored working copy and the
  54 MB TextMap lives only there. The unit lane runs with `socket.connect` blocked and
  asserts by parsed imports that nothing in `app/` imports the toolkit (E.6).
- **`app/services/_ported/` is read-only porting source, not runtime code.** Eight ZZZ
  modules staged in B.1/B.3 for Chunks F, G and H to port *against*, excluded from ruff and
  pytest, with no `__init__.py` so they are not importable. Each is deleted when its port
  lands — see that directory's README.
- **Do not "fix" ZZZ code to make it run.** Per the BRIEF: *delete* ZZZ concepts rather than
  aliasing them. Leaked ZZZ shapes in the Genshin domain model are the fork strategy's main
  long-term hazard. This applies with full force to Chunk C: new files, new class names, no
  column that exists because its ZZZ counterpart did.
- **What is deliberately unfinished** is marked in-place with `TODO(chunk-X)` naming the task
  that finishes it — the disabled CI kit-validation gate, the two `scripts/` stubs that exit
  non-zero, the removed DI factories, the skipped perf baseline, the 401-sweep table in
  `tests/integration/test_auth_endpoints.py`. `rg "TODO\(chunk-" ` is the inventory.

`docs/LOG_mistilteinn.md` records every task, including the findings that contradicted the
plan. Read it before assuming DESIGN is describing the current tree.

### What was stripped in the fork commit

| Removed | Why |
|---|---|
| `references/` | ZZZ community docs (Leifa anomaly/stun references), ZO exports, screenshots |
| `backend/app/data/{modifiers,skill_overrides,moves,atlas,validation}` | ZZZ kit corpus + validation ledgers |
| `backend/app/data/dimbreath/` | ZZZ upstream snapshots (Genshin's equivalent is AnimeGameData) |
| `backend/app/data/core_stats_overrides.yaml` | ZZZ per-agent overrides |
| `frontend/public/icons/` | ZZZ agent art |
| `docs/*` except `DEPLOY.md` | fairy's feature-cycle docs (BRIEF/DESIGN/TASKS/LOG/RESEARCH/MAP) |

Everything stripped still exists in `/root/fairy` and in the fairy repo — copy anything back
that turns out to be worth porting rather than re-deriving.

### Carried over but NOT ported

- `.claude/agents/kit-{curator,auditor}.md` and `.claude/skills/kit-curation/` — the curation
  pipeline the BRIEF wants ported. Still written entirely against ZZZ kits.
- ~~`.github/workflows/` — still dispatches fairy's kit-validation harness.~~
  **Resolved in A.10:** the `kit-validation` job is `if: false` with a `TODO(chunk-H)` block
  naming every level to restore; `validate_kits.py` itself was deleted in B.9.
- `docs/DEPLOY.md` — fairy's runbook; hosts, tunnel config, and DB names are fairy's.
- ~~`docker-compose.yml` binds host ports **5432 / 8000 / 4200**, the same as fairy.~~
  **Resolved in A.4/A.5:** there is no `db` service any more (mistilteinn uses fairy's
  Postgres server and owns separate databases in it), and the host ports are **8001 / 4201**.
  Both stacks run simultaneously.
- ~~**Package and project identifiers still say `fairy`.**~~ **Resolved in A.1/A.2/A.12.**
  Surviving `fairy` hits are deliberate: the shared-Postgres wiring in `docker-compose.yml`,
  upstream provenance in prose, and `frontend/src/styles/_tokens.scss` (the Fairy palette
  stays until Chunk J supplies a Mitya-derived one — DESIGN §A4).
- ~~**`backend/scripts/download_*_icons.py` write into the other repo.**~~ **Resolved in B.9:**
  all four were deleted unrun.

### Database

The `mistilteinn` and `mistilteinn_test` databases live in the **fairy stack's Postgres
container** (DESIGN §A3) and were created by hand in A.6 — nothing in this repo creates them.
`docker compose up` needs `fairy-db-1` running. The backend reaches it over the **host
gateway** (`host.docker.internal:5432`), not by joining fairy's compose network — joining it
registered this backend under the alias `backend` on `fairy_default`, where fairy's own
`backend` service already lives, so fairy's tunnel would have intermittently served
mistilteinn's API. If the database is down the app says so and retries before failing loudly
(`app/database.py`, A.7).

Host ports are **8001** (backend) and **4201** (frontend), so both stacks run at once.

### Changed in the fork commit

- `.github/workflows/deploy-prod.yml` **deleted** — it targeted the `fairy-prod` self-hosted
  runner and `/home/ubuntu/fairy`, so running it from this repo would have redeployed fairy's
  production directory. Re-author it when mistilteinn has its own deploy target.
- DB identity renamed fairy → mistilteinn in `.env.example`, `backend/app/config.py` (default
  URL), and `.github/workflows/test.yml` (service-container credentials).
- `security/zap/` retargeted from `fairy.aetherus.dev` to `mistilteinn.aetherus.dev`. The scan
  is gated behind `security/zap/run-baseline.sh` (A.11): opt-in via `ZAP_SCAN_ENABLED=1`, and it
  refuses to scan a target that is not serving. Note the host **does** resolve —
  `aetherus.dev` has wildcard DNS onto Cloudflare — so "it does not resolve" is not the check;
  it answers `525` because there is no origin behind it yet.
- `docker-compose.yml`: dropped the `./references` and `./frontend/public/icons` bind mounts
  (both directories were stripped). ~~healthcheck now uses `${POSTGRES_USER}`~~ — **superseded
  in A.4:** there is no `db` service, so no healthcheck and no `POSTGRES_*` variables; the
  three of them were removed from `.env.example` because nothing read them any more.

## Tech Stack

Unchanged from fairy (a deliberate BRIEF decision):

- **Backend**: FastAPI + SQLAlchemy 2.0 async + PostgreSQL + Alembic
- **Frontend**: Angular (deferred — backend-first development)
- **Infrastructure**: Docker Compose (db, backend, frontend containers)
- **Deploy**: Cloudflare Tunnel, target `mistilteinn.aetherus.dev`

## Data Source of Truth

**The PostgreSQL database is the single source of truth for all game data** — this rule ports
over from fairy unchanged and is load-bearing.

- **Always query the DB first** when you need character/weapon/artifact data. Never hardcode or
  manually derive element, weapon type, or other metadata. Fill it with
  `cd backend && python -m scripts.seed_db` (Chunk D) and check it with
  `python -m scripts.verify_seed`; `seed_runs` records which patch it holds.
- Static JSON files (modifier configs) are supplementary artifacts derived from DB data — they
  do not replace or override the DB.
- Planned sources per the BRIEF: gi.hakush.in + Project Amber (ambr.top) as the live importers;
  Dimbreath AnimeGameData as **committed snapshots only**, never a live-fetch gate; GOOD format
  for user artifact import; gcsim as the crossval oracle.

## Docker Commands

```bash
docker start fairy-db-1             # The database lives in the FAIRY stack (see §Database)
docker compose up -d                # Start this stack (backend :8001, frontend :4201)
docker compose exec backend alembic upgrade head   # Run migrations
docker compose run --rm backend pytest             # Run tests
docker compose run --rm backend ruff check app/    # Lint
docker compose down                 # Stop containers (the database is not ours to stop)
```

There is **no `db` service here** — `docker compose up -d db` fails with
`no such service: db`. The backend reaches the shared Postgres over the host gateway
(`host.docker.internal:5432`) and deliberately does *not* join fairy's compose network; the
header of `docker-compose.yml` explains why.

**Generate Alembic revisions on the host, not in the container.**
`docker compose run --rm backend alembic revision --autogenerate` fails with
`PermissionError` on `/app/alembic/versions/` — the image runs as a non-root user against a
root-owned bind mount. `upgrade` and `downgrade` work fine in the container.

### Frontend dependency changes — gotcha

The frontend service uses anonymous volumes to shadow `node_modules` and `.angular`. Those
volumes **persist across container recreation**, so a plain `up -d --build` reuses the stale
one and new deps are missing in the running container. Whenever `frontend/package.json` or
`package-lock.json` changes:

```bash
docker compose up -d --build --force-recreate --renew-anon-volumes frontend
```

## Local Development (conda)

```bash
cd backend && pip install -e ".[dev]"
pytest
ruff check app/
```

`ruff` and `pytest` are pinned to exact versions in `backend/pyproject.toml` so that "run
`ruff check` before every commit" means the same program CI runs.

### `backend/build/` is a stale shadow copy of `app/` — never search it

`pip install -e .` leaves a full duplicate of every module under `backend/build/lib/app/`. It
is gitignored but can be weeks behind source, and a call-site audit that picks up those files
gets phantom hits for code that no longer exists. Use `rg` (respects `.gitignore`) rather than
plain `grep -rn`, or scope the search to `backend/app backend/tests`.

### Run backend scripts as `python -m`, never by file path

`python backend/scripts/foo.py` sets `sys.path[0]` to `backend/scripts/`, so `import app` falls
through to the editable install — which points at whatever checkout was installed, not the tree
you are looking at. Always `cd backend && python -m scripts.<name>`, matching CI.

## Architecture

**Legibility is a product goal (DESIGN §1 A6, owner ruling).** gcsim and Genshin Optimizer
are the references for correctness and feature scope, **not** for code structure — logic
nobody can follow is logic nobody can check. Four standing constraints on Chunks F-I:
characters are modelled as **data a shared evaluator reads**, never per-character branches in
the damage chain; each mechanic (reactions, DEF/RES terms, curves, snapshot timing) has
**one** implementation everything reuses; a damage number must be able to **explain itself**
— which multipliers applied, in what order, from where; and speed comes from the search
strategy and a clean model, not from inlined special cases nothing else can reuse. This costs
implementation speed in F and H on purpose. It does not override the citation rule: an
explainable wrong number is still wrong.

- **Repository pattern** for data access — no raw queries in services
- **Service layer** for business logic — no SQLAlchemy imports in services
- **Pydantic v2 schemas** for all API I/O validation
- **Dependency injection** via FastAPI `Depends()`
- All database operations are **async** (asyncpg driver)
- API versioned under `/api/v1/`

## Domain: Genshin Impact

Modelled in Chunk C (`app/models/{character,weapon,artifact,build}.py`, enums in
`app/models/enums.py`). **Every enum value and column was read off the committed fixtures in
`backend/tests/fixtures/nanoka_gi/`** (nanoka 7.0.51), never from memory, and
`tests/unit/test_genshin_enums.py` asserts them against those files. Extend the same way:
commit the payload, then derive.

See
`docs/BRIEF_mistilteinn.md` ("Constraints handed to Planner") for the phase order:
domain models/importers → damage chain + crossval → optimizer/GOOD → gauge sim → kit corpus.

**Do not write damage or reaction formulas from memory.** Every multiplier, reaction
coefficient, and level curve must be sourced from gcsim, KQM, or Project Amber and cited in
the code or the DESIGN doc that introduces it. Fairy's hardest-won lesson was fabricated
citations in curated data — do not import that failure mode into this repo.

## Code Conventions

- Python: PEP 8, enforced by Ruff
- All public functions must have type hints
- No business logic in route handlers — delegate to services
- Every feature gets tests FIRST (TDD)
- Commit messages: conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`)
- **Fix pre-existing lint errors in files you touch**
- **Fix pre-existing failing tests in scope** — but see the fork-state warning above: a ZZZ
  test failing because its data was stripped is not "in scope", it is the port.

## Git Workflow

- **Commit atomically as you go — do not wait to be asked.** This project overrides Claude
  Code's default "only commit when explicitly asked" behavior: on a feature/fix branch
  (never `dev`/`main`), once a logical unit of work is complete and clean, commit it right
  away. This is a standing authorization for the *timing* of ordinary commits on the current
  branch — it does not extend to pushing, merging, force operations, or anything on
  `dev`/`main`, all of which still require the user to ask.
- **Test before committing when the change is big enough to warrant it.** For anything that
  touches logic or more than a couple of files, run the relevant tests and `ruff check` first
  — a commit should represent a *verified* unit of work, not just a completed one.
- **Commit early and often** — each commit should be atomic (one logical change)
- **Never bundle unrelated changes** in a single commit
- Branch naming: `feat/<short-description>`, `fix/<short-description>`, `refactor/<short-description>`
- Feature branches off `dev`, merge to `dev` via PR. `main` is for releases only.
- **No direct commits to `dev` or `main`.** All work happens on a feature/fix branch; `dev` is
  updated only by PR merge after review. Verify `git branch --show-current` before every commit.
- **Every DESIGN doc (`docs/DESIGN_<feature>.md`) must include a "Branch policy" section** near
  the top that names the branch, restates the no-direct-`dev`/`main` rule, lists sub-branches if
  the feature has parallel tracks, and points at Task 0 of its TASKS file as the branch-setup
  gate.
- Run `ruff check` and `pytest` before every commit — code must pass lint and tests
- Keep commits buildable: every commit should leave the project in a working state

### Gate discipline ported from fairy (apply as the equivalents are built)

Two rules cost fairy real incidents and should be honored from day one here — the BRIEF calls
this "process parity":

1. **A skipped check BLOCKS. It is never a pass.** A validation level that could not run
   (no seeded DB, missing fixture) means *could not check*, not *checked and clean*. Fairy's
   crossval suite was green-by-absence on CI for months and shipped a stale golden fixture.
   Build require-DB modes in from the start (`CROSSVAL_REQUIRE_DB=1`-style guards) rather than
   retrofitting them.
2. **The agent RUNS the harness; it never reasons in its place.** A model answering a
   ground-truth question from the same JSON file where the error lives will confirm the error.
   Query the DB; do not infer.

## Testing

- **Unit tests**: `backend/tests/unit/` — pure logic, mocked DB
- **Integration tests**: `backend/tests/integration/` — real DB via Docker
- **Fixtures**: Factory Boy factories in `backend/tests/factories/`
- Target: >90% coverage on services, 100% on damage calculation

## Session Cadence

After completing each task from a TASKS file, **stop and report** what was done and what the
next task is. Do not continue to the next task without user confirmation.

**Handoff Blurb Policy**: Whenever finishing a major task in a design doc, provide a structured
handoff blurb summarizing current state, branch details, tasks completed, and the immediate next
task, so the user can paste it into a new conversation.
