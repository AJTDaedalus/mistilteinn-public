# DESIGN: a formula fallback, so every team can be optimized

**Status: P0 merged; P1 complete and merged (#367–#371). P3's reactions built on `feat/formula-reactions` (2026-11-14, §2.7; owner go-ahead `DECISIONS.md` §43), and its weapon passives on `feat/formula-weapon-passives` (2026-11-14, §2.8; `DECISIONS.md` §44). Weapon comparison under the estimate, the wielder conversions, GO's non-stacking and weapon proc rows on `feat/formula-weapon-compare` (2026-11-14, §2.9; `DECISIONS.md` §45). P2 foundation built on `feat/math-fallback-p2-sheets` (2026-11-13): the sheet schema, the two-pass team evaluation, GO fixtures, and sheets for Bennett and Kazuha (§2.6). Plunges no longer make a character `partial` (owner, 2026-11-13). Owner rulings in `DECISIONS.md` §38: the estimate is opt-in for every team (D-F3), and Genshin Optimizer, not gcsim, is the accuracy comparator for the fallback (D-F4).** §2.4 below predates D-F4. Read "gcsim" there as "GO" for sheet verification; gcsim remains the oracle for the damage chain itself. The owner asked for two things:
- an evaluation of carrying each character's gcsim status in its catalogue entry;
- a plan for a Genshin Optimizer-style fallback that uses closed-form math instead of
  simulation, so every team can be optimized whatever its gcsim status.

Research: `docs/RESEARCH_math_fallback_inventory.md` (what this repo has) and
`docs/RESEARCH_go_team_math.md` (how GO does it). Gap ids **G1–G15** below are the
inventory's §5.

## Branch policy

- Each phase is its own branch off `dev`: `feat/math-fallback-p0` … `p3`. Each merges by PR
  after `scripts.ci_local` passes on the PR head. Nothing is committed to `dev` directly.
- Phase 0 is a defect fix and ships first, independent of the rest.
- `TASKS_team_math_fallback.md` Task 0 is the branch-setup gate.

## 1. Evaluation: gcsim status in the character entry

**Recommendation: yes, expose it on every catalogue entry, but compute it on read rather
than storing a column.**

**Why not a column.** gcsim status is a fact about *(character, gcsim pin)*, not about the
game:
- **It changes when the pin moves.** A re-pin rewrites `keys.json` without a re-seed; the
  v2.50.0 re-pin moved four characters from "none" to "full". A stored column would be
  stale from that moment until someone re-seeds.
- **The rule this repo already learned.** That is exactly the drift `keys.json`'s
  `pinned_commit_sha` exists to prevent: the database is the source of truth for *game data*,
  and this is not game data.

**What exists.** `gcsim_keys.character_key()` already resolves a character against the pinned
snapshot in memory, and `/roster` already returns `simulatable` plus a reason. No other
catalogue surface does. The catalogue, the team builder and the optimizers each find out
only when a search fails with a 422.

**Proposal.** A `gcsim` block on `CharacterRead`, and the same on `WeaponRead` and
`ArtifactSetRead`, since weapons and sets are also partially implemented:

```
gcsim: {
  status: "full" | "partial" | "none",
  key: "nahida" | null,
  pin: "b107b5dc…",
  missing_actions: ["aim", …],   # partial: from character_implemented_actions (896 probed pairs)
  reason: str | null             # none: gcsim's own refusal text
}
```

- `partial` means gcsim knows the character but not every base action. Ganyu has no
  `charge`, and some Travelers have no plunges. **Amended by the owner, 2026-11-13:** only a
  missing normal, charged/aimed, skill or burst makes a character `partial`. Missing plunges
  (and movement) stay in `missing_actions` and the tooltip. At the pin that moved 75 characters
  from `partial` to `full`: 114 full, 14 partial, 22 none.
- A list filter (`?gcsim=none`) and a badge in the team builder make the status visible
  *before* a search is attempted.
- The fallback (§2) routes on this block (G14).
- **Size S.** It is a pure function of data already in memory, and it adds to the API
  contract without changing anything existing.

**Measured at the v2.50.0 pin.** 22 of 150 seeded characters are `none`. Fourteen are
mannequins and two are Travelers; the real ones are Kachina, Nefer, Lohen, Linnea,
Vodyanitsa and Vesna. Mitya, Valeriy and the two characters in the current beta are also absent from gcsim.
Fifteen catalogue weapons are unresolved.

## 2. The fallback

### 2.1 Goal and non-goals

**Goal.** Any team, including one with no gcsim support, can be optimized on:
- a **single ability** (one hit, as GO's default target); or
- a **weighted multi-target**: Σ count × hit across chosen abilities, as GO's
  "Multi-Optimization Target".

The team's buffs are estimated as well as the data allows. Every assumption (a buff
uptime, a stack count, a reaction) is something the user can see and change.

**Non-goals:**
- **Not a gcsim replacement.** For a gated team, gcsim stays the score. The fallback is the
  path when gcsim refuses, and an explicit opt-in otherwise.
- **No rotation timing, energy flow or buff-uptime modelling.** Those are exactly what the
  static approach cannot see; GO's own documentation and KQM say the same
  (`RESEARCH_go_team_math.md` §6). ER is a user-set floor, as in GO, until G13 — now §2.10,
  a closed-form energy model from particle data.
- **Results are not comparable across teams.** The score has no time axis, so it is
  "damage per chosen sequence", never DPS.

### 2.2 Approach: synthesise a `Recipe`; don't build a second optimizer

**The reuse point.** `frontend/src/app/sim/recipe.ts` is already a weighted, multi-hit,
closed-form objective. It holds per-hit talent multiplier, scaling stat, flat terms, bonus,
crit, DEF/RES and amplifier, plus a `mine` flag. `recipe-search.ts`, ranking, upgrade
potential and the energy ladder all consume a `Recipe`.

**Today**, a recipe is *calibrated* from a gcsim run.

**The fallback *synthesises* one from formulas (G5):**

```
team + build(s) + target spec ──► buff assembly ──► per-hit terms ──► Recipe ──► existing search/rank/upgrade
       (rows × counts,          (sheets, sets,     (talent mult ×
        conditionals)            resonance,         scaling stat,
                                 weapons)           crit, DEF, RES, amp)
```

So "single ability" is a one-row recipe, and "multi-opt" is a recipe with counts. Each row
carries its own conditional set, as GO's new engine does with "frames". That lifts GO's live
limit, where conditionals apply to every row at once.

**Buff assembly uses the Pando evaluator we already ported.** It is GO's tagged DAG engine,
and it has the scope axes declared but unused: `SRC_TALENT`, `SRC_CONSTELLATION`,
`SRC_ASCENSION_PASSIVE`, `SRC_TEAM`, `COND`. GO's design carries over directly:
- each buff is evaluated in the **giver's** context while reading the **receiver's** stats;
- buffs are tagged self / team / others / enemy debuff (`RESEARCH_go_team_math.md` §2).

### 2.3 Kit data: the real cost, and where it comes from

**Math is cheap; kit data is not (G6).** About 130 characters' talent, passive and
constellation buffs, plus 245 weapon passives and 60 conditional four-piece sets.

**Source policy (proposed; decision D-F2):**
1. **Numbers come from our own seeded database**, extending the importer to keep
   `param_list` for passives and constellations (G3). It drops them today, keeping only the
   text. GO's `allStat_gen.json` is HoYoverse data and not GO's to license.
2. **Structure** (which param buffs what, for whom, under what condition) is transcribed into
   a **sheet format of our own**. Each sheet is cited to either:
   - **gcsim's Go source** at the pin, for every character gcsim implements; or
   - **GO's sheets** (MIT, `libs/gi/sheets` / `libs/gi/formula/src/data/char`, notice
     already in `THIRD_PARTY_NOTICES.md`).

   GO has sheets for every ungated real character. That matters most, because those are
   exactly the characters with no gcsim code to read.
3. **Never prose-parsed.** Turning description text into numbers is the fabricated-citation
   failure this repo was founded against (BRIEF, fairy's lesson).

**A team needs every member's sheet, not just the ungated one.** Teammates' buffs come from
their own sheets. Coverage therefore grows by *teams used*: the ungated characters first,
then the buffers most often teamed with them. The usual buffers are Bennett, Kazuha,
Furina, Nahida, Xilonen, Citlali, Escoffier, Mavuika and Sucrose. A character without a
sheet still contributes base stats, set bonuses and resonance, and is labelled "no kit
buffs modelled".

### 2.4 Trust: every sheet is checked against gcsim before it counts (G15)

**gcsim is a free oracle for gated teams.** Run both paths on the same team and build, and
compare per hit. The recipe already publishes every per-hit term.

**A sheet is "verified" only when** its character's hits match gcsim's calibrated terms
within a stated tolerance, on fixtures committed like `tests/crossval`.

**Ungated characters** cannot be crossvalidated, so their sheets ship marked
**unverified**:
- they are cited to GO;
- GO's own `pando-parity` specs are a second, weaker check;
- the UI says so.

Known divergence to settle up front: GO's vaporize/melt EM bonus uses 25/9, while gcsim and
our `damage.py` use 2.78 (`RESEARCH_go_team_math.md`). We follow gcsim, as for every other
constant.

### 2.5 Honesty in the UI

- **Labelled as an estimate.** A fallback result says *"Formula estimate: no simulation"*,
  in a style distinct from gcsim results. It lists every assumption: conditionals, uptimes,
  the reaction share and unmodelled kits. This is the repo's standing rule that a number
  must be able to explain itself.
- **Reasons, not dead ends.** When gcsim refuses, the 422 becomes a choice: "gcsim can't
  run Lohen. Use the formula estimate?" It no longer ends the flow (G14).

### 2.6 Kit sheets and the two-pass team evaluation (P2, tasks 9–11; built 2026-11-13)

**Where it lives.** `backend/app/formula/genshin/sheets.py` (schema, pins, giver-context
resolution), `backend/app/data/formula/sheets/<slug>.json` (one per character),
`backend/app/services/kit_buffs.py` (the two passes), `GET /api/v1/formula/kit-buffs`
(the caller's own builds), and in the browser `formula-recipe.ts` (`flat_atk`,
`dmg_bonus_from_em`), `formula-calibration.ts` (kits ride with resonance) and the shared
`formula-panel`.

#### The sheet format

One JSON file per character, validated by `sheets.Sheet` on load. **No number is written in a
sheet.** It carries structure, cited, and references into our seeded rows:

| field | what it says |
|---|---|
| `nanoka_id`, `slug`, `character` | whose kit; `slug` names the file and the source id `kit:<slug>` |
| `go_commit`, `go.{pando,wr}` | GO's sheet files at the pinned commit (the same commit `set_effects.json` uses) |
| `gcsim_commit`, `gcsim` | gcsim's package at the pin, where it implements the same buffs |
| `verified_by` | GO fixtures in `go_fixtures.json` that check this sheet. Empty = **unverified**; the API and the panel say which |
| `talent_boosts` | which constellation raises which talent by 3 (GO `ownBuff.char.<t>.add(cmpGE(constellation, n, 3))`, gcsim `SkillCon`/`BurstCon`) |
| `pins` | the talent-row labels, constellation `param_list`s and passive `param_list`s the sheet was curated against |
| `conditions` | P1's condition vocabulary, the default **derived** in one place (`SheetCondition.resolve`, `DECISIONS.md` §41): a curated `usual` (value, reason, citation) wins; else `self` is on at its maximum and `giver_is_subject` is `self` for the optimized character and a teammate's buff, on at its maximum, for anyone else; a `situational` condition must carry a `usual` (0 with its reason where it stays off). Was §39's "teammate and situational off" until §40 (ii) |
| `effects` | each: `source` (`talent`, `a1`, `a4`, `c1`–`c6`; gated on ascension phase / constellation as GO's `input.asc` / `cmpGE`), `receivers` (`self` / `active` / `team` / `others` / `enemy`), `stat` (P1's `EffectStat`, plus `flat_atk` and `dmg_bonus_from_em`), scope (`elements`, `moves`, `reactions`), `when`, a `value` reference, and its `go` (and `gcsim`) file:lines |
| `unmodelled` | each part of the kit not applied, with its reason (cooldowns and healing: "no damage effect"; infusions, extra hits, deferred parts named) |

A `value` names exactly one of:

- `{"talent": T, "row": "ATK Bonus Ratio"}` — the parameter the row's format string names
  (`"ATK Bonus Ratio|{param4:P}"` → `params[3]`), at the giver's **effective** level (stored +
  constellation boosts);
- `{"constellation": n, "param": i}` or `{"passive": 1|4, "param": i}`;
- `{"constant": x, "cite": "…"}` for something no seeded list carries;

optionally `"times_stat"`: multiplied by one of the giver's stats (`base_atk`/`base_hp`/
`base_def`, `atk`/`hp`/`def`, `elemental_mastery`, `energy_recharge`).

**Added for the ungated sheets (task 11), each small and in the format's spirit:**

