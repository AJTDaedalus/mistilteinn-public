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
| `weekly_boss` | **0.8** per **30** resin. 2.4 items a run (always 2 or 3), each randomly one of the boss's three materials, so a named one is 2.4/3. Getting that split wrong scales every weekly-boss figure by three |
| `ley_line_exp` | **122,500** EXP points per 20 resin. *"6-7 blue xp books per ley line and 4-5 purple books"* at World Level 9 → 6.5 × 5,000 + 4.5 × 20,000 |
| `ley_line_mora` | **60,000** mora per 20 resin, flat |
| `mora_per_exp.character` / `.weapon` | **0**. *"there is no more per exp point conversion"* — Genshin stopped charging mora for feeding EXP material. **Not the same as levelling being free**: ascension and talent mora still come from the payload's own `cost` fields |

## Reconciled against the wiki, 2026-09-07

The owner pointed at [Loot System](https://genshin-impact.fandom.com/wiki/Loot_System) and its
Material Drop Distribution tab.

| | |
|---|---|
| ley lines | **confirmed exactly** — 6-7 blue and 4-5 purple, 122,500 EXP average, 60,000 mora, 20 resin, and **flat across WL6-9** rather than a WL9-only figure |
| world bosses | **confirmed** — the wiki's 2.5556 matches the 2.556 our snapshot reads from the game's own preview, which is independent evidence that those fractional counts are expected values |
| domains | **wrong, 4.6× and 7.6×.** A domain has a guaranteed 2-star roll *and* variable drop packs; the preview publishes only the first. Fixed |
| weekly bosses | **corrected to 2.4.** The owner first gave 2.2, read off the part of the wiki's table that stops at World Level 8, then confirmed 2.4 — *"I forgot WL9"* |
| trounce resin | 60, halved to 30 only three times a week — our 30 is the optimistic price |

**World Level 9 is missing from the wiki's weekly-boss and elite-boss tables**, which is what
the owner spotted. The ley-line table does carry it.

## World Level 9 did change world bosses — researched 2026-09-07

The owner asked whether it had, expecting not. It did, and our number is the old one.

`WorldLevelExcelConfigData` (primary) puts WL8 at monster level 90 and **WL9 at 100**. The
wiki's *Adventure Rank* page — a different page from the drop tables — gives the WL9 row the
note **"Normal Bosses guarantees at least Character Level-Up Material × 3"**, against ×2 since
WL4, and puts the normal-boss level at 103. Coverage of the 5.0 announcement says all world
bosses drop three with a low chance of four.

**Two things hid it, and both are the same shape as bugs this feature already had.** The
wiki's Material Drop Distribution page stops at WL8 and its formula caps `Ratio = 1` above
reward tier 18 — a table that stops reads exactly like a table that plateaus.
`RewardPreviewExcelConfigData` carries **one** value across all 101 boss previews (2.556, the
WL8 figure to four decimals), with no world-level variants, so the game data cannot show the
change either.

**The exact WL9 split is not published** — how often the fourth drops — and the two published
claims disagree. *"Three with a low chance of four"* caps the mean below 4; the separately
reported *"50% increase in ascension materials"* would give 2.5556 × 1.5 = **3.8333**, which
is also exactly 46 materials in 12 runs against WL8's 46 in 18. A mean of 3.8333 needs the
fourth to land 83% of the time, which is not a low chance.

**Owner's call: 3.1**, the conservative reading (a 10% fourth). If the 50% figure turns out to
be literal this is 24% low and one number changes. A full ascension goes from 720 resin to
594.

**Weekly bosses did not change** — confirmed by the owner, and consistent with the wiki: the
WL9 row carries no weekly-boss note and the by-enemy-level table already gives 2.4 for levels
100–104.
