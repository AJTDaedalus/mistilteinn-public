# TASKS — ownership, saved runs, and the teapot tracker

**Status: Tracks 1, 2 and 3 built, 2026-09-03.** Everything below is done except the three
items named here, each blocked on something that is not effort:

| open | why |
|---|---|
| **3.1** the primogem reward constant | needs a **citation**, which this repo does not write from memory. The headline sort ships without it: the reward is one constant per character, so `reward × remaining` and `remaining` order identically. |
| **2.16 / 2.17** deleting the client recipe cache | needs the corpus **hit rate measured** first (OQ-A3). The read path is wired now, so the measurement is available; deleting the local cache before taking it would be a regression nobody would attribute to this change. |
| **X.2 / X.4** surfacing build names and team notes in the UI | the columns and API exist; the build page shows `name`, and the team page does not yet show `notes`. |

**Status: not started, 2026-09-03.** Plan for `docs/DESIGN_account_tracking.md`; read that
first. **Queued behind `TASKS_rotation_language.md`** by the owner's sequencing.

**Track 3 cannot start before Track 1** — the teapot tracker is backed by `builds.owned`.
Tracks 1 and 2 are independent of each other.

---

## Phase 0 — the gate

| # | task | acceptance |
|---|---|---|
| 0.1 | Cut `feat/account-tracking` from `dev`, and a sub-branch per track | nothing committed to `dev` |
| 0.2 | `docs/LOG_account_tracking.md`, opened with the nanoka data findings | 109 suites, 79 with favourites, 116 characters |

## Track 1 — `builds.owned`

| # | task | acceptance |
|---|---|---|
| 1.1 | Alembic revision: `builds.owned` boolean, `NOT NULL`, **server default true** | generated **on the host**; existing rows are all real builds, so the default is a no-op |
| 1.2 | `Build` model + `BuildCreate`/`BuildUpdate`/`BuildRead` | `owned` defaults true on create |
| 1.3 | GOOD import sets `owned=True` explicitly rather than relying on the default | a test asserts it, so a later default change cannot silently flip imports |
| 1.4 | Build page toggle, with a one-line explanation of what it means | *"a build you made to test"* is the distinction, not a jargon word |
| 1.5 | Contract regenerated, `npm run codegen`, frontend green | |

## Track 2 — saved optimization runs

### 2a — storage

| # | task | acceptance |
|---|---|---|
| 2.1 | `optimization_runs` table: owner, created_at, visibility, share_key, score, margin, iterations, elapsed | mirrors the rotation library's shape rather than inventing a second one |
| 2.2 | The **objective** column — sets searched, weapons compared, energy model, enemy | a run whose objective is unknown cannot be interpreted, let alone reproduced |
| 2.3 | The **snapshot** columns — build, artifacts *with their substats at the time*, rotation signature, gcsim pin | **OQ-A1**; a shared result must not silently re-read today's gear |
| 2.4 | `POST /optimization-runs` — save a completed search | rejects a run whose objective and snapshot do not agree |
| 2.5 | `GET /optimization-runs` — the user's own, newest first | |
| 2.6 | Filters: character, team, element, artifact set, weapon, energy model, date, mine-only | ordered by recency, because score is meaningless across characters |
| 2.7 | Query-count test on the list endpoint | `test_rotation_library_query_count.py` is the model — **and it once passed while counting zero**, so this one asserts a specific number |

### 2b — sharing

| # | task | acceptance |
|---|---|---|
| 2.8 | `visibility` + share key, reusing the rotation library's enum and helpers | **OQ-A2** — explicit publish, matching rotations |
| 2.9 | `GET /optimization-runs/{share_key}` — readable without owning it | a private run 404s rather than 403s, so a share key cannot be probed |
| 2.10 | Public list with the same filters | |

### 2c — the optimize page

| # | task | acceptance |
|---|---|---|
| 2.11 | Previous runs listed on arrival, before any search is started | the owner's stated first impression of the page |
| 2.12 | Re-open a run: its result renders without re-running gcsim | the whole point of storing it |
| 2.13 | A run whose snapshot no longer matches the live build says so | *"your gear changed since this ran"* is the honest banner |
| 2.14 | Save is offered when a search completes | |

### 2d — the cache question

| # | task | acceptance |
|---|---|---|
| 2.15 | Server **read** path over `sim_runs`, keyed by the `context_key` it already stores | cross-device and cross-user; it is a calibration cache already, in everything but name |
| 2.16 | Measure hit rate and latency against the client cache | the number that decides **OQ-A3** |
| 2.17 | Decide on deleting `recipe-cache.ts`, and record it | deleting it *before* 2.16 would be a regression nobody would attribute to this change |

## Track 3 — the teapot set tracker — **needs Track 1**

| # | task | acceptance |
|---|---|---|
| 3.1 | **Cite the primogem reward constant** | **OQ-A4**, and it gates everything below. This repo does not write game values from memory; a fabricated constant would be wrong in the page's most visible place |
| 3.2 | Capture `furniture.json` and `suite.json` as committed fixtures at the pinned version | 2,381 furnishings, 109 suites; the pin is 7.0.51, matching `FIXTURE_VERSION` |
| 3.2b | Vendor the 109 suite icons through `scripts/download_icons.py` | all 109 resolve, ~6 MB total; assert on **`content-type`**, since a 404 and an SPA fallback both answer 200 |
| 3.3 | Alembic + models: `furnishing_suites`, `furnishing_suite_favorites` | `favorite` holds nanoka character ids, which `characters.nanoka_id` already uses — no new identifier scheme |
| 3.4 | Seed them, and extend `verify_seed` with hand-read anchors | the seeding convention this repo already has |
| 3.5 | `teapot_progress` table — `(user, suite, done_at)` | one row per set a user has finished; Seelie's affordance is exactly this |
| 3.6 | `GET /teapot/suites` — suites joined to the user's **owned** characters | the join Track 1 exists for |
| 3.7 | Remaining-primogem calculation and its test | `reward × (favouring characters that are owned and not yet done)` |
| 3.8 | The page: sortable by remaining primogems, mark-off, and a "hide completed" toggle | the owner's stated headline |
| 3.9 | Screenshot pass via `scripts/shoot.py` | a green suite has never caught a layout defect here |

## Extras from `DESIGN_account_tracking.md` §"What else is worth storing"

Each is small and independent; do them when they are cheapest, not as a phase.

| # | task | acceptance |
|---|---|---|
| X.1 | Artifact `locked`, read from GOOD's `lock` | an optimizer that builds around a locked piece gives advice the user cannot take |
| X.2 | A build `name` | two builds for one character are currently told apart by their gear |
| X.3 | `imported_at` on an inventory import | the commonest reason a saved result stops being true |
| X.4 | Team `notes` | the reason a team exists is what a user forgets |
