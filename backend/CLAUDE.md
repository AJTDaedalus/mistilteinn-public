# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with the backend.

## Quick Start

```bash
cd backend && pip install -e ".[dev]" && pytest
```

## Project Layout

```
app/
  main.py           — FastAPI app factory with lifespan, CORS, router includes
  config.py         — pydantic-settings: DATABASE_URL, TESTING, LOG_LEVEL
  database.py       — create_async_engine, async_session_maker, get_db dependency
  dependencies.py   — DI factories: get_agent_repo, get_damage_service, etc.
  models/           — SQLAlchemy 2.0 Mapped models (one file per entity)
  schemas/          — Pydantic v2 request/response models (Create, Update, Read)
  repositories/     — Data access layer: BaseRepository[T] + entity-specific
  services/         — Business logic (no SQLAlchemy imports here)
  api/v1/           — Versioned route handlers, thin controllers
  data/importers/   — nanoka GI transport (nanoka_gi_importer) + payload mappings
tests/
  conftest.py       — async test DB session, test client, factory registration
  unit/             — Pure function tests, mocked dependencies
  integration/      — Tests hitting real async PostgreSQL
  factories/        — Factory Boy async factories for all models
```

## Key Patterns

### Repository Pattern
Every repository extends `BaseRepository[T]` which provides:
`get_by_id`, `get_all`, `create`, `update`, `delete`, `get_by_filters`.
Entity-specific repos add domain queries (e.g., `AgentRepository.get_by_element`).

### Service Layer
Services receive repositories via constructor injection.
Services contain all business logic. They NEVER import from sqlalchemy.
Services return Pydantic schemas, not ORM models.

### Pydantic Schema Conventions
- `{Entity}Create` — for POST bodies
- `{Entity}Update` — for PATCH bodies (all fields Optional)
- `{Entity}Read` — for responses (includes id, timestamps)
- `{Entity}Summary` — lightweight list responses

### Database Models
- All models inherit from `Base` (DeclarativeBase)
- Use `Mapped[type]` annotations (SQLAlchemy 2.0 style)
- Timestamps: `created_at`, `updated_at` with `server_default`
- UUIDs as primary keys (uuid7 for time-ordering)
- Enums stored as PostgreSQL ENUM types

### Testing Rules
- Write the test FIRST, then the implementation (TDD)
- Unit tests use `unittest.mock` to patch repositories
- Integration tests use a real PostgreSQL via Docker
- Use Factory Boy for all test data (never raw dict fixtures)
- Async tests: use `@pytest.mark.asyncio` and `async def`

## Damage Calculation Reference

**Not yet ported.** This section held fairy's ZZZ damage chain (standard + anomaly, stun area,
disc substat values). All of it is wrong for Genshin and was removed in the fork commit rather
than left to be mistaken for authority.

The Genshin chain — base DMG, amplifying reactions, transformative/additive reactions, DEF/RES
multipliers, level curves — belongs here once `docs/DESIGN_<feature>.md` establishes it, with
every coefficient cited to gcsim / KQM / Project Amber. **Do not write these formulas from
memory.** If you need fairy's ZZZ version for structural reference, it is in
`/root/fairy/backend/CLAUDE.md` and in the fairy repo.

## Data Values

Fairy's basis-point conventions were hakushin/ZZZ-specific and are gone. What the nanoka GI
importer (Chunk D) actually stores:

- **Fractions, not percents or basis points.** 10% RES is `0.1`; a 15% DMG bonus affix is
  `0.15`. That is how the source expresses them, and converting on the way in would mean
  every citation had to be re-checked against a converted number.
- **Talent multipliers are kept as published tables**, one row per level, with the `desc`
  format strings (`"1-Hit DMG|{param1:F1P}"`) beside the `param` list. Parsing them is Chunk
  F's job; a mis-parse there is then a bug in a parser rather than data that was lost on
  import.
- **Enemy `base_hp`/`base_atk`/`base_def` are curve bases, not level-90 stats.** The curve
  name is in `enemy_profiles.stat_curves`; the curve tables are Chunk E's.
- **Weapon `base_atk` and substat carry their `GROW_CURVE_*` name** for the same reason.
- **Absent is absent.** A `FIGHT_PROP_NONE` substat is stored as NULL, not as a substat worth
  zero; a passive gated by a condition rather than an ascension phase has a NULL gate, not a
  `0` that would claim it is ungated.

## Linting

