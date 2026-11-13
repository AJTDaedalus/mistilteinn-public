# DESIGN: a formula fallback, so every team can be optimized

**Status: proposed, 2026-11-13. Nothing is built.** The owner asked for two things:
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
  `charge`, and some Travelers have no plunges.
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
