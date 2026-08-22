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
    scripts/capture_nanoka_fixtures.py scripts/yuanshen/ scripts/bench_optimizer.py
```

`scripts/` as a whole is not linted — it carries ~65 pre-existing violations in unrelated
one-off scripts. Scripts something *depends on* are named individually instead, which is the
convention fairy used for its harness: an unlinted script that a gate runs is a gate nobody
trusts. Chunk D adds the first three (D.2/D.7/D.8), Chunk E `scripts/yuanshen/`, and Chunk G
`scripts/bench_optimizer.py` — the run behind `artifact_prefilter.SECONDS_PER_COMBINATION`.
fairy also named
`scripts/validate_kits.py` and `scripts/refresh_kit_refs.py`; both are deleted in B.9 and
their Genshin replacements are re-added to this command in Chunk H (see the `TODO(chunk-H)`
on the Ruff step in `.github/workflows/test.yml`).

`app/services/_ported/` is excluded in `pyproject.toml`: it is read-only ZZZ porting source
that imports deleted modules, so linting it would be permanent noise.

**Do not run `ruff format`.** The backend is not formatter-clean (75 of 372 files would
change), and formatting it piecemeal spreads that churn through unrelated diffs instead of
one reviewable commit. Adopting it is a deliberate decision tracked in #142, together with
adding `ruff format --check` to CI; until then formatting is unenforced and left alone.

## API Versioning

All routes under `/api/v1/`. If breaking changes needed, create `/api/v2/`.