| addition | where | why |
|---|---|---|
| `"negate": true` on a value | `ValueRef` | a seeded list publishes a reduction as a positive number (Vodyanitsa's "Hydro/Cryo RES Reduction" 0.3); GO negates it into `enemyRes_` |
| `"times_param"` on a value | `ValueRef` | one seeded parameter times another: Vesna's C4 multiplies her A4 by its 2.0 (GO `prod(a4, 1 + c4)`, written as A4 plus a C4 effect of A4 × C4) |
| `per` on an effect | `SheetEffect` | P1's stack multiplier, carried through: Nefer's burst DMG per Veil, Mitya's EM per Beacon, Valeriy's A4 per Momentum |
| `receiver_elements` | `SheetEffect` | a buff that reaches receivers of some elements (GO `target.char.ele`, Linnea's C2), decided in `resolve` from the subject's element |
| `per_team_elements` | `SheetEffect` | times the count of team members of some elements (GO `team.common.count.<ele>`, Vesna's A4), decided in `resolve` from the members' elements |
| `flat_damage_from_def`, and `flat_damage` from ATK → `flat_damage_from_atk` | `SELF_CONVERSIONS`, `formula-recipe.ts` | a giver who is the subject adding flat damage from their own DEF (Kachina's A4) or ATK (Valeriy's Offensive Directive and A4): the recipe's resolved flat-term conversion, which `recipe-eval.ts` already evaluated from DEF |

`resolve` takes `receiver_element` and `team_elements` (`kit_buffs.team_kit` passes both); an
effect that needs one and is not given it is withheld by name, and one whose receiver is not of
its elements, or whose team count is 0, is absent, like a locked constellation.

**Not added, and named in the sheets instead:** a threshold and cap on a value (Vodyanitsa's A4,
flat damage from her HP above 40,000, capped); a talent boost gated on a condition (Lohen's High
Spirits, skill +1); an unlock-free passive's list (Lohen's Hexerei rite); a stack condition whose
maximum moves with a constellation (Nefer's C2, Valeriy's C4: the C0 maximum is kept); a
base-damage multiplier (GO `baseMulti`: Nefer's Phantasm Performance, Lohen's Will, Vesna's Spirit
Blade, Vodyanitsa's Song); and a buff scoped to one talent row rather than a move.

**Added for the buffers (task 11, second batch), each small and in the format's spirit:**

| addition | where | why |
|---|---|---|
| `max_raise` on a condition | `SheetCondition` | a constellation parameter raising a stack maximum once unlocked: Furina's C1 adds its 100 to the Fanfare limit (GO `sum(maxFanfare, cmpGE(constellation, 1, fanfareLimitInc))`). The `self` default follows the raised maximum; a stale pin keeps the maximum and says so |
| `index_by_team` on a value | `ValueRef`, `TeamIndex` | a value read from a seeded **table** by a team count (GO `subscript(count, table)`): Escoffier's A4 by Hydro/Cryo members, Yelan's A1 by distinct elements. Count 0 is no buff; a count past the table's `size` is withheld rather than read into the next field |
| `team_gate` on an effect | `SheetEffect`, `TeamGate` | a buff that holds only for some compositions: Chevreuse's A1 (only Pyro and Electro, one of each), Escoffier's C1 (four Hydro/Cryo members) |
| `cap` and `stat_unit` on a value | `ValueRef` | GO `min(prod(percent(x), stat, 1 / 1000), max)`: Chevreuse's A4, ATK 1% per 1,000 of her HP up to 40%. The unit is a cited constant (no seeded list carries the 1,000); the cap is a pinned parameter. On a giver who is the subject, a capped value from an artifact-moved stat is withheld by name |
| `min_ascension` on an effect | `SheetEffect` | a constellation buff that also needs an ascension (GO `cmpGE(ascension, 4, …)` inside C1): Escoffier's C1 reads her A4's count, Citlali's C2 copies her A1 shred |
| `flat_damage_from_hp`, `flat_damage_from_em` | `SELF_CONVERSIONS`, `formula-recipe.ts` | a giver who is the subject adding flat damage from their own HP (Zhongli's A4) or EM: the recipe already resolved a flat term from any of ATK, HP, DEF and EM (`recipe.ts:ConversionSource`); `formula-recipe.ts` now emits all four, one per hit |

**Constants no seeded list carries.** Xingqiu's A4 (Hydro DMG 20%) and C2 (Hydro RES -15%), and
Zhongli's Jade Shield RES -20%, are all-zero or absent in the seeded lists. They are `constant`
values, each citing GO's sheet line and gcsim's, which agree.
Shenhe's C2 (Cryo CRIT DMG 15%) is the same case in the fourth batch: GO reads it from her A1's
list, her C2 list carries only its duration, and gcsim writes 0.15 (`cons.go:35`).

**Still not added at the second batch, and added in the fourth:** a value from the team's
**highest** stat (Nahida's A1), a talent row chosen by a team count (Nahida's burst), enemy DEF
reduction (Nahida's C2) — see the table below. Still not added: a capped conversion of the
subject's own stat (Furina's A4, Nahida's A4 — the owner's open question in `DECISIONS.md` §39,
priced since §40: see "Capped self-conversions" below) and the Hexerei party mechanic (Sucrose's Witch's Eve Rite, Mona's lock parts).

**Added for the fourth batch (task 11: Nahida, Kujou Sara, Shenhe, Yun Jin, Gorou, Xilonen,
Xianyun, Mona, Raiden Shogun; Nefer's and Valeriy's raised maxima), each small and tested:**

| addition | where | why |
|---|---|---|
| `times_team_max` on a value | `ValueRef`, `kit_buffs._team_max` | a value times the party's **highest** pass-1 stat (GO `team.premod.eleMas.max`, Nahida's A1, capped by the existing `cap`). The max is over every member **but the subject** — their stat moves with every candidate — and a giver who is the subject is withheld by name. Pass 1 only, so rule 5 holds. `giver_stats` reports it as `team_max_<stat>` |
| `rows_by_team` on a talent value | `ValueRef`, `TeamRows`, `CountBonus` | a talent **row** chosen by a team count (GO `cmpEq(level, 1, row_1, row_2)`): Nahida's one- or two-Pyro burst row, her C1 counting one more (a cited constant: her C1 list is all zeros). Count 0 is no buff; past the last row reads the last, as GO does. The rows share their text before `|`, so the labels are pinned in full |
| `rows` on an effect | `SheetEffect`, `Effect.rows`, `FormulaRow.hit` | a **self** buff scoped to the giver's own talent rows (`/hits`' talent and label): Nahida's burst bonus reaches Tri-Karma Purification and not her press; Raiden's Resolve reaches her Musou rows, the initial slash apart; Xianyun's C6 her Driftcloud Wave. Only `self` effects may name rows: a teammate cannot know another character's labels. A row that does not name its talent row skips the buff and says so |
| `def_reduction`, `def_ignore` effect stats | `formula_effects.EffectStat`, `formula-recipe.ts` | enemy DEF reduction (Nahida's C2, `enemy` receivers) and DEF ignore (Raiden's C2, `self` only). Both feed the DEF term the chain **already** carries — `damage.py:def_multiplier` and `damage.ts:defMultiplier`, reduction capped at 90% as GO's `enemy.def` and gcsim cap it, the two multiplied separately — so the term, the kernels and the crossval are unchanged; the recipe adds the kit's value to the target's own |
| `flat_def` effect stat | `formula_effects`, `formula-recipe.ts` | flat DEF after the percentage (Gorou's banner), as `flat_atk` is for ATK |
| `by_stack` on an effect | `SheetEffect` | a stack table read from a pinned list, entry `param + n - 1` at `n` stacks up to the condition's (fixed) maximum (GO `subscript(stacks - 1, [p0, p1, …])`): Nahida's C4 by opponents, Xianyun's A1 and C6 |
| `counts` on a team gate | `TeamGate`, `TeamCount` | at least / at most N members of some elements (GO `cmpGE(count.geo, 3, …)`, `cmpLT(converted, 3, …)`): Gorou's banner at three Geo, Xilonen's Geo sample while fewer than three samplers are converted and her A1 at most one. `only` now defaults to every element |
| `clamp` on a team table | `TeamIndex` | a count past the table reads its last entry, as GO writes it again (Gorou's C6 `[c6[0], c6[1], c6[2], c6[2]]`) |
| `stat_cap` on a value | `ValueRef` | the giver's stat capped **before** it multiplies (GO `prod(ratio, min(total.atk, 4500))`, Xianyun's A4), a pinned parameter |
| `part` on a talent value | `ValueRef` | which `{paramN}` of a row with several: Raiden's "Resolve Bonus\|{param2} Initial/{param3} … Per Stack" |
| a talent row as a factor | `ParamRef.talent`/`row` | one talent row times another at the giver's effective level: Raiden's Eye on herself is the skill's per-Energy ratio times her burst's own "Energy Cost" row (GO `dm.burst.enerCost`) |
| `max_constellation` on an effect | `SheetEffect` | an effect held only up to a constellation, where a higher one **replaces** it (GO `cmpGE(constellation, 2, c2, a1)`): Nefer's A1 EM at 3 Veils gives way to her C2's at 5 |
| `max_raise_cited` on a condition | `SheetCondition` | a maximum raised by a cited constant no seeded list carries: Valeriy's C4, Impact Momentum +30 (GO `momentumLimitInc: 30`) |

**OR of conditions, without a new mechanic.** Xilonen's Geo sample is GO's `cmpGE(sum(sourceActive,
nsBlessing, C2), 1, …)` — an OR. It is written as three effects whose `when`s are disjoint
(Source Samples on; Samples off and Nightsoul's Blessing on; both off, from C2), so under any
state at most one applies; a test enumerates the states.

**Not added, named in the sheets:** a second Energy Recharge conversion on one hit. Raiden's A4
(Electro DMG from ER above 100%) and Mona's A4 (Hydro DMG, 20% of ER) are conversions of the
subject's own ER; the recipe carries one per hit (`recipe.ts:bonusFromEnergyRecharge`), and
Emblem of Severed Fate's — which Raiden most often wears — is it. Raiden's would also need its
100% offset. A plunge-**impact** scope (Xianyun's A4 reaches low/high plunges, not the
collision): the sheet scopes by move and its toggle's label tells the user to turn it off on a
collision row, which per-row conditionals allow.

`max_raise` and `max_raise_cited` now carry Nefer's C2 and Valeriy's C4 (the "fixed max" named
above is gone). Vodyanitsa's A4 still needs a **threshold** (HP above 40,000) and is a self
conversion, so `cap` alone does not unlock it.

**Added for the DPS characters (task 11, third batch), each small and in the format's spirit:**

| addition | where | why |
|---|---|---|
| `nth` on a talent value | `ValueRef` | the n-th parameter a row's format string names: Skirk's `0/1/2/3 Void Rift Absorption DMG Bonus|{param4}/{param5}/{param6}/{param7}` is one row with four values, one per absorbed count (GO `talentSubscript(burst, void_dmg_[k])`). A row naming fewer is withheld through its pinned label |
| `stat_unit` on a `per` value | `ValueRef`, `SheetEffect` | the unit counts the condition when there is no stat: Neuvillette's A4 is 0.6% Hydro DMG per percentage point of HP above 30%, and the seeded list carries 0.6 (GO `passive2[2][0] / 100`; gcsim `(hpRatio - 0.3) * 0.6`). A unit with neither a stat nor a `per` is refused |
| `flat_atk_from_def` | `EffectStat`, `SELF_CONVERSIONS`, `formula-recipe.ts`, `recipe.ts` | Noelle's Sweeping Time on herself: ATK + a share of her own DEF (GO `ownBuff.premod.atk.add(prod(own.premod.def, …))`). The recipe carries it as a resolved flat-ATK conversion from DEF, with the flat ATK's constant part beside it (`ResolvedConversion.offset`, absent = 0 for every probe-resolved conversion), so a teammate's flat ATK (Bennett's burst) on the same hit is kept and every ATK-scaling term reads it |
| `base_atk` | `EffectStat`, `formula-recipe.ts` | base ATK before the percentage (GO `ownBuff.base.atk`, Mavuika's C2 +200), so every ATK% multiplies it |
| `base_dmg_bonus` | `EffectStat`, `formula-recipe.ts` | GO `baseMulti` on the talent term, the `baseDamageBonus` the single-hit kernel already had: Neuvillette's A1 (×1.1/1.25/1.6 by stack) and Skirk's A4, each read by a `when` on the stack count. A mixed-stat hit with one is refused rather than guessed |

**Constants no seeded list carries.** Mavuika's A4 is 0.2% DMG per point of Fighting Spirit. The
seeded A4 list publishes 0.0001; GO multiplies it by 20 (`pando Mavuika.ts:80`, with a `TODO` that
says so) and gcsim writes `burstStacks*0.002` (`asc.go:50`). The sheet uses a `constant` 0.002 citing
both.

**Scoped by move where GO scopes by row, said in each sheet** *(resolved since by row scope and
per-row moves, §40 (iv): see "Defaults at usual values, per-row moves, row scope" below)*. The estimate scopes a buff by move,
not by talent row. Three sheets carry buffs that GO limits to a subset of one move: Neuvillette's A1
and C2 (Equitable Judgment only, not the ordinary Charged Attack), Skirk's Void Rift bonus, A4 and C2
(the Seven-Phase Flash attacks only, not her ordinary ones). They are applied to the whole move and
the over-reach is named in `unmodelled`. A row for the attack GO excludes would read high; the
characters' players do not use those rows in the modes the buffs belong to. Mavuika's Flamestrider
Normal and Charged Attack bonuses are **not** applied, because her ordinary physical attacks are rows
people do use.

**Found: Skirk's Seven-Phase Flash and Mavuika's Flamestrider attacks are skill-talent rows.** *(Resolved by the sheets' `row_moves`, §40 (iv).)*
`suggestMove` gives every elemental-skill row the move `skill`. GO counts them as normal, charged and
plunging attacks. A teammate's Normal Attack buff, and Skirk's own, reach those rows only once the
user sets the row's move. Both sheets say so. Deriving the move from the label would be the guess
`suggestMove` refuses to make; the per-hit `attack[]` import (task 4) is the real source.

**Still not added, and named in the sheets:** enemy DEF reduction (Ayaka's C4, Mavuika's C2 ring
form), a buff scoped to one talent row (above), a time-decaying buff (Mavuika's A4 is applied at its
peak, a toggle), the A4 multiplier on the flat part of Skirk's burst (GO multiplies both parts; the
base multiplier here reaches the talent term only), and a team talent-level passive (Skirk's skill +1
in a Hydro and Cryo party). No capped self-conversion was needed: Neuvillette's A4 is a user-set HP
condition in GO, not a conversion of his Max HP.

**Found driving it, and fixed: picking another ability kept the old row's move.** `formula-panel`'s
`pickHit` replaced the hit and left `move` as it was, so a row first made for a 1-Hit DMG (normal)
and switched to Skirk's Final Slash stayed a normal attack, and her burst-scoped Serpent's Subtlety
silently missed it: the drive's first run read the same top build with the condition at 22 and at 0.
A new ability now takes `suggestMove`'s move, as a new row does.

**Added for the fifth batch (task 11: Hu Tao, Arlecchino, Clorinde, Navia, Wriothesley, Lyney,
Yoimiya, Ganyu, Eula, Arataki Itto, Cyno), each small and tested (`test_formula_sheets_dps2.py`):**

| addition | where | why |
|---|---|---|
| source `a0`, `passive: 0` | `Source`, `PASSIVE_PHASES`, `kit_buffs.giver_of` | the passive a character holds from ascension 0 (`ascension_passives.unlock_ascension` 0): Arlecchino's Balemoon Pyro DMG (GO `passive3`, ungated). `kit_buffs` now reads phase-0 lists; a passive with no phase (the locked Hexerei ones) is still dropped |
| `offset` on a value | `ValueRef` | a talent row that is a hit's **whole** multiplier ("Enhanced Repelling Fist DMG\|{param1} Normal Attack DMG", GO `prod(auto row, skill row, atk)` / `baseMulti: skillMult`) written as `base_dmg_bonus`, which adds to the default multiplier of 1 — so the value is the row plus a cited −1. Wriothesley's Chilling Penalty, Yoimiya's Niwabi. Only on a plain parameter (no stat, cap or team max) |
| a unit on a self conversion | `sheets._effect_node` | a unit is a constant divisor, so the per-candidate coefficient carries it: Arlecchino's Masque is the Normal Attack row × her ATK per Bond of Life percentage point / 100 (GO `Number(per) / 100`). A cap or a stat cap on a self conversion is still withheld |

No frontend change: every effect these sheets write was already carried by the recipe.
Arataki Itto's Kesagiri carries ATK from his own DEF (`flat_atk_from_def`) and flat damage from his
own DEF (`flat_damage_from_def`) on the **same** hit; Cyno's flat damage from EM reads the EM his own
burst adds. Both are checked by fixture, both agree with GO exactly.

**Counts written as gated effects, no new mechanic.** Navia's A4 (ATK × min(Pyro/Electro/Cryo/Hydro
members, 2), GO `cmpGE(n, 2, 2x, cmpGE(n, 1, x))`) and Lyney's A4 extra (×min(Pyro − 1, 2)) are two
effects each with `team_gate` counts `at_least` 1 and 2 (Lyney 2 and 3). Navia's shrapnel is two
number conditions (the first three for C2's CRIT Rate; beyond three for the skill DMG and C6), since
`per` multiplies by the condition and GO reads `min(n, 3)` and `n − 3` of one count.

**Bond of Life is a number condition, `self` at its maximum.** Arlecchino's (0–200, the Bond cap,
GO's list 10..200) and Clorinde's C4 (0–100 points, where C4's 2% per point reaches its own 200%
cap). §39 puts a self-built condition at its maximum, so Arlecchino's Masque defaults to 200%
Bond; her own A1 gives 130% from one Blood-Debt Directive and real rotations sit near there. The
label says so and the owner may want the default lower — see the LOG's owner decisions.

**Constants no seeded list carries.** Navia's 15% Skill DMG per Crystal Shrapnel beyond three is
the seeded skill row's `param2`, which no row label names (GO `skill[1][0]`, gcsim `0.15 * excess`;
the test checks the constant against the seeded parameter). Ganyu's C4 5% per stack is GO's literal
`percent(0.05)` and gcsim's `* 0.05`; her C4 list is all zeros.

**Named, not applied (the batch's open edges):**

- **Capped self-conversions** (`DECISIONS.md` §39's open question): Hu Tao's Guide to Afterlife
  ATK from Max HP (capped at a multiple of base ATK — her main buff, and its cap is a parameter no
  seeded label names), Clorinde's A1 (a share of ATK per stack up to a flat cap, raised by C2).
  Alhaitham's and Tighnari's A4 (DMG% from EM, capped) are the same shape, which is why those two
  were **skipped** in this batch rather than shipped without their main effect. *Priced since
  2026-11-14 (`DECISIONS.md` §40), and both skipped sheets written: see the next table.*
- **Infusions** (G4): Hu Tao, Arlecchino (at 30% Bond), Navia (A1), Yoimiya, Wriothesley's fist
  is Cryo already, Itto, Clorinde's Night Vigil, Cyno's Pactsworn attacks.
- **Skill- or burst-talent rows that are Normal Attacks** (as Skirk's): Clorinde's Swift Hunt,
  Cyno's Pactsworn attacks. Cyno's A4 names his burst rows, so it reaches them either way.
- **Move scope over GO's row scope**: Wriothesley's Gracious Rebuke (every Charged Attack row
  while the toggle is on), Ganyu's A1 (aimed shots too), Navia's C2/C6 (Surging Blade too).
- **Navia's shots-hit base multiplier**: GO's table is hard-coded and marked `TODO: Verify this`;
  the estimate reads the shardshot's base row (GO's default of 0 shots gives the same 1×).
- **The Hexerei mechanic** (Wriothesley's, Cyno's Stellar parts), damage instances (Arlecchino's
  C2, Clorinde's C1/C6, Lyney's C6, Eula's A1, Yoimiya's C6, Cyno's Duststalker Bolts).

**Capped self-conversions, priced per build (owner ruling 2026-11-14, `DECISIONS.md` §40; branch
`feat/formula-capped-conversions`; `test_formula_sheets_capped.py`, `capped-conversions.spec.ts`).**
A kit value read from the optimized character's own artifact-moved stat through a cap or a
threshold resolves to a per-candidate conversion carrying both, and the recipe prices
`min(k × max(stat − threshold, 0), cap)` for every candidate (`recipe.ts:cappedAmount`). gcsim
recipes are untouched: a probe still cannot see a cap, and still reports such a term.

| addition | where | why |
|---|---|---|
| `threshold` on a value | `ValueRef`, `Effect`, `FormulaEffect`, `ResolvedConversion`, `StatConversion` | the stat counts only above a pinned parameter (GO `max(sum(final.eleMas, -200), 0)`, Nahida's A4). Applied before `stat_cap`, which then bounds the counted stat (her 800) |
| `cap_times_stat` on a value | `ValueRef` | the cap times a giver stat (GO `prod(percent(maxAtkInc), own.base.atk)`, Hu Tao's 400% of base ATK). On the subject it must be a static stat, or the cap would move and is withheld |
| `unnamed` on a talent parameter | `ParamRef` | a row's published parameter no label names, by index, pinned through the row's label: Hu Tao's `params[6]` (GO `skill[6][0]`). Withheld if a seeded label comes to name that index |
| a cap on a self-conversion | `sheets._effect_node`, `Effect.cap` | was withheld; now the cap travels in the term's units — the `cap` parameter (× `cap_times_stat`), or `stat_cap` × the coefficient, the smaller if both. A `per` multiplies the slope and leaves the cap (Clorinde's A1 caps the stacked total, GO `min(max, prod(ratio, atk, stacks))`) |
| `flat_atk_from_hp`, `dmg_bonus_from_hp`, `crit_rate_from_em` | `EffectStat`, `SELF_CONVERSIONS` | Hu Tao's skill ATK, Furina's A4, Nahida's A4 CRIT Rate. `flat_atk_from_hp` rides the same resolved flat-ATK conversion as Noelle's from DEF (one per hit); the DMG%/CRIT Rate ones are `RecipeHit.statConversions`, each capped alone — `min(a, x) + min(b, y)` is not `min(a + b, x + y)` — read from the hit owner's own `rawTotal` |
| a cap on a resolved flat conversion | `ResolvedConversion.cap`/`.threshold` | a row's count folds into the slope and the cap (`n × min(k s, c) = min(n k s, n c)`); a second conversion beside a capped one on the same term is refused |

**The bound.** `cappedAmount` is non-decreasing in its stat for a non-negative slope (a `max` with
0 and a `min` with a constant both keep monotonicity), so the optimistic completion still
dominates every real one and `searchRecipe` stays exact; `liveQuantitiesFor` keeps each
conversion's source live. `capped-conversions.spec.ts` shows bounded == exhaustive over 243
combinations with the cap deciding the winner (a mix of EM or HP pieces and others, where the
uncapped recipe would go all-in), for Nahida's shape and Hu Tao's.

**Planted errors** (`formula:verify`): every fixture with a capped conversion states `cap_state`;
ignoring the cap must fail a `past` figure and change nothing on a `below` one; freezing the stat
at the zero-artifact build must fail wherever the conversion reaches the row; the 1% plant scales
the cap too. Mutating `cappedAmount` to ignore caps fails all six past-cap fixtures; reading the
conversions' stat at zero artifacts fails all eight Nahida, Furina, Alhaitham and Tighnari
fixtures, both sides of the cap.

| sheet | conversion | GO |
|---|---|---|
| Hu Tao | Paramita ATK = min(6.256% × premod HP, 4 × base ATK); Paramita a `self` toggle | `pando HuTao.ts:48-56,103-112,144` |
| Clorinde | A1 flat damage = min(20% × ATK × stacks, 1,800) on her burst (by move) and Night Vigil rows (by row); C2 replaces it with 30% / 2,700 (`max_constellation` / `min_ascension`); stacks situational | `pando Clorinde.ts:62-67,81-84,129-146,164-174,184` |
| Nahida | A4 DMG% 0.1% and CRIT Rate 0.03% per EM above 200, 800 counted, on Tri-Karma | `pando Nahida.ts:83-87,184-197,246-255` |
| Furina | A4 Salon DMG% 0.7% per 1,000 HP (a cited unit), capped at 28%, on the three Salon rows | `pando Furina.ts:73-77,143-150,180-191` |
| Xianyun | A4 on her own plunges (its stat cap, withheld until now) | `pando Xianyun.ts:79-80,122-134` |
| Alhaitham (new) | A4 0.1% DMG per EM up to 100% on his projections (rows) and burst; C2 EM per Debate stack; C4 EM to the others per mirror consumed, and Dendro DMG per mirror generated (3 − consumed; 3 at C6) as `when`-gated effects; C6 CRIT | `pando Alhaitham.ts` |
| Tighnari (new) | A4 0.06% DMG per EM up to 60% on Charged Attacks and burst; A1 EM; C1 Charged CRIT Rate; C2 Dendro DMG; C4 party EM, twice on a reaction (two effects, GO `eleMas * 2`) | `pando Tighnari.ts` |

**Still withheld:** Nahida's A1 on herself (a conversion *into* EM from the party's highest, her
own included), Chevreuse's A4 on herself (ATK% from HP, a pair the recipe does not carry),
Raiden's and Mona's A4 (a second ER conversion per hit). Vodyanitsa's A4 is priced since §41. Alhaitham's C4 Dendro DMG follows GO's pando port, which loses WR's "0 consumed at C6"
state; said in his sheet.

**Defaults at usual values, per-row moves, row scope and Vodyanitsa's A4 (owner rulings
2026-11-14, `DECISIONS.md` §40 (ii), (iv), (vi), built as §41; `test_formula_sheets_defaults.py`,
`test_formula_sheets_rowscope.py`, `go_fixtures_rowscope.py`).**

| addition | where | why |
|---|---|---|
| `usual` on a condition (`value`, `reason`, `cite`; `value` may be `"max"`, or `"receiver_element"` for a choice of elements) | `SheetCondition`, `Usual`, `Condition.default_note`, `FormulaConditionRead` | the curated usual value of §40 (ii), its reason shown in the panel (`formula-recipe.ts:defaultWhy`). Required on a `situational` condition, so nothing is off without a reason |
| `receiver_elements` on a usual | `Usual` | a usual that holds only for some receivers: Kazuha's and Sucrose's swirl toggles are on for the optimized character's element |
| `default_reason` `usual` / `teammate` | `formula_effects.DefaultReason` | the two new reasons; `usual` may hold any value in range and must carry its note, `teammate` is on at its maximum |
| `row_moves` (`talent`, `labels`, `move`, `go`) | `Sheet`, `RowMove`, `sheets.row_move`, `AvailableHitRead.move`, `formula-recipe.ts:hitMove` | a row's move where GO declares one that is not its talent's (Skirk's Seven-Phase Flash, Mavuika's Flamestrider, Clorinde's Night Vigil, Cyno's Pactsworn, Lohen's skill attacks, Neuvillette's Equitable Judgment, Ganyu's aimed shots); `/hits` reports it and the label guess covers the rest. The per-hit `attack[]` import was checked first and cannot give it: `attack_type` is strike geometry (`Melee`/`Range`/`Default`) and no entry links to a row |
| `receiver` on an unmodelled note | `SheetUnmodelled` | a note about the kit reaching a teammate is not repeated beside the withheld effect when the giver is the subject (Nahida's A1) |

Row scope reuses `rows` (self effects naming the giver's own talent rows); the change is in the
sheets that scoped by move what GO scopes by row. Skirk's Void Rift bonus stays by move: GO adds it
to every Normal Attack (`premod.dmg_.normal`). Wriothesley's Gracious Rebuke stays by move with
its toggle, because GO makes it a row the catalogue does not have.

| sheet | scoped or added | GO |
|---|---|---|
| Neuvillette | A1 base multiplier and C2 CRIT DMG: Equitable Judgment only | `pando Neuvillette.ts:122-130,143-154` |
| Skirk | A4 normal multiplier: Seven-Phase Flash 1-5-Hit; C2 ATK: the Seven-Phase Flash attacks (removed from her ordinary attacks and burst in GO) | `pando Skirk.ts:146-151,192-195,223-274,298-306` |
| Mavuika | Flamestrider Normal/Charged Attack DMG per Fighting Spirit and C2's share of ATK: flat damage on those rows (were withheld) | `pando Mavuika.ts:137-146,185-198,217-222,258-294` |
| Ganyu | A1 CRIT Rate: Frostflake Arrow and Bloom only | `pando Ganyu.ts:116-135` |
| Navia | C2 CRIT Rate, C6 CRIT DMG: Rosula Shardshot only | `pando Navia.ts:183-192` |
| Lohen | C6 CRIT DMG: the Etched hit only | `pando Lohen.ts:223-231` |
| Linnea | C2: Lumi's Million Ton Crush CRIT DMG (was withheld) | `pando Linnea.ts:209-211,280-290` |
| Valeriy | C6: Thunderburst Shell DMG +100% (was withheld) | `wr Valeriy/index.tsx:233,271-273` |
| Xiangling | C6 on her own 3-Hit Swing, the burst row `antiC6` leaves it on | `pando Xiangling.ts:97-98,128-150` |
| Vodyanitsa | A4 Lead Vocal: flat Hydro/Cryo damage from Max HP above 40,000, 140 per 1,000, capped at 3,500; a number for a teammate, a per-build conversion on herself | `pando Vodyanitsa.ts:134-145,161-163,178-182,281-283` |

Nine GO fixtures, each naming its row (`hit`), so `formula:verify` also checks that the figure
misses with the row unnamed; Vodyanitsa's have one build below the cap and one past it, and a
teammate's figure. All agree with GO exactly (relative ≤ 3e-8, the f32 floor).

**Sixth batch (task 11, 2026-11-14; `feat/math-fallback-p2-sheets-batch6`;
`test_formula_sheets_batch6.py`, `go_fixtures_batch6.py`).** The fifth batch's leftovers, then the
supports and buffers next by use: Chasca, Kinich, Wanderer, Keqing, Sangonomiya Kokomi, Yae Miko,
Kamisato Ayato, Baizhu, Dehya, Layla, Kirara, Lynette, Thoma, Beidou, Ororon, Iansan, Lan Yan.
Two additions, each small and tested (and mutation-checked: dropping either fails a test and a
fixture):

| addition | where | why |
|---|---|---|
| `distinct` with `elements`, and `count_bonus`, on a team table | `TeamIndex`, `sheets._team_shift` | how many of some elements are present (GO `sum(cmpGE(count.pyro, 1, 1), …)`), a constellation counting one more (GO `cmpGE(constellation, 2, 1)` inside the count; a cited constant, as `TeamRows.count_bonus`), `clamp` capping it: Chasca's A1 by the absorbable elements present, her C2 adding one, `min(…, 3)` |
| `times_constant` on a value | `ValueRef`, `sheets._number` | a value times a number no seeded list carries, cited: Kokomi's A4 is 15% of her Healing Bonus, whose innate 25% is GO's and gcsim's literal (her Flawless Strategy list is zeros) |

No frontend change: every effect these sheets write was already carried by the recipe (Kokomi's
CRIT Rate −100% is a `crit_rate` effect, clamped at 0 by `damage.ts` as GO's `avgHit` clamps it).

| sheet | main effects | row scope / row moves | named, not applied |
|---|---|---|---|
| Chasca | A1 Shining Shell DMG by absorbable elements (+1 at C2), C6 CRIT DMG | both by row; Multitarget Fire Tap → normal, Shadowhunt Shells → charged | A4/C2/C4 extra shells; the shell's element is the row's channel |
| Kinich | A4 cannon flat damage from ATK per stack, C1 cannon CRIT DMG, C2 Dendro RES and first-cannon DMG, C4 burst DMG | cannon effects by row | C6 second cannon |
| Wanderer | Windfavored Normal/Charged multipliers (skill rows as base multipliers less 1), A1 ATK/CRIT Rate from Pyro/Cryo, C2 burst DMG per point | — | A1 needs the element in the party (a team gate GO leaves to the user); A4, C1, C6 hits |
| Keqing | A4 CRIT Rate and ER, C4 ATK after a reaction, C6 Electro DMG per stack | — | A1 infusion, C1 hit |
| Sangonomiya Kokomi | innate CRIT Rate −100% (cited constant), burst flat damage from HP on Normal/Charged/Bake-Kurage, A4 on her innate Healing Bonus, C6 Hydro DMG | — | A4's share of artifact Healing Bonus (no such stat), C1 hit |
| Yae Miko | A4 skill DMG from EM, C4 party Electro DMG, C6 DEF ignore | C6 on Sakura Levels 2-4 | the Hexerei parts (C1 Stellarconduct, C2 EM, C4 burst, C6 CRIT DMG), A1 |
| Kamisato Ayato | Namisen flat damage from HP per stack (max 5 from C2, `max_raise`), burst Normal Attack DMG to the active character, C1, C2 HP at ≥3 stacks | Namisen and C1 on the Shunsuiken rows; Shunsuiken → normal | C6 strikes |
| Baizhu | A1 Dendro DMG, C4 party EM, C6 Spiritvein flat damage from HP | — | A4's reaction DMG (P3) |
| Dehya | C1 HP and skill/burst flat damage from HP, C2 Field DMG, C6 burst CRIT | C2 on Field DMG | — |
| Layla | A4 Shooting Star flat damage from HP, C4 party Normal/Charged flat damage from her HP, C6 | A4/C6 by row | shields |
| Kirara | A4 skill/burst DMG per 1,000 HP (cited unit), C6 party DMG | — | C1, C4 hits |
| Lynette | A1 party ATK by distinct elements, A4 burst DMG, C6 Anemo DMG | — | C6 infusion, C2 shot |
| Thoma | A4 Fiery Collapse flat damage from HP, C6 party Normal/Charged/Plunging DMG | A4 by row | shields |
| Beidou | A4 Normal/Charged DMG, C6 Electro RES | — | the Hexerei parts of C6, C4 hit |
| Ororon | C2 Electro DMG and its per-opponent table (`by_stack`), C6 ATK per stack to the active character | — | Hypersense hits |
| Iansan | burst flat ATK to the active character from her ATK, capped by a burst row at her boosted level; A1, C2, C6 | — | below 42 Nightsoul points (a cap after a per-point multiply); the burst on herself (no flat-ATK-from-ATK conversion) |
| Lan Yan | A4 skill/burst flat damage from EM, C4 party EM | — | C6 ring |

Eighteen fixtures, one per sheet on its main damage effect and Yae's C4 on a teammate; all agree
with GO exactly (relative ≤ 3.6e-8, the f32 floor). **Tartaglia was not written**: his one damage
effect is a team Normal Attack talent level (+1, GO `teamBuff.char.auto`), which this section names
as not modelled (talent boosts from a passive), so a sheet would ship verified on nothing but its
row moves.

**Seventh batch (task 11, 2026-11-14; `feat/math-fallback-p2-sheets-batch7`;
`test_formula_sheets_batch7.py`, `go_fixtures_batch7.py`).** The commonly played characters next on
the list: Xiao, Venti, Nilou, Albedo, Chiori, Sigewinne, Sethos, Shikanoin Heizou, Freminet,
Rosaria, Candace, Mika, Diluc, Klee, Lisa, Ningguang, Chongyun. One addition, small and tested
(mutation-checked: dropping it fails 63 tests):

| addition | where | why |
|---|---|---|
| `crit_rate` as a giver stat | `sheets.GIVER_STATS` | Rosaria's A4 shares 15% of her own CRIT Rate with the others, capped at 15% (GO `min(prod(percent(crBonus), own.premod.critRate_), percent(maxBonus))`). Her pass-1 CRIT Rate, as every giver stat is (rule 5): GO's includes her own A1 when it is up, so GO's share is higher until the cap, said in her sheet |

No frontend change: every effect these sheets write was already carried by the recipe.

| sheet | main effects | row scope / row moves | named, not applied |
|---|---|---|---|
| Xiao | burst Normal/Charged/Plunging DMG (talent row), A1 DMG per stack in the burst, A4 skill DMG per stack | — | the Anemo infusion (G4); C4 DEF (he scales with ATK) |
| Venti | C2 Anemo/Physical RES −12% (−24% launched: a choice), C4 Anemo DMG, C6 Anemo RES −20% and the absorbed element's (a choice that follows the receiver, as Sucrose's C6) | — | every Hexerei part (Windsunder, the doubled C2, C4 to others, C6 CRIT DMG); C1 arrows |
| Nilou | A1 party EM, C2 Hydro and Dendro RES −35%, all behind a team gate (only Hydro and Dendro, both present); C4 burst DMG | — | Bountiful Cores and A4 (P3); C1 (one part of a two-hit row); C6 CRIT from HP (a capped conversion into CRIT the recipe does not carry) |
| Albedo | A1 Transient Blossom DMG (opponent below half HP, off), A4 party EM, C2 burst flat damage from DEF per stack, C4 plunge DMG and C6 DMG to the active character in his field | A1 on Transient Blossom | every Hexerei part |
| Chiori | A4 Geo DMG (after a teammate's construct: off, with the reason), C6 Normal Attack flat damage from DEF | — | A1 infusion and dolls |
| Sigewinne | A1 Hydro DMG, A1 party skill flat damage from her Max HP above 30,000 capped (a number for teammates, a per-build conversion on herself), C1's raise as a second effect (A1 and C1 reach their caps at the same HP, so the two sum to GO's one), the skill's per-tier DMG (cited 5%), C2 Hydro RES | — | C1's raise on her own skill (two capped conversions on one hit are refused); C6 CRIT from HP |
| Sethos | burst Dusk Bolt flat damage from EM, A4 Shadowpiercing flat damage from EM, C1 CRIT Rate, C2 Electro DMG per stack, C4 party EM (two opponents: off) | Dusk Bolt on his 1–3-Hit rows; A4/C1 on Shadowpiercing; Shadowpiercing → charged | Dusk Bolts are Charged Attacks in GO (the rows keep their move) |
| Shikanoin Heizou | Declension and Conviction (talent rows, flat damage from ATK on Skill DMG), A4 EM to the others, C6 skill CRIT per stack and at four | Declension/Conviction on Skill DMG | — |
| Freminet | Frost DMG doubled after his burst (a cited base multiplier), A4 and C1 on the five Shattering Pressure rows, C4 ATK capped at two of three stacks (two gated effects: per stack below the top, × C4's own 2 at three), C6 CRIT DMG per stack | Frost; the pressure rows | — |
| Rosaria | A1 CRIT Rate, A4 CRIT Rate share (above), C1 Normal Attack DMG, C6 Physical RES | — | her A1 in GO's reading of A4 |
| Candace | burst elemental Normal Attack DMG (talent row) and A4 per 1,000 Max HP (a cited unit; a per-build conversion on herself), C2 HP | — | the Hydro infusion; C6 waves |
| Mika | A1 Physical DMG per Detector stack to the active character (maximum 4, 5 from C6 by `max_raise`), C6 Physical CRIT DMG | — | the stack below A4 (the maximum counts A4) |
| Diluc | A4 Pyro DMG, C1 DMG above half HP (off), C2 ATK per stack (off: he must take DMG), C4 second/third skill strike, C6 Normal Attack DMG | C4 on skill 2-/3-Hit | the infusion |
| Klee | A1 Charged DMG with Explosive Spark (cited 0.5), C2 DEF −23%, C6 party Pyro DMG (cited) | — | every Hexerei part; GO's A1 is its own Charged row |
| Lisa | A4 DEF −15% | — | — |
| Ningguang | A4 party Geo DMG | — | C4's RES (no damage effect) |
| Chongyun | A4 Cryo RES −10%, C6 burst DMG (opponent below his HP share: off) | — | the infusion |

Seventeen fixtures, one per sheet on its main damage effect; all agree with GO exactly
(relative ≤ 4.3e-8, the f32 floor). **Where GO's own files or GO and gcsim disagree**: Nilou's pando
port gives C3 to her skill; her WR sheet, gcsim and the generated table give C3 to her burst, which
the sheet follows. Klee's C2 is GO's 23%, gcsim's 23.3% (`cons.go:51`); GO is the comparator. Lisa's
A4 is gated at ascension 4 here, as the passive is; GO's sheet gates it at 1 (`pando Lisa.ts:81-84`,
noted there). Mika's C6 CRIT DMG has its own GO toggle, folded here into Soulwind as the
constellation's text gives it.

**Eighth batch** (task 11, 2026-11-14; `feat/math-fallback-p2-sheets-batch8`;
`test_formula_sheets_batch8.py`, `go_fixtures_batch8.py`).** The twelve the seventh batch said
needed nothing new, then the newer kits as far as they go without reactions. **No format
extension**: every effect is a shape an earlier batch built (rows, row moves, `per`, `max_raise`,
`negate`, `when`-gated stack tables, self conversions from ATK, DEF and HP).

| sheet | main effects | row scope / row moves | named, not applied |
|---|---|---|---|
| Amber | A1 burst CRIT Rate, A4 ATK after a weak-spot hit, C2 manual detonation skill DMG (a toggle: GO prices it on its own row), C6 party ATK | — | C1 second arrow |
| Xinyan | A4 party Physical DMG while shielded, C2 burst Physical CRIT Rate, C4 Physical RES (published negative), C6 Charged Attack ATK from her own DEF (per candidate; gcsim leaves it unimplemented) | C2 on the burst's Skill DMG | C1 ATK SPD |
| Yanfei | burst Charged Attack DMG (talent row), A1 Pyro DMG per Seal (maximum 3, 4 from C6 by `max_raise`; GO's 4 at any constellation), C2 Charged CRIT Rate (below half HP: off) | — | A4 extra hit |
| Barbara | C2 Hydro DMG to the active character (a cited 15%) | — | healing; gcsim gives C2 to the others only |
| Razor | C1 DMG, C2 CRIT Rate (below 30% HP: off), C4 DEF −15% (all cited constants) | — | every Hexerei part; C6 strike |
| Kaeya | C1 Normal/Charged CRIT Rate against Cryo (cited 15%) | — | — |
| Qiqi | C2 Normal/Charged DMG against Cryo (cited 15%; her C2 list carries the Hexerei ATK) | — | every Hexerei part |
| Sayu | C2 kick DMG: flat on the pressed kick, per half-second held on the held and elemental kicks | the three kick rows | C6 Daruma DMG (ATK × EM, a product of two stats) |
| Diona | C2 skill DMG, C6 EM to the active character above half HP (a toggle: below half HP GO's choice gives healing only) | — | every Hexerei part |
| Collei | C4 EM to the others after her burst | — | Sprouts, C6 |
| Yaoyao | C1 Dendro DMG to the active character | — | C4 EM from HP (reactions only) |
| Gaming | A4 Cloudstrider DMG at 50% HP+, C2 ATK after overflowing healing (both situational, off), C6 Cloudstrider CRIT | A4/C6 on Charmed Cloudstrider; that row → plunge | — |
| Fischl | C2 Summoning DMG + 200% ATK (per candidate) | Summoning DMG | every Hexerei part; Oz's strikes |
| Mualani | Wave Momentum per stack and the Surging Bite's share of HP, C1 on the first bite, all flat damage from her Max HP; A4 burst flat damage by Nightsoul Burst count (three gated effects, situational); C4 burst DMG | the bite effects on Sharky's Bite Base DMG; that row → normal | — |
| Flins | C2 Electro RES −25% under Ascendant Gleam (published positive, negated; Moonsign situational), C4 ATK | his Manifest Flame skill rows → normal / charged | every Lunar-Charged part (P3); A4/C4 EM from ATK |

Fifteen fixtures, one per sheet on its main damage effect; all agree with GO exactly (relative
≤ 5.2e-8, the f32 floor). **Constants no seeded list carries**, each cited to GO and gcsim:
Barbara's C2, Razor's C1/C2/C4, Kaeya's C1, Qiqi's C2. **Mualani's bite** carries three flat
damages from her Max HP on one row (per stack, at three stacks, and C1); the recipe sums
uncapped conversions, and the fixture agrees. Her C1 is its own toggle: GO adds it on the
Surging Bite row, gcsim on the first bite at any stack count.

**Not written, with the reason.** Kaveh (bloom DMG and EM), Dori (healing and Energy), Yumemizuki
Mizuki (swirl), Zibai, Sandrone, Ineffa and Ifa (Lunar/Stellar/swirl reaction DMG and EM): none has
a non-reaction damage effect a sheet could be verified on, so a sheet would ship unverified on
nothing (the Tartaglia rule). They wait for P3. Varesa, Illuga and Lauma do have one and were not
reached.

**A kit's talent-level raise and CRIT from Max HP (owner approval 2026-11-14, `DECISIONS.md` §42;
`feat/formula-team-talent-crit-hp`; `test_formula_sheets_talent_crit.py`, `go_fixtures_talent_crit.py`,
`talent-crit.spec.ts`).** The two edges every batch since the sixth named as an owner question.

| addition | where | why |
|---|---|---|
| `talent_level` effect stat, with `talent` | `formula_effects.Effect`, `sheets.SheetEffect`, `FormulaEffectRead` | a raise of the receiver's level in one talent, a cited whole number (GO and gcsim write a literal 1). Reaches every row of its talent, so it names no element, move, row or count; a `when` is allowed (Lohen's High Spirits) |
| `raised_talents` | `team_talent_levels.raised_talents`, `kit_buffs.subject_raised_talents`, `FormulaTeamKitRead` | the subject's rows at each raise up to the sum of every raise they receive (conditional ones too), from `talent_hits.available_hits` — the parse `/search-context` reads a row with. A raise past the table's last row is published as unavailable, with why |
| `raiseRow` | `formula-recipe.ts` (its own function, before `rowHits`) | per row: sum the raises whose `when` holds for that row and whose talent is the row's, swap the multiplier (and a mixed row's other terms) for the published one, say "read at level N (base + giver +1)". An unknown talent row, no published row or a scaling stat that differs leaves the row unraised and says so; nothing is guessed |
| `Giver.talent_raises`, `sheets.talent_raises`, `kit_buffs.member_raises` | `sheets.effective_level` | a teammate's **unconditional** raise reaches a giver's own values read off a talent row (Shenhe's Icy Quill at skill + 1 in Skirk's party, as GO reads `own.char.skill`). Conditional raises are the browser's, per row; `Sheet._check_conditional_raises` refuses a sheet whose values read a talent its own conditional raise lifts |
| `crit_rate_from_hp`, `crit_dmg_from_hp` | `SELF_CONVERSIONS`, `CAPPABLE_CONVERSIONS`, `formula-recipe.ts`, `recipe.ts:ConvertedTerm`, `recipe-eval.ts` | CRIT from the subject's own Max HP per candidate, each capped alone (`StatConversion`, `cappedAmount`). `critDmg` is a `ConvertedTerm` and not a `PercentTerm`, which names terms a gcsim probe reports |

**Ordering and caps.** Read level = stored (at most 10, §40 (v)) + constellation boosts (3 each,
9b) + kit raises: a sum, as GO's `premod.<t> = base + <t>Boost` and gcsim's `TalentLvlAttack`
both compute it. 10 + 3 + 1 = 14; Lohen C3 in High Spirits in Skirk's party reaches 15, the
table's last row. No cap is applied beyond the table (GO has none; gcsim's +5 is never reached).

**Surfaces.** The formula estimate only. `/hits`, `/explain`, `/search-context` (single-hit
Optimize) keep stored + constellation: a build there has no party and so no giver. gcsim applies
the raises itself (`ChildePassive`, `SkirkPassive`) and is untouched: its config carries stored
levels.

| sheet | added | GO |
|---|---|---|
| Tartaglia (new) | Master of Weaponry: the party's Normal Attack +1, himself included (his **phase-0** passive, not an A1); row moves for his aimed shots, Riptide Flash/Burst (normal) and melee-stance skill rows (normal, charged). Nothing else in his kit is a damage effect | `pando Tartaglia.ts:77-79,107-124,129-137` |
| Skirk | Mutual Weapons Mentorship: the party's Elemental Skill +1, team-gated (only Hydro and Cryo, one of each) | `pando Skirk.ts:206-219,290-291` |
| Lohen | High Spirits: **his own** Elemental Skill +1 (GO `ownBuff`; not a raise to teammates), a self toggle | `pando Lohen.ts:132,197-199` |
| Nilou | C6: CRIT Rate 0.6% and CRIT DMG 1.2% per 1,000 Max HP, to 30% / 60%, every hit | `pando Nilou.ts:91-96,167-182,191-192` |
| Sigewinne | C6: burst CRIT Rate 0.4% and CRIT DMG 2.2% per 1,000 Max HP, to 20% / 110%; a self toggle "after she heals" (GO applies it at C6 without reading its own toggle) | `pando Sigewinne.ts:89-95,182-197,209-210` |

Eight GO fixtures, all exact (relative ≤ 3.7e-8): Tartaglia on Xiangling's 1-Hit (Physical) and
on his own Riptide Flash, Skirk on Furina's Gentilhomme Usher, Lohen C3 in High Spirits on his
Masterstroke 1-Hit (level 14), Nilou's and Sigewinne's C6 each below and past both caps (which
bind at 50,000 HP for each). A raise fixture carries `raised_talents`, its row's own multiplier is
the unraised one, and `formula:verify` fails it if it passes with the raised rows dropped. The
older `lohen_c6_on_his_own_etch` now states High Spirits off, GO's default it was worked at.
`formula:verify` 139/139.

**Pinned, as `set_effects.json` is.** A constellation or passive list that differs from its pin,
or a talent row whose label changed or which has no row at the effective level, **withholds
that effect** and lists it as unmodelled with the reason. It is never read by a stale index.

#### Pando: used for the giver context, and why conditions stay out of it

Each effect value is a node (`const(param)`, times the stat graph's own node for `times_stat`)
registered in the **giver's pass-1 registry** under `tags.formula_tag(sheet, effect)` — the
`SHEET` and `NAME` axes, which gained their constructor here — and read back there by a
`Calculator`. The formula is evaluated with both axes cleared (`tag_(node, {sheet: None, name:
None})`), so its own stat reads gather the giver's stats and not, through the subset rule,
itself; that recursion was the first thing the tests found. "Bennett's base ATK" is thus
resolved by the same graph as every other stat in the repo. `SRC_TALENT`,
`SRC_ASCENSION_PASSIVE` and `SRC_CONSTELLATION` label the source of each effect
(`sheets.SOURCE_LABEL`) — attribution, not tag categories, for the reason `tags.py` gives.

**`COND` is deliberately not used.** A condition can differ per row of the target (GO's
"frames"), and the backend does not know the rows. So the DAG resolves a value as if its
conditions held, and the effect travels to the browser with its `when`, where P1's
`applySources` gates it per row, exactly as it gates a set bonus. One application path for
resonance, sets and kits. This is reversible: if a kit ever needs a condition *inside* a value
(a stack count multiplying a giver stat), the condition joins the DAG then.

#### The two-pass rules

1. **Pass 1, every member's own stats, from their build alone**: character, weapon, equipped
   artifacts and the static bonuses of the sets they wear, through
   `artifact_optimizer.build_combination_log` (the one definition of a build's stats). **No kit
   buff from anyone — their own or a teammate's — enters pass 1.** Nor do resonance, weapon
   passives or the giver's conditional set tiers.
2. **Pass 2, every giver's sheet, in that giver's pass-1 context**, resolved for the optimized
   character as the receiver.
3. **Receivers.** The receiver is always the optimized character, who deals every hit of the
   target: `team` and `enemy` always reach them, `active` reaches them (they are on the field
   when they hit; the effect's own `when` says "in the field"), `self` only when they are the
   giver, `others` only when they are not.
4. **A giver who is the optimized character** resolves against their equipped build for
   constants only. A value reading `base_*` is a constant (artifacts do not move it). A value
   reading a stat artifacts move becomes a per-candidate term the recipe evaluates —
   `dmg_bonus` from EM → `dmg_bonus_from_em`, `bonus += coefficient × (calibrated EM +
   candidate EM)` in `recipe-eval.ts`, and `flat_damage` from ATK or DEF →
   `flat_damage_from_atk`/`_def` (task 11) — or it is withheld by name. The equipped artifacts
   never reach the estimate as a number.
5. **No cycles, by construction.** A giver stat never includes another kit's buff, so no buff
   can feed itself or another. **The cost:** where a teammate's kit raises a stat another
   giver's buff reads (a Sucrose EM share read by Kazuha's A4; Kazuha's own C2 EM read by his
   A4), GO, which evaluates the whole team graph, gives more. Each sheet names its case in
   `unmodelled`; Kazuha's C2 is deferred for exactly this reason. When the first such pair of
   sheets exists, the fix is a third pass for the stats a buff reads, ordered by the
   dependency (still acyclic as long as no stat-to-stat loop exists; one that does is refused).
6. **Talent levels.** Builds store GOOD's levels, which exclude constellation boosts (the
   importer copies GOOD's `talent` block); sheets add each `talent_boosts` entry, as GO and
   gcsim both do.

#### Where GO and gcsim differ, and what was followed

- **Bennett's burst needs the active character above 70 % HP below C1** in gcsim
  (`burst.go:120-126`); GO's sheets have no HP condition. Followed **GO**, the comparator
  (D-F4), and the field toggle's own label says so ("above 70% HP below C1, assumed as GO
  does"). It was first listed as "Not applied", which the drive showed reads as the opposite
  of the truth: it *is* applied, on an assumption. Reversible: a situational toggle if the
  owner wants the stricter reading.
- **Kazuha's A4 EM.** GO reads `premod.eleMas` (which would include teammates' EM buffs);
  gcsim `NonExtraStat(EM)` at swirl time; we read pass-1 EM (rule 5). Identical for every team
  that has no EM-sharing kit sheet.

#### Where GO's own files disagree: the talent boosts (task 11)

At `2c13fc40` GO carries two sheets per character, the WR sheet the app runs on and a pando
port. For Mitya and Valeriy the pando file is an unfilled template (its C3/C5 lines are marked
`TODO: Double check these`), and for Vesna and Vodyanitsa it swaps C3 and C5. The game data
settles it: `BinOutput/Talent/AvatarTalents/ConfigTalent_<name>.json` at the YuanShenResources
pin (`f11cf545`, read through `scripts.yuanshen.fetch` into the gitignored cache, never at run
time) gives each constellation's talent index and +3 (1 normal attack, 2 skill, 9 burst; checked
on Bennett first). It agrees with the WR sheet in all eight characters, so the sheets follow WR:
Mitya C3 skill / C5 normal attack, Valeriy C3 normal attack / C5 skill, everyone else C3 skill /
C5 burst. Each `talent_boosts` entry cites both. Effects are cited to pando where pando is
filled in and to WR for Mitya and Valeriy.

#### Recorded constants

None new. The four kit fixtures have no amplifying reaction, so they agree with GO exactly
(`relative_divergence_from_go` 0); the 25/9 vs 2.78 divergence is unchanged in the P1 fixtures.

#### Found while building it: the subject's own hits ignore constellation talent boosts

Rule 6 is applied to **givers** only. The optimized character's own hits are resolved by
`talent_hits._row_for` at the build's stored level, and builds store GOOD's levels, which
exclude the +3 a C3/C5 grants. gcsim adds the boost itself (`SkillCon`/`BurstCon`, so the gcsim
path is right), and GO adds it, so **single-hit Optimize, `/explain` and the formula estimate
score a C3+/C5+ character's boosted talent three levels low** — on the drive team, a C6
Xiangling's Pyronado at level 9 where GO and gcsim use 12. Not fixed here: it changes a live
surface's numbers beyond the scope of P2, and the boost table it needs (which constellation
boosts which talent) is per character data that sheets now carry for two characters only. It
is the next task proposed in `TASKS_team_math_fallback.md` (9b).

**Fixed in 9b (2026-11-13).** `app/services/talent_boosts.py` holds the rule and the table. The
table is never hand-written: gcsim's `NewChar` assignments (`keys.json:character_talent_boosts`)
first, GO's sheets (`data/formula/talent_boosts_go.json`) for characters gcsim lacks, both
generated at their pins. Who reads which level:

| surface | level | why |
|---|---|---|
| `/hits`, `/hits/refused`, `/explain`, `/search-context` (so single-hit Optimize and the formula estimate) | effective | GO and gcsim both read the boosted row (`api/v1/builds._hit_levels`) |
| kit sheets (givers) | effective | `sheets.effective_level`; its `talent_boosts` are test-held equal to the table |
| gcsim config | stored | gcsim adds `SkillCon`/`BurstCon`/`NormalCon` itself and refuses a level above 10 |
| planner | stored | a constellation costs no books or crowns |
| storage, GOOD import | stored | GOOD's own number; nothing exports GOOD, so there is no round trip to compound |

Not modelled: talent-level boosts a passive gives the **team** (Tartaglia's +1 normal attack,
gcsim `ChildePassive`; Skirk's and Lohen's skill boosts, GO `teamBuff.premod.skillBoost`).
They are not constellations and not this table's question. *Built since as a kit effect for the
formula estimate (`DECISIONS.md` §42; "A kit's talent-level raise" above); Lohen's turned out to
be his own skill only.*

### 2.7 Reactions (P3, task 13; built 2026-11-14)

**Owner, 2026-11-14: "Start P3: reactions."** Branch `feat/formula-reactions`; rulings and choices
in `DECISIONS.md` §43. Weapon passives (task 12) are §2.8; ER from particles (task 14) is §2.10.

**Where it lives.** `backend/app/formula/genshin/reactions.py` (the chain),
`app/data/yuanshen/snapshot/reaction_level_multipliers.json` (the level table), `damage.ts`
(the browser mirror), `formula-recipe.ts:reactionRowHits` and `additiveOf` (kept apart from
`rowHits` for the merge with the concurrent sheets branch), `recipe-eval.ts:evaluateReaction`,
the panel's *Add reaction* and per-ability *Reaction* select.

#### The formulas, each cited

| family | damage | gcsim (`b107b5dc`) | GO (`2c13fc40`) |
|---|---|---|---|
| transformative | `k × lvl × (1 + 16·EM/(2000+EM) + bonus) × RES × (1 + CR_r × CD_r)`; no DMG%, DEF ignored | `combat/reaction.go:33-39`, each reaction's `FlatDmg = k * …`, `IgnoreDefPercent: 1`; `enemy/damage.go:22-43` skips DMG% | `reaction/trans.ts:36-108`, `multi.ts:26-31` |
| additive | flat `k × lvl × (1 + 5·EM/(1200+EM) + bonus)` inside the hit's base, under its DMG%, DEF, RES, crit | `combat/reaction.go:41-43`, `reactable/catalyze.go:24,43` | `formula.ts:263,405-431` |
| Lunar | `k × lvl × (1 + 6·EM/(2000+EM) + bonus) × (1 + base_bonus) × RES × (1 + CR × CD)` with the character's CRIT | `combat/reaction.go:20-31`, `reactable/lunarcharged.go:140-150` | `reaction/special.ts:26-122`, `lunar.ts:27-40` |

Multipliers: overloaded 2.75, electro-charged 2, superconduct 1.5, swirl 0.6 (the swirled
element's RES), shattered 3 (Physical), burning 0.25, bloom 2, hyperbloom and burgeon 3 (Dendro),
spread 1.25, aggravate 1.15, Lunar-Charged 3 (Electro), Lunar-Crystallize 1.6 (Geo); both oracles
agree on each (`reactions.py` cites both per reaction). Reaction CRIT only where GO's `canCrit`
allows (burning, bloom, hyperbloom, burgeon, swirl) and only from reaction-specific stats.

**The level table is the game's.** `ElementCoeffExcelConfigData.playerElementLevelCo` at the
YuanShenResources pin, committed by `scripts.yuanshen.build_snapshot`. gcsim's `reactionLvlBase`
(generated) and GO's `transformativeReactionLevelMultipliers` (commented as this column) agree with
it to 4.6e-8, float32 against 7-digit decimals; `test_reaction_damage.py` holds anchors of both.
The server sends the value at the build's level (`/search-context`'s `reaction_level_multiplier`),
so the browser has no copy.

**Refused by name** (`reactions.REFUSED`): Lunar-Bloom (no reaction-triggered instance in either
oracle: gcsim's `LunarBloom()` only signals the party, GO's multiplier is 0 — its damage is kits'
direct hits), Stellar-Conduct (a kit's direct hit on Polestar stacks), Stellar Swirl (outside the
owner's P3 list).

#### Crossval and parity

- **gcsim**: three committed runs at the pin, `tests/crossval/test_reaction_crossval.py`:
  overloaded by Pyro Aether (75 EM through the story buffs), a Pyro swirl by Venti (+100 EM
  stated), superconduct by Ayaka (0 EM). Each trigger's EM is checked against gcsim's snapshot
  from the seeded rows, then the damage within 1e-7 (measured 1.1e-8, the float32 level base).
  Additive and Lunar have no gcsim run: none of the committed nanoka payloads is a Dendro, Electro
  or Lunar trigger; GO fixtures cover them.
- **Python ↔ TypeScript**: 900 generated cases (`reaction_cases.json`, 300 per family, additive
  through the whole talent chain), `kernel:verify`, worst 2.6e-7 at the f32 tolerance 1e-6, with a
  planted additive-outside-the-DMG-bonus that must fail.
- **GO**: nine fixtures (`go_fixtures_reactions.py`), one per family and part, `formula:verify`
  140/140 (worst 8.5e-8). The only divergence is GO's `enemy.transDef`
  (`99999999 / (99999999 + 5·lvl + 500)`, about 1 − 1e-5) against gcsim's ignored DEF, recorded per
  fixture; additive fixtures agree exactly.

#### In the estimate

| thing | rule |
|---|---|
| reaction row | `count` instances triggered by **the optimized character**: their EM (calibrated + candidate) and level apply. A teammate's reactions are constants to every candidate and are not rows, as a teammate's hits are not |
| what reaches it | EM, a `reaction_bonus` naming the reaction, an `enemy_res` on its element, `reaction_crit_rate`/`_dmg` (transformative, crittable only), the character's CRIT and `lunar_base_dmg_bonus` (Lunar). ATK%, DMG% and move/row-scoped effects are computed and ignored, silently (a reaction row is not a move) |
| additive | a talent row's `additive` (spread for a Dendro hit, aggravate for an Electro one; a mismatch and an amplified hit are refused); the flat term rides on the first scaling term, × count |
| Lunar weight | **gcsim's solo-contributor weight, 0.6, by default** (owner ruling 2026-11-14, `DECISIONS.md` §44; it was GO's whole contribution, 1, until then): gcsim ranks every contributor 0.6/0.3/0.05/0.05 (`pkg/reactable/lunarcharged.go:22,171-184`, `lunarcrystallize.go:27,220-230`) and the subject is the only one priced. `weight` in (0, 1] overrides; the panel does not offer it yet. Each Lunar GO fixture records ours at 0.6 of GO's |
| bound | a reaction row makes EM live and nothing else; every reaction term is monotone in EM (and CRIT), so the optimistic completion still dominates |
| assumptions | each reaction row's count and trigger, and the two divergences, in the estimate's list |

**Wired since** (each with a GO fixture): VV swirl +60%; Thundering Fury overloaded/EC/
superconduct/hyperbloom +40%, aggravate and Lunar-Charged +20%; Crimson Witch overloaded/burning/
burgeon +40% (now `modelled`); Flower of Paradise Lost +40% and +10% per stack; Disenchantment
superconduct +80%; Night of the Sky's Unveiling and Silken Moon's Serenade Lunar +10% under their
Gleaming Moon choice; Aubade's Lunar +20%/+40% (two new situational conditions); Nahida C2's
bloom-family CRIT 20%/100% (new `c2_bloom` condition); Mona C1's EC/Lunar-Charged/Hydro swirl/
Lunar-Crystallize +15% (**a Hydro swirl only** since the owner's ruling of 2026-11-14, `DECISIONS.md` §44, as gcsim `mona/cons.go:71-80` and her text have it; GO adds it to every swirl, recorded by `mona_c1_hydro_swirl_on_kazuha`); Baizhu A4's reaction bonus from his Max HP to 50,000 (a teammate's
number; withheld by name when he is the subject).

**Not wired, named:** every kit's direct Lunar or Stellar hit and Lunar base-damage bonus from a
giver's stat (Flins, Linnea, Nefer, Ineffa…: GO's `lunarDmgNode(… base: stat …)` — a hit of its
own, which the target has no row kind for yet), Nilou's Bountiful Cores (her sheet is on the
concurrent branch), swirl's amplified/aggravated variants, burning's tick count, the Stellar
reactions, and contributors other than the subject.

**Found driving it:** none in the chain. The panel's two actions ran together ("ADD ABILITYADD
REACTION"); `.formula__actions` now spaces them.

### 2.8 Weapon passives (P3, task 12; built 2026-11-14)

**Owner, 2026-11-14: "Weapon passives".** Branch `feat/formula-weapon-passives`; the go-ahead and
the two P3 changes that came with it are `DECISIONS.md` §44.

**Where it lives.** `backend/app/formula/genshin/weapon_passives.py` (schema, pins, resolution),
`backend/app/data/formula/weapons/<slug>.json` (one per weapon), `services/kit_buffs.py:
team_weapons` (after the kits, the same two passes), `/formula/kit-buffs` (`sources[].kind`,
`weapons[]`), and in the browser `formula-calibration.ts` (weapon sources ride with the kits;
`missingWeapons`), `formula-recipe.ts:weaponAssumptions`, the panel.

#### The format, and why it is not a kit sheet

A weapon is a giver whose numbers index **its refinement's** `param_list`. A sheet's `ValueRef`
names a talent row, a constellation or an ascension passive, its pins are those lists and its
sources gate on ascension and constellation; none of that exists for a weapon, and a refinement
index exists in none of it. Adding a fifth kind to `ValueRef` would put a weapon branch into every
sheet validator. So the file has its own small value type, and **everything else is the sheet's**:

| shared with sheets | |
|---|---|
| conditions | `sheets.SheetCondition`: the §41 default rule (curated `usual`, `self` at its maximum, a teammate's buff on at its maximum, a `situational` one off only with a reason) is the one already written |
| team gates, receivers | `sheets.TeamGate`, `sheets.Receivers`, `sheets._reaches` |
| giver stats, per-candidate conversions | `sheets.GIVER_STATS`, `STATIC_STATS`, `SELF_CONVERSIONS`: a wielder who is the subject turns a value reading an artifact-moved stat into the recipe's per-candidate term, or it is withheld by name |
| evaluation | the Pando DAG in the wielder's **pass-1** registry, under `formula_tag("weapon:<slug>", effect)` so it cannot collide with the wielder's own sheet |
| output | `sheets.ResolvedKit` in the P1 `Bonus` vocabulary: the browser applies a weapon exactly as a kit |

| weapon-only field | why |
|---|---|
| `{"param": i}` | the wielder's refinement list, entry `i` (or a cited `constant`) |
| `pins` | all five refinements' lists as seeded at curation (nanoka 7.2.51); a wielder whose list differs withholds the whole passive by name |
| `times_param` | one refinement entry times another (Makhaira Aquamarine's 30% share, A Thousand Blazing Suns' +75%) |
| `threshold`, `cap`, `stat_cap` | a refinement entry or a cited constant (Engulfing Lightning's ER above 100%; Finale of the Deep's 150 ATK; Peak Patrol Song's 3,200 DEF) |
| `own_element` | a DMG bonus for the wielder's own element (Mistsplitter's Emblem), resolved to the receiver's element on a `self` effect |
| `per_team` | times a teammate count, as Gilded Dreams (A Thousand Floating Dreams) |
| `negate` | a decrease the list publishes positive (Rust's Charged Attack -10%) |

**The wielder's own unconditional stats enter what its values read.** Key of Khaj-Nisut's party
EM is 0.2% of the wielder's Max HP **with** its own +20% HP (GO `input.total.hp`). Pass 1 carries
no weapon passive (§2.6 rule 1) — that rule is about other sources' buffs; a weapon reading a stat
it raises itself is GO's arithmetic, not a cycle — so each resolution registers its own
unconditional `self` stat bonuses into a registry built for it alone before evaluating.
Conditional ones are not, and the one passive this changes says so (Peak Patrol Song's Ode DEF%).

**Two wielders of one weapon** get two sources, `weapon:<slug>` and `weapon:<slug>:2`, so their
conditions stay apart. GO's `nonStackBuff` (two Millennial Movement weapons apply one) is **not**
modelled: both apply, and each such file says so.

**A condition no effect reads is refused** by the schema. Found curating: Thrilling Tales' ATK%
had lost its gate, so its toggle switched nothing and the buff was always on; its GO fixture stated
the toggle on, so the figure could not tell.

#### Receivers

As a sheet's: the receiver is the optimized character. `self` reaches them only when they wield
it; `others` only when a teammate does (Thrilling Tales, Makhaira Aquamarine's share, A Thousand
Floating Dreams' party EM); `team`, `active` and `enemy` always. A teammate's weapon's self buffs
(their Homa, their Mistsplitter) are the teammate's own stats, which enter no number the estimate
reads, so they are simply not this receiver's.

#### The subject's weapon, and the weapons-in-optimizer search

The formula estimate scores **the build's equipped weapon**: `/search-context` puts its base ATK
and substat in each row's base, and `/formula/kit-buffs` resolves its passive. The weapon picker
(`DESIGN_weapons_in_the_optimizer.md`) is offered on the rotation objective only; a formula search
runs one weapon, as before. Comparing weapons under the estimate would need `/search-context` and
`/formula/kit-buffs` to take a candidate weapon id — an owner question, not built. *Built since: §2.9.*

**Staff of Homa beside Hu Tao's Paramita.** Both are flat ATK from her Max HP; hers is capped at
400% of her base ATK, Homa's is not, and summed before the cap they would be the wrong number. The
recipe used to refuse a second conversion into flat ATK; it now prices each apart
(`ResolvedConversion.extra`, each `cappedAmount` on its own and summed — monotone, so the bound
holds; `capped-conversions.spec.ts`).

#### Coverage (catalogue: 253 released weapons at nanoka 7.2.51, beta and crossbow rows excluded)

| status | count | |
|---|---|---|
| modelled | 46 | every damage part applied |
| partial | 16 | a part named and not applied, below |
| no damage effect | 9 | Favonius ×5, Sacrificial Sword/Bow/Greatsword/Fragments: energy only, said |
| unmodelled | 1 | Crescent Pike: its only effect is a damage instance of its own |
| **no file** | **181** | named in the panel as "no weapon passive modelled": base ATK and substat only |

Partial, each part with its reason in the file: **weapon damage instances** (Aquila Favonia's
Falcon, the five Skywards' procs) — the target has no weapon-hit row kind, as kits' direct hits
have none; **a conversion the recipe does not carry per candidate on the wielder** — Engulfing
Lightning's ATK% from ER, Key of Khaj-Nisut's EM from HP (self and party, when the subject wields
it), Makhaira Aquamarine's and Wandering Evenstar's ATK from EM, Peak Patrol Song's party bonus
from DEF; each is a number when a teammate wields it; **Stellar-Conduct** (Kagura's Verity),
refused by name since task 13; **a timeline** (Alley Hunter's decay, Light of Foliar Incision's
28 instances); Starcaller's Watch's EM (the seeded list does not carry it); Peak Patrol Song's
Ode DEF% not in the DEF its party bonus reads; Polar Star's R4 three-stack value (GO writes 0.528,
the seeded list 0.525; ours is read).

**Tiers.** `RESEARCH_passive_tiers.md`'s tier 1/1c were a regex over gcsim's Go and its per-row
list was never committed. The estimate's question is GO's, where a stack, a duration or an aura is
a **condition the user states** — so gcsim's tier 2 (timed, stacking) is as expressible as tier 1
here, and most of the weapons above are tier 2 by that survey. What stays out is what has no
closed form in GO either: weapon damage instances, and the conversions the recipe lacks. All of
tier 1's named weapons are in (The Stringless, Festering Desire, "The Catch", White Tassel, Rust,
Redhorn Stonethresher, Primordial Jade Cutter), and 1c's Staff of Homa and Engulfing Lightning
(the latter partial, above).

#### GO agreement

73 weapon fixtures (`go_fixtures_weapons.py` to `_weapons4.py`), one or more per weapon with a
damage effect on its main effect, R1 and R5 for Staff of Homa, Primordial Jade Cutter, Mistsplitter,
Amos' Bow, Polar Star, Calamity Queller, The Widsith, Deathmatch and Peak Patrol Song. Each is GO's formula worked
by hand with our seeded refinement values written out (never read through the resolver), against
the resolver's source for a stated wielder. **66 exact** (`relative_divergence_from_go` 0; the browser within 8.5e-8, the f32 floor), the
six amplified ones (2.78 vs 25/9, ~2e-4) and Engulfing Lightning's (its withheld ATK% from ER,
recorded). `formula:verify` plants on weapon sources as on kits: every effect 1% off must fail, a
frozen self-conversion must fail where it reaches the row, a cap ignored must fail past it
(Finale of the Deep below and past its 150).

### 2.9 Weapon comparison, wielder conversions, non-stacking and proc rows (P3; built 2026-11-14)

**Owner, 2026-11-14, after #389**: weapon comparison under the formula estimate; the per-build
conversions #389 withheld on the wielder; *"Millennial Movement: one"*; weapon proc rows. Branch
`feat/formula-weapon-compare`; the four approvals and the choices made are `DECISIONS.md` §45.
§2.8's "a formula search runs one weapon", its "Not carried per candidate on the wielder" list,
its Millennial note and its "weapon damage instances: named" are superseded by what follows.

#### Weapon comparison: the data flow

```
Optimize (formula) ──"Compare other weapons too"── selected ids (the gcsim picker, unchanged)
   │  for each of [equipped, ...selected]:
   ├─ POST /builds/{id}/search-context {…, weapon_id}  → base: candidate base ATK + substat at
   │                                                      the build's weapon level (#240's guard:
   │                                                      resolved, never trusted; 404 / 422)
   ├─ GET  /formula/kit-buffs ?subject_weapon_id=&subject_weapon_refinement=
   │        → the candidate's passive instead of the equipped one's; the subject's pass 1 on the
   │          candidate (their own kit's base-ATK reads, the passive's stat reads); teammates
   │          unchanged; `weapons[]` names the subject's weapon and its status
   ├─ formulaCalibration → one recipe per 4-piece state
   └─ searchRecipe — one full search per weapon (H1 of DESIGN_weapons_in_the_optimizer: the
      Pareto filter stays inside each call)
   → weaponRanking (the gcsim path's list): best-against-best, equipped first and marked,
     "passive not modelled" / "passive partly modelled" per weapon
```

| rule | |
|---|---|
| refinement and level | the build's own, as the gcsim comparison's `SubstituteWeapon` rules; the API takes a refinement (1–5) and the page does not offer one yet |
| which weapons | the gcsim picker's list, unchanged: every weapon of the character's class, KQM-tiered (OQ-W2 is still open; the formula path follows the gcsim path, as asked) |
| a weapon with no passive file | competes on base ATK and substat, labelled "passive not modelled" in the ranking and named in the assumptions |
| the build | `kit_buffs.WeaponSwap`, a read-only view; the session-attached ORM row is never assigned to (the integration test reads the build back) |
| cache keys | `FormulaEstimateService.kitCache` keyed by subject, team **and weapon + refinement** (`kitKey`); `/search-context` is not cached. #240 shipped flat rankings because a key lacked the weapon: `formula-weapon-compare.spec.ts` asserts two weapons are asked for separately and never answered from each other, and that three weapons give three different scores; `test_formula_weapon_compare.py` asserts two candidates' bases differ |
| conditions | a candidate's passive conditions take their §41 defaults; the panel's toggles are the equipped weapon's (a candidate's own toggles are not shown) |

#### The wielder conversions

`sheets.SELF_CONVERSIONS` gains four pairs, so a weapon value reading one of the wielder's
artifact-moved stats becomes a per-candidate term instead of being withheld:

| effect stat | from | weapon (GO) | recipe term |
|---|---|---|---|
| `atk_pct_from_er` | ER above 100%, capped | Engulfing Lightning (`min(x × (premod.enerRech_ − 1), max)`) | `RecipeHit.atkPercentFromEnergyRecharge`, into the ATK percentage of every ATK read |
| `em_from_hp` | total HP (with the weapon's own HP%) | Key of Khaj-Nisut, self per stack and the party share (`total.hp`) | `RecipeHit.emFrom`, into the EM every reader takes (amplifying, reactions, conversions from EM) |
| `flat_atk_from_em` | EM | Makhaira Aquamarine, Wandering Evenstar (`premod.eleMas`) | the flat-ATK conversion (`ResolvedConversion`), now from EM too |
| `dmg_bonus_from_def` | total DEF, to 3,200 | Peak Patrol Song's party bonus (`min(total.def, 3200) / 1000`) | a `StatConversion`; the **stat** cap becomes the value's cap, `x × 3.2` (`k × min(s, c) = min(k × s, k × c)`) |

Each is monotone in its source, which the Pareto layer makes live (ER for the first, HP for the
second, EM, DEF), so the bound stays admissible. Peak Patrol Song on its wielder now reads the
Ode's own DEF% (GO's `total.def`); a teammate wielder's still does not (§2.8).

#### Millennial Movement: one (GO's non-stacking)

**The families are GO's, generated, never typed.** `scripts/build_go_nonstack.py` reads every
`Weapons/<Type>/<Key>/index.tsx` at `2c13fc40` for `nonStackBuff(name, …)` and commits
`app/data/formula/weapon_nonstack_go.json` (16 weapons). Each passive file names the buff on its
effects (`non_stack`), and the schema refuses a name GO does not declare for that sheet and a
sheet GO marks without one. The Millennial Movement series is GO's `millenial*` names:
`millenialatk` (Freedom-Sworn, Song of Broken Pines, Elegy for the End), `millenialncpdmg`
(Freedom-Sworn), `millenialelemas` (Elegy). The other families are a weapon's own (`ttds`,
`wolf`, `key`, `patrol`, `starcaller`, `hakushin<element>`) or a pair (`leafCon`: Forest Regalia
and Sapwood Blade), and the same rule applies to them.

**Which one wins, and why.** GO resolves `input.nonStacking[name]` with its `small` string
accumulator (`uiData.ts:217-218,266-276`) over every member whose write condition holds: **the
wielder whose GO character key sorts first** — `KaedeharaKazuha` before `Venti` — whatever the
refinement. It is GO's rule, deterministic and arbitrary; it is not "the stronger buff", and the
GO fixture is built to show it (Kazuha's R1 Freedom-Sworn 20% applies, Venti's R5 Elegy 40% does
not). Followed because GO is the comparator (D-F4). Each weapon source carries its wielder's key
as `stack_rank` (`talent_boosts.go_character_key`, the cased key from GO's committed sheet list;
a character without a GO sheet sorts after every cased key). The browser applies the rule per row
(`formula-recipe.ts:nonStackWinners`): a source writes only when its effect's `when` holds, as
GO's write is gated, so a winner toggled off hands the buff to the other. The loser is named in
the assumptions.

#### Proc rows

A **proc row** is `count` instances of the subject's weapon's own damage instance:
`proc.multiplier × ATK` in the proc's element, through `rowHits` with no move and no talent row —
DMG% for its element and every channel, CRIT, DEF, RES and every ATK buff reach it; a move- or
row-scoped buff does not (GO `customDmgNode(…, 'elemental', {hit: {ele: physical}})`,
`dataUtil.tsx:113-138`; gcsim `AttackTagWeaponSkill`). Seven weapons carry one, each cited to GO
and gcsim lines (`procs` in the file): Aquila Favonia (Falcon, 200–320%), Skyward Atlas (160–320%),
Skyward Blade (20–40%), Skyward Harp (125%), Skyward Pride (80–160%), Skyward Spine (40–100%),
Crescent Pike (20–40%). The multiplier is the refinement's seeded entry, pinned like every value.
Only the wielder-subject's weapon offers procs (a teammate's proc is a constant, as their hits
are, and is named). A proc row of a weapon not in the run — a candidate in a comparison — deals
nothing and says so. **Recorded:** GO reads Aquila's and Skyward Blade's procs off `premod.atk`;
the estimate reads total ATK, equal unless an ATK-from-another-stat buff is in play (said per row).

#### Status

A weapon whose only unapplied parts deal no damage (Aquila's healing, a Skyward's attack speed)
is now `modelled`, and a proc counts as an effect: as a wielder-subject at R1, **57 modelled, 5
partial** (Alley Hunter's decay, Kagura's Verity's Stellar-Conduct, Light of Foliar Incision's
instance limit, Polar Star's R4 value, Starcaller's Watch's EM), 9 no damage effect, 1 with
nothing for its wielder (Thrilling Tales).

#### GO agreement

11 new fixtures (`go_fixtures_weapon_compare.py`; 233 in all): Engulfing Lightning's ATK% from ER
below and past its cap, Key of Khaj-Nisut's EM from HP (vaporize), Makhaira and Evenstar's ATK
from EM, Peak Patrol Song's DMG from DEF below and past its 3,200 cap, the Millennial pair, and
Aquila/Harp/Pride proc rows. All exact but the two amplified ones (2.78 vs 25/9). The #389
Engulfing Lightning emblem fixture, whose ATK% from ER was a recorded withholding, is now exact.
`formula:verify` 233/233 (worst 8.5e-8) with new plants: each new conversion frozen at the
zero-artifact build must fail; the non-stacking names stripped, and the tie-break reversed, must
each fail; a proc's multiplier 1% off must fail.

### 2.10 Energy Recharge from particle data (P3, task 14; built 2026-11-15)

**Owner, 2026-11-15: "ER from particles."** Branch `feat/formula-er-particles` (off `dev`; no
direct commits to `dev`). Until now the estimate had no energy model, so ER was worth nothing to
it — the pre-`DESIGN_energy_in_the_optimizer` behaviour, and §2.1's "ER is a user-set floor, as
in GO, until G13". G13 is this section.

#### The model, and where each part comes from

A closed form in the spirit of KQM's ER methodology, with every constant gcsim's at the pin and
cross-checked against KQM's Energy library page (library.keqingmains.com/combat-mechanics/energy):

| part | rule | cited to |
|---|---|---|
| particle value | 3 own element, 2 clear, 1 other | gcsim `pkg/core/player/character/energy.go:61-71`; KQM's table (Same 3.0, Clear 2.0, Different 1.0) |
| off field | `1 − 0.1 × party size`: 0.6 in four, 0.7 in three, 0.8 in two | `energy.go:58-60`; KQM ("In a party of 4 … 60% … parties of 3, 70%; parties of 2, 80%") |
| ER | multiplies particles only: `amt * er * p.Num` | `energy.go:72-77`; KQM ("flat energy … is not affected by Energy Recharge") |
| flat energy | added as-is | `energy.go:35-43` (`AddEnergy`) |
| who receives | every member, on- or off-field by who is active | `pkg/core/player/player.go:197-200` |
| requirement | `max((cost − flat) / raw particle energy, 1)` | gcsim's own substat optimizer, `pkg/optimization/optstats/energy_stats.go:85` |
| enemy particles | one clear particle every 599.5 frames (≈ 10 s) | the same `ENERGY_DRIP` the waiting model emits (`gcsim_config.py`, five community configs, `DESIGN_waiting_for_energy.md`), as the mean of `pkg/simulation/setup.go:522-531` (`start + Intn(end − start)`) |

So over a rotation of `L` seconds the subject banks `E(ER) = ER × Σ particles × value × field +
flat`, and needs `ER ≥ (cost − flat) / Σ particles × value × field`. The cost is the game data's
(`Character.burst_energy_cost`).

**Particle counts are curated, not imported.** `character_energy_drops` (#369) publishes the
game's per-drop entries, not a count per cast — Kazuha's `per_drop` is 1 where his tap drops 3,
Xingqiu's is 1 with 2 applications where a cast drops 5 — so they cannot be read as counts. The
counts are gcsim's, each read off its `QueueParticle` call:
`backend/app/data/formula/energy/particles.json`, 17 characters (Bennett 2.25 tap, Xingqiu 5,
Yelan 4, Xiangling 4, Kazuha 3 tap, Ayaka 4.5, Nahida 3 per 7 s, Escoffier 4, Citlali 5,
Neuvillette 4, Jean 2.67, Chevreuse 4, Mavuika 5, Skirk 4, Sucrose 4, Navia 3.5, Furina one per
3.25 s — KQM's measured average; gcsim's 2.5 s ICD is the ceiling). A random count is its
expectation. **Every cited line is snapshotted** (`gcsim_lines.json`,
`scripts/gcsim/snapshot_particle_lines.py`) and `test_formula_energy_data.py` holds each count to
the literal on its line. Characters whose particles come from a summon's hits with a chance per
hit (Raiden's Eye, Oz, Kuki's ring, Kokomi's jellyfish, Zhongli's stele, Yae's totems) are **not
curated**: their count per cast is how many hits land, which nothing cited states. The panel names
them and takes the user's number; none are counted until then.

#### The assumptions, all in the panel

`/formula/energy` serves each member's burst cost, burst cooldown (the burst's own `CD` row) and
curated sources. The panel's **Energy** section shows the requirement and every input, each with
its default and citation:

- **Rotation length**: the subject's burst cooldown (game data). It times per-second sources
  (Furina's Salon, Nahida's Tri-Karma, capped by a duration) and the drip.
- **Skill casts per rotation**, per member: 1 — KQM's Bennett guide's baseline playstyle ("1 E per
  Q"). A target row's count is not used: rows count hits, not casts (Guoba lands four).
- **Particles per cast**, per source: the table's (a hold is entered here: Bennett's level-1 hold
  is 3, `skill.go:242`).
- **Caught on field**: the subject's own particles caught while still casting (`caster`) 100 %;
  an off-field generator's (`active`: Guoba, Salon, Tri-Karma) and every teammate's 0 % — the
  subject is assumed off field when others' particles land. Editable per source, as a share
  (Guoba in the gcsim sample: two of four on field).
- **Enemy particles**: on, at the drip's rate, caught off field.
- **Flat energy**: 0. Not counted unless entered: Favonius procs, a kit's flat refund (Raiden's
  burst), normal attacks' chance of 1 energy (`pkg/core/energy.go:30-90`).

The requirement also fills the recipe's `minimumEnergyRecharge` — the field the page's existing
"This build has X Energy Recharge and the rotation needs Y" warning reads — so the ER floor UI is
unchanged and now speaks for the formula estimate too, net of the recipe's own ER (base 100 %,
weapon, ascension, kit ER buffs, a 4-piece state's static set ER).

#### What the score does with it: the owner's fork

CLAUDE.md records the owner's ruling for the gcsim path (2026-09-02): skipping by default,
**waiting as an option**, and that the two disagree by a factor — ER worth +7.3 % skipping
against +44.4 % waiting on their own Furina, because **a skipped burst costs no time**. The
closed form can price either, and they mean different things:

- **skip** — a burst the energy cannot fund is not cast. Energy carries between rotations, so in
  the long run the burst lands `min(1, E(ER) / cost)` as often, and **the burst rows** are scaled
  by it. Like gcsim's skipping, it is blind to what the burst does beyond its own hits: a skipped
  Bennett burst still buffs every row, Furina's 98 % skill damage does not move
  (`recipe-eval.ts:evaluateRecipe`'s own note), and a self-buff from the subject's burst stays on.
- **wait** — the team holds the rotation until the burst is funded, as a player at a keyboard does.
  The deficit `cost − E(ER)` is paid by the drip alone (the team stands still), so the rotation
  takes `L + wait` and **every row** is scaled by `L / (L + wait)`. It prices ER the way the
  owner's question did ("without the ER she doesn't burst on time making the DPS drop"), and it
  needs the drip, as gcsim's waiting model does; with the drip off it steps back to skip and says
  so.

The honest model is **wait** for the question this estimate answers — damage of the chosen
sequence, which a player performs by waiting rather than by silently dropping the burst — and it
carries the delay to every row, as the gcsim ladder's DPS does. **But which one the score uses
by default changes what every formula score means**, so it is not picked here: the default is a
third mode, **off** (report the requirement; ER still worth nothing), which leaves today's scores
unchanged, and both priced modes are a choice in the panel. *Owner question (TASKS 14): default
to off, skip or wait?*

Both priced factors are non-decreasing in ER, so the search's optimistic bound stays admissible;
`liveQuantitiesFor` makes ER live exactly when a priced mode leaves the requirement unmet (the
same rule the gcsim ladder follows, so an ER sands is no longer Pareto-pruned before it is
scored). The model lives in `sim/formula-energy.ts`, read by `recipe-eval.ts:formulaEnergyTotal`
and attached per recipe in `formula-calibration.ts`; nothing in `formula-recipe.ts` changes but
one added function (`subjectEnergyRecharge`).

#### Verification

GO has no energy model (ER is a user floor there), so D-F4's comparator has nothing to compare;
KQM publishes ER requirements as **ranges** per team archetype (Furina C0 solo Hydro "~200-260%")
with no stated inputs, and its library page publishes no worked example, so neither gives a
fixture. The oracle is **gcsim's own energy events**: a native build at the pin
(`backend/tests/fixtures/formula/energy/`, PROVENANCE beside it) running the owner's National
team (Xiangling, Xingqiu, Bennett, Yelan) with `ignore_burst_energy=true`, so four identical
rotations, and no drip.

- **All 112 particle events** are exactly `count × value × field × ER`, in Python
  (`test_formula_energy_gcsim_sample.py`) and through `formula-energy.ts` (`formula:verify`).
- **Particles per cast** are the table's: Xingqiu 5, Yelan 4, Guoba 1 a hit × 4 a cast.
- **Xiangling's steady rotation banks 39.97176** at her 195.94 % ER — 1.9594 × 20.4 (Bennett 3
  Pyro off field 5.4, Guoba 4 Pyro two on field and two off 9.6, Xingqiu 5 Hydro off 3.0, Yelan 4
  Hydro off 2.4), built from the table rather than the log — and gcsim's drain reads 39.97176. Her
  requirement for that rotation, gcsim's formula, is 80 / 20.4 = 392.2 %.
- Plants that must miss the drain: every particle caught on field, an off-element particle valued
  as same-element, Guoba all off field.

## 3. Phases

Each phase ends in something usable.

| phase | contents | gaps | size | usable result |
|---|---|---|---|---|
| **P0** | **Live defects.** The multiplier parser drops the scaling stat, and mixed rows such as Nahida's ATK+EM become two ATK hits. The frontend hardcodes `scaling_stat: 'atk'`. **Today's single-hit Optimize scores HP, DEF and EM scalers off ATK** (Neuvillette, Furina, Nilou, Yelan, Itto, Noelle and others: 29 characters) | G1, G2 | S | Correct single-hit results today, fallback or not |
| **P1** | Gcsim status on catalogue entries (§1). Import passive and constellation `param_list` plus per-hit element and energy data. Synthetic recipe (single ability + weighted multi-target). Routing when gcsim refuses, with labels. Elemental resonance. Conditional set bonuses with toggles. A minimal assumptions panel | §1, G3, G5, G7, G9, G12 (lite), G14 | ~1–2 wk | **Every character can be optimized** on any ability or ability mix, with their own sets and the team's resonance, **labelled "no kit buffs"** |
| **P2** | Sheet schema on the Pando tags. Team-stat-dependent buffs (two-pass: teammates before the subject). Crossval harness against gcsim. Sheets for the ungated characters plus the top buffers, then by usage | G6, G10, G15 | L (weeks; per-sheet cost after the schema) | Team buffs for the teams people run, each sheet verified or marked unverified |
| **P3** | Weapon passives: tiers 1 and 1c first (58 portable, `RESEARCH_passive_tiers.md`). Transformative, additive and Lunar reactions with a stated reaction-count assumption. ER from particle data | G8, G11, G13 | M–L | Closes the biggest remaining accuracy gaps |

**Follow-up from the gcsim re-pin, independent of this plan.** gcsim v2.50.0 no longer
runs out of memory on an unfundable burst; it hangs at about 23 MB indefinitely. Bursts are
gated, so no current path reaches it, but a browser worker timeout is cheap insurance.
(`RESEARCH_gcsim_repin_2026_11.md`, open question 1.)

## 4. Decisions for the owner

| | question | recommendation |
|---|---|---|
| D-F1 | Gcsim status: computed on read, or stored? | **On read** (§1). A stored column goes stale at every re-pin |
| D-F2 | Kit data source policy (§2.3) | Numbers from our DB. Structure cited to gcsim Go (gated) or GO sheets (ungated). Never prose-parsed |
| D-F3 | Where the fallback appears: only when gcsim refuses, or also as an opt-in "fast estimate" for gated teams? | Both. Default to gcsim when it can run; offer the estimate as a labelled toggle |
| D-F4 | Accuracy bar for "verified" sheets | Per-hit terms within 1 % of gcsim's calibrated recipe on committed fixtures. Tune after the first ten sheets |
| D-F5 | Which surfaces get the fallback in P1 | Optimize (single ability + multi-target) and Rank/Upgrade, since all of them take a `Recipe`. Calculate's rotation view stays gcsim-only |
| D-F6 | Ship P0 now, ahead of the rest? | **Yes.** It is a live defect in today's single-hit optimizer |
