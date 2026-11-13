# RESEARCH: Genshin Optimizer's closed-form team math, as a fallback for un-simulated characters

Status: COMPLETE (2026-11-13). Research only — no code changed, nothing decided.

Researched 2026-11-13 against `frzyc/genshin-optimizer` `master` (last push 2026-11-13; latest
`libs/gi/formula` commit 2026-11-10, "GO: Add 7.2 content and fix issues (#3343)"). All paths
below are relative to that repo unless they start with `backend/` or `docs/` (this repo).
Link form: `https://github.com/frzyc/genshin-optimizer/blob/master/<path>`.

## 0. What this repo already has from GO — and what it does not

- `backend/app/pando/calculator.py` (244 lines) is a port of **only** `libs/pando/engine/src/node/calc.ts`
  — a generic recursive evaluator over a tagged node DAG (`app/formula/nodes.py`). No game data,
  no sheets, no team logic, no solver. `backend/app/pando/__init__.py` says so itself: pruning,
  solver and compilation were "later phases", and `translator.py` (ZZZ DSL → DAG) was deleted.
- `backend/app/formula/genshin/damage.py` is mistilteinn's own single-hit chain cited to gcsim
  `damage.go` — **amplifying reactions only**; it explicitly excludes transformative/additive.
- THIRD_PARTY_NOTICES.md already carries GO's MIT notice (for `pando/` and for the artifact draw
  weights from `libs/gi/upopt/src/consts.ts`).

So what has **not** been taken from GO, and is the subject of this note: the character/weapon/
artifact **sheets** (kit math), the **team-buff composition**, the **reaction** formulas beyond
amplifying, **multi-target**, and the **solver**.

## 1. How GO represents a kit for math

GO currently has **two parallel engines** for Genshin, both in the monorepo:

| | Legacy "Waverider" (live site) | New Pando-based (prototype, in progress) |
|---|---|---|
| engine | `libs/gi/wr/src/` (`formula.ts`, `api.ts`, `optimization.ts`, `reaction/`) | `libs/pando/engine/src/` (`node/calc.ts`, `node/transform.ts`, `optimization/`) |
| kit sheets | `libs/gi/sheets/src/Characters/<Key>/index.tsx` (+ `Weapons/<Type>/<Key>/`, `Artifacts/<Set>/`, `Resonance.tsx`, `Reaction.tsx`) — formula **and** UI text in one TSX file | `libs/gi/formula/src/data/char/<Key>.ts`, `data/weapon/`, `data/artifact/`, `data/common/` — formula only; UI lives in `libs/gi/formula-ui` |
| solver | `libs/gi/solver/src/GOSolver/` | `libs/game-opt/solver/src/` + `libs/gi/pando-solver/src/index.ts` |
| page | `libs/gi/page-team/` (TabOptimize, CustomMultiTarget) | `libs/gi/pando-page-optimize/` ("GO: Gi frontend pando prototype (#3305)", 2026-10-10) |
| parity | — | `libs/gi/pando-parity/src/<char>.spec.ts` — one spec per character + artifacts/weapons, asserting the Pando sheets reproduce WR numbers (`relDiff.ts`, `harness.ts`) |

The Pando engine is the same one this repo ported the calculator from, and the same engine
GO's ZZZ (`libs/zzz/formula`) and HSR (`libs/sr/formula`) optimizers use. **If anything is
reused, the Pando-side sheets are the ones that match our engine**; the WR sheets are a different
node IR (`libs/gi/wr/src/type.d.ts`).

### Coverage

- WR: `libs/gi/sheets/src/Characters/` has **125 named characters + Traveler (6-7 elements × 2
  genders)** (143 entries minus 5 support files: `CharacterSheet.tsx`, `ICharacterSheet.d.ts`,
  `charTemplates.tsx`, `dataUtil.tsx`, `index.ts`). Includes current releases (Columbina, Nefer,
  Lauma, Flins, Aino, Zibai, Varka, Illuga, Linnea, Prune, Lohen, Somnia, Jahoda, Durin, Mitya…).
  68 artifact-set folders under `Artifacts/`; weapons by type under `Weapons/{Bow,Catalyst,...}`.
