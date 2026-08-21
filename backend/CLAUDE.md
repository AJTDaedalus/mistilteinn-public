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
  data/importers/   — Hakushin + Dimbreath + scanner import adapters
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

**Not yet ported.** Fairy's basis-point conventions were hakushin/ZZZ-specific (skill
multipliers, monster RES, disc substat rolls). Genshin's importer conventions get documented
here as the importers are written.

## Linting

Ruff with a comprehensive rule set, pinned to an exact version in `pyproject.toml` so the
local gate is the CI gate (#135). Run **exactly what CI runs**:

```bash
ruff check app/ tests/
```

`scripts/` as a whole is not linted — it carries ~65 pre-existing violations in unrelated
one-off scripts. fairy additionally named `scripts/validate_kits.py` and
`scripts/refresh_kit_refs.py` so the two the harness depended on could not rot unlinted; both
are deleted in B.9 and their Genshin replacements are re-added to this command in Chunk H
(see the `TODO(chunk-H)` on the Ruff step in `.github/workflows/test.yml`).

`app/services/_ported/` is excluded in `pyproject.toml`: it is read-only ZZZ porting source
that imports deleted modules, so linting it would be permanent noise.

**Do not run `ruff format`.** The backend is not formatter-clean (75 of 372 files would
change), and formatting it piecemeal spreads that churn through unrelated diffs instead of
one reviewable commit. Adopting it is a deliberate decision tracked in #142, together with
adding `ruff format --check` to CI; until then formatting is unenforced and left alone.

## API Versioning

All routes under `/api/v1/`. If breaking changes needed, create `/api/v2/`.
