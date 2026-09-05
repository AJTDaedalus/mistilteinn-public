# Contributing to mistilteinn

mistilteinn is a Genshin Impact build optimizer and rotation simulator:
FastAPI + SQLAlchemy async + PostgreSQL backend, Angular 21 frontend. It is
forked from [fairy](https://github.com/AJTDaedalus/fairy), the ZZZ optimizer,
and reuses its engine with a rewritten domain layer.

This doc covers how to get set up, how the codebase is organized to work in,
and the conventions a PR is expected to follow. For *where things live*, see
[`CLAUDE.md`](CLAUDE.md) and [`docs/DESIGN_mistilteinn.md`](docs/DESIGN_mistilteinn.md)
— fairy's `docs/ARCHITECTURE.md` did not come along in the fork.

## Dev setup

Two supported paths — pick one:

**Docker (recommended, matches CI-adjacent behavior):**

```bash
docker compose up -d
```

Frontend at <http://localhost:4201>, backend at <http://localhost:8001>
(Swagger at `/docs`). Source edits flow through both containers via bind
mounts. See the root [README](README.md#quick-start) for the full command
table, including the anonymous-volume gotcha after editing
`frontend/package.json`.

**Conda (backend-only, faster iteration on Python):**

```bash
conda activate mistilteinn   # or whichever env holds this checkout
cd backend && pip install -e ".[dev]"
pytest
```

## Branch policy

- **`dev` is the trunk, the default branch, and what serves production.**
  There is no `main`. No direct commits — `deploy-prod.yml` triggers on a
  push to `dev` (see [`docs/DEPLOY.md`](docs/DEPLOY.md)), so a commit there
  ships, with no staging step in between.
- All work happens on a feature/fix branch off `dev`:
  `feat/<short-description>`, `fix/<short-description>`,
  `refactor/<short-description>`.
- Feature branches merge to `dev` via reviewed PR only.
- Large features may use parallel sub-branches for independent tracks,
  merged into the feature branch before the integration PR to `dev`. Every
  `docs/DESIGN_<feature>.md` states its own branch policy near the top —
  check it before starting work on an in-flight feature.
- Verify `git branch --show-current` before every commit.

## The gate: run CI yourself

**GitHub Actions does not run the checks.** `test.yml` and `security.yml` are
`on: workflow_dispatch:` — their seven `ubuntu-latest` jobs were billed on every
push and everything they do can be done here. `deploy-prod.yml` still runs
automatically; it is on a self-hosted runner and it is the deploy, not a check.

**Before any merge to `dev`, on the final commit:**

```bash
cd backend && python -m scripts.ci_local     # exit 0 over every job
```

It parses `.github/workflows/*.yml` at run time and runs the steps it finds, so
it is CI rather than a stand-in for it — a gate added to a workflow is a gate it
runs the same day. `--list` shows the plan, `--job <id>` runs one job while
iterating, and `--clean` runs from a fresh clone of HEAD when a change could
touch installing or building.

The final commit is the one that matters. "Only docs changed since I ran it" is
the reasoning this requirement exists to refuse.

After merging, check that the deploy actually happened — `gh run list --branch
dev`, then a request against the site — rather than assuming the merge was the
deploy. `deploy-prod.yml` runs on a self-hosted runner and kept working through
a failed-payment state that stopped every hosted job, so this is not about
billing; it is that a merge and a deploy are two events and only one of them is
visible in git.

## TDD and test layout

Every feature gets tests **first**. Layout under `backend/tests/`:

- `unit/` — pure logic, dependencies mocked (repositories, external calls)
- `integration/` — hits a real async PostgreSQL (via the `db` Docker
  service or a local Postgres pointed at by `DATABASE_URL`)
- `perf/` — performance/benchmark tests, not part of the correctness gate
- `fixtures/` — shared JSON/data fixtures for integration tests
- `conftest.py` — the async test DB session, HTTP test client, and
  authenticated-user fixtures every test builds on

Coverage target: >90% on services, 100% on damage calculation
(`app/formula/`, `app/services/attribution.py`).

Frontend tests are Vitest (`npm test`, jsdom environment) — see
`frontend/CLAUDE.md`.

## Conventional commits

`feat:`, `fix:`, `test:`, `docs:`, `refactor:` — one logical change per
commit. Don't bundle unrelated changes. Good granularity: one model = one
commit, one bugfix = one commit, one test file = one commit. Every commit
should leave the project buildable (tests + lint passing).

Run before every commit:

```bash
docker compose run --rm backend pytest
docker compose run --rm backend ruff check app/
```

## Lint and docstring standards

Ruff enforces PEP 8 plus a broad rule set (see `backend/pyproject.toml`).
Docstring presence is enforced via Ruff's `D` rules
(`pydocstyle`, `convention = "pep257"`):

- **Required**: module (D100), public class (D101), public method (D102),
  public function (D103), public package `__init__` (D104).
- **Not required**: magic methods (D105 — self-documenting), `__init__`
  (D107 — the class docstring covers construction).
- **Not enforced**: a handful of pep257 prose/formatting nitpicks
  (D205/D209/D400/D401) that would flag already-good docstrings for style
  rather than presence.
- `tests/**` and `alembic/**` are fully exempt (test names document
  themselves; migrations are generated).

Content guidance (not machine-checked — applied opportunistically under
the "fix files you touch" rule): docstrings say **why and what for**, not
just what the code obviously does; document args/returns only where
non-obvious; module docstrings state the module's architectural role;
game-mechanic constants cite the relevant doc in `references/`.

**TypeScript**: JSDoc on exported symbols (functions, classes, public
methods) where the *why* isn't obvious from the signature. This is a
convention, not a CI gate — no linter currently enforces it on the
frontend.

## Fixing pre-existing issues

- **Fix pre-existing lint errors in files you touch** — when editing a
  file, resolve existing Ruff violations in that file alongside your own
  changes, not just the new lines.
- **Fix pre-existing failing tests in scope** — if tests in the same file
  or a closely related module are failing for reasons within scope, fix
  them. Skip only clearly out-of-scope failures (unrelated subsystem,
  missing infra).

## OpenAPI codegen workflow

The frontend's typed API client is generated from a checked-in
`frontend/openapi.json` snapshot, not a live call to the backend. Whenever
backend routes or schemas change:

```bash
cd frontend
npm run openapi:fetch   # snapshot live backend → frontend/openapi.json
npm run codegen         # regenerate src/app/api/api.types.ts (gitignored)
```

`prestart` / `prebuild` run `codegen` automatically, so a fresh `npm start`
or `npm run build` always picks up the latest committed snapshot — but the
snapshot itself must be refreshed and committed **in the same PR** as any
backend schema change. The deployed frontend must never race a changed
backend contract.

## The BRIEF / DESIGN / TASKS / LOG planning system

Non-trivial features are planned across four files in `docs/` before any
code is written:

- **`BRIEF_<feature>.md`** — problem statement, goals/non-goals, approach
  selected and alternatives rejected, constraints handed to planning.
- **`DESIGN_<feature>.md`** — architecture, module breakdown, data flow,
  testing strategy, branch policy, open questions.
- **`TASKS_<feature>.md`** — numbered atomic tasks (5–30 min each) with
  acceptance criteria, checked off as work lands.
- **`LOG_<feature>.md`** — running execution log: what was done, test
  results, and any `## ESCALATION` blocks where an ambiguity got kicked
  back up to design.
- **`docs/DECISIONS.md`** — shared log of tradeoffs and rationale across
  features.

If you're picking up an in-flight feature: read BRIEF → DESIGN → TASKS →
LOG in that order, then continue from the next unchecked task. These
files are the source of truth for *why* a feature looks the way it does —
`docs/ARCHITECTURE.md` is the source of truth for *where things are now*,
and must be updated when a feature's code moves, since DESIGN/LOG are
historical snapshots that are never revised after the fact.