- Pando: `libs/gi/formula/src/data/char/` has **132 files** — the same 125 named characters plus
  `TravelerAnemo/Cryo/Dendro/Electro/Geo/Hydro/Pyro` (genderless), `index.ts`, `util.ts`.
  i.e. **full parity of roster** between the two engines as of 7.2.

Coverage is therefore essentially the whole released roster — the point relevant to us: GO
covers characters gcsim has not implemented yet, because adding a GO sheet is a one-file job
mostly driven by generated data (below).

### Shape of a character sheet (Bennett, both engines)

`libs/gi/formula/src/data/char/Bennett.ts` (Pando) — representative:

```ts
const skillParam_gen = allStats.char.skillParam[key]   // datamined talent tables
const dm = { normal: { hitArr: [skillParam_gen.auto[a++], ...] },
             burst: { dmg: skillParam_gen.burst[b++], atkBonus: skillParam_gen.burst[b++], ... },
             constellation6: { pyro_dmg: skillParam_gen.constellation6[0] }, ... }
const { activeInArea } = allListConditionals(info.key, ['activeInArea'])   // user toggle
const inAreaActive = prod(activeInArea.map({ activeInArea: 1 }), destIsActive)
const activeInAreaAtk = prod(inAreaActive, sum(burstAtkRatio, c1AtkRatio), own.base.atk)
export default register(info.key, entriesForChar(info, data_gen),
  ownBuff.char.skill.add(cmpGE(constellation, 3, 3)),          // C3 talent level
  ownBuff.premod.enerRech_.add(underHP_enerRech_),             // C2, self
  teamBuff.final.atk.add(activeInAreaAtk),                     // burst ATK, whole team, dest-gated
  teamBuff.premod.dmg_.pyro.add(c6PyroDmg_),                   // C6
  dmg('skill_press', info, 'atk', dm.skill.press, 'skill'),    // one named hit
  dmg('burst', info, 'atk', dm.burst.dmg, 'burst'),
  customHeal('burst_regen', ...), customParam('burst_cd', dm.burst.cd), ...)
```

The WR version (`libs/gi/sheets/src/Characters/Bennett/index.tsx`, 461 lines) is the same math
with `dataObjForCharacterSheet(key, dmgFormulas, { teamBuff: { premod: {...}, total: { atk } },
premod: {...} })` plus the talent/constellation UI text and conditional widgets.

