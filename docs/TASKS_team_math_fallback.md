# TASKS: formula fallback

**Status: P0 (tasks 0–2) merged (#367). P1 started 2026-11-13 (owner: "start"): tasks 3 and 4
done on `feat/math-fallback-p1-data`, not yet merged; tasks 5–7 are on
`feat/math-fallback-p1-recipe`.** The owner's rulings are `DECISIONS.md` §38 (D-F1, D-F2, D-F5
as recommended; D-F3 opt-in for every team; D-F4 GO is the comparator). Evidence for each task
is in its row and in `LOG_mistilteinn.md` §"Math-fallback P0" and §"Math-fallback P1 data".

Each task lists its acceptance criteria. "Crossval" means a committed fixture checked against
gcsim at the pin.

| # | task | files | acceptance |
|---|---|---|---|
| 0 ✅ | Branch `feat/math-fallback-p0` off `dev` | — | `git branch --show-current` — **done**, off `e257636` |
| **P0** | | | |
| 1 | Parse the talent tail into a per-part scaling stat; split mixed-stat rows into one hit with several terms, not several hits | `services/talent_scaling.py`, `TalentHit` | Every level-1 DMG row classified (the inventory's tail table). Nahida's Tri-Karma is one hit with ATK and EM terms. A crossval test compares the tail with `talent_multipliers.json` — **done** (`eade7bc`). All 35 level-1 tail shapes classified (`test_talent_scaling_stat.py::SURVEY`); 120 level-1 rows over 42 characters changed classification; 9 rows refused by name; Tri-Karma is one ATK+EM hit. `crossval_multipliers` against the seeded DB: 114 characters, 20,021 hits, 1,050 stats checked against gcsim's tail, 0 mismatched, 0 refused. GO fixtures in `test_go_single_hit_fixtures.py` (`0c52763`) |
| 2 | Pass each hit's scaling stat through single-hit Optimize and explain; remove the hardcoded `'atk'` | `optimize.service.ts:58`, `explain.service.ts:59`, `sim/search.ts` | Neuvillette and Furina single-hit results scale off HP, with a spec per stat. `npm run verify`. Driven in the browser — **done** (`02d88db`, `415d372`, `4e76b25`, plus `027e80a`, a pre-existing search-context base bug found while driving). Driven: Neuvillette burst Skill DMG searched on the owner's 2,370-piece inventory; kernel winner 24,272.3 = server `/explain` of the same five 24,272.305; Nahida Tri-Karma 7,708.8 = 7,708.84. `npm run verify` 1,436 passed |
| **P1** | | | |
| 3 ✅ | `gcsim` block on Character/Weapon/ArtifactSet reads, plus a `?gcsim=` filter | `api/v1/{characters,weapons,artifact_sets}.py`, `gcsim_keys.py` | Statuses full/partial/none match the coverage fixture. The OpenAPI diff is additive only. Badge in the team builder — **done** (`8d0961a`). `services/gcsim_status.py`, computed on read; on the summaries too, so `BuildRead.character` carries it. Over the 150 committed characters: **39 full, 89 partial (70 lack only plunges), 22 none**, and `none` equals `gcsim_character_coverage.json` exactly (`test_gcsim_status.py`). Weapons 246 full / 40 none, sets 55 / 10 — full\|none only. OpenAPI: 2 schemas added, 5 gain `gcsim`, 3 list paths gain the query; nothing removed or altered. Badge driven on `/characters` and `/teams` |
| 4 ✅ | Import passive and constellation `param_list`, and per-hit `attack[]` / `energy[]` | importer, mappings, migration | `verify_seed` counts. Numbers equal the payloads for the nine fixtures — **done** (`811c2aa`). Migration `22ba8f830ff9` (up and down run). Equal to the payloads for all four character fixtures (unit + integration). Re-seeded a throwaway DB at nanoka **7.2.51**: 154/154 characters, **509 passives and 828 constellations with params, 2,199 attack rows, 243 energy drops**, and every row equal to the live payload (0 mismatches over 154). `verify_seed --live` passes with two new Ayaka anchors |
| 5 | Synthetic recipe: (team, builds, rows × counts, conditionals) → `Recipe` | new `sim/formula-recipe.ts` (+ backend mirror if needed) | On a gated team with no kit buffs, terms equal a calibrated recipe stripped of buffs. Multi-target row counts sum correctly |
| 6 | Elemental resonance | formula buffs | Each resonance cited. Team-element tally tests |
| 7 | Conditional set bonuses with toggles and defaults | set bonus evaluator | All 60 four-piece and 9 two-piece sets have a condition and a default. Specs for stacks |
| 8 | Routing when gcsim refuses (`GcsimKeyError`), offering the estimate; labels; assumptions panel (lite) | optimize, rank and upgrade pages | A Lohen team is optimizable end to end. The result is labelled "Formula estimate". Screenshots at 1280 and 390 |
| **P2** | | | |
| 9 | Sheet schema on Pando tags (`SRC_*`, `COND`, scope) and the two-pass team evaluator | `pando/`, new `formula/sheets/` | One worked sheet (Bennett) round-trips. Its buff reaches teammates. Two-pass ordering tested |
| 10 | Crossval harness: formula recipe vs gcsim, per hit | `tests/crossval/` | Planting a wrong buff fails it. Tolerance per D-F4 |
| 11+ | Sheets: ungated characters (marked unverified) and the top buffers (verified), one task per character | `formula/sheets/<char>` | Each verified sheet passes task 10, or is marked unverified with a GO citation |
| **P3** | | | |
| 12 | Weapon passives, tiers 1 and 1c | per `RESEARCH_passive_tiers.md` | Crossval where gcsim has the weapon |
| 13 | Transformative, additive and Lunar reactions with a reaction-count assumption | `formula/genshin/damage.py`, `damage.ts` | Cited level-multiplier table; crossval |
| 14 | ER from particle data | energy model | Compared with gcsim's waiting-mode ER on gated teams |
