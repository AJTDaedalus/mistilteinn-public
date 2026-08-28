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

This tree is a fork of fairy `dev` @ 76909c4. **`docs/TASKS_mistilteinn.md` chunks A–G are
done, S is done, `TASKS_client_optimizer.md` is complete (PRs #31–#41), K is deployed, and
`docs/TASKS_rotation.md` R.0–R.6 is complete (PRs #50–#58).** Read each TASKS file's own
status banner rather than this paragraph — this one is a summary and summaries go stale,
which is why the numbers below name how to re-derive them.

**Every chunk in `TASKS_mistilteinn.md` is done**, and seven further plans have been written
and completed since. Each has its own file with its own status banner; read those rather than
this list.

| plan | delivered |
|---|---|
| `TASKS_client_optimizer.md` | the browser kernel — CPU, GPU, run corpus, retrieval (#31–#41) |
| `TASKS_rotation.md` | authoring rotations, compiled to gcsim (#50–#58) |
| `TASKS_teams_builds.md` | the build editor and team builder (#60–#65) |
| `TASKS_artifacts.md` | inventory, GOOD import, equipping, upgrade potential — closes G.9 (#67–#72) |
| `TASKS_multipliers.md` | talent multipliers, crossvalidated against gcsim (#73–#77) |
| `TASKS_optimizer.md` | the search surface (#78–#82) |
| `TASKS_loose_ends.md` | icons, and the stale-marker sweep (#84–#89) |

**The app is walkable end to end**: import a GOOD export, equip pieces to a build, assemble a
team, author a rotation, compile it to gcsim, search your own artifacts for the best five, and
ask why the winner won. The earlier notes here saying there was no reachable optimizer and no
way to make a team were true when written and are not now.

**Two chunks closed without being built.** **H** was superseded — gcsim already implements the
kits the corpus existed to curate — though its two markers survive, pointing at weapon passives
the damage chain does not model. **I's rotation-optimization half is closed by owner decision
(2026-08-25): rotations are authored, never optimized.** A user writes a rotation deliberately,
and one arrived at by search is not one they would recognise as theirs.

**What is genuinely open is one plan — `docs/TASKS_weapon_passives.md` — and the two
`TODO(chunk-)` markers it exists to close.** `rg "TODO\(chunk-"` is the inventory. It counted
**nine** before `TASKS_loose_ends.md`, seven of them naming a closed chunk; that sweep closed
the seven and left the two that name real, unbuilt work. **Every other plan in this repo has
zero open tasks.**

**Both markers now have a destination.** `TASKS_weapon_passives.md` is the open plan:
**242 of 260 weapons carry a passive and 5 are expressible in the damage chain as it stands**,
so by owner decision (2026-08-26, `docs/DECISIONS.md`) weapon comparison gets a **gcsim second
tier** rather than a hand-derived modifier model — deriving 237 conditions from refinement
prose is the fabricated-citation failure fairy actually suffered. `weapon_comparison` keeps
reporting `unmodelled_passives` until that ships, precisely so a caller cannot publish a
ranking it does not claim to have made.

**The cost figure in the escalation is wrong and the DESIGN says so.** It inferred ~14 s for
59 candidates from §6's **native, all-cores** 0.238 s/run. Measured against the committed
browser build, a 100-iteration 90-second rotation is **7.84 s single-threaded** — 59
candidates is **~7.7 minutes**. The decision holds; the interaction it implies does not. It is
a job with progress, never a request that blocks.

- **Both suites pass, with nothing skipped.** **1294 backend tests, 0 skipped**; **394
  frontend tests**; `create_app()` serves **38 paths**; the SPA has **14 routes plus a
  catch-all**. (The previous figures here — 1273 / 255 / 40 paths — were stale; the path
  count had never been 40. Re-derive rather than trust, which is what the commands below
  are for.) Re-derive rather than trust:
  `cd backend && python -m pytest -q`, `cd frontend && npm test`. Run CI's own gates rather
  than a remembered subset: `cd backend && python -m scripts.ci_local` reads
  `.github/workflows/*.yml` and executes them here — 20 gates, including the WGSL kernel,
  gcsim crossval, gitleaks and pip-audit. `--list` shows the plan; `--clean` runs from a
  fresh clone of HEAD. **A red suite is a regression, not the size of the port** — that
  excuse expired at B.13.
- **`npm test` is `ng test`, and the distinction matters.** It builds the app first; a bare
  `npx vitest run` skips that and every TestBed spec collapses — 53 failures that mean
  nothing. *Run what CI runs* applies to the command, not only to the suite.
- **The frontend compiles and is tested in CI.** It did not, at the fork: 161 TypeScript
  errors against endpoints B.6 deleted, hidden because `frontend/openapi.json` was stale and
  `npm run codegen` builds `api.types.ts` from that file. The contract is regenerated on
  every API change and guarded by `backend/tests/unit/test_openapi_contract_is_current.py`.
  Regenerate it in-process — `create_app().openapi()` — rather than by curling a running
  backend; the contract test builds the app the same way and needs no server.
- **The catalogue is seeded.** 19 tables across 14 migrations. `cd backend && python -m
  scripts.seed_db` fills them from nanoka GI **7.0.51** in ~10s (150 characters including all
  28 Traveler variants, 260 weapons, 65 artifact sets, 360 enemy profiles) and `python -m
  scripts.verify_seed` checks the result against the committed indexes and nine hand-read
  anchors. Readable at `/api/v1/{characters,weapons,artifact-sets,enemies}`; a GOOD export
  imports at `/api/v1/artifacts/import/good`; `/api/v1/builds/{id}/explain` and
  `/compare-weapons` run the Chunk F damage chain over it; `/api/v1/rotations` authors and
  compiles rotations.
- **Upstream nanoka has moved to 7.0.52 and this repo has not.** That is a deliberate pin, not
  drift: the committed fixtures, `nanoka_transport.FIXTURE_VERSION` and
  `verify_seed.FIXTURE_VERSION` all name **7.0.51**, and
  `tests/unit/test_capture_pinning.py` fails if they stop agreeing. Bumping it is a chunk of
  its own. **`capture_nanoka_fixtures.py` without `--version` follows upstream**, which is
  what it silently did in N.2 — pulling two characters at 7.0.52 into a 7.0.51 directory and
  rewriting three index files, one with real content changes. Pass the version.
- **Never emit `swap_delay=0` in a gcsim config.** gcsim queues a character swap to land
  `Delays.Swap` frames later, so at zero it **never lands** and any rotation touching a second
  character dies with *"requested next char X is not active and next action is not swap"*.
  `build_config` hardcoded it, so **every multi-character rotation this repo produced was
  unrunnable** — natively and in the browser alike — while solo rotations, which never swap,
  looked fine. Omitted now, inheriting gcsim's default of 1;
  `tests/unit/test_swap_delay_is_never_zero.py` pins it and
  `docs/RESEARCH_recipe_cost.md` §2 explains it. **The symptom is misleading**: `flush()`
  reports `index out of range [0] with length 0` while the real message is on `simulate()`'s
  return value, which is a *string* on failure.
- **A saved rotation is authored here and compiled to gcsim, never read back.** The compiler
  emits the `while 1` loop and a `.ready` gate on every step, because gcsim's two worst
  behaviours are silent: a bare action list runs **once**, and `while 1` **deadlocks** on an
  ungated action — both producing a plausible config with exactly one burst in it.
  `rotation_signature` and `compile_rotation` share `_resolve`, and `gcsim_config.target_fields`
  backs both the rendered target and the hashed one, so a cache key and the config it was
  cached from cannot describe different things.
- **A seeded database says which patch it is.** `seed_runs` holds one append-only row per
  seed run: version pinned, per-entity counts, failed ids, and whether the run finished.
  `succeeded` is written `False` first and flipped at the end, so a run that died half way
  does not look complete. **Query it before trusting a stale checkout's database.**
- **A seed refuses to prune an implausible share of a table.** If an index comes back empty
  or truncated — a valid HTTP 200 that no retry can detect — deleting every row would take
  each user's builds with it through `ON DELETE CASCADE`. The pass reports `PRUNE REFUSED`,
  exits non-zero and deletes nothing; `python -m scripts.seed_db --force-prune` is the
  override for when a patch really did retract that much and someone has read the numbers.
- **The damage chain is verified against gcsim, not merely cited to it.**
  `pytest tests/crossval` recomputes a committed gcsim run and matches it to **1.3e-8**,
  inside the argued `1e-7` — the tolerance and the residual are explained in
  `docs/CROSSVAL_gcsim.md`, and a test proves the tolerance cannot hide a formula error.
  **It is not an exact match, and nothing here should say it is**: the residual is real,
  understood, and the reason the tolerance is not zero. **CI runs it with
  `CROSSVAL_REQUIRE_DB=1`, so a skip is a failure** — that is the gate fairy shipped a stale
  golden fixture without. The harness seeds itself from the committed nanoka fixtures through
  the real importer, so it needs no network.
- **Two deliberate divergences from gcsim** are recorded in `docs/CROSSVAL_gcsim.md`: the
  RES curve is continuous at exactly 0.75 (gcsim's `>` looks like a `>=`), and crit is
  computed rather than rolled. A crossval mismatch landing on either is not a formula error
  here.
- **Enemy base stats are curve bases, not level-90 stats.** A Hilichurl's `base_hp` is
  `13.584`; the growth curve is named in `enemy_profiles.stat_curves` and the curve table is
  `app/data/yuanshen/snapshot/growth_curves.json` (E.5). Anything that multiplies those
  numbers and calls the result damage without applying the curve is wrong.
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
- ~~**`app/services/_ported/` is read-only porting source.**~~ **Gone in G.1.** Three of the
  five remaining files were marked *ported* in its own table and its own rule was to delete
  each when its port landed; the other two were staged for **Chunk H**, which is closed, and
  the plan that replaced it transcribes from **gcsim's Go** rather than fairy's ZZZ modifier
  DSL. Nothing was left with a consumer. `docs/PORT_zzz_disposition.md` keeps the table, and
  `/root/fairy` plus git history keep the code.
- **Do not "fix" ZZZ code to make it run.** Per the BRIEF: *delete* ZZZ concepts rather than
  aliasing them. Leaked ZZZ shapes in the Genshin domain model are the fork strategy's main
  long-term hazard.
- **`rg "TODO\(chunk-"` is the inventory of what is deliberately unfinished — two markers,
  both `TODO(chunk-H)`.** It counted nine before `TASKS_loose_ends.md`, seven of them naming a
  closed chunk, which is a worse failure than it sounds: **an inventory of open work that
  counts finished work is the reason a reader looks somewhere else.** The sweep closed the
  seven — one of which claimed a DI factory was missing forty lines above where it is defined.

  The two that remain are about weapon and character passives the Chunk F chain does not
  model. `weapon_comparison` carries `unmodelled_passives` precisely so a caller cannot
  publish a ranking it does not claim to have made — **it is not a precision caveat, the
  ordering itself can be wrong.** N.5 measured the gap: **242 of 260 weapons carry a passive
  and 5 are expressible today**, because nine of the rest ask about target state
  (`KernelTarget` is level, resistance, DEF reduction and DEF ignore — no aura, no enemy type,
  no weak spot), which makes them *unaskable questions rather than unimplemented ones*.
  **Where that work lands is escalated, not resolved**, so the markers stay pointed at H
  rather than at a chunk that does not exist yet.
- **Two verification harnesses exist because checking the check went wrong twice.**
  `python -m scripts.ci_local` runs what CI runs, parsed from the workflow files at run time.
  `python -m scripts.inject` is mutation testing with inverted exit codes — `0` caught, `1`
  survived, `2` cannot vouch — and it **refuses** rather than reports when the target is
  missing or ambiguous. Both are documented in `backend/CLAUDE.md`.

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
  **Resolved in A.10 and retired since:** the job sat `if: false` until Chunk S found gcsim
  already implements the kits the corpus existed to curate. The stanza where it stood now
  records where each validation level went — L6's coverage question became
  `tests/unit/test_gcsim_character_coverage.py`, L1/L2's citation discipline became snapshot
  provenance, LC became `tests/crossval`. `validate_kits.py` was deleted in B.9.
- ~~`docs/DEPLOY.md` — fairy's runbook; hosts, tunnel config, and DB names are fairy's.~~
  **Resolved in K:** rewritten for this stack — `mistilteinn-prod` runner, own Postgres,
  own tunnel, `/home/ubuntu/mistilteinn`.
- ~~`docker-compose.yml` binds host ports **5432 / 8000 / 4200**, the same as fairy.~~
  **Resolved in A.4/A.5:** there is no `db` service any more (mistilteinn uses fairy's
  Postgres server and owns separate databases in it), and the host ports are **8001 / 4201**.
  Both stacks run simultaneously.
- ~~**Package and project identifiers still say `fairy`.**~~ **Resolved in A.1/A.2/A.12.**
  Surviving `fairy` hits are deliberate: the shared-Postgres wiring in `docker-compose.yml`,
  and upstream provenance in prose. ~~`frontend/src/styles/_tokens.scss` (the Fairy
  palette)~~ **resolved in J:** the palette is sampled from the Mitya references and the
  emblem is his ornament (#46).
- ~~**`backend/scripts/download_*_icons.py` write into the other repo.**~~ **Resolved in B.9:**
  all four were deleted unrun. **N.1 wrote a Genshin replacement**, `scripts/download_icons.py`
  — one script, not four, vendoring from `https://static.nanoka.cc/assets/gi/` into
  `frontend/public/icons/`. **The icons are gitignored and not committed** (OQ-N1): the run
  vendored **472 of 475**, all reproducible from this script and a seeded database, and a
  repository is not a CDN. Take that 475 from the script's own run, not from a query over
  `{characters,weapons,artifact_sets}.icon` — those columns hold 449 distinct basenames,
  because Travelers share art and set icons expand per slot.
  A **404 is `absent_upstream`, not a failure** — some catalogue rows genuinely have no art,
  and exiting non-zero on those would make the script cry wolf. **Prod therefore ships with no
  icons until the script runs there**; `docs/DEPLOY.md` §5a says so, and that is deliberately
  not automated.

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
  (both directories were stripped). The icons directory exists again as of N.1 —
  gitignored, filled by `scripts/download_icons.py` — and needs no mount restored: the
  frontend service bind-mounts `./frontend:/app` wholesale, so `public/icons/` arrives through
  that. The stripped mount was always redundant with it. ~~healthcheck now uses `${POSTGRES_USER}`~~ — **superseded
  in A.4:** there is no `db` service, so no healthcheck and no `POSTGRES_*` variables; the
  three of them were removed from `.env.example` because nothing read them any more.

## Tech Stack

Unchanged from fairy (a deliberate BRIEF decision):

- **Backend**: FastAPI + SQLAlchemy 2.0 async + PostgreSQL + Alembic
- **Frontend**: Angular 21, standalone components, signals — see `frontend/CLAUDE.md`.
  No longer deferred: it compiles, it is tested in CI, and it serves thirteen routes plus a
  catch-all.
- **Infrastructure**: Docker Compose (backend + frontend here; **no `db` service** — see
  §Database)
- **Deploy**: **live at `https://mistilteinn.aetherus.dev`**, alongside `fairy.aetherus.dev`
  on one host (2026-08-24). Separate compose projects, separate networks, **no host ports on
  either**, and mistilteinn owns its Postgres in prod because fairy's publishes none. Pushes
  to `dev` auto-deploy via a `mistilteinn-prod` self-hosted runner. `docs/DEPLOY.md`. **Prod runs its own Postgres**: fairy's prod publishes no host port, so the dev
  arrangement of borrowing its container cannot work there. And **never join fairy's compose
  network** — it once had fairy's tunnel serving this API, and
  `tests/unit/test_prod_stack_can_coexist_with_fairy.py` now enforces that

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