So a kit is: **(a)** a `dm` block that indexes datamined per-level arrays by *position*
(`skillParam_gen.skill[s++]` — fragile to datamine reordering, guarded by tests), **(b)** a list
of **named hits** (`dmg(name, info, scalingStat, multiplierArray, moveType, {ele, cond,
baseMulti})`) — each is a top-level formula the UI can display or the optimizer can target,
**(c)** buff entries tagged self/team/notOwn/enemy, **(d)** conditionals the user sets.
Constants missing from the datamine are hand-written with a comment ("cd_red: 0.2, // Not in the
dm for some reason").

### Where the talent scalings come from

- `.gitmodules`: `libs/gi/dm/GenshinData` = `https://gitlab.com/Dimbreath/AnimeGameData2.git`
  (Dimbreath's datamine, shallow, `main`), and `libs/gi/dm/HakushinData` =
  `https://github.com/genshin-optimizer/gi-hakushin-data` (Hakushin, used for beta/unreleased
  data before the datamine has it; parsers in `libs/gi/dm/src/hakushin/{character,weapon,artifact}.ts`).
  `yarn run update-dm` = `git submodule update --remote`.
- `libs/gi/dm/src/` parses the Excel/TextMap JSON; `libs/gi/stats/src/executors/gen-stats`
  dumps the result into `libs/gi/stats/src/allStat_gen.json` (+ `libs/gi/stats/Data/`), which
  every sheet imports as `allStats.char.skillParam[key]` / `allStats.char.data[key]`
  (base stats, curves, ascension), and similarly for weapons/artifacts.
- This is the same upstream lineage mistilteinn's BRIEF names (Dimbreath AnimeGameData as
  committed snapshots), and the same lineage as our nanoka/YuanShen snapshot — so GO's
  `skillParam` arrays should be cross-checkable against our `talent_scalings` rather than
  imported blindly.

## 2. Team buffs, conditionals, reactions, enemy

### Composition (WR, the live engine)

`libs/gi/ui/src/hooks/useTeamData.ts:getTeamData` builds, per team member, a list of `Data`
objects: artifacts (`dataObjForArtifact`), character (`dataObjForCharacterNew` — level, cons,
talents, **conditional values**, enemy overrides, bonus stats), weapon, merged sheet data
(char sheet + weapon sheet + all artifact sheets), `common`, `resonanceData`, `reactionData`.
Team conditionals (`team.conditional`) are merged into every member's conditional map.

`libs/gi/uidata/src/uiData.ts:uiDataForTeam` (opens with "May the goddess of wisdom bless any
and all souls courageous enough to attempt for the understanding of this abomination") then
does the cross-product:

```
own[i]                 = pre-buffed calc for member i
own[i].teamBuff.X      = X buff computed by member i (in i's own context)
buff[to][from].X       = teamBuff.X from `from`, evaluated under own[from] with target = own[to]
totalBuff[i]           = mergeData(...buff[i])          // sum over all sources
final calc of X for i  = merge(own[i], totalBuff[i])
```

i.e. a buff is a node evaluated **in the giver's context** (Bennett's base ATK, Bennett's burst
talent level) but may read `target.*` — the receiver's stats (`target.charKey`, `target.weaponType`
in Bennett's C6 infusion). `input.activeCharKey` vs `target.charKey` is how "on-field only" buffs
are gated. There is no per-buff target selection beyond that: entries go under `teamBuff` (all
members, including self) or self (`premod`/`total` directly); a buff for "the next character"
or "one chosen teammate" is a **conditional** whose value is the chosen character key.

Accumulation rules live on the read nodes (`libs/gi/wr/src/formula.ts` `inputBase`): most stats
`read('add')`; `infusion.*` uses `'small'` string priority; `nonStacking` keys (e.g. two
Instructor/Noblesse wearers) use `stringRead('small')` so only one copy applies; `tally.maxEleMas`
uses `'max'`. `mergeData` (`libs/gi/wr/src/api.ts`) errors in dev if two `unique` entries collide.
Stat stages: `base` → `premod` (pre-%-conversion stats) → `total` (after conversions like
"ATK from HP") — a buff author picks the stage, and the Bennett WR sheet carries the comment
"Not 100% sure if this should be in premod or total": **stage choice is a judgement per buff**.

### Composition (Pando, the new engine)

`libs/gi/formula/doc/tag_arch.md` is the spec. Every value is a tagged entry
`{src, dst, sheet, et, qt, q, | region, move, ele, trans, amp, cata}`. Write-side `et:` decides
scope: `own`, `teamBuff` (whole team), `notOwnBuff` (others only), `enemyDeBuff` (shared enemy).
Read-side `et:team` sums a stat across members. Conditionals are tagged with **both** `src:`
(giver) and `dst:` (receiver), so a per-recipient toggle is native. Non-stacking is
`Read.addOnce` (2026-11-02 "Fully fix non-stacking for all games (#3334)"). Optional tags make
"hydro DMG% + all DMG%" fall out of tag matching instead of hand-written sums.

### Sources covered

- **Talents/constellations**: in each char sheet, gated with `greaterEq(input.constellation, n, …)`
  / `cmpGE(constellation, n, …)` and `input.asc` for passives.
- **Weapon passives**: `libs/gi/sheets/src/Weapons/<Type>/<Key>/index.tsx` and
  `libs/gi/formula/src/data/weapon/` — refinement-indexed arrays from `allStats.weapon`.
- **Artifact sets**: `libs/gi/sheets/src/Artifacts/<Set>/`, `libs/gi/formula/src/data/artifact/`
  — 2pc/4pc entries, team-wide ones (Noblesse, Instructor, ToM, VV shred) under `teamBuff` /
  enemy debuff.
- **Resonance**: `libs/gi/sheets/src/Resonance.tsx` — reads `tally.<element>` (count of members
  per element) and `tally.ele` (distinct elements; Protective Canopy at ≥4); some resonances are
  user conditionals (`['resonance','ShatteringIce']`, `EnduringRock`). Requires `teamSize ≥ 4`.
- **Moonsign / Hexerei / region tallies**: `tally.moonsign`, `tally.hexerei`, `flags.isMoonsign`,
  `tally.<region>` in `inputBase` — the Nod-Krai lunar mechanics are modelled as team counts.
- **Conditionals** are plain user-set values (`cond(key, 'activeInArea')` → `'activeInArea'` or
  absent; list/number conditionals for stacks). **They are static for the whole calculation**:
  a stack count is a number the user types, not something derived from a timeline.

### Reactions

`libs/gi/wr/src/formula.ts` + `libs/gi/wr/src/reaction/{multi,trans,lunar,stellar,special}.ts`,
`libs/gi/sheets/src/Reaction.tsx`:

- **Amplifying** (vaporize/melt, forward/reverse): `hit.ampMulti` lookup on `hit.reaction` ×
  `hit.ele`, with `baseAmpBonus = 1 + (25/9)·EM/(1400+EM)` + `total.<reaction>_dmg_`.
  **Note the constant**: GO uses 25/9 = 2.7778; gcsim (and our `damage.py:51`) uses 2.78. A
  0.08% difference in the EM term — irrelevant for ranking, but it means GO numbers will not
  crossval against ours to 1e-7 on any amplified hit. The reaction is a
  **per-hit or per-character setting** (`hit.reaction`, `teamChar.reaction`), i.e. "assume 100%
  of this hit vaporizes" — not a gauge model.
- **Additive** (spread/aggravate): added to `hit.dmgInc` (`hit.addTerm`, `formula.ts` ~L408) as
  `transformativeReactionLevelMultipliers[lvl] × {1.25 spread | 1.15 aggravate} × (1 + 5·EM/(1200+EM) + <r>_dmg_)`.
- **Transformative** (swirl, overload, electro-charged, superconduct, shatter, bloom/hyper/
  burgeon, burning): `reaction/trans.ts`, level multiplier × `16·EM/(2000+EM)` term, own
  `enemy.transDef`; `crittableTransformativeReactions` get `<r>_critRate_`/`_critDMG_`.
  Displayed per character as standalone "hits" (Reaction.tsx), so they can be multi-target rows.
- **Lunar** (lunar-charged, lunar-bloom, lunar-crystallize): `reaction/lunar.ts` — base
  multiplier 3 / 1 / 1.6, `<r>_baseDmg_` and `<r>_specialDmg_` stat keys; **stellar** reactions
  (`reaction/stellar.ts`, `<r>_mult_`) also exist. Crystallize shield: `reaction/multi.ts`.
- No aura/gauge, ICD, or reaction-rate modelling anywhere: the user decides which hits react.

### Enemy

`dataObjForCharacterNew` (`libs/gi/wr/src/api.ts`): per-element enemy RES defaults to **10%**,
enemy level defaults to **the character's level**, overridable per team
(`team.enemyOverride`: `enemyLevel`, `<ele>_enemyRes_`, `enemyDefRed_`, `enemyDefIgn_`). DEF
multiplier `(lvl+100) / ((lvl+100) + (enemyLvl+100)(1-defRed)(1-defIgn))` with defRed capped at
90% (2026-11-07 fix #3338); RES uses the standard piecewise `res()`. Shred from teammates (VV,
Zhongli, Nahida C2, etc.) arrives as `enemyDefRed_`/`<ele>_enemyRes_` team/enemy buffs.

## 3. Multi-target ("Multi-Optimization Target")

### Data model (WR, live)

`libs/gi/db/src/Database/DataManagers/CustomMultiTarget.ts`:

```ts
customTargetSchema = { weight: number>0 (default 1), path: string[],   // a display node, e.g. ['CharKey','skill','press']
                       hitMode: 'avgHit'|'hit'|'critHit'|'global', reaction?: amp|additive,
                       infusionAura?: element, bonusStats: Partial<Record<InputPremodKey,number>>,
                       description }
customMultiTargetSchema = { name, description?, targets: CustomTarget[] }   // stored per team-character
```

Evaluation is in `dataObjForCharacterNew` (`libs/gi/wr/src/api.ts`, ~L195-230):

```ts
targetNode_i = prod(weight_i, data(displayNode(path_i), {
                 premod: bonusStats_i, hit: { hitMode_i, reaction_i }, infusion: { team: aura_i } }))
multiTarget  = sum(...targetNode_i)        // variant: 'invalid'
```

So a multi-target is literally **Σ wᵢ · hitᵢ(with per-row overrides)**, one scalar node; the
solver optimizes it exactly like a single hit. Points that matter for a port:

- **Rows can only point at the active character's own display nodes** (`sheetData.display` of
  the character in "custom" mode = own char + weapon + artifact sheets, incl. own transformative
  reaction rows from `Reaction.tsx`). Teammate damage is not part of the target.