Ruff with a comprehensive rule set, pinned to an exact version in `pyproject.toml` so the
local gate is the CI gate (#135). Run **exactly what CI runs**:

```bash
ruff check app/ tests/ scripts/seed_db.py scripts/verify_seed.py \
    scripts/capture_nanoka_fixtures.py scripts/yuanshen/ scripts/bench_optimizer.py \
    scripts/gcsim/ scripts/kernel/ scripts/inject.py scripts/ci_local.py \
    scripts/download_icons.py
```

`scripts/` as a whole is not linted — it carries ~65 pre-existing violations in unrelated
one-off scripts. Scripts something *depends on* are named individually instead, which is the
convention fairy used for its harness: an unlinted script that a gate runs is a gate nobody
trusts. Chunk D adds the first three (D.2/D.7/D.8), Chunk E `scripts/yuanshen/`, and Chunk G
`scripts/bench_optimizer.py` — the run behind `artifact_prefilter.SECONDS_PER_COMBINATION`.
fairy also named `scripts/validate_kits.py` and `scripts/refresh_kit_refs.py`; both were
deleted in B.9 and **have no Genshin replacement coming** — the kit-validation job they
served is retired, because gcsim implements the kits that harness existed to check. The
scripts named here beyond fairy's are `scripts/inject.py` and `scripts/ci_local.py`, added
with the verification tooling, and `scripts/download_icons.py` (N.1).

**This block drifted from CI once already** — it was three entries short while the prose
directly above claimed two of them were in it. Copy the `run:` line out of
`.github/workflows/test.yml` rather than editing this by hand; `python -m scripts.ci_local`
executes the workflow's own list, so it is the list that matters.

`app/services/_ported/` is excluded in `pyproject.toml`: it is read-only ZZZ porting source
that imports deleted modules, so linting it would be permanent noise.

**Do not run `ruff format`.** The backend is not formatter-clean (75 of 372 files would
change), and formatting it piecemeal spreads that churn through unrelated diffs instead of
one reviewable commit. Adopting it is a deliberate decision tracked in #142, together with
adding `ruff format --check` to CI; until then formatting is unenforced and left alone.

## API Versioning

All routes under `/api/v1/`. If breaking changes needed, create `/api/v2/`.

## Verification tooling

Two scripts exist because *checking the check* went wrong twice in one session, and both
times the harness reported something the run had not produced.

### `python -m scripts.ci_local` — run what CI runs, here

Reads `.github/workflows/*.yml` **at run time** and executes their steps. Add a step to CI
and it runs locally on the next invocation with no edit; delete one and it stops. There is no
second list to fall out of date, which is the whole point — "run what CI runs" degrades into
"run what I remember CI running" within a week, and the gap is invisible because everything
passes.

```bash
cd backend && python -m scripts.ci_local            # everything
cd backend && python -m scripts.ci_local --list     # the plan, without running it
cd backend && python -m scripts.ci_local --job frontend
cd backend && python -m scripts.ci_local --clean    # from a fresh clone of HEAD
```

**Adaptations are the only place a gate can go missing**, so each one carries a reason *and* a
precondition proving the thing it skips is genuinely present — skipping the
`mesa-vulkan-drivers` install on a box with no ICD would turn the GPU gate into a silent
no-op. `tests/unit/test_ci_local_covers_the_workflows.py` fails if a CI step is neither run
nor adapted, if an adaptation has no reason, or if a skip has nothing verifying its
justification.

**What it cannot do.** CI runs on a clean checkout on a machine that is not yours, and that
has caught two real bugs here: the WGSL gate passed locally because this box had
`mesa-vulkan-drivers` and runners did not, and `npm run typecheck` passed against a
gitignored, stale `api.types.ts` while CI failed. `--clean` recovers the second class by
cloning HEAD into a temp directory. It does **not** recover "a different machine". Green here
is not green there, and the summary line says so every run.

`pip-audit` is the sharpest example: `--local` audits the *environment*, and this box has 212
packages against the project's 20, so it reports 84 vulnerabilities in things the project does
not depend on. The adaptation audits `backend/` instead.

### `python -m scripts.inject` — mutation testing that refuses to guess

Break something on purpose and check a test notices. **Exit codes are inverted**: `0` when the
mutation is caught, `1` when it *survives* (a guard nobody is holding), `2` when the harness
cannot vouch for the run.

```bash
cd backend && python -m scripts.inject --file app/services/x.py \
    --old 'if value < 0:' --new 'if False:' --tests tests/unit/test_x.py
cd backend && python -m scripts.inject --spec docs/injections/some.json
```

It refuses rather than reports when the target is missing or ambiguous, when the suite was
already red, or when the source did not come back — the three ways the hand-rolled version
produced fiction. Its own meta-tests are `tests/unit/test_inject_harness.py`, and they caught
a real parsing bug in it on the first run.
