# DESIGN — the leveling planner

**Feature:** a `/planner` tab that plans one character and one weapon from where they are now
to where you want them, priced in materials, mora and resin.

**Founding data audit:** `docs/RESEARCH_leveling_planner_data.md`. Every number below is
derived there or cited to a table; nothing is recalled. Read it before changing this.

## Branch policy

Work happens on **`feat/leveling-planner`**, branched from `dev`.

**No direct commits to `dev`.** `dev` is the trunk and a merge to it deploys to production;
this branch merges by PR after `cd backend && python -m scripts.ci_local` exits 0 over every
job on the exact commit that is the PR head. There are no parallel sub-branches. Task 0 in
`docs/TASKS_planner.md` is the branch-setup gate.

## 1. Owner's rulings, 2026-09-07

| | |
|---|---|
| character art | **full splash, committed as-is** (~64 MB). `DECISIONS.md` gains an entry saying the §4 weight argument was re-made, not inherited |
| current progress | read from a **build the user picks** as the "from" state |
| plan shape | **one character + one weapon per plan** |
| owned stock | read GOOD's `materials` map, subtract it, show *still need* |
| mora | **totalled, never imported** — GOOD has no currency field, so the planner prices mora and never claims you can afford it |
| talents | **1→10 only.** 11–15 come free from C3/C5 and have no material rows |
| resin | shown as **an average and a histogram**, for the whole plan and per section, plus a **per-item** figure |
| crafting bonuses | selectable characters whose passive doubles product or refunds materials |

## 2. What the data supports, in one table

| need | source | curation |
|---|---|---|
| ascension / talent / weapon material costs | nanoka detail payloads, already pinned | none |
| character EXP per level | nanoka `level_exp` — **per-level, not cumulative**; first 89 sum to 8,362,650 | none |
| weapon EXP per level | nanoka `xp_requirements` (per weapon, so rarity is already baked in) | none |
| ascension → level cap | `AvatarPromoteExcelConfigData.unlockMaxLevel` → `(0,20)(1,40)(2,50)(3,60)(4,70)(5,80)(6,90)` | none |
| EXP item denominations | `MaterialExcelConfigData.itemUse[ITEM_USE_ADD_EXP]` → 104001/2/3 = 1,000 / 5,000 / 20,000; `ADD_WEAPON_EXP` → 104011/2/3 = 400 / 2,000 / 10,000 | none |
| material name / rarity / **icon** | `MaterialExcelConfigData.icon` — `UI_ItemIcon_104161`, **cited, no longer a guessed basename** | none |
| crafting tree | `CombineExcelConfigData` — `materialItems` → `resultItemId`, with `scoinCost` mora | none |
| resin per run | `DungeonExcelConfigData.statueCostCount` (20, item 106), `InvestigationMonsterConfigData.resinCost` (40/60), `BlossomChestExcelConfigData.resin` (20) | none |
| domain weekday rotation | `DailyDungeonConfigData` + `DungeonEntryExcelConfigData.descriptionCycleRewardList` | none |
| expected drop per run | `RewardPreviewExcelConfigData` fractional counts — **94 of 247 resin-reachable materials**; 120 more derive through the crafting tree | **12 numbers** |
| mora charged per EXP point | **not published in any of the 1,935 tables** | **2 numbers** |
| crafting-bonus passives | `ascension_passives`, already seeded — 26 rows, 3 effect shapes | a 26-row id→effect table |

## 3. The two things that are not derivable, and how they are handled

