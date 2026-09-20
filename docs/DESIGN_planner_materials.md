# DESIGN — editing the materials you own

The planner subtracts your stock from every bill it prints, and that stock has exactly one
writer: the `materials` map of a GOOD export. This adds a second — you — for the case the
owner asked about on 2026-09-19: *"can you make it to where users can modify their 'owned'
materials in the planner if there's a bug in their import?"*

Read `docs/DESIGN_planner.md` first. Nothing here changes how a plan is priced; it changes
who is allowed to say what goes into it.

## Branch policy

Work happens on **`feat/planner-materials`**, branched from `dev`.

**No direct commits to `dev`.** `dev` is the trunk and a merge to it deploys to production;
this branch merges by PR after `cd backend && python -m scripts.ci_local` exits 0 over every
job on the exact commit that is the PR head. There are no parallel sub-branches. Task M.0 in
`docs/TASKS_planner_materials.md` is the branch-setup gate.

## 1. Owner's rulings, 2026-09-19

| question | ruling |
|---|---|
| where does the editing live | **both** — a `Materials` tab on `/planner`, *and* an editable `Owned` cell on every row of a printed bill |
| what does a later GOOD import do to a hand-typed count | **replaces it**, and the page says so out loud |
| who builds it | Planner writes DESIGN + TASKS; a Worker session implements |

## 2. Why an import is allowed to overwrite you, when the roster is not

`/roster` already solved a question that looks identical and answered it the other way:
`character_roster.source` is written `manual` on a user edit, and that is precisely what stops
the next import undoing it (`app/api/v1/roster.py:set_owned`). Materials deliberately diverge,
and a reader who does not find the reason here will read the divergence as an oversight.

**"Do I own Ayaka" is a durable fact; "how many Teachings of Ballad do I hold" is a reading of
a number that changes every time you play.** A sticky material override goes stale within a
day — and worse, it goes stale *invisibly*, because the planner would keep printing a figure
the user's own export disagrees with, for as long as they never notice. The failure mode of
the rule we are choosing is "my correction was replaced by a fresh scan", which the user can
see and redo. The failure mode of the other rule is "my planner has been wrong for a month and
told me it was importing my inventory". We take the visible one.

So: **one source of truth per row, last writer wins, and the last writer is named on screen.**
No `source` column, no merge, no second layer of state.

**The consequence has to be stated where the editing happens** — the Materials tab carries a
standing line saying an import replaces every count on it. That is the whole of the mitigation
and it is not optional; without it this is a feature that silently discards user input.

## 3. Surfaces

Two new routes, both under the planner's prefix, both requiring a signed-in caller.

### `GET /api/v1/planner/materials`

Every row of `materials` joined to this caller's `user_materials`, with `count: 0` where there
is no row. **Unpaginated**: the table holds 514 rows at 7.0.51, which is one ~40 KB response
and a client-side search, against a paging protocol and a server round trip per keystroke.

```
{"items": [{"material_id": 104161, "name": "Teachings of Ballad",
            "icon": "UI_ItemIcon_104161", "rarity": 2, "count": 40}, ...],
 "owned_count": 137}
```

**It lists everything the table holds, including the 6 rows no cost bill reaches.** A user's
export can carry them, and a list that quietly omits a material the user is looking at is the
bug this feature exists to fix, wearing a different hat.

### `PATCH /api/v1/planner/materials`

```
{"counts": [{"material_id": 104161, "count": 40}, ...]}
```

**A partial update, naming only the rows it means to change.** Not a whole-inventory `PUT`:
the tab sends its dirty rows and the inline edit sends one, and a replace-everything body
built from a *filtered* view would delete every material the filter was hiding. That is a
one-line mistake with a whole-inventory blast radius, so the route simply cannot express it.

Returns the rows written, as `MaterialStockRead`, so the inline edit can reconcile without a
second fetch.

**Refusals, all 422 and all by name** — the discipline `set_owned` uses for a mannequin and
the rotation compiler uses for an unmodelled condition, because a silent no-op leaves a
control that appears to work:

| body | refused because |
|---|---|
| `count < 0` | you cannot hold less than none |
| `count > 2_147_483_647` | **`user_materials.count` is `int4`.** Unbounded, a pasted 20-digit number reaches asyncpg and returns a 500 from a route that should have said no. The bound is the column's, cited as the column's — it is not a claim about the game's stack limit, which this repo has not sourced |
| the same `material_id` twice | last-wins would quietly discard one of two numbers the user typed |
| an id not in `materials` | an export newer than the seeded patch is the usual cause, and the user can act on being told which id |

