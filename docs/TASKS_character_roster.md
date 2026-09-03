# TASKS — the character roster

Reads `docs/DESIGN_character_roster.md`. Owner ruling 2026-09-03; the case is
`BACKLOG_frontend.md` §14.

**Status: complete.** Every task done and driven on screen; the measurements each one
predicted are in the table.

| task | state | what it produced |
|---|---|---|
| 0. Branch | done | `feat/character-roster` off `dev` |
| 1. Model + migration | done | 80 roster rows from 80 distinct `(owner, character)` pairs; round-tripped |
| 2. Repository | done | `upsert_imported` leaves `manual` rows alone — tested both directions |
| 3. Mannequin exclusion | done | 14 rows matched, and a widened prefix fails 4 tests (`scripts.inject`) |
| 4. Service + API | done | `GET /roster`, `PATCH /roster/{id}`; both in the 401 sweep |
| 5. Import writes roster rows | done | **87 roster rows, 75 builds** on the owner's export |
| 6. Teapot reads the roster | done | **146 → 168 sets, +440 primogems** |
| 7. Drop `builds.owned` | done | model, schemas, client, editor toggle |
| 8. ROSTER / BUILDS tabs | done | shared search and chips; toggle persists across reload |
| 9. Unbuilt owned characters | done | **12 cards**, dashed and last: Dahlia, Yun Jin, Ningguang… |
| 10. Verify end to end | done | 2062 backend, 995 frontend, driven in a browser |

---

## 0. Branch

`git switch -c feat/character-roster dev`. Confirm with `git branch --show-current` before the
first commit. No direct commits to `dev`/`main`.

---

## 1. Model + migration

`backend/app/models/roster.py` → `CharacterRosterEntry`, table `character_roster`.

- Composite PK `(owner_id, character_id)` — the constraint that makes §1.1's disagreement
  unrepresentable. Follows `teapot_progress`, which is keyed the same way.
- `owner_id` FK → `users.id` `ON DELETE CASCADE`; `character_id` FK → `characters.id`
  `ON DELETE CASCADE`.
- `owned: bool`, not null.
- `source: str`, not null — `'import'` or `'manual'`, with a CHECK constraint.
- `created_at` / `updated_at`, matching the other models.

**Generate the revision on the host, not in the container** — `docker compose run … alembic
revision --autogenerate` fails with `PermissionError` on a root-owned bind mount.

Migration body, in order: create table → backfill `(owner_id, character_id, bool_or(owned),
'import')` grouped from `builds` → drop `builds.owned`. Downgrade re-adds the column defaulting
true and drops the table.

**Acceptance:** `alembic upgrade head` then `downgrade -1` then `upgrade head` runs clean; after
upgrade, every `(owner_id, character_id)` that had a build has exactly one roster row.

## 2. Repository

`backend/app/repositories/roster.py`, owner-scoped like the others. No raw queries in services.

- `list_for_owner()` → the user's rows.
- `set_owned(character_id, owned, source)` → upsert.
- `upsert_many(rows)` → the import path, **never overwriting a row whose `source` is `'manual'`**.

**Acceptance:** a unit test proves `upsert_many` leaves a `manual` row untouched and updates an
`import` one.

## 3. Mannequin exclusion

`backend/app/services/roster.py` — a pinned constant naming the mannequin `nanoka_id` prefixes
(`10000117-`, `10000118-`), with the capture cited, plus the fourteen-row count so a seed change
is visible.

**Acceptance:** a test asserts against the seeded catalogue that the constant matches exactly 14
rows and that all 14 are named `Manekin`/`Manekina` — so a prefix that stops meaning what it
means fails loudly rather than silently excluding a real character.

## 4. Service + API

`GET /api/v1/roster` — the catalogue left-joined to this user's rows, so **absent** and
**`owned=false`** are distinguishable (DESIGN §2.1). Mannequins excluded.
`PATCH /api/v1/roster/{character_id}` — `{owned: bool}`, writes `source='manual'`.

Regenerate the contract in-process (`create_app().openapi()`), never by curling a running
backend.

**Acceptance:** integration tests for both; `test_openapi_contract_is_current.py` passes.

## 5. Import writes roster rows

`good_build_service` keeps its build rule unchanged. It gains a roster output: every
non-mannequin character in `characters[]` → `owned=True, source='import'`, skipping `manual`.

**Acceptance:** an integration test importing the reference export produces **75 builds and 87
roster rows** (89 in the export, minus the two mannequin entries), and Dahlia, Yun Jin and
Ningguang are among the roster rows with no build.

## 6. Teapot reads the roster

`api/v1/teapot.py`'s `owned_ids` query joins `character_roster` instead of `builds`.
`services/teapot.py` is **unchanged** — it already takes the ids as a parameter.

**Acceptance:** after a re-import, the tracker's available counts rise by the 22 sets the twelve
characters are owed. Assert the delta, not a magic total.

## 7. Drop `builds.owned` from schemas and the client

Remove from the model, `schemas/build.py`, the API, and `frontend/src/app/pages/builds/`.
`npm run codegen` after the contract changes.

## 8. `/builds` gains ROSTER and BUILDS tabs

Owner: *"we need a tab for both so users can change ownership manually if needed."* The filter
chips are shared between tabs — they are one bordered-tile control as of #254.

**Acceptance:** both tabs render; toggling ownership persists across a reload.

## 9. Unbuilt owned characters on the builds tab

An owned character with no build appears as a muted placeholder sorted last, offering to create
one — the owner's original ask, kept because it is a useful thing for the tab to say.

## 10. Verify end to end

`cd backend && python -m scripts.ci_local`, `cd frontend && npm run verify`, `npm run
check:tokens`. Then **drive it**: re-import the owner's export, open both tabs, toggle a
character, reload, and read the teapot page. A green suite is good at formulas and blind to
wiring — the repo's standing lesson, and #240 is the reason it is written here.
