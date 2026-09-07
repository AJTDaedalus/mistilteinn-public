# TASKS — the leveling planner

Design: `docs/DESIGN_planner.md`. Data audit: `docs/RESEARCH_leveling_planner_data.md`.

**Status:** P.0–P.10 done. The feature is walkable at `/planner`.

| # | task | state |
|---|---|---|
| P.0 | Branch `feat/leveling-planner` off `dev`; DESIGN + TASKS committed | **done** |
| P.1 | Snapshot: derive material meta, level caps, EXP items, crafting tree, resin costs, drop EVs into `app/data/yuanshen/snapshot/planner_economy.json` via `build_snapshot.py` | **done** |
| P.2 | `app/data/planner/curated_rates.json` — keyed by **source**, not by material; test asserts every filled entry cites one. Collapsed from twelve per-material numbers to five once gems and overworld drops were ruled resin-free | **done** |
| P.3 | Migration + models: `materials`, `character_ascension_costs`, `character_talent_costs`, `weapon_ascension_costs`, `user_materials`, plus `characters.level_exp` / `weapons.xp_requirements` | **done** |
| P.4 | nanoka importer writes the cost tables and the EXP curves; seed + verify | **done** |
| P.5 | GOOD importer reads the `materials` map into `user_materials` | **done** |
| P.6 | Cost engine: levels → EXP → books → mora; ascension; talents 1–10; weapon. Sections + cumulative | **done** |
| P.7 | Resin engine: craft-root reduction, average, histogram, per-item; `null` where uncurated | **done** |
| P.8 | Crafting bonuses: classify the passives already in `ascension_passives` — **12** are planner-relevant, 7 applied and 5 reported | **done** |
| P.9 | API `/planner/options` + `/planner/plan`; regenerate the OpenAPI contract | **done** |
| P.10 | Frontend `/planner` page, nav link, splash art + material icons vendored | **done** |

**Acceptance for the feature as a whole:** a plan for a character the user owns at some level,
against a weapon they own, priced in materials/mora/resin with a histogram, subtracting their
GOOD stock — driven in the real app, not only in tests. `CLAUDE.md` §"Drive the feature".


## What was found by building it, not by testing it

Six things a green suite could not see. Each is recorded because the shape repeats:

1. **The route 404'd** against the running backend until the container was restarted.
2. **`Resin ≈ 0`** where nothing in the section could be priced. Zero is an answer; that was
   the absence of one.
3. **A satisfied material rendered `?`**, claiming its drop rate was unknown — false, and
   about the one row a user least needs to worry about.
4. **The summary added character EXP to weapon EXP** while crediting only the character's
   stock. Books and Enhancement Ore are different pools.
5. **Hero's Wit and Mystic Enhancement Ore bound to nothing**, because EXP denominations are
   never named in an ascension bill so nanoka never names them. The planner would have priced
   levelling as though the user held none of the 204 books they actually have.
6. **`Spectral Husk` was priced at 40 resin a run**, because an elite enemy's reward preview
   lists it. It is an ordinary overworld mob drop and costs nothing.

## The five curated numbers, answered 2026-09-07

All filled by the owner, each carrying its `source` in `app/data/planner/curated_rates.json`.
`uncurated_sources` is now `[]`, and `test_every_resin_source_is_now_priced` is what should
fail the day a patch adds a source nobody has costed.

| | |
|---|---|
| `weekly_boss` | **0.733333** per 20… per **30** resin. *"2.2 named materials per run on average (always 2 or 3), randomly selected between 3 options for each boss"* — 2.2 is the run's **total across the boss's three materials**, so one named material is 2.2/3. Getting that split wrong scales every weekly-boss figure by three |
| `ley_line_exp` | **122,500** EXP points per 20 resin. *"6-7 blue xp books per ley line and 4-5 purple books"* at World Level 9 → 6.5 × 5,000 + 4.5 × 20,000 |
| `ley_line_mora` | **60,000** mora per 20 resin, flat |
| `mora_per_exp.character` / `.weapon` | **0**. *"there is no more per exp point conversion"* — Genshin stopped charging mora for feeding EXP material. **Not the same as levelling being free**: ascension and talent mora still come from the payload's own `cost` fields |

**One world-level assumption is now load-bearing and stated on the page**: the ley-line yields
are World Level 9 figures.