- **Per-row overrides are limited to** `bonusStats`, `hitMode`, `reaction`, `infusionAura`.
  **Conditionals are global to the character**: you cannot say "rows 1-3 have Gorou C6, row 4
  doesn't" with a toggle — KQM's guide does it by turning the buff on globally and adding a
  negative `bonusStats` to the rows without it (https://keqingmains.com/misc/multi-optimization/).
- Weights are **hit counts per rotation** (decimals allowed). KQM: "Weights are based on how often
  each attack or Reaction occurs in the rotation"; its Thoma example takes the ratio 98/55 from a
  gcsim run. Partial reaction uptime = the same hit listed twice, once with `reaction:'vaporize'`
  weight 0.5 and once without, weight 0.5.

### New engine

`libs/gi/pando-solver/src/index.ts:buildDetachedSolverBase` takes `frames: Array<{tag, multiplier}>`
and builds `sum(prod(multiplierᵢ, Read(frameᵢ.tag).with('preset', 'preset' + i)))`. Each frame
reads under **its own `preset`** tag, and `withPreset` (`libs/gi/formula/src/util.ts`) can scope
data entries — including conditionals — to a preset. That is the ZZZ/HSR "combo" design, and
it removes the WR limitation that conditionals are global across rows. (The GI pando prototype
page, `libs/gi/pando-page-optimize/src/index.tsx`, still displays with `preset: 'preset0'`;
per-frame conditionals in the GI UI should be treated as in progress.)

### Limits (both engines)

- No timing: no rotation length, no cooldowns, no action frames, no swap delays. KQM: "Genshin
  Optimizer cannot take into account in-game execution of the actions described in a config" and
  "the damage value of a config doesn't say what a build's damage per second (DPS) is."
- No energy: ER only matters if (a) a kit converts it to damage (Raiden, Mona, Engulfing
  Lightning, Emblem) or (b) the user adds an ER **constraint** (min-stat filter). The number is
  computed separately by the community ER calculator; KQMS for GO calcs: "energy requirements must
  be calculated with 3 clear orbs from enemies over 90s" (https://compendium.keqingmains.com/).
- No buff uptime except via conditionals (on/off, stack count) and weight/bonus-stat tricks.
- No reaction gauge/ICD: reaction share is the author's assumption, per row.
- "two configs aren't comparable unless they're specifically designed to be" — the absolute value
  is unitless (Σ weighted hits), so it ranks builds for one config but does not compare teams.

## 4. The optimizer

### WR / GOSolver (live)

Pipeline: `libs/gi/page-team/src/CharacterDisplay/Tabs/TabOptimize/index.tsx` builds team data
with the active character's artifacts replaced by **dynamic reads** (`libs/gi/wr/src/dynamic.ts`;
artifact main/sub totals become variables `dyn.<stat>` and set counts `dyn.<set>`), so every
teammate buff, conditional and enemy stat is folded to a constant.
`libs/gi/wr/src/optimization.ts:optimize` constant-folds, normalises (sorted canonical form,
CSE — doc comment ~L190) and leaves an `OptNode` graph over ~20 artifact variables;
`precompute` compiles it to a JS `Function` over the 5 slots.

