# KQM recommendations reach nobody: weapons join on a local UUID, sets have no caller

**Status:** **both fixes built** (see the closing section). Findings first, 2026-09-04, from the owner's report *"weapon
recommendations don't seem to work in the build/optimizer selectors, sets too — I know we parsed
all of that but it's not showing up in the UI."*

The data is there. `app/data/kqm/weapons.json` holds **102 characters, 1,353 weapon
recommendations and 346 set rows**, captured 2026-09-02 with citations. Two separate faults stop
any of it reaching a screen, and they need different fixes.

## 1. Weapons: the snapshot stores this machine's primary keys

`scripts/capture_kqm_weapons.py:388` writes `str(weapon.id)` — the **`uuid7` primary key of the
database the capture happened to run against**:

```json
{"position": 1, "weapon_id": "01a025dd-ea34-7dd1-8164-4d2445d52115", "weapon_name": "Staff of Homa"}
```

`app/models/base.py:46` gives every row `default=generate_uuid7`, so an id is minted at insert
and **a fresh seed mints different ones**. The snapshot is therefore a set of pointers into one
particular database, committed to git as though it were portable data.

Both consumers join on exactly that:

```ts
// builds.ts:270      optimize.ts:543-573 does the same
new Map((guide?.weapons ?? []).map((w) => [w.weapon_id, w]))
… const kqm = listed.get(w.id);   // w.id is the catalogue row's uuid
```

A miss is silent by construction — `recommended: Boolean(kqm)`, `tooltip: kqm?.note`, and the
KeqingMains filter chip is only offered `if (listed)`. Nothing errors; the picker simply looks
like a picker with no guide.

### Measured against production, 2026-09-04

```
prod GET /api/v1/weapons        → 254 weapons;  KQM's 205 distinct weapon_ids present:  0
prod GET /api/v1/artifact-sets  →  65 sets;     KQM's  32 distinct set_ids present:     0
```

Staff of Homa is `01a03190-775c-…` in production and `01a025dd-ea34-…` in the snapshot — the
uuid7 timestamp prefixes differ because they are two seed runs. **Zero of 205. Not "some
drift" — the entire feature is dark in production**, and it will be dark in any environment
that did not seed the exact database the capture ran against. It happens to work on this
checkout, which is why a green suite and a working local page both say it is fine.

The capture already knew the right pattern and used it for the other half: `characters()`
(`:394-406`) keys on **`nanoka_id`**, which is the game's own stable id, and the snapshot's
top-level character keys are those. Weapons and sets carry a `nanoka_id` column too
(`13501` for Staff of Homa) and the catalogue API already publishes it on every weapon and set.
The asymmetry is the whole bug.

### The test could not have caught it

`test_kqm_weapons.py:43` is `assert weapon.weapon_id` — truthy. Per this repo's own rule about
checks that can only return one answer: **ask what input would make it disagree.** Nothing
would; a UUID from any database, or from no database, passes. There is no test anywhere that
joins the snapshot to the catalogue.

## 2. Sets: parsed, served, and consumed by nobody

`SetRecommendation`, `SetRecommendationRead`, and the `sets` array on
`GET /characters/{nanoka_id}/weapons` all exist and are populated — 346 rows, 134 of them
resolved to a named set. **No frontend file reads `guide.sets`.** `optimize.html:400` renders
only the weapons caption; `builds.html` has no guide markup at all.

This is the failure mode `CLAUDE.md` names twice — `/compare-weapons` and `createGpuKernel`
before it — *built, tested, reachable from no caller*, and found by the owner going to use a
feature rather than by anybody reading the code.

### And 47 real sets are misfiled as stat descriptions

`kind` distinguishes a named set from a *kind* of two-piece (`2pc HP% / ER`), which is a good
distinction and the module docstring defends it well. But the resolver strips a refinement and
not a trailing parenthetical, so:

| `as_written` | stored `kind` | is actually |
|---|---|---|
| `4pc Crimson Witch of Flames (1 Stack)` | `stat` | Crimson Witch of Flames |
| `4pc Emblem of Severed Fate (EoSF)` | `stat` | Emblem of Severed Fate |
| `4pc Gilded Dreams (3 Stack EM)` | `stat` | Gilded Dreams |
| `4pc Husk of Opulent Dreams (4Husk)` | `stat` | Husk of Opulent Dreams |

**47 of the 212 `kind="stat"` rows resolve to a seeded set once a trailing `(...)` is removed**
— abbreviations (`EoSF`, `4GT`, `VG`) and stack counts, never a different set. So the set half
is not merely unwired; a quarter of what it would show is mislabelled underneath.

---

# Suggested fixes

## A. Store the game's id, resolve at read time — fixes production

1. **Capture writes `weapon_nanoka_id` / `set_nanoka_id`** beside the name, instead of
   `weapon_id` / `set_id`. One line each in `capture_kqm_weapons.py` (`:388`, `:512`), and it
   makes the snapshot mean the same thing in every environment — which is what a committed
   snapshot has to do.
2. **`character_weapon_guide` resolves them against the live catalogue** and keeps publishing
   `weapon_id` / `set_id` as row ids. The endpoint is currently static; it gains a session and
   a `WHERE nanoka_id IN (…)`, the same shape every other catalogue route already has. **No
   client change**, so this fix stands alone and ships on its own.
   * A nanoka id the seeded patch does not have resolves to `null` rather than being dropped:
     the row keeps its name, note and citation, and the client marks it unlisted. A weapon
     released after the pin is a fact about the pin, not a reason to hide KQM's sentence.
3. **Re-capture is not required.** The 205 weapon ids and 32 set ids in the current file all
   resolve against this checkout's database, so a one-off migration script can rewrite the
   snapshot in place — read it, join to the local catalogue, write nanoka ids — and the diff is
   reviewable.

