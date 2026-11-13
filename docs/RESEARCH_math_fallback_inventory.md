# RESEARCH: what exists toward a closed-form (GO-style) optimizer fallback

Status: COMPLETE (2026-11-13). Research only. No code changed, nothing decided.
Companion: `docs/RESEARCH_go_team_math.md`, written the same day by another agent, covers the
**GO side** (how Genshin Optimizer's team math works). This file covers **our side**: what
the repo already has, where it falls short, and what a fallback would need.

**Owner goal.** Every team should be optimizable whether or not gcsim implements every member,
via a closed-form fallback "in the vein of GO": an estimate of the team's buffs and damage
potential, for one picked ability or a weighted mix of abilities (multi-opt).

**How this was measured.** Code read at `feat/gcsim-v2-50` @ `dff7678` (gcsim pin `b107b5dc`,
v2.50.0, working tree; `dev` is still at `caf738dc`). Counts come from the **local DB**
(`seed_runs`: 7.2.50, succeeded, 2026-11-08) and the committed JSON. Each count says which
query produced it. Line numbers are against that tree.

---

## TL;DR

1. **Every surface that scores a team requires gcsim**: rotation Optimize, Rank, Upgrade,
   Calculate, and the weapon comparison inside Optimize. A team with one member gcsim lacks
   is **blocked with a 422** that names the member. It is never silently wrong.
2. **The only gcsim-free path is the single-hit chain**: Optimize's "For a single hit" tab and
   `/builds/{id}/explain`. It works for ungated characters, because talent multipliers come
   from nanoka rather than gcsim. **It is a solo, static model.** No team buffs, no
   talents/passives/constellations, no weapon passives, no conditional sets (that is every
   4-piece), no resonance, amplifying reactions only. The frontend also **hardcodes
   `scaling_stat: 'atk'`**, so it is silently wrong for HP, DEF and EM scalers.
3. **The scaffolding for a GO-style model is there, but it holds no data.** It has a tagged
   DAG with scope gating (the Pando evaluator), a contribution log with provenance, and
   declared but unused axes (`SHEET`, `NAME`, `COND`) and sources (`SRC_TALENT`,
   `SRC_CONSTELLATION`, `SRC_ASCENSION_PASSIVE`, `SRC_TEAM`). **The Pando port is the engine
   only. None of GO's per-character sheets came with it.** `BuffPreset` is a dead table with
   no API.
4. **The best reuse point is the recipe kernel.** `sim/recipe.ts` is already a weighted
   multi-hit closed-form objective: per-hit talent multiplier, scaling, flat terms, bonus,
   crit and DEF/RES multipliers, `mine` flag. `recipe-search.ts` optimizes it. A fallback
   that **synthesises a `Recipe` from closed-form math**, instead of calibrating one from
   gcsim, would reuse the search, ranking, upgrade and ER machinery unchanged. That covers
   both the single-ability and the weighted multi-opt case.
5. **The big cost is kit data, not math.** That means about 130 characters' talent, passive
   and constellation buffs (509 passive rows and 828 constellation rows in the DB, as **text
   only**), 245 weapon passives and 60 conditional 4-piece sets. This is size L and it is
   bound by the citation rule.

---

## 1. What the optimizer optimizes against, end to end

### 1.1 Surfaces, and whether each needs gcsim

| surface | objective | engine | needs gcsim? |
|---|---|---|---|
| `/artifacts/optimize`, **"rotation"** (default, `optimize.ts:1376`) | team DPS over an authored rotation | gcsim calibration per 4-piece state → `Recipe` → `recipe-search.ts` replays it closed-form | **yes**: `POST /builds/{id}/calibrate` (`builds.py:1077`) emits a gcsim config for the **whole team** |
| `/artifacts/optimize`, **"For a single hit"** (`optimize.html:90-93`) | one talent hit's expected damage | `POST /builds/{id}/search-context` (`builds.py:365`) → `sim/search.ts` + `sim/damage.ts` (CPU) | **no** |
| `/artifacts/rank` | per-piece score against a build | `artifact-ranking.service.ts:1-27`: `evaluateRecipe` over a calibrated recipe | **yes** |
| `/artifacts/upgrade` | upgrade potential | imports `CalibrationCancelled` and the recipe flow from `recipe-optimize.service` (`upgrade.ts:17`) | **yes** |
| `/calculate` | whole-rotation breakdown | `calculate.ts:20-40`: "gcsim is calibrated once per character … recipe evaluated at real gear" | **yes** |
| weapons in Optimize | rotation DPS per weapon | `weapon_id` in calibrate, grouped per weapon (`recipe-optimize.service.ts:254`) | **yes** |
| `POST /builds/{id}/explain` | one hit, contributions with provenance | `build_combination_log` + `BuildEvaluator` (Python) | **no** (reached from the Optimize single-hit result rows, `optimize.ts:1778`) |
| `POST /builds/{id}/compare-weapons` (first tier) | one hit, weapon swapped, passives listed as `unmodelled_passives` | `weapon_comparison.py` | **no**, and **no frontend caller** (`rg compare-weapons frontend/src/app` finds only `api.types.ts`) |
| GPU kernel `createGpuKernel` | single hit | WGSL | no, but wired to nothing (CLAUDE.md) |

### 1.2 How an ungated team behaves today

"Ungated" means gcsim has no key for a member. **26 of 154 DB characters**
(`gcsim_keys.character_key` over `characters`, pin `b107b5dc`). Fourteen are practice
mannequins and two are unreleased Traveler bodies. The real ones are **Mitya** (the project's
namesake), Kachina, Nefer, Lohen, Linnea, Valeriy, Vodyanitsa, Vesna and two characters still in beta.
The committed list at 7.0.51 is `tests/fixtures/gcsim_character_coverage.json` (26 entries,
which predates Mitya). Weapons: 40 of 286 nanoka weapon ids have no key, nearly all event or
non-player items. Sets: 10 of 65 have no key: Tiny Miracle, Adventurer, Lucky Dog, Traveling
Doctor, Glacier and Snowfield, and the five Prayers.

| surface | behaviour with an ungated member |
|---|---|
| Builds/roster | flagged: `roster.py:90` sets `simulatable=False` with gcsim's reason, and `builds.html:143` shows it |
| Rotation authoring | **allowed**. `_offers_for` (`rotations.py:242-265`) offers the base ten actions "so a rotation naming them fails for that reason", at compile time |
| Rotation Optimize / Rank / Upgrade / Calculate | **blocked, loudly.** `build_config` raises `GcsimKeyError` → 422 with the message (`builds.py:1043,1062,1228`; `rotations.py:721,1115`). This holds even when the *optimized* character is gated and only a teammate is not, because the config carries every member |
| Ungated **set** in rotation mode | **degraded, named.** Filtered from the picker (`optimize.ts:607`, `catalogue.py:220` sets `simulable`), listed as `unsimulableSets` (`optimize.ts:623`). Calibrating one directly → 422 (`builds.py:1150`) |
| Single-hit Optimize / explain | **works**, for the reasons and with the limits in §2. **Silently wrong** for HP/DEF/EM scalers because of the hardcoded `'atk'` (§2.3) |

So nothing gives a silent wrong answer *because* a character is ungated. The rotation surfaces
refuse, and the single-hit surface is equally limited for every character.

---

## 2. The closed-form damage chain

### 2.1 Implemented (Python oracle, mirrored in TS/WGSL)

| mechanic | where | notes |
|---|---|---|
| Stat aggregation `base*(1+pct)+flat` | `formula/genshin/stats.py:1-30` | a DAG of Pando nodes. Scope-gated reads via `stats.scoped` |
| Character base stats, level curves, ascension rows | `services/stat_calculator.py:14-40, add_character` | curve names read from the payload (`prop_grow_curves`), growth curves in `data/yuanshen/snapshot/growth_curves.json` |
| Weapon base ATK + substat on curves, ascension | `stat_calculator.py:add_weapon` (~l.238) | |
| Artifact main/sub stats | `stat_calculator.py:add_artifact` | |
| **Static** set bonuses (2pc props) | `artifact_optimizer.py:503-541` `_apply_set_bonuses` | conditional tiers skipped and counted (§3.3) |
| Traveler story buffs | `formula/genshin/story_buffs.py`, `stat_calculator.py:_add_story_buffs` | the only "buff" in the chain that is not gear |
| Talent multiplier | `services/talent_scaling.py`, `talent_hits.py` | parsed from **nanoka** rows in the DB, not from gcsim (§4.1) |
| DEF multiplier (reduction ≤0.9, ignore ≤1) | `formula/genshin/damage.py:34-57` (+80 offset) | |
| RES multiplier incl. negative and ≥0.75 branches | `damage.py:~138` | |
| Crit: **expected** value `1+CR·CD` (not rolled) | `damage.py:~183` | deliberate divergence, `CROSSVAL_gcsim.md` |
| Amplifying reactions (melt/vape, forward/reverse) + EM bonus `2.78·EM/(1400+EM)` | `damage.py:41-79, amplifying_multiplier` | the only reactions in the chain |
| RES shred / DEF reduction / DEF ignore as registrable quantities | `damage_calculator.py:151-169` | readable, but **no writer** registers any except the enemy profile |
| Multi-hit evaluation with a held memo cache | `damage_calculator.BuildEvaluator` (l.100) | can evaluate many hits per build, but the API exposes one |

Crossval: `tests/crossval` matches a committed gcsim run to 1.3e-8 (`CROSSVAL_gcsim.md`). The
TS mirror is bound to Python by 2,000 cases at 1e-6 (`sim/damage.ts:1-22`).

### 2.2 Not implemented

- **Transformative reactions** (overloaded, swirl, electro-charged, superconduct, shatter,
  bloom/hyperbloom/burgeon, burning): absent. `damage.py:62-67` defers them on purpose.
  **No reaction level-multiplier table** exists: `growth_curves.json` has avatar, weapon and
  monster curves only.
- **Additive reactions** (aggravate/spread): absent (same note).
- **Lunar reactions** (lunar-charged, lunar-bloom, lunar-crystallize): absent from damage.
  `data/reactions/elemental_reactions.json` keeps them, but `services/reactions.py` is a
  *party filter* ("which reactions can this team produce"), not damage, and excludes lunar
  and stellar rows by owner ruling.
- **Any team, talent, passive or constellation buff.** The sources `SRC_TALENT`,
  `SRC_CONSTELLATION`, `SRC_ASCENSION_PASSIVE` and `SRC_TEAM` are declared at
  `tags.py:245-252` and have **zero writers** (`rg` outside `tags.py` finds none). The
  `SHEET`/`NAME`/`COND` tag axes are declared at `tags.py:47-62` "with no constructor yet …
  Chunk H adds the condition constructor". Chunk H was closed without being built.
- **Elemental resonance**: not modelled anywhere. The only hit is a comment in
  `story_buffs.py:74`.
- **Weapon passives**: not applied in the chain. They are listed as `unmodelled_passives`
  (`weapon_comparison.py:15-30`).
- **Infusion / channel derivation**: the caller states `channel` (`schemas/build.py:239-243`,
  `talent_hits.py:16-21`).
- **Energy / ER without gcsim**: the ER model (`recipe-energy.ts`, `energy-delay.ts`) reads
  gcsim's per-run energy observations. Nothing estimates particles closed-form.

### 2.3 Silent defects that would leak into a fallback

1. **The scaling stat is dropped by the multiplier parser.** `talent_scaling._hits_from`
   (`talent_scaling.py:145-193`) reads only the `{paramN}` tokens and throws away the tail
   text. Survey of every level-1 DMG row in the DB:

   | tail | rows |
   |---|---|
   | `#` (ATK) | 1342 |
   | `#/#` | 175 |
   | `#+#` | 120 |
   | `# Max HP` | 34 |
   | `# DEF` | 28 |
   | `# ATK+# Elemental Mastery` | 12 |
   | `# Elemental Mastery` | 5 |
   | `# ATK+# Max HP` | 3 |
   | `# ATK+# DEF` | 3 |
   | `# Elemental Mastery+# DEF` | 3 |
   | `# Cryo + # Physical` | 3 |
   | `# Normal Attack DMG` | 5 |
   | … | … |

   **29 characters** have a non-ATK tail, and **34 rows** mix stat words with more than one
   param. A mixed-stat row such as Nahida's `Tri-Karma Purification DMG` (`# ATK+#
   Elemental Mastery`) or Alhaitham's projections is parsed as **two hits that both land**.
   Both are then scaled by the caller's single `scaling_stat`. M.4 crossvalidated the
   *numbers* against gcsim, but not the scaling stat.
2. **The frontend hardcodes `scaling_stat: 'atk'`**: `pages/optimize/optimize.service.ts:58`
   and `pages/explain/explain.service.ts:59`. The single-hit Optimize result for Neuvillette,
   Furina, Nilou, Yelan, Itto, Noelle and others is therefore scored off ATK. `sim/search.ts`
   supports the other scalings (`search.ts:224-227, 345-350`), but nothing passes them.

---

## 3. Buffs: how they are represented today

### 3.1 Inside the gcsim path: everything, implicitly

The rotation recipe captures every buff gcsim applies (talents, constellations, team buffs,
weapon passives, conditional sets, resonance) **as frozen per-hit terms**: `bonusDmg`,
`calibratedPercent`, `critRate`, `defMultiplier` and so on (`sim/recipe.ts:66-186`). Buffs
whose amount depends on the candidate's own stats (Homa, Engulfing, Redhorn, Jade Cutter,
Noelle's burst) are re-resolved by probe calibration (`recipe.ts:170-190, 517`,
`ResolvedConversion`). **None of this exists without gcsim.**

### 3.2 Outside the gcsim path: essentially nothing

- **No buff table or data.** There is no kit or buff JSON under `backend/app/data/`. The
  directories there are `gcsim`, `kqm`, `reactions`, `yuanshen`, `planner`, `teapot`,
  `wishes`, `external` and `validation`.
- **`BuffPreset` is a dead table.** `models/buff_preset.py` stores "custom (stage) buffs" as
  JSONB. Its schema was deleted in B.5, and there is no repository or API
  (`dependencies.py:113`, `repositories/__init__.py:9-13`, `api/v1/__init__.py:4`). Table
  `buff_presets` exists in the DB.
- **No custom-buff input** on any request. `HitSpec`/`ExplainRequest`
  (`schemas/build.py:232, 413`) take no extra stats. `ExplainRequest` refuses client numbers
  by design ("an explanation of a lie"). The single-hit kernel's `SearchContext.base`
  (`sim/search.ts:66-85`) is a flat record, so unscoped buffs *could* be injected there.
- **Teams** exist as data (`schemas/team.py`, four slots), but no closed-form path reads
  teammates.

### 3.3 Artifact set bonuses, measured (DB `artifact_set_affixes`, 125 tiers, 65 sets)

| tier | static (a real `add_props`) | conditional (all `FIGHT_PROP_NONE`) |
|---|---|---|
| 1-piece (Prayers) | 0 | 5 |
| 2-piece | **51** | 9 |
| 4-piece | **0** | **60** |

Static tiers are applied (`artifact_optimizer.py:503-541`). Conditional tiers are skipped and
counted. They reach the kernel as empty stat dicts (`optimize.service.ts:83-92`,
`RESEARCH_conditional_sets.md`). **Every 4-piece in the game scores zero** in the single-hit
path. `param_list` **is stored** for every affix (`nanoka_gi_mappings.py:534`), so the numbers
are available. What is missing is their meaning: condition, scope, stacks.

### 3.4 Weapon passives

1,218 refinement rows, 1,213 with text, over **245 weapons** (DB `weapon_refinements`), each
with `param_list`. **None applied** in the closed-form chain. `docs/RESEARCH_passive_tiers.md`
tiers 231 gcsim implementations:

| tier | count | what it needs |
|---|---|---|
| 1, static + stat conversion | 44 | no new primitive |
| 1c, gated on character state | 14 | an assumption toggle |
| 2, rotation-evaluable (stacks, durations) | 93 | uptime assumptions |
| 3, target state | 34 | `KernelTarget` cannot express these |
| 0, no damage primitive | 46 | nothing |

`TASKS_passive_port.md` P.3–P.5 were **superseded** by gcsim calibration, so no port exists.

### 3.5 What the Pando port contains

`backend/app/pando/calculator.py` (244 lines) plus `app/formula/{nodes,builder,tags}.py`
(488 lines). This is a port of GO's `libs/pando/engine/src/node/calc.ts` only: a recursive
evaluator over a tag DAG, with a node registry, `Read`/`ReRead` gathering and a per-context
memo. **No GO game data, no per-character sheets, no team/target logic, no solver or
pruning.** The package docstring (`pando/__init__.py:1-19`) lists those as "later phases",
and the ZZZ `translator.py` was removed. The engine is used today only for **stat
aggregation** (`formula/genshin/stats.py`). The damage chain is deliberately a list of floats,
not a DAG (`damage.py:15-24`).

What the engine *can* already express is what GO sheets need: scope-gated contributions,
since `NodeRegistry.gather` matches tag subsets (`tags.py:38-46`), and the
`Threshold`/`Match`/`Lookup`/`Min`/`Max` nodes (`nodes.py`) for conditional and capped buffs.

---

## 4. Data sources that could feed a fallback

### 4.1 Talent multipliers: nanoka (DB), the runtime source

`talent_scalings` (labels + params per level) parsed by `talent_scaling.parse_talent_row`.
Measured over level-1 rows, all 154 characters:

- **152 of 154 characters have at least one parseable DMG hit**, 2,115 hits in total, with 0
  parse errors. The two with none are the unreleased Traveler bodies 10000134 and 10000135.
- **Every ungated real character has multipliers.** Normal / skill / burst hit counts:

  | character | normal | skill | burst |
  |---|---|---|---|
  | Mitya | 9 | 5 | 2 |
  | Kachina | 9 | 2 | 1 |
  | Valeriy | 8 | 1 | 2 |
  | (two beta characters) | 9 / 8 | 8 / 20 | 5 / 14 |
  | Nefer | 8 | 9 | 4 |
  | Lohen | 10 | 11 | 1 |
  | Linnea | 6 | 3 | 0 |
  | Vesna | 10 | 10 | 2 |
  | Vodyanitsa | 8 | 2 | 1 |

  Each mannequin has 9 / 1 / 2.
- **Caveat:** `scaling_stat` and `channel` are not derived (§2.3).

### 4.2 `backend/app/data/gcsim/talent_multipliers.json`: crossval only

Generated from gcsim `zz_*.dm.go`. It covers **114 characters** at `b107b5dc` (110 at `dev`'s
`caf738dc`), against 129 and 125 keys in `keys.json`. **No runtime consumer in `app/`**. It
is read by `scripts/gcsim/{build_multiplier_snapshot,crossval_multipliers}.py`, plus an
unrelated mention in `planner/service.py`. Its `tail` field does carry the stat suffix. By
construction it cannot cover ungated characters, so it is a validator, not a source.

### 4.3 nanoka payloads: richer than what is imported

Committed detail fixtures (`tests/fixtures/nanoka_gi/detail/character_*.json`) carry:

- `passives[].param_list` and `constellations[].param_list`. These are **structured numbers
  that are dropped on import.** The DB tables `ascension_passives` (509 rows / 152 chars) and
  `constellations` (828 rows / 138 chars) store only `name` and `description`. Weapon
  refinements and set affixes do keep `param_list`.
- `attack[]`: per damage instance, `element`, `icd`, `gauge`, `attack_type`, `strike_type`,
  `damage_param`. This is a basis for channel derivation and ICD. **Not imported.**
- `energy[]`: particle drops per skill (`per_drop`, `chance`, `cd`, `element`). This is a
  basis for a closed-form ER estimate. **Not imported.**
- Talent `promote[level].desc/param` *is* imported, and is what §4.1 parses. Some buff values
  live in talent tables, e.g. burst "ATK Bonus" rows, which `_NOT_A_HIT` filters out as
  non-hits (`talent_scaling.py:69`). 50 of 430 distinct DMG labels carry such words.

### 4.4 KQM (`backend/app/data/kqm/weapons.json` + DB `SetRecommendation`)

102 characters captured (158 refused), weapon rankings with notes, plus 346 cited set rows
(CLAUDE.md). **No buff values.** It is useful as a *prior* for a fallback, e.g. which 4-piece
state to assume first and which weapon to default to, not as math.

### 4.5 gcsim keys and source

`keys.json` (`character_implemented_actions`, aliases) only says *what gcsim has*. A local
gcsim checkout at `/root/gcsim` holds the Go implementations of every buff for gated
characters. That is the citable transcription source the passive-port design assumed
(`DESIGN_passive_port.md`). GO's sheets are not checked out locally. See
`RESEARCH_go_team_math.md` for those.

### 4.6 A free oracle

For **gated** teams, gcsim is a ready crossval oracle for any closed-form fallback: run both,
compare. The recipe already publishes every per-hit term (`recipe.ts:11-16`). The fallback
can therefore be validated term by term on gated characters before it is trusted on ungated
ones.

---

## 5. Gaps a GO-style fallback needs

Sizes: **S** is under a day, **M** is days, **L** is weeks.

| # | gap | size | why |
|---|---|---|---|
| G1 | **Derive `scaling_stat` (and split mixed-stat hits) from the talent tail** | S | tails are in the data (§2.3). Needs a per-part stat in `TalentHit`. Crossval against `talent_multipliers.json` `tail` |
| G2 | **Stop hardcoding `'atk'`** in `optimize.service.ts:58` / `explain.service.ts:59` | S | depends on G1. A live defect today, fallback or not |
| G3 | **Import `param_list` for passives/constellations, and `attack[]`/`energy[]`** | S–M | migration + importer (`nanoka_gi_mappings.py:442`). The data is already in the payloads |
| G4 | **Channel/infusion derivation** | M | `attack[].element` gives the base element. Infusions are kit buffs (they fall under G6) |
| G5 | **Synthetic recipe: closed-form → `Recipe`** (single ability or weighted list) | M | the highest-leverage piece. `recipe-search`, ranking, upgrade and `/calculate`-style breakdowns accept a `Recipe`. Hits need `talent`, `scaling`, `calibratedBase/Percent/Flat`, `bonusDmg`, `critRate/Dmg`, `def/resMultiplier`, `ampMultiplier` and `mine`. Teammate hits can be omitted or estimated. Multi-opt is a hit list with counts, which is exactly what a recipe is |
| G6 | **Per-character buff data ("sheets")** for talents, A1/A4 passives and C1–C6, self and team | **L** | ~130 characters. 1,337 passive + constellation rows are text today. Needs a schema using the declared `SRC_*`, `COND` and scope axes, and transcription cited to gcsim Go (`/root/gcsim`) or GO sheets. The citation rule forbids prose-parsing (fairy's failure). gcsim does not cover the ungated ones by definition, so **the characters the fallback exists for are exactly those with no gcsim source**. Their buffs must come from GO's sheets or hand transcription from the nanoka text and `param_list` |
| G7 | **Conditional 4-piece set bonuses** (60) + 9 conditional 2-piece | M | `param_list` stored. Needs condition and stack toggles with defaults. Small and finite |
| G8 | **Weapon passives** | L (M for tiers 1/1c) | 58 portable with no new primitive. 93 need uptime assumptions, 34 need target state (`RESEARCH_passive_tiers.md`) |
| G9 | **Elemental resonance** | S | 7 or 8 static or near-static effects. Needs only the team's elements, which teams already give |
| G10 | **Team-stat-dependent buffs** (Bennett burst off his base ATK, Kazuha/Nahida/Furina-style EM/HP/fanfare scaling) | M | needs evaluating teammates' builds (the teams table has them) before the subject. Ordering and two-pass rules |
| G11 | **Transformative / additive / lunar reaction damage** | M | needs a cited reaction level-multiplier table (not in snapshot) and gcsim's `calcDirectReaction` path. Lunar has extra rules. Also how many reactions a rotation triggers, an assumption a fallback must state |
| G12 | **Conditional/assumption UI** (GO's per-buff toggles and stacks) | M–L | the user must see and own each assumption, per the repo's "named, not silently assumed" rule. Grows with G6–G8 |
| G13 | **ER without gcsim** | M | particle data (G3) + burst cost (`talent_scaling.energy_cost`). Otherwise a fallback scores ER as zero, the pre-`DESIGN_energy_in_the_optimizer` behaviour |
| G14 | **Routing: fall back when calibration 422s on `GcsimKeyError`**, and label results as estimates | S–M | today the 422 is a dead end. The surface needs a mode switch and a distinct label, because a fallback number must not read like a gcsim number |
| G15 | **Crossval harness: fallback vs gcsim on gated teams** | M | §4.6. Without it, G6–G8 are the "confident wrong number" this repo keeps refusing |

**Cheapest useful slice:** G1, G2, G3, G5, G7, G9 and G14 give an honest solo-plus-own-set
estimate for any character, a weighted ability mix, and resonance. The output should be
explicitly labelled "no talent/team buffs". **The expensive, valuable part is G6** (plus G8
and G10), and for the ungated characters it has no gcsim source to transcribe from.

---

## Files

- Chain: `backend/app/formula/genshin/{damage,stats,tags,story_buffs}.py`,
  `backend/app/services/{stat_calculator,damage_calculator,artifact_optimizer,talent_scaling,talent_hits,weapon_comparison,build_assembler}.py`
- Engine: `backend/app/pando/calculator.py`, `backend/app/formula/{nodes,builder,tags}.py`
- Endpoints: `backend/app/api/v1/builds.py` (search-context 365, explain 432, compare-weapons 550, calibrate 1077)
- Kernels: `frontend/src/app/sim/{damage,search,recipe,recipe-eval,recipe-search}.ts`
- Pages: `frontend/src/app/pages/optimize/{optimize.ts,optimize.service.ts,recipe-optimize.service.ts}`, `pages/artifacts/artifact-ranking.service.ts`, `pages/calculate/calculate.ts`
- Data: `backend/app/data/gcsim/{keys,talent_multipliers}.json`, `backend/app/data/kqm/weapons.json`, `backend/tests/fixtures/gcsim_character_coverage.json`, `backend/tests/fixtures/nanoka_gi/detail/`