`libs/gi/solver/src/GOSolver/GOSolver.ts:preprocess` then runs `pruneAll`
(`libs/gi/solver/src/common.ts`) to a fixed point:

- `pruneExclusion` — set-count constraints (2pc/4pc filters, rainbow) baked into the graph.
- `reaffine` — collapse the graph's dependence on artifact stats to affine combinations where
  possible (fewer variables).
- `pruneOrder` — per-slot **dominance**: drop an artifact if ≥ `topN` others in the slot are ≥ on
  every relevant stat and set-switchable. Comment: assumes the target is monotone increasing in
  every stat.
- `pruneArtRange` / `pruneNodeRange` — **interval arithmetic**: bound each node's [min,max] over
  remaining artifacts (`computeNodeRange`) and drop artifacts that cannot reach a constraint
  minimum (ER ≥ x etc.).

Search: `WorkerCoordinator` (`libs/gi/solver/src/coordinator.ts`) over N **WebWorkers**
(`BackgroundWorker.ts`). Each splits the build space either by `DefaultSplitWorker` or
`BNBSplitWorker` — **branch and bound**: it computes a per-artifact contribution upper bound
by linearising the target (`linearUB.ts`, with a polynomial bound in `polyUB.ts` and a small LP
solver `solveLP.ts`/`solveLPBland.ts`), keeps the current top-N threshold, and skips any
sub-box whose bound is below it; `heuristicSplitting.ts` picks split keys/values. Leaves under
`maxIterateSize = 32_000_000` go to `ComputeWorker.ts` for brute force with the compiled function.
**No GPU** in GO (no `navigator.gpu`/WGSL hits in the repo); it is CPU workers only.