**Five curated numbers, in one file, each with a `source` string — all supplied by the owner
on 2026-09-07.** Keyed by **source**, not by material: the weekly-boss yield (0.8 of a
named material per 30-resin run, being 2.4 items split across the boss's three), the two
ley-line yields (122,500 EXP and 60,000 mora per 20 resin at World Level 9), and the two
mora-per-EXP rates, which are **zero** — Genshin no longer charges mora for feeding EXP
material. They live in `app/data/planner/curated_rates.json` — **not** under
`app/data/yuanshen/snapshot/`, because that directory means *derived from the pinned dump* and
these are not. A test asserts every filled entry carries a non-empty `source`.

**It began as twelve per-material numbers and shrank, on the owner's ruling (2026-09-07):**
*"gems and overworld drops don't have a resin cost, same with the local specialties"*, and
*"Mora, talent books, weapon ascension mats, world boss drops, character xp books, and weekly
boss mats are the only things that should have a [resin] cost"*. The gem rule is a
double-counting fix rather than an omission — a gem drops from a world boss alongside the
boss's own material in the same 40-resin run — and it removed seven of the twelve outright.
The rest became per-source, because a trounce domain's yield is a property of the activity and
not of the item, so one number prices all 47 weekly-boss drops.

**Anything without a rate reports `resin: null`, never a guess.** Nothing does today; the
mechanism exists for the next patch that adds a source, and a test asserts the list is empty
so its arrival is visible. The calculator does not fall
back to an average, and the UI says *"resin unknown for this material"*. A skipped check is
never a pass; an unpriced material is not free.

## 4. The resin model — an average and a histogram

Materials are reduced to their **craft-root equivalent** using the real `CombineExcelConfigData`
ratios (accumulating `scoinCost` as mora), because a domain run drops several tiers of one
family and you convert upward anyway. Roots are then grouped by farm source.

- **Average.** `expected_runs = need_base / ev_base`, `resin = expected_runs × resin_per_run`.
  This is what the summary and the per-item figure show.
- **Histogram.** Per-run yield `Y` is modelled as the **two-point integer distribution matching
  the published mean** — `P(⌈μ⌉) = μ − ⌊μ⌋`, else `⌊μ⌋`. The number of runs to meet the
  requirement is then a first-passage time, computed by dynamic programming over the
  accumulated total, and total resin is `runs × resin_per_run`.

**The histogram is a model and the UI says so.** Two-point is the *minimum-variance*
distribution with that mean, so the real spread is **wider** than what is drawn. It is
labelled as a floor on the spread, not a prediction. The per-run distribution is a swappable
field on the rate entry, so a curated richer distribution can replace the default without
touching the engine.

**No true distribution exists to check this against.** Nothing in the dump resolves a
`drop_id`; the randomised tables are server-side.

## 5. Schema

Five new tables. Costs live in the database because §"Data Source of Truth" makes it the
single source for game data, and the nanoka importer already runs.

- `materials` — `id` (game id, PK), `name`, `icon`, `rarity`.
- `character_ascension_costs` — `character_id`, `phase` 1–6, `mora`, `items` JSONB.
- `character_talent_costs` — `character_id`, **`talent_id`**, `level` 1–9, `mora`, `items` JSONB.
  **Keyed per talent, not per character.** An earlier draft justified this by saying Ayaka's
  four cost lists hold two distinct sets; that is true of the *bytes* and false in substance —
  measured, her three levelable talents carry **identical** bills and the second signature is
  the **empty** list belonging to `Kamisato Art: Senho`, her alternate sprint, which has no
  talent levels at all. The real reasons are that the list is positional against `skills[]` so
  a per-character schema would have to guess which entry is "the" cost, and that per-talent
  keying is what lets the planner take Burst to 10 and Skill to 8 independently — which is
  the feature.
- `weapon_ascension_costs` — `weapon_id`, `phase` 1–6, `mora`, `items` JSONB.
- `user_materials` — `owner_id`, `material_id`, `count`. Written by the GOOD import.

`level_exp` and `xp_requirements` go on `characters.level_exp` and `weapons.xp_requirements`
as JSONB rather than a row per level — they are read whole, always.

## 6. Surfaces

`GET /api/v1/planner/options` — buildable characters and weapons, with owned/unowned marked.
`POST /api/v1/planner/plan` — the plan request (character, from-build or explicit state,
targets, weapon, crafting-bonus characters) → sections, cumulative summary, resin.

Frontend route `/planner`, one page, three sections plus a summary, splash art behind the
character column, weapon art, talent icons, material icons on every row.

## 7. Out of scope

A queue of targets (owner: one per plan), rotation or artifact planning, resin *income* over
time (a "when will I finish" date), and domain-day scheduling beyond showing the weekdays.