### `count == 0` deletes the row rather than storing a zero

`UserMaterial`'s own docstring says an absent row means zero and records that a real export
carries no zero-valued entry. Storing one anyway would break something measured rather than
theoretical: `service.py:698` computes `stock_is_empty=not stock`, so an account whose entire
stock had been typed down to zeros would report a non-empty inventory and lose the banner that
tells a user their materials were never imported.

## 4. The bill's editable `Owned` cell

Every row of a printed section — material rows *and* the EXP-book rows, which read their
counts from the same `user_materials` stock — carries an editable `Owned` number. On commit:
`PATCH`, then re-request the plan, then redraw from the response.

Three traps, each of which produces a wrong number rather than an error:

1. **Re-send the stored request, never re-derive one from the form.** The plan on screen was
   priced from the request that produced it; the controls above it may have been touched
   since. Re-deriving would re-price a *different* plan and present it as the effect of
   editing one count. The page must keep the last `PlanRequest` it sent and reuse it verbatim.
2. **Do not patch the bill locally.** Editing one count can move rows the user did not touch:
   `_convert_surplus` credits spare Teachings toward Philosophies, so one edit can change
   another row's `from_surplus`, its `still_needed`, the section's mora and its resin
   histogram. The whole bill comes back from the server or it is not trustworthy.
3. **Sequence the re-prices.** Two quick edits are two `PATCH`es and two plans, and the second
   response is not guaranteed to arrive second. Stamp each round trip and drop a response that
   is not the newest, or the bill settles on the older of two answers.

`POST /planner/plan` writes nothing and the owner's own 243-action plans return in well under a
second, so a re-price per edit is affordable. Debounce the input; do not batch across rows.

## 5. The Materials tab

A second tab on `/planner`, following `builds.html`'s `role="tablist"` markup and `builds.ts`'s
`tab()` signal — the pattern exists, and the reason this repo keeps reaching for
`shared/{icon,token,element,combobox}` is that a pattern nobody owns gets decided again on
every page.

- **Sorted owned-first, then by name.** *Not* by rarity: rarity 0 is not "worst", it is
  *unranked*, and it is where the local specialties live — Sakura Bloom, Philanemo Mushroom,
  Valberry. Sorting by rarity descending would bury sixty real ascension materials under the
  gem tiers.
- A search box over the name, and an **owned-only** toggle, default off. The case this feature
  was asked for is *the import missed something*, so the material you are hunting for is the
  one with no row.
- An explicit `Save`, sending only the dirty rows. Leaving the tab with unsaved edits warns.
- The standing line from §2: **an import replaces every count here.**
- Mora is absent, and the tab says why: GOOD carries no currency field, so the plan asks for
  it per request. See OQ-M1.

## 6. Code placement

- `app/repositories/user_material.py` — a `UserMaterialRepository` with `all_for_owner()` and
  `set_counts()`. CLAUDE.md §Architecture puts data access in a repository, and the existing
  `planner/service.py:_load_stock` is an inline `select` that predates this rule; it moves onto
  the repository in the same task so the read path and the write path share one implementation.
- `app/services/planner/stock.py` — `list_stock()` and `set_stock()`, holding the refusals.
- `app/api/v1/planner.py` — the two routes and their schemas, beside the ones they extend.
- `frontend/src/app/pages/planner/materials/` — the tab component, with the planner page
  owning the tablist and `planner.service.ts` gaining the two calls.

## 7. Out of scope

Mora (§5), bulk paste or CSV, an undo history, per-material notes, and any attempt to
reconcile a hand edit against a later import — §2 is the ruling that there is nothing to
reconcile.

## 8. Open questions

- **OQ-M1** — should the mora balance persist too? It is typed into every plan request today
  and thrown away, which is the same papercut this feature fixes for everything except the one
  quantity a user has to type. It is not a `user_materials` row and GOOD has no field for it,
  so it needs a home of its own. Deliberately not decided here.
- **OQ-M2** — should the GOOD import surface on `/inventory` warn, before it runs, that it
  replaces hand-edited counts? §2's mitigation lives on the Materials tab; the user who is
  about to lose an edit is standing on a different page.
- **OQ-M3** — should the tab offer a *materials in the current plan* filter? Cheap, since the
  plan response already names them, and it is the fastest route from "this bill is wrong" to
  the row that is wrong. Left out of the task list to keep the first cut small.