### Pando side

`libs/gi/pando-solver/src/index.ts` → `detach()` (pando engine) turns the tagged graph into a
tag-free `NumTagFree[]` whose only free reads are artifact stats, set counts and weapon
refinement/level (so **weapons are searchable too** — `weaponKeys` candidates) →
`libs/game-opt/solver/src/solver.ts` calls `prune()` from `libs/pando/engine/src/optimization/`
and fans out to workers (`worker.ts` `compile(...)`, `split.ts`). This is the code path that
lines up with our `backend/app/pando/` and with the "later phases" its docstring promised.

### Versus simulation

The formula approach evaluates one closed-form scalar per build in ~µs after folding, so it
searches the **full inventory** (10⁹-10¹² combinations, pruned) exhaustively and provably finds
the top N for that formula. A simulation is ~0.03-8 s per run here (CLAUDE.md figures), so
mistilteinn's gcsim path must search a pre-filtered candidate set and treats noise. The trade:
GO is exact for a fixed *assumed* state; gcsim is approximate for a *derived* state. They answer
different questions, and the natural combination (which mistilteinn's `artifact_optimizer.py` +
gcsim recipe arguably already approximates) is "formula to search, simulation to score finalists".

## 5. Licensing and data provenance

- GO is **MIT** (`LICENSE`: "Copyright (c) 2020-present, frzyc"). MIT code may be incorporated
  into an AGPL-3.0-or-later work provided the copyright notice and permission text are kept;
  THIRD_PARTY_NOTICES.md already carries GO's notice, so porting sheets only needs the notice's
  scope sentence extended (e.g. "and character/weapon/artifact formulas ported from
  `libs/gi/formula/src/data/`"). `docs/DECISIONS.md` §34 already records this compatibility
  argument for `pando/`. The combined work is distributed under AGPL; GO's portion stays
  MIT-licensed upstream.
- **The datamined numbers are not GO's to license.** `allStat_gen.json` (2.3 MB) is generated
  from Dimbreath AnimeGameData2 and Hakushin — HoYoverse game data, the same legal status as
  this repo's nanoka/YuanShen snapshot. Do **not** vendor `allStat_gen.json`; port the
  **formula structure** (which hit uses which array, buff stages, gates) and feed it from our own
  seeded `talent_scalings`/snapshot, which also satisfies the CLAUDE.md data-source-of-truth rule
  (DB first) and the citation rule (GO sheet path + datamine field as the citation).
- Hakushin data is beta/unreleased: GO ships sheets for characters before release. That
  collides with this repo's `release/` gate on unreleased content (#362 "the gate checks …
  nanoka's unreleased list on every blob") — a ported sheet for an unreleased character would be
  caught there, which is the desired behaviour.
- Practical fragility: sheets index datamine arrays **by position** (`skillParam_gen.skill[s++]`)
  and carry hand constants ("Not in the dm for some reason"). A port must map positions to our
  `talent_scalings` by name, and those hand constants each need a citation.
- WR sheets are TSX mixing UI text and math (461 lines for Bennett); Pando sheets are pure TS
  (~200 lines) on the engine we already run — the Pando ones are the realistic port source, and
  `libs/gi/pando-parity/src/*.spec.ts` gives a free per-character regression oracle against WR.

## 6. Accuracy limits of the static approach

From the mechanics above and KQM's guidance:

1. **Uptime is an input, not an output.** Any buff that is time-limited (Bennett field, Kazuha
   A4, Furina fanfare stacks, Shenhe quills, Xilonen, Citlali) is either 100% or a user-chosen
   fraction. Furina's fanfare and stack-based kits (Neuvillette, Arlecchino Bond of Life,
   Mavuika fighting spirit, Lunar teams) are particularly assumption-sensitive.
