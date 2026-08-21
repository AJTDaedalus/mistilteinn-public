# Mistilteinn

A Genshin Impact build optimizer and rotation simulator — artifact optimization evaluated
*through* a stateful reaction simulator, rather than against a static multiplier sheet.

Forked from [fairy](https://github.com/AJTDaedalus/fairy) (Zenless Zone Zero optimizer), reusing
its engine, validation harness, and curation pipeline with a rewritten domain layer.

> **Status: bootstrap.** This repo is fairy's tree with the ZZZ corpus stripped and nothing yet
> ported. The code still models agents, discs, and anomaly; the tests do not pass. See the
> "Fork state" section of [`CLAUDE.md`](CLAUDE.md) before touching anything.

## Founding documents

Read these first — they set goals, non-goals, approach, and the constraints handed to Planner:

- [`docs/BRIEF_mistilteinn.md`](docs/BRIEF_mistilteinn.md) — direction, tool decisions, open questions
- [`docs/RESEARCH_genshin_port.md`](docs/RESEARCH_genshin_port.md) — feasibility survey, reuse map, effort phasing

## Stack

- **Backend**: FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL · Alembic
- **Frontend**: Angular 21 · standalone + signals · openapi-fetch · SCSS (deferred; backend first)
- **Infra**: Docker Compose (db + backend + frontend) · Cloudflare Tunnel

## Quick Start

```bash
cp .env.example .env    # fill in a real password
docker compose up -d
```

| URL | What |
|---|---|
| <http://localhost:4201>          | Frontend (Angular dev server, HMR) |
| <http://localhost:8001>          | Backend (FastAPI, auto-reload) |
| <http://localhost:8001/docs>     | Swagger API explorer |

These are deliberately *not* fairy's ports (8000 / 4200), so both stacks run at once.
There is no Postgres here at all — mistilteinn uses the fairy stack's database server on
5432 and owns the `mistilteinn` / `mistilteinn_test` databases inside it. Start fairy's
`db` service before this one.

### Common commands

```bash
docker compose run --rm backend pytest             # backend tests
docker compose run --rm backend ruff check app/    # lint
docker compose exec backend alembic upgrade head   # migrations
docker compose down                                 # stop (keep DB)
```

## Repository Layout

```
backend/    FastAPI app, SQLAlchemy models, Alembic migrations, tests
frontend/   Angular SPA, design tokens, typed API client
docs/       BRIEF / DESIGN / TASKS / LOG planning documents
```

Per-area docs:

- [`CLAUDE.md`](CLAUDE.md) — project-wide conventions, fork state, git workflow
- [`backend/CLAUDE.md`](backend/CLAUDE.md) — Python conventions, layout, testing rules
- [`frontend/CLAUDE.md`](frontend/CLAUDE.md) — Angular conventions, design system, codegen
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, branch policy, planning workflow

## Planned data sources & credits

Per the BRIEF — none wired up yet:

- [gi.hakush.in](https://gi.hakush.in) and [Project Amber](https://ambr.top) — character,
  weapon, and artifact metadata (live importers)
- [Dimbreath/AnimeGameData](https://gitlab.com/Dimbreath/AnimeGameData) — raw game files, as
  **committed snapshots only**, never a live-fetch gate
- [gcsim](https://github.com/genshinsim/gcsim) — crossval oracle, frame-data corpus, and
  rotation corpus (MIT; KQM-sourced frame data — harvest with attribution)
- [frzyc's Genshin Optimizer](https://github.com/frzyc/genshin-optimizer) — secondary kit
  cross-reference; [GOOD format](https://frzyc.github.io/genshin-optimizer/#/doc) for artifact import

## License

Game data © miHoYo / HoYoverse. Fan project, not affiliated with miHoYo.
