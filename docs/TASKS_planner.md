# TASKS — the leveling planner

Design: `docs/DESIGN_planner.md`. Data audit: `docs/RESEARCH_leveling_planner_data.md`.

**Status:** P.0 done. P.1–P.10 open.

| # | task | state |
|---|---|---|
| P.0 | Branch `feat/leveling-planner` off `dev`; DESIGN + TASKS committed | **done** |
| P.1 | Snapshot: derive material meta, level caps, EXP items, crafting tree, resin costs, drop EVs into `app/data/yuanshen/snapshot/planner_economy.json` via `build_snapshot.py` | open |
| P.2 | `app/data/planner/curated_rates.json` — the 14 numbers, each with a `source`; test asserts every entry cites one | open |
| P.3 | Migration + models: `materials`, `character_ascension_costs`, `character_talent_costs`, `weapon_ascension_costs`, `user_materials`, plus `characters.level_exp` / `weapons.xp_requirements` | open |
| P.4 | nanoka importer writes the cost tables and the EXP curves; seed + verify | open |
| P.5 | GOOD importer reads the `materials` map into `user_materials` | open |
| P.6 | Cost engine: levels → EXP → books → mora; ascension; talents 1–10; weapon. Sections + cumulative | open |
| P.7 | Resin engine: craft-root reduction, average, histogram, per-item; `null` where uncurated | open |
| P.8 | Crafting bonuses: parse the 26 passives into an id→effect table with a test that all 26 still parse | open |
| P.9 | API `/planner/options` + `/planner/plan`; regenerate the OpenAPI contract | open |
| P.10 | Frontend `/planner` page, nav link, splash art + material icons vendored | open |

**Acceptance for the feature as a whole:** a plan for a character the user owns at some level,
against a weapon they own, priced in materials/mora/resin with a histogram, subtracting their
GOOD stock — driven in the real app, not only in tests. `CLAUDE.md` §"Drive the feature".
