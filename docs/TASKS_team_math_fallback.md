# TASKS: formula fallback

**Status: P0 (tasks 0–2) done on `feat/math-fallback-p0`, 2026-11-13 — not yet merged.**
D-F6 was answered *ship P0 now*; P1 onward still waits on owner decisions D-F1–D-F5
(`DESIGN_team_math_fallback.md` §4). Evidence for each task is in its row and in
`LOG_mistilteinn.md` §"Math-fallback P0".

Each task lists its acceptance criteria. "Crossval" means a committed fixture checked against
gcsim at the pin.

| # | task | files | acceptance |
|---|---|---|---|
| 0 ✅ | Branch `feat/math-fallback-p0` off `dev` | — | `git branch --show-current` — **done**, off `e257636` |
| **P0** | | | |
| 1 | Parse the talent tail into a per-part scaling stat; split mixed-stat rows into one hit with several terms, not several hits | `services/talent_scaling.py`, `TalentHit` | Every level-1 DMG row classified (the inventory's tail table). Nahida's Tri-Karma is one hit with ATK and EM terms. A crossval test compares the tail with `talent_multipliers.json` — **done** (`eade7bc`). All 35 level-1 tail shapes classified (`test_talent_scaling_stat.py::SURVEY`); 120 level-1 rows over 42 characters changed classification; 9 rows refused by name; Tri-Karma is one ATK+EM hit. `crossval_multipliers` against the seeded DB: 114 characters, 20,021 hits, 1,050 stats checked against gcsim's tail, 0 mismatched, 0 refused. GO fixtures in `test_go_single_hit_fixtures.py` (`0c52763`) |
| 2 | Pass each hit's scaling stat through single-hit Optimize and explain; remove the hardcoded `'atk'` | `optimize.service.ts:58`, `explain.service.ts:59`, `sim/search.ts` | Neuvillette and Furina single-hit results scale off HP, with a spec per stat. `npm run verify`. Driven in the browser — **done** (`02d88db`, `415d372`, `4e76b25`, plus `027e80a`, a pre-existing search-context base bug found while driving). Driven: Neuvillette burst Skill DMG searched on the owner's 2,370-piece inventory; kernel winner 24,272.3 = server `/explain` of the same five 24,272.305; Nahida Tri-Karma 7,708.8 = 7,708.84. `npm run verify` 1,436 passed |
| **P1** | | | |
| 3 | `gcsim` block on Character/Weapon/ArtifactSet reads, plus a `?gcsim=` filter | `api/v1/{characters,weapons,artifact_sets}.py`, `gcsim_keys.py` | Statuses full/partial/none match the coverage fixture. The OpenAPI diff is additive only. Badge in the team builder |
| 4 | Import passive and constellation `param_list`, and per-hit `attack[]` / `energy[]` | importer, mappings, migration | `verify_seed` counts. Numbers equal the payloads for the nine fixtures |
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