2. **Energy is invisible to the score.** This repo measured on the owner's own team that ER is
   worth +7.3% skipping vs **+44.4% waiting** (CLAUDE.md, DESIGN_waiting_for_energy.md). A
   formula optimizer sees none of that unless an ER floor is set by hand; burst-reliant DPS
   (Raiden teams, Xiangling, Eula, Yelan) is where GO builds most need an ER constraint.
3. **Reactions are declared, not resolved.** No aura, gauge, ICD or reaction rate: vaporize
   share, spread/aggravate proc rate, swirl element, bloom core counts, lunar-charged ticks are
   all guesses. Reaction-centric teams (hyperbloom, nilou bloom, lunar-charged/bloom, burning,
   electro-charged, taser, quicken) are the weakest case; mono-element or freeze teams with
   simple amp-free damage are the strongest.
4. **No timing.** Snapshotting vs dynamic buffs (e.g. Xiangling Pyronado, Bennett snapshot)
   requires the sheet author to encode it; swap and animation time, CDs and rotation length are
   absent, so DPS (vs damage per config) is not produced.
5. **Monotonicity assumptions in pruning** (`pruneOrder` comment): stats with non-monotone value
   (HP thresholds, Hu Tao below-50%, Nilou HP caps, "ER above X") are handled by the formula but
   weaken pruning.
6. **Team value is not comparable across configs.** A multi-target score ranks builds for one
   character's assumed rotation; it does not compare two teams or say which teammate to bring.
   That is the single biggest gap against what mistilteinn's gcsim path does.
7. **Small constant drift** vs gcsim (amp EM term 25/9 vs 2.78), and GO computes average crit
   like we do — so crossval to our `tests/crossval` tolerance would fail on amplified hits.

Where it is strong: per-hit numbers that match the in-game "damage formula" exactly, full-roster
coverage within days of a patch, and exhaustive artifact search. That fits mistilteinn's gap
precisely: **as of the v2.50.0 re-pin (`3f46f84`), `backend/tests/fixtures/gcsim_character_coverage.json`
lists the non-mannequin characters gcsim cannot run as Kachina, Nefer, Lohen, Linnea,
Vodyanitsa, Vesna and two Traveler entries** — every one of which has a GO sheet in both
`libs/gi/sheets/src/Characters/` and `libs/gi/formula/src/data/char/`.

## 7. Implications for a mistilteinn fallback (for Planner/Brain; not a decision)

- The engine is in hand (`backend/app/pando/calculator.py`); what is missing is the **tag
  vocabulary and sheet layer** (`libs/gi/formula/src/data/util/`, `data/common/`), the
  **team-data assembly** (`teamData`/`withMember`, tag_arch.md), and the **reaction** terms
  beyond amplifying. `prune()`/`detach()` from `libs/pando/engine/src/optimization/` are the
  natural next port for search.
- A fallback scoped to "the ~8 characters gcsim lacks + their teammates' buffs" still needs the
  **teammates'** sheets (their buffs flow in via `teamBuff`), so a partial port is by team, not by
  character. Teammate buff sheets are the bulk of the work.
- Multi-target should be the Pando `frames` shape (per-frame preset) rather than the WR shape,
  so per-hit conditionals are not a workaround. Weights could be seeded from a gcsim run of a
  similar team where one exists (KQM's own method).
- Its output is unitless and per-character; any UI must not present it next to gcsim DPS as if
  comparable — the same honesty rule as the repo's "resin is an average and a spread".

## Sources

- GO repo: https://github.com/frzyc/genshin-optimizer (paths above, `master`, 2026-11-13)
- GO tag architecture: https://github.com/frzyc/genshin-optimizer/blob/master/libs/gi/formula/doc/tag_arch.md
- KQM, Multi-Optimization guide: https://keqingmains.com/misc/multi-optimization/
- KQM Standards (GO and gcsim calc requirements): https://compendium.keqingmains.com/
- Rentry "How to Use the Genshin Optimizer": https://rentry.co/optimizer (search result only; not read in full)
