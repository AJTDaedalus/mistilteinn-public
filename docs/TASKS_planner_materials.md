# TASKS — editing the materials you own

Design: `docs/DESIGN_planner_materials.md`. The planner itself: `docs/DESIGN_planner.md`.

**Status:** M.0 done, M.1–M.9 open.

Branch **`feat/planner-materials`** off `dev`. One task at a time; stop and report after each
(CLAUDE.md §Session Cadence). Run `ruff check app/` and the named tests before each commit.

| # | task | state |
|---|---|---|
| M.0 | Branch off `dev`; DESIGN + TASKS committed | **done** |
| M.1 | `UserMaterialRepository`; `_load_stock` moves onto it | open |
| M.2 | `services/planner/stock.py` — list, set, and the four refusals | open |
| M.3 | `GET`/`PATCH /planner/materials` + schemas; regenerate the contract | open |
| M.4 | Integration tests, including the import-replaces-an-edit pin | open |
| M.5 | `planner.service.ts` gains both calls; `npm run codegen` | open |
| M.6 | The Materials tab component | open |
| M.7 | The tablist on `/planner` | open |
| M.8 | The editable `Owned` cell on a bill row | open |
| M.9 | Drive it in the real app; `ci_local`; PR | open |

---

## M.1 — `UserMaterialRepository`

**Files:** `app/repositories/user_material.py` (new), `app/services/planner/service.py`.

Add `all_for_owner(owner_id) -> dict[int, int]` and
`set_counts(owner_id, counts: Mapping[int, int]) -> None`, following `repositories/roster.py`
for shape. `set_counts` upserts a positive count and **deletes** a zero (DESIGN §3).

Then delete `service.py:_load_stock` and call the repository from its one caller.

**Acceptance:** `pytest tests/unit tests/integration -k planner` stays green with no change to
any planner test — this task moves code and changes no behaviour.

## M.2 — `services/planner/stock.py`

**Files:** `app/services/planner/stock.py` (new), `tests/unit/test_planner_stock.py` (new).

`list_stock(session, owner_id)` joins `materials` to the caller's rows, zero-filling, sorted
owned-first then by name. `set_stock(session, owner_id, updates)` validates and delegates to
M.1's repository.

The four refusals from DESIGN §3, each raising `PlanError` (or a sibling) that the route turns
into a 422 **naming the offending id or value**: negative count, count above `2_147_483_647`,
a duplicated `material_id`, an id absent from `materials`.

**Acceptance / tests that must pass:**
- one test per refusal, asserting the message names the id or the bound;
- `count == 0` removes an existing row, and `stock_is_empty` is `True` again for an account
  whose only row was zeroed — this is the measured trap in DESIGN §3, so assert it directly;
- a count at exactly `2_147_483_647` is accepted and round-trips.

## M.3 — The two routes

**Files:** `app/api/v1/planner.py`, `frontend/openapi.json`.

`MaterialStockRead` (`material_id`, `name`, `icon`, `rarity`, `count`), `MaterialStockList`
(`items`, `owned_count`), `MaterialStockUpdate` (`material_id`, `count`), and the `PATCH` body
holding `counts: list[MaterialStockUpdate]` — **a list of named objects, not a `dict[int, int]`
and not a tuple**, for the reason `ExpBookRead` already records.

Regenerate the contract in-process (`create_app().openapi()`), never by curling a running
backend.

**Acceptance:** `pytest tests/unit/test_openapi_contract_is_current.py` green; both routes
require a signed-in caller and a signed-out request gets the same refusal every other planner
route gives.

## M.4 — Integration tests

**Files:** `tests/integration/test_planner_materials.py` (new).

- `PATCH` then `GET` reflects the new count;
- `PATCH` then `POST /planner/plan` prices the bill against the edited number — drive it
  through a material the fixtures already use (`TEACHINGS`, as
  `test_planner_endpoints.py` does);
