# DESIGN — the character roster

**Status: designed 2026-09-03, implementation in progress.**

Owner's ruling, 2026-09-03, choosing between two candidates written up as
`BACKLOG_frontend.md` §14:

> *"we could take the broader approach and make a character table (with ownership) and a build
> table (with builds) and track them separately, but we need a tab for both so users can change
> ownership manually if needed."*

Chosen over the cheaper *"make builds for empty characters and grey them out"* after two
measurements, both against the owner's own data.

---

## Branch policy

Work happens on **`feat/character-roster`**, branched from `dev`.

**No direct commits to `dev` or `main`.** `dev` is updated only by PR merge after review; `main`
is for releases. Verify `git branch --show-current` before every commit. There are no parallel
sub-branches — this is one track.

The branch-setup gate is **Task 0** of `docs/TASKS_character_roster.md`.

---

## 1. Why `builds.owned` cannot be the record

`builds.owned` was added days ago (`DESIGN_account_tracking.md` Track 1) and its own docstring
names the asymmetry it was closing: `owned_weapons` records a user's actual weapons, artifacts
arrive from a GOOD export, and **characters were the only entity with no ownership record**. A
build was the only per-character row there was, so the flag went there.

Two facts make that the wrong home, and neither is hypothetical.

### 1.1 The schema permits a character to have several builds, which can then disagree

**This one is latent, not live, and an earlier draft of this document got that wrong.** A first
pass grouped builds by character name *across all users* and read the result as one user holding
several builds of one character. Re-measured per owner:

| | |
|---|---|
| builds | **84** |
| orphaned (`owner_id IS NULL`, a deleted user's) | **4** |
| **users holding 2+ builds of one character** | **0** |

So nothing diverges today. What makes it a question of *when* rather than *if* is that the
schema deliberately allows it — `build.py` says so at the top:

> **A user may own several builds of one character.** `uq_builds_owner_character` […] was
> dropped by owner decision (2026-08-24, T.1a): comparing a C0 against a C6, or a Physical Eula
> against a Cryo one, is an ordinary thing to want in this game.

The moment someone does that ordinary thing *and* marks one of the two a test build — which is
`owned`'s entire stated purpose — the account has two stored answers to *"do you have Eula?"*
and no correct way to reduce them. `bool_or` says yes when they meant no for that build;
`bool_and` says no when they plainly own her.

**A per-build flag cannot express a per-character fact**, and this repo has already ruled that a
user may have many builds per character. The two decisions are incompatible; this is the one
that gives way.

**§1.2 is the live defect**, and it is the one that actually forced the change.

### 1.2 Twelve characters the owner owns have no build at all

`good_build_service` creates a build only for a character *holding a weapon or an artifact*, and
argues the rule well: the export lists GO's `Manekin` / `Manekina` practice mannequins, and
keying on "is something equipped" excludes them without the module ever naming them.

Measured on `references/genshin_export_2026-08-28_11-07.json`:

| | |
|---|---|
| characters in the export | **89** |
| holding a weapon or artifact | **75** ← the builds that exist |
| owned, wearing nothing | **15** |
| …real characters (minus 2 mannequins, 1 Traveler variant) | **12** |

Dahlia, Yun Jin, Ningguang, Amber, Razor, Yaoyao, Mika, Kaveh, Sethos, Shikanoin Heizou, Alyosha
and Ifa. Eleven of the twelve favour two furnishing sets each, so the teapot tracker cannot see
**22 sets — 440 Primogems** the owner is owed.

The rule excludes the mannequins **correctly by accident**, and twelve real characters pay for
it. That is the shape of the whole problem: *equipment* was standing in for *ownership*.

---

## 2. The model

Ownership becomes its own per-user, per-character row. A build stays a build.

```
character_roster (owner_id, character_id)   ← composite PK, one row per character per user
    owned    bool     not null
    source   enum     'import' | 'manual'
    …timestamps

builds (…)                                   ← `owned` column DROPPED
    zero, one, or many per character
```

The composite primary key is deliberate and follows the precedent already in this repo:
`teapot_progress` and `teapot_built` are keyed `(owner_id, suite_id[, character])` rather than
carrying a surrogate id. It is the constraint that makes the disagreement in §1.1 unrepresentable
— a character has exactly one ownership answer per user, enforced by the database rather than by
whoever writes the next query.

`source` records **who said so**, and exists because an import must never silently overwrite a
person's own correction. A row the user set by hand is `manual`; a re-import refreshes `import`
rows and leaves `manual` ones alone. This is the same rule `good_build_service` already applies
to builds — *"a build carries decisions that no scanner knows about"* — applied to the one fact
this table holds.

### 2.1 Absent is not the same as unowned

A missing row means **nobody has said** — a character in the catalogue that this user has never
imported or touched. `owned = false` means the user said no. The API renders the catalogue
left-joined to the roster so the distinction is visible on screen, and the difference matters:
a fresh account should not read as *"you own none of the 150 characters"*, and a character the
user has explicitly un-owned should not silently come back on the next import.

### 2.2 The mannequins are excluded by id, not by name

`Manekin` and `Manekina` are structurally identifiable in the seeded catalogue, verified rather
than assumed:

| | |
|---|---|
| `nanoka_id` | `10000117-2` … `10000117-8`, `10000118-2` … `10000118-8` |
| `icon` | `UI_AvatarIcon_MannequinBoy`, `UI_AvatarIcon_MannequinGirl` |

Fourteen rows, seven elements each. Excluded by a pinned id prefix with the capture cited, which
is what the current "is something equipped" rule was written to avoid needing — reasonably, since
a name match on `"Manekin"` would be fragile across localisations. An id prefix is not.

They stay in the catalogue (they are real entries in the game data and `/characters` should show
what the game has); they are simply never given a roster row, and never offered a toggle.

---

## 3. Migration, and the backfill that must not lose anything

One revision, three statements, in this order:

1. **Create** `character_roster`.
2. **Backfill** from existing builds: for each `(owner_id, character_id)`, one row with
   `owned = bool_or(builds.owned)` and `source = 'import'`.
3. **Drop** `builds.owned`.

`bool_or` is the right reducer for the backfill specifically — **no user holds two builds of one
character today** (§1.1, measured), so it is lossless by construction on the data that exists,
and where a disagreement did exist the generous read is the safe one: a character wrongly marked owned costs a teapot row the user can
untick, while one wrongly marked unowned silently hides a character they have.

The **import backfill is separate and is not the migration's job**: the migration can only see
builds, so it cannot recover the twelve characters that never got one. Those arrive when the
owner re-imports their GOOD export, and §4 is what makes that work.

**Downgrade** re-adds `builds.owned` defaulting true and drops the table. It cannot restore
per-build divergence, and nothing has any.

---

## 4. The import path

`good_build_service` keeps its rule for **builds** exactly as it is — an unequipped character has
no gear to optimize, so it has no build, and the mannequin exclusion keeps working for free.

What it gains is a second, independent output: **a roster row for every non-mannequin character
in `characters[]`**, `owned = True`, `source = 'import'`, skipping any row already marked
`manual`.

The two outputs answer different questions and are computed from different fields, which is the
whole point of the change:

| question | source in the export | result |
|---|---|---|
| what gear does this character have? | `artifacts[].location`, `weapons[].location` | a build |
| does this account have this character? | `characters[]` | a roster row |

---

## 5. The surface

`/builds` gains two tabs, per the owner: **ROSTER** and **BUILDS**.

**ROSTER** — every catalogue character (minus mannequins), each with an own / not-own toggle.
Filterable by the same element / weapon / rarity chips the builds tab already carries, since
those are now one shared bordered-tile control. Shows what a user needs to correct an import:
which characters the app thinks they have.

**BUILDS** — unchanged, except that an **owned character with no build** appears as a muted
placeholder card sorted to the end, offering to create one. That is the owner's original request
from the cheaper option, and it survives into this design because it is a genuinely useful thing
for the builds tab to say: *you own this character and have not built them*. The difference is
that the card is a prompt rather than an empty row pretending to be a build.

---

## 6. What reads the roster

- **The teapot tracker** — `progress_for` already takes `owned_character_ids: set[str]` as a
  parameter, so only its caller in `api/v1/teapot.py` changes: the query joins the roster instead
  of builds. The service itself needs no edit, which is what taking the ids as an argument bought.
- **Nothing else yet.** `builds.owned` connected to nothing but the teapot, deliberately — it was
  *"a record kept now so a later feature can rely on it having been kept all along."* That
  reasoning is unchanged; the record is just kept somewhere it can be true.

---

## 7. Open questions

**OQ-R1 — should the optimizer refuse to build for an unowned character?** It currently cannot
know. Arguably a search over a character you do not have is a legitimate "what if I pulled them",
which is the same argument that made `owned` default true. Not decided; nothing depends on it.

**OQ-R2 — should a roster row carry constellation and level?** The export has both, and they are
per-character facts sitting on `builds` for the same reason `owned` was. Deliberately **not** in
this chunk: they are used by the damage chain, which reads them off a build, and moving them is a
much larger change than moving a boolean nothing computes with.
