# DESIGN: a formula fallback, so every team can be optimized

**Status: P0 merged; P1 complete and merged (#367–#371). P2 foundation built on `feat/math-fallback-p2-sheets` (2026-11-13): the sheet schema, the two-pass team evaluation, GO fixtures, and sheets for Bennett and Kazuha (§2.6). Plunges no longer make a character `partial` (owner, 2026-11-13). Owner rulings in `DECISIONS.md` §38: the estimate is opt-in for every team (D-F3), and Genshin Optimizer, not gcsim, is the accuracy comparator for the fallback (D-F4).** §2.4 below predates D-F4. Read "gcsim" there as "GO" for sheet verification; gcsim remains the oracle for the damage chain itself. The owner asked for two things:
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
  (`RESEARCH_go_team_math.md` §6). ER is a user-set floor, as in GO, until G13.
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
| `conditions` | P1's condition vocabulary, but the default is **derived** (§39): `self` on at max, `situational` off, and `giver_is_subject` — `self` when the giver is the optimized character, `situational` when a teammate is (Bennett standing in his own field is his doing; a teammate standing in it depends on the fight) |
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
subject's own stat (Furina's A4, Nahida's A4 — the owner's open question in `DECISIONS.md` §39)
and the Hexerei party mechanic (Sucrose's Witch's Eve Rite, Mona's lock parts).

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
They are not constellations and not this table's question.

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