- **a GOOD import after an edit replaces the edited count.** This pins DESIGN §2's ruling.
  Left untested it is an accident rather than a decision, and the next person to touch
  `_import_materials` has nothing telling them the overwrite is deliberate;
- one caller cannot read or write another's rows.

## M.5 — The client calls

**Files:** `frontend/src/app/pages/planner/planner.service.ts`.

`materials()` and `saveMaterials(updates)`, typed from `components['schemas']` like everything
else in the file. Run `npm run codegen` first — `api.types.ts` is generated and gitignored and
describes whichever branch generated it last.

## M.6 — The Materials tab component

**Files:** `frontend/src/app/pages/planner/materials/` (new), plus its spec.

Per DESIGN §5: owned-first then name (**not** rarity — rarity 0 is unranked, and it is where
the local specialties live), a name search, an owned-only toggle defaulting **off**, a number
input per row, an explicit `Save` that sends **only dirty rows**, an unsaved-changes warning on
leaving, the standing "an import replaces every count here" line, and the one-line note about
why mora is not on this table.

**Acceptance / tests:** search narrows the list; Save sends only the rows that changed, proven
by asserting the request body rather than the rendered table; a row edited back to its original
value is not dirty.

## M.7 — The tablist

**Files:** `frontend/src/app/pages/planner/planner.{html,ts,scss}`, `planner.spec.ts`.

Copy `builds.html`'s `role="tablist"` / `aria-selected` markup and `builds.ts`'s `tab()`
signal. Switching tabs must not discard a computed plan.

**Acceptance:** `npm test` green; `npm run check:tokens` green — every colour used comes from
the palette, because an undefined custom property invalidates its whole declaration silently.

## M.8 — The editable `Owned` cell

**Files:** `frontend/src/app/pages/planner/planner.{html,ts}`, `planner.spec.ts`.

The `Owned` cell on every material row **and every EXP-book row** becomes an input. On commit:
`PATCH`, then re-request the plan, then redraw from the response.

All three traps in DESIGN §4 are the acceptance criteria, and each needs its own test:
1. the re-price sends the **stored** `PlanRequest`, verbatim — assert it after mutating the
   form controls, which is the only way the test can tell a stored request from a re-derived
   one;
2. **no local patching of the bill** — the redraw comes from the response; assert a row the
   user did not touch changes when the server says it does;
3. an out-of-order response is dropped — resolve two re-prices newest-first and assert the
   newest wins.

## M.9 — Drive it, gate it, ship it

Not a test-suite task. CLAUDE.md §"Drive the feature": a green suite here is good at formulas
and blind to wiring, and every one of the failures that entry lists was found by using the
thing.

1. Restart the backend container — it does not hot-reload, and a stale API looks exactly like
   a broken feature in a screenshot.
2. In the real app: open `/planner`, price a plan, note a row reading `Owned 0` for something
   you hold, fix it inline, watch the bill re-price. Then open the Materials tab, search for a
   material, change two counts, save, and reload to confirm they stuck.
3. Screenshot both tabs (`scripts/shoot.py`) at a phone width as well — the DOM audit measures
   what a screenshot cannot.
4. `cd backend && python -m scripts.ci_local`, exit 0 over **every** job, on the exact commit
   that is the PR head. Record the commit and the gate count.
5. PR to `dev`, then confirm the deploy landed — `gh run list --branch dev`, then a request
   against the site.

---

## Handoff

Implementation is Worker-tier (Sonnet). Load `docs/DESIGN_planner_materials.md` and this file;
nothing in a chat transcript is needed. Start at **M.1**, stop and report after each task.

Escalate to Planner (Opus) per CLAUDE.md if a task's acceptance criteria turn out to be
ambiguous or the same task fails twice — particularly M.8, where the three traps are the whole
point and a passing test that does not actually distinguish a stored request from a re-derived
one would be worse than no test.