### The tests that would have caught it

* **Integration, require-DB:** every `*_nanoka_id` in the snapshot resolves to a seeded row.
  Guarded like `CROSSVAL_REQUIRE_DB=1` — per the repo rule, a skip here is a failure, because
  "could not check" is exactly the state this bug lived in.
* **Unit, and the one that generalises:** no id in `app/data/kqm/weapons.json` may look like a
  `uuid7` — a committed snapshot must not carry a primary key from anybody's database. That is
  a check on the *class* of mistake, and it would fail today.
* Replace `assert weapon.weapon_id` with something that can disagree.

## B. Wire the set recommendations — the "sets too" half

1. Run `npm run codegen` first: `frontend/src/app/api/api.types.ts` is gitignored and currently
   absent from this checkout, so `SetRecommendationRead` is not typed here yet.
2. Feed `guide.sets` into the artifact-set selectors the way `guide.weapons` already feeds the
   weapon picker in `builds.ts:273-312` — position, `relative_dps`, `playstyle`, KQM's verbatim
   note on hover, listed-first ordering, and a "KeqingMains lists it" filter chip. Reuse
   `CardOption`; do not write a second recommendation renderer.
3. `kind` decides the treatment: `set` marks a specific set card, `stat` is a sentence shown
   above the grid (it names a property, not a card, and turning it into one would be this repo
   asserting a resolution KQM did not write).
4. **Strip a trailing parenthetical before resolving**, recovering the 47 rows above. Do it in
   the capture, not at read time, so the snapshot's `kind` is true on disk and the diff is
   reviewable — and keep `as_written` verbatim, since the parenthetical is KQM's own qualifier
   and belongs in the note.

## Worth deciding

**Which page owns this.** Weapon recommendations are wired into *two* pickers (`builds` and
`optimize`) with two near-identical `recommended`/`weaponOptions` computeds. Adding sets to both
makes it four. A single `shared/kqm/` helper that turns a guide into `CardOption` decorations
would be the third caller's cost paid once — the same argument `shared/{icon,token,element}`
already settled for a pattern nothing owned.


---

# What was built

Both, on `fix/kqm-recommendations`.

## The snapshot holds the game's ids

`weapon_id` / `set_id` became `weapon_nanoka_id` / `set_nanoka_id` in
`app/data/kqm/weapons.json`, in `capture_kqm_weapons.py` (so a re-capture writes them), and in
`services/kqm_weapons.py`. `GET /characters/{id}/weapons` resolves them against the live
catalogue through `WeaponRepository.ids_by_nanoka_ids` and its `ArtifactSetRepository` twin, and
still publishes `weapon_id` / `set_id` as row ids — **so no client had to change to be fixed.**

The existing file was migrated in place rather than re-captured: every id still resolved
against this checkout, so the rewrite is a join and the diff is names-unchanged,
ids-swapped. `retrieved_at` is untouched, because nothing was re-fetched and saying otherwise
would be a false citation.

A row whose nanoka id this pin does not have gets `weapon_id: null` and **keeps its note,
position and citation**. Dropping it would quietly shorten a cited list; what is missing is a
card, which is a fact about the pin.

## The 47 mislabelled sets

`capture_kqm_weapons.py` now retries a set row with a trailing `(…)` removed — **only after
the name as written fails**, so nothing that already resolved is re-read, and `resolve` still
refuses ambiguity. `as_written` keeps KQM's text verbatim, qualifier included.

Resolved set rows went **134 → 181**. Distinct sets named stayed 32: every promoted row was a
set the snapshot already named elsewhere, which is why the gap was invisible in aggregate.

## The sets reach the UI

`shared/kqm/kqm.ts` is the one place a guide becomes picker decorations —
`weaponsById`, `setsByNanokaId`, `statAdvice`, `marked`, `weaponCard`, `listedFirst`,
`KQM_FILTER`. `builds` and `optimize` both moved onto it, and the optimizer's 4-piece and
2-piece pickers now mark and order by KQM the way the weapon picker already did.

`kind` decides the treatment, as §B proposed: a `set` row marks a card; a `stat` row is
rendered as KQM's own sentence above the grid and never resolved to one.

Where a guide lists one set under several playstyles — Zhongli's has 32 rows over five — the
**earliest position wins**, matching the rule the capture already applies to a weapon listed
twice.

## Tests, and the one that would have caught it

* `test_every_id_resolves_against_the_catalogue` reads the **committed nanoka fixtures**, not a
  seeded database, so it can never pass by being skipped — which is the state the bug lived in.
  Planted-failure checked: a bad id makes it fail.
* `test_no_id_in_the_snapshot_is_a_row_id_from_somebody_s_database` fails on the *shape* of a
  `uuid7` anywhere in the file, so it catches a re-capture that reintroduces a row id under a
  new field name. It fails against the old snapshot.
* `test_a_named_set_is_not_filed_as_a_stat_description` — narrow on purpose. A cell naming
  *several* sets is correctly a `stat` row; what must not survive is a `stat` row whose whole
  text is one set the snapshot names elsewhere.
* `assert weapon.weapon_id` is gone. It could not return a second answer, and it passed for
  months against ids that existed in exactly one database.
* 14 new frontend tests across `shared/kqm/kqm.spec.ts` and the optimize set filter.

## Still open

**OQ-K1 — whether an unresolved row should be visible at all.** A row with `weapon_id: null`
keeps its citation and cannot be clicked. Nothing renders that state specially today, so it
simply does not appear among the cards while still counting in the guide. A caption saying
*"KQM also lists N weapons this patch does not have"* is the honest version and needs an owner
ruling on whether it is worth the line.
