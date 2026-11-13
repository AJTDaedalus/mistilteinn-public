# TASKS: formula fallback

**Status: proposed, 2026-11-13. Waiting on owner decisions D-F1–D-F6**
(`DESIGN_team_math_fallback.md` §4). Not started.

Each task lists its acceptance criteria. "Crossval" means a committed fixture checked against
gcsim at the pin.

| # | task | files | acceptance |
|---|---|---|---|
| 0 | Branch `feat/math-fallback-p0` off `dev` | — | `git branch --show-current` |
| **P0** | | | |
| 1 | Parse the talent tail into a per-part scaling stat; split mixed-stat rows into one hit with several terms, not several hits | `services/talent_scaling.py`, `TalentHit` | Every level-1 DMG row classified (the inventory's tail table). Nahida's Tri-Karma is one hit with ATK and EM terms. A crossval test compares the tail with `talent_multipliers.json` |
| 2 | Pass each hit's scaling stat through single-hit Optimize and explain; remove the hardcoded `'atk'` | `optimize.service.ts:58`, `explain.service.ts:59`, `sim/search.ts` | Neuvillette and Furina single-hit results scale off HP, with a spec per stat. `npm run verify`. Driven in the browser |
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
