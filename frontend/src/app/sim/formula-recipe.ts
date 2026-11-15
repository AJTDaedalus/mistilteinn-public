/**
 * A recipe **synthesised from formulas** instead of calibrated from a gcsim run.
 *
 * Math-fallback P1, task 5 (`docs/DESIGN_team_math_fallback.md` §2.2). A `Recipe` is already a
 * weighted, multi-hit, closed-form objective, and `recipe-search.ts`, ranking and upgrade
 * potential all take one. So the fallback does not build a second optimizer: it builds the
 * recipe the existing one consumes, from the single-hit chain's own terms plus the buffs the
 * formula estimate can see — conditional set bonuses and elemental resonance.
 *
 * ## The target: rows × counts, each with its own conditions
 *
 * A **row** is one of the character's own talent hits (`AvailableHit`) and a **count** — how
 * many times it lands in whatever sequence the user means. A single ability is one row with a
 * count of 1; GO's "Multi-Optimization Target" is several (`RESEARCH_go_team_math.md` §3:
 * `Σ weight_i × hit_i`). Teammates' damage is not a row: only the optimized character's
 * artifacts move during a search, and their damage is the part a formula has no business
 * estimating for someone else (DESIGN §2).
 *
 * **Every row carries its own conditional state**, which is GO's newer "frames" design
 * (`pando-solver/src/index.ts:buildDetachedSolverBase`, each frame reading under its own
 * preset) rather than its live one, where a conditional applies to every row at once. Team-
 * level conditionals are the default; a row overrides any of them.
 *
 * ## What "the same terms as the single-hit kernel" means here
 *
 * With no buffs, a synthesised hit evaluated against a candidate gives exactly what
 * `search.ts`'s kernel gives for the same five pieces — `formula-recipe.spec.ts` proves it, and
 * `scripts/verify-formula-recipe.mjs` holds it against the GO-cited fixtures. Three of the
 * kernel's terms move with the candidate in ways a frozen gcsim term does not, so the recipe
 * carries them as optional fields `recipe-eval.ts` reads: EM (`calibratedEm`), the amplifying
 * multiplier (`amplifying`, through `damage.ts:amplifyingMultiplier` itself) and Emblem's
 * Energy-Recharge conversion. A mixed-stat hit (`# ATK+# Elemental Mastery`) becomes one
 * recipe entry **per term**: every later factor multiplies the base linearly, so the parts sum
 * to the whole, and the flat part rides on the first.
 *
 * A count folds into `talent` and `flatDamage` for the same reason — damage is linear in the
 * base — so every consumer that sums `evaluateHit` over `hits` scores the weighted target with
 * no idea weights exist. The count itself is kept in `meta.formula.rows` for display.
 *
 * ## The estimate's honesty
 *
 * `meta.formula` marks the recipe as a formula estimate, not gcsim-calibrated, and lists every
 * assumption: each condition's value and why, every unmodelled part of a bonus, every row whose
 * move is unknown. Kit sheets (P2) and weapon passives (P3, task 12) arrive as sources like any
 * other, and the recipe names whose are modelled and whose are not.
 */

import {
  ADDITIVE,
  type Additive,
  type Amplifying,
  amplifyingMultiplier,
  defMultiplier,
  LUNAR,
  type Lunar,
  resMultiplier,
  type ScalingStat,
  TRANSFORMATIVE,
  type Transformative,
  transformativeElement,
} from './damage';
import {
  cappedAmount,
  type ConversionSource, type ConvertedTerm, type FormulaMove, type FormulaProvenance,
  type ReactionTerm, type Recipe, type RecipeHit, type RecipeScaling,
  type StatConversion,
  type TripleStat,
} from './recipe';
import { emTotal, evaluateHit, NO_STATS, totalFor } from './recipe-eval';
import {
  FORMULA_ALL_DMG_BONUS,
  FORMULA_MOVE_BONUS_PREFIX,
  type RecipeSet,
} from './recipe-search';
import type { SearchContext, SetBonus } from './search';

// ── The buff data, as `/api/v1/formula/*` serves it ─────────────────────────────────────────
//
// Snake case on purpose: these are the API's own shapes (`app/schemas/formula.py`), passed
// through unmapped, so a field added there cannot be dropped by a translation here.

export type ConditionValue = number | string;

export interface FormulaCondition {
  key: string;
  label: string;
  kind: 'toggle' | 'stacks' | 'choice' | 'number';
  default: ConditionValue;
  /**
   * `self`: triggered by the wearer or character, on at its maximum. `situational`: off.
   * `usual`: a kit condition at its curated usual value. `teammate`: a teammate's kit buff, on
   * at its maximum (owner ruling 2026-11-14, `DECISIONS.md` §40 (ii)).
   */
  default_reason: 'self' | 'situational' | 'usual' | 'teammate';
  /** Why the default is what it is, one line, for a kit condition. */
  default_note?: string | null;
  max?: number | null;
  step?: number | null;
  options?: string[] | null;
}

export interface FormulaEffect {
  stat: string;
  value: number;
  elements?: string[] | null;
  element_from?: string[] | null;
  moves?: string[] | null;
  /**
   * The hit owner's own talent rows it reaches (`formula_effects.TalentRowScope`): a kit buff
   * its giver applies to their own hits (Nahida's burst bonus, Tri-Karma Purification only).
   */
  rows?: { talent: string; label: string }[] | null;
  reactions?: string[] | null;
  when: { condition: string; values: ConditionValue[] }[];
  per?: string | null;
  by_stack?: number[] | null;
  per_team?: 'same_element_others' | 'different_element' | null;
  per_team_max?: number | null;
  /**
   * Emblem's Energy Recharge cap, or a capped self-conversion's (owner ruling 2026-11-14,
   * `DECISIONS.md` §40): the most the term grants, in its own units, after any `per`.
   */
  cap?: number | null;
  /** A self-conversion's stat counts only above this (Nahida's A4, EM above 200). */
  threshold?: number | null;
  weapon_types?: string[] | null;
  /** `talent_level` only: the talent whose level it raises (`raiseRow`). */
  talent?: string | null;
  /**
   * GO's non-stacking buff name (`nonStackBuff`, owner approval 2026-11-14, `DECISIONS.md` §45):
   * of the sources holding an effect with this name, **one** applies — the source whose
   * `stack_rank` sorts first (GO `uiData.ts:_small`). Weapon passives only.
   */
  non_stack?: string | null;
}

/** A weapon's own damage instance at the wielder's refinement (`/formula/kit-buffs`, §45). */
export interface FormulaProc {
  key: string;
  label: string;
  multiplier: number;
  scaling?: 'atk';
  element: string;
  /** GO's ATK read: `premod` (Aquila, Skyward Blade) or `total`. */
  stat_layer: 'premod' | 'total';
}

export interface FormulaBonus {
  conditions: FormulaCondition[];
  effects: FormulaEffect[];
  unmodelled: { what: string; reason: string }[];
}

/** One bonus the estimate applies: a resonance, one tier of one set, or a member's kit. */
export interface FormulaSource {
  /**
   * `resonance:<key>`, `set:<set id>:<pieces>` or `kit:<sheet slug>`. Condition keys are
   * `<id>/<condition>`.
   */
  id: string;
  label: string;
  bonus: FormulaBonus;
  citation: string;
  /** A weapon source's wielder as GO keys them: GO's tie-break for `non_stack` (§45). */
  stack_rank?: string | null;
  /** The subject's weapon's damage instances, priced by a proc row (§45). */
  procs?: FormulaProc[];
}

/** A conditional set tier as `/formula/set-effects` returns it. */
export interface FormulaSetTier {
  set_id: number;
  set_name: string;
  pieces: number;
  status: 'modelled' | 'partial' | 'unmodelled' | 'no_damage_effect' | 'stale' | 'uncurated';
  bonus: FormulaBonus;
  citation: string;
  problem?: string | null;
}

/** An active resonance as `/formula/resonance` returns it. */
export interface FormulaResonance {
  key: string;
  name: string;
  element: string | null;
  bonus: FormulaBonus;
  citation: string;
}

/**
 * One team member's kit as `/formula/kit-buffs` returns it (math-fallback P2): the same
 * `bonus` vocabulary, every number already resolved in the **giver's** context by the
 * server's two-pass evaluation — Bennett's ATK bonus arrives as flat ATK from Bennett's own
 * base ATK. Only a giver who is also the optimized character can carry a per-candidate term
 * (`dmg_bonus_from_em`).
 */
export interface FormulaKit {
  id: string;
  label: string;
  giver: string;
  build_id: string;
  status: 'modelled' | 'partial' | 'unmodelled' | 'no_damage_effect';
  /** A GO-cited fixture checks this sheet. False is **unverified**, and is said. */
  verified: boolean;
  bonus: FormulaBonus;
  citation: string;
  /** The giver's pass-1 value of each stat an effect read. */
  giver_stats: Record<string, number>;
  /**
   * `kit` for a member's sheet, `weapon` for a member's weapon passive (`weapon:<slug>`,
   * math-fallback P3, task 12): the same vocabulary, applied alike. Absent is `kit`.
   */
  kind?: 'kit' | 'weapon';
  /** A weapon's wielder's GO key, the non-stacking tie-break (§45). */
  stack_rank?: string | null;
  /** The subject's weapon's own damage instances (§45). */
  procs?: FormulaProc[];
}

/**
 * One talent of the optimized character a kit raises (`/formula/kit-buffs`' `raised_talents`,
 * owner approval 2026-11-14, `DECISIONS.md` §42): its rows read 1, 2, … levels above the level
 * `/search-context` reads them at, by the same parse. Formula estimate only — gcsim applies these
 * raises itself, and a single-hit search has no party to raise anything.
 */
export interface FormulaRaisedTalent {
  talent: string;
  /** Stored plus constellation boosts: the level a row's own context was read at. */
  level: number;
  max_raise: number;
  rows: {
    label: string;
    index: number;
    raise_by: number;
    multiplier: number;
    scaling_stat: string;
    extra_terms: { stat: string; multiplier: number }[];
  }[];
  /** Raises that read no row (past the table's last level), with why. */
  unavailable: { raise_by: number; reason: string }[];
}

/** Whose kits the estimate models, for its assumptions. */
export interface KitCoverage {
  /** Givers whose sheet is applied, with whether it is verified. */
  modelled: { name: string; verified: boolean }[];
  /** Members with no sheet: base stats, sets and resonance only. */
  missing: string[];
  /**
   * Weapon passives (task 12): the ones applied (`<weapon> R<r> (<wielder>)`), and the members'
   * weapons with no passive data. Absent: the estimate says no weapon passive is modelled.
   */
  weapons?: {
    modelled: { name: string; verified: boolean; inert?: boolean }[];
    missing: string[];
  };
}

/** `{ "<source id>/<condition key>": value }`. */
export type ConditionState = Readonly<Record<string, ConditionValue>>;

// ── The target ──────────────────────────────────────────────────────────────────────────────

export interface FormulaRow {
  /** Stable within the target, so a row's conditionals can be addressed. */
  id: string;
  label: string;
  /**
   * What kind of move the hit is, for a move-scoped bonus. **`null` is "unknown", not "none"**:
   * such a row receives no move-scoped bonus and the recipe lists that as an assumption.
   * `suggestMove` offers a default only where the label leaves no doubt.
   */
  move: FormulaMove | null;
  /**
   * The talent row the hit comes from, as `/hits` names it, for a row-scoped kit buff.
   * Absent is "unknown": such a row receives no row-scoped buff, and the recipe says so.
   */
  hit?: { talent: string; label: string; index?: number } | null;
  /** How many times it lands. Decimals allowed, as in GO; must be positive. */
  count: number;
  /**
   * The row's resolved single-hit context — `/builds/{id}/search-context` for this hit, in
   * the kernel's spelling. Its `base` is character + weapon, its `hit` carries the scaling
   * stat(s) and any amplifying reaction, its `target` the enemy.
   */
  context: SearchContext;
  /** This row's overrides of the team-level conditionals (GO "frames"). */
  conditionals?: ConditionState;
  /**
   * A **reaction row** (math-fallback P3): `count` instances of a transformative or Lunar
   * reaction triggered by the optimized character, whose EM and level apply. The row's `hit`,
   * `move` and the context's talent hit are not read; its `base`, `target`, `characterLevel`
   * and `reactionLevelMultiplier` are.
   */
  reaction?: FormulaReaction | null;
  /** Spread or aggravate on this talent row's every hit: flat damage before its DMG bonus. */
  additive?: Additive | null;
  /**
   * A **proc row** (owner approval 2026-11-14, `DECISIONS.md` §45): `count` instances of a
   * weapon's own damage instance — Aquila Favonia's Falcon, a Skyward proc — dealt by the
   * optimized character, who wields it. `source` is the weapon's source id and `key` the proc.
   * Its damage is the proc's multiplier × ATK through the whole chain, with no move: GO
   * `customDmgNode(…, 'elemental', {hit: {ele}})`. A source the run does not carry (another
   * weapon in a comparison) contributes nothing, and says so. The context's talent hit is not
   * read; its base, target and level are.
   */
  proc?: { source: string; key: string } | null;
}

/** What a reaction row prices (`reactionRowHits`). */
export interface FormulaReaction {
  reaction: Transformative | Lunar;
  /** A swirl's element; required for a swirl, refused for anything else. */
  swirled?: string | null;
  /**
   * A Lunar contribution's weight. **Default 0.6, gcsim's weight for a solo (top-ranked)
   * contributor** (owner ruling 2026-11-14, `DECISIONS.md` §44): gcsim ranks every contributor
   * and weights them 0.6/0.3/0.05/0.05 (`pkg/reactable/lunarcharged.go:22,171-184`,
   * `lunarcrystallize.go:27,220-230`). GO prices the whole contribution (1), a recorded
   * divergence; a stated weight in (0, 1] overrides.
   */
  weight?: number;
}

/** gcsim's weight for the top-ranked (here: the only priced) Lunar contributor. */
export const LUNAR_SOLO_WEIGHT = 0.6;

export interface FormulaTeam {
  /** The optimized character's element, lower case — `wearer` in an effect. */
  element: string;
  /** Their weapon class, as the catalogue spells it (`WEAPON_CATALYST`). */
  weaponType: string;
  /**
   * Every member's element including the optimized character's, lower case, `null` for one
   * without. Read only for team counts (Gilded Dreams); resonance arrives already decided.
   */
  memberElements: readonly (string | null)[];
}

export interface FormulaInput {
  rows: readonly FormulaRow[];
  team: FormulaTeam;
  /** The team's active resonances, from `/formula/resonance`. */
  resonances: readonly FormulaResonance[];
  /** Every conditional set tier, from `/formula/set-effects`. */
  setTiers: readonly FormulaSetTier[];
  /** Sets the search may reach a 4-piece of, by catalogue (nanoka) id. */
  fourPieceSetIds: readonly number[];
  /** Team-level conditionals; any row may override. Absent keys take the default. */
  conditionals?: ConditionState;
  /** Names for `meta.characters`, the optimized character first. */
  characters?: string[];
}

export interface FormulaRecipeSet {
  /** What `searchRecipe` takes — one recipe per 4-piece state, like a calibrated set. */
  recipes: RecipeSet;
  /**
   * Conditional **2-piece** bonuses as stat pools, to add to the static ones in
   * `RecipeSearchContext.setBonuses`. A 2-piece applies in every state that holds two pieces,
   * including no 4-piece at all, so it cannot live in a per-state recipe; the pool reaches a
   * hit by its `move` (`recipe-eval.ts`).
   */
  setBonuses: SetBonus[];
  /** Sets whose 4-piece could not be scored (`stale`, `uncurated`), each with the reason. */
  withheld: { setId: number; reason: string }[];
}

// ── Helpers ─────────────────────────────────────────────────────────────────────────────────

/** gcsim's attack tag per move (`recipe.ts:BURST_ATTACK_TAG`'s enum), so energy code reads it. */
const ATTACK_TAG: Record<FormulaMove, number> = {
  normal: 1, charged: 2, plunge: 3, skill: 4, burst: 6,
};

const RECIPE_SCALING: Record<ScalingStat, RecipeScaling> = {
  atk: 'atk', hp: 'hp', def: 'def', elemental_mastery: 'em',
};

/**
 * A move for a talent hit, only where the label leaves no doubt — otherwise `null`.
 *
 * The talent type decides skill and burst. Inside the normal-attack talent the label is all
 * there is, and the vocabulary is not regular (`Arataki Kesagiri Combo Slash DMG` is a charged
 * attack, `Frostflake Arrow DMG` an aimed shot), so this matches only the phrasings that are
 * unambiguous and leaves the rest for the user to state. The per-hit `attack_type` import
 * (task 4) is the real source and replaces this when it lands.
 */
export function suggestMove(talent: string, label: string): FormulaMove | null {
  if (talent === 'elemental_skill') return 'skill';
  if (talent === 'elemental_burst') return 'burst';
  if (talent !== 'normal_attack') return null;
  if (/\bplunge\b/i.test(label)) return 'plunge';
  if (/\bcharged attack\b|\baimed shot\b/i.test(label)) return 'charged';
  if (/^(\d+-hit dmg|normal attack dmg)\b/i.test(label)) return 'normal';
  return null;
}

/**
 * A hit's move: the one its character's kit sheet names (`/hits`' `move`, GO's own per-row
 * declaration: Skirk's Seven-Phase Flash rows are skill-talent rows dealt as Normal Attacks),
 * else `suggestMove`'s guess from the label (owner ruling 2026-11-14, `DECISIONS.md` §40 (iv)).
 */
export function hitMove(
  hit: { talent: string; label: string; move?: FormulaMove | null },
): FormulaMove | null {
  return hit.move ?? suggestMove(hit.talent, hit.label);
}

/** A condition's value for one row: the row's override, the team's, or the default. */
function valueOf(
  key: string, condition: FormulaCondition, row: ConditionState, team: ConditionState,
): ConditionValue {
  return row[key] ?? team[key] ?? condition.default;
}

function conditionsBy(source: FormulaSource): Map<string, FormulaCondition> {
  return new Map(source.bonus.conditions.map((c) => [c.key, c]));
}

/** The elements an effect reaches for this wearer and state, or `null` for every channel. */
function elementsOf(
  effect: FormulaEffect, team: FormulaTeam, state: (key: string) => ConditionValue,
): Set<string> | null {
  if (effect.elements) return new Set(effect.elements);
  if (!effect.element_from) return null;
  const out = new Set<string>();
  for (const from of effect.element_from) {
    const element = from === 'wearer' ? team.element : String(state(from));
    if (element) out.add(element);
  }
  return out;
}

/** Teammates for Gilded Dreams, GO `GildedDreams/index.tsx:32-40`. */
function teamCount(kind: 'same_element_others' | 'different_element', team: FormulaTeam): number {
  const elements = team.memberElements.filter((e): e is string => !!e);
  if (kind === 'same_element_others') {
    // `teamSameNum - 1`: the wearer is in the tally and does not count for itself.
    return Math.max(elements.filter((e) => e === team.element).length - 1, 0);
  }
  return elements.filter((e) => e !== team.element).length;
}

/** What a set of effects adds to one hit. */
interface Buffs {
  percent: { atk: number; hp: number; def: number };
  em: number;
  er: number;
  critRate: number;
  critDmg: number;
  dmgBonus: number;
  reactionBonus: number;
  resistance: number;
  flatDamage: number;
  /**
   * Flat damage per point of the hit owner's own total ATK, HP, DEF or EM: a kit whose giver is
   * the subject (Valeriy's Offensive Directive, Kachina's A4, Zhongli's A4). One source per hit.
   */
  flatFrom: Record<ConversionSource, number>;
  /**
   * The threshold and cap of a capped flat-damage conversion (Clorinde's A1), by source. A
   * capped conversion is alone on its term: summed with another before its cap it would be
   * the wrong number, so a second one on the same hit is refused.
   */
  flatLimits: Partial<Record<ConversionSource, Limits>>;
  erConversion: { perUnit: number; cap: number } | null;
  /** Flat ATK, after the percentage — a kit buff resolved from its giver's stats. */
  flatAtk: number;
  /** DMG% per point of the hit owner's own total EM (a giver who is the subject). */
  bonusFromEm: number;
  /** Flat DEF, after the percentage (Gorou's banner). */
  flatDef: number;
  /** The target's DEF reduced (Nahida's C2), into the chain's own DEF term. */
  defReduction: number;
  /** The target's DEF ignored by this hit (Raiden's C2), the chain's other DEF input. */
  defIgnore: number;
  /**
   * Flat ATK per point of the hit owner's own total DEF (Noelle's Sweeping Time on herself) or
   * HP (Hu Tao's Guide to Afterlife, capped at 400% of her base ATK). One source per hit: the
   * recipe resolves one conversion into flat ATK.
   */
  atkFrom: ({ from: ConversionSource; perUnit: number; extra?: AtkPart[] } & Limits) | null;
  /** Capped self-conversions into DMG% or CRIT Rate (Nahida's, Furina's, Alhaitham's A4). */
  statConversions: StatConversion[];
  /** ATK% from the hit owner's own ER, capped: Engulfing Lightning on its wielder (§45). */
  atkPctFromEr: ({ perUnit: number } & Limits) | null;
  /** EM from the hit owner's own Max HP, each priced alone: Key of Khaj-Nisut (§45). */
  emFrom: ({ from: TripleStat; perUnit: number } & Limits)[];
  /** Base ATK, before the percentage (Mavuika's C2). */
  baseAtk: number;
  /** Added to the talent term's base-damage multiplier (GO `baseMulti`). */
  baseDmgBonus: number;
  /** A reaction's own CRIT (GO `<reaction>_critRate_`/`_critDMG_`): Nahida's C2 on bloom. */
  reactionCritRate: number;
  reactionCritDmg: number;
  /** A Lunar reaction's base DMG bonus (GO `<reaction>_baseDmg_`). */
  lunarBaseDmgBonus: number;
}

/** A capped self-conversion's threshold and cap (`recipe.ts:cappedAmount`); absent is none. */
interface Limits {
  threshold?: number;
  cap?: number;
}

/** A further conversion into flat ATK, priced on its own (`ResolvedConversion.extra`). */
type AtkPart = { from: ConversionSource; perUnit: number } & Limits;

function noBuffs(): Buffs {
  return {
    percent: { atk: 0, hp: 0, def: 0 }, em: 0, er: 0, critRate: 0, critDmg: 0, dmgBonus: 0,
    reactionBonus: 0, resistance: 0, flatDamage: 0, flatFrom: { atk: 0, hp: 0, def: 0, em: 0 },
    flatLimits: {}, erConversion: null,
    flatAtk: 0, bonusFromEm: 0, flatDef: 0, defReduction: 0, defIgnore: 0,
    atkFrom: null, statConversions: [], atkPctFromEr: null, emFrom: [], baseAtk: 0,
    baseDmgBonus: 0,
    reactionCritRate: 0, reactionCritDmg: 0, lunarBaseDmgBonus: 0,
  };
}

/** The effect's threshold and cap, only those it carries. */
function limitsOf(effect: FormulaEffect): Limits {
  return {
    ...(effect.threshold != null ? { threshold: effect.threshold } : {}),
    ...(effect.cap != null ? { cap: effect.cap } : {}),
  };
}

const isLimited = (limits: Limits): boolean =>
  limits.threshold !== undefined || limits.cap !== undefined;

/** Flat damage from the hit owner's own stat, capped or not, onto the one flat conversion. */
function addFlatFrom(
  buffs: Buffs, from: ConversionSource, amount: number, limits: Limits, source: string,
): void {
  if (isLimited(limits) || buffs.flatLimits[from] !== undefined) {
    if (buffs.flatFrom[from] !== 0) {
      throw new Error(`${source}: a capped flat-damage conversion from ${from} beside another`);
    }
    buffs.flatLimits[from] = limits;
  }
  buffs.flatFrom[from] += amount;
}

/**
 * Flat ATK from the hit owner's own DEF or HP. Two uncapped ones from the same stat sum; any
 * other pair is kept apart and each priced alone (`ResolvedConversion.extra`), so a kit's capped
 * ATK from HP and a weapon's uncapped one (Hu Tao's Paramita beside Staff of Homa, task 12) are
 * never summed before the cap binds.
 */
function addAtkFrom(
  buffs: Buffs, from: ConversionSource, amount: number, limits: Limits, _source: string,
): void {
  if (buffs.atkFrom === null) {
    buffs.atkFrom = { from, perUnit: amount, ...limits };
    return;
  }
  if (buffs.atkFrom.from === from && !isLimited(limits) && !isLimited(buffs.atkFrom)) {
    buffs.atkFrom.perUnit += amount;
    return;
  }
  const same = (buffs.atkFrom.extra ?? []).find(
    (p) => p.from === from && !isLimited(p) && !isLimited(limits),
  );
  if (same) {
    same.perUnit += amount;
    return;
  }
  buffs.atkFrom.extra = [...(buffs.atkFrom.extra ?? []), { from, perUnit: amount, ...limits }];
}

/** A conversion into DMG% or CRIT Rate, priced alone (`StatConversion`). */
function addStatConversion(
  buffs: Buffs, into: ConvertedTerm, from: ConversionSource, amount: number, limits: Limits,
): void {
  buffs.statConversions.push({ into, from, perUnit: amount, ...limits });
}

/** One hit's identity, for scoping. */
interface HitScope {
  element: string;
  move: FormulaMove | null;
  amplifying: Amplifying | null;
  /** The talent row, for a row-scoped kit buff; `null` when the row did not say. */
  hit: { talent: string; label: string } | null;
  /**
   * The reaction a `reactions`-scoped effect must name: the amplifying one, the additive one,
   * or a reaction row's own (P3). Absent is the amplifying reaction alone, as before P3.
   */
  reaction?: string | null;
  /**
   * A reaction row (P3): it is not a move or a talent row, so a move- or row-scoped effect
   * simply does not reach it — rather than being reported as unapplied for an unknown move.
   */
  reactionRow?: boolean;
  /** A proc row (§45): no move and no talent row, so move- and row-scoped effects miss it. */
  procRow?: boolean;
  /**
   * The hit owner's zero-artifact totals, for weighing a non-stacking **conversion** against
   * its rivals (owner ruling 2026-11-15): absent, a conversion is weighed by its per-unit value,
   * which compares like with like inside one GO family (every family is one stat).
   */
  zero?: Partial<Record<ConversionSource | 'er', number>>;
}

/** The stat a conversion effect reads, for weighing it at the zero-artifact build. */
const CONVERSION_READS: Record<string, ConversionSource | 'er'> = {
  dmg_bonus_from_em: 'em', dmg_bonus_from_hp: 'hp', dmg_bonus_from_def: 'def',
  crit_rate_from_em: 'em', crit_rate_from_hp: 'hp', crit_dmg_from_hp: 'hp',
  flat_damage_from_atk: 'atk', flat_damage_from_hp: 'hp', flat_damage_from_def: 'def',
  flat_damage_from_em: 'em', flat_atk_from_def: 'def', flat_atk_from_hp: 'hp',
  flat_atk_from_em: 'em', em_from_hp: 'hp', atk_pct_from_er: 'er',
  dmg_bonus_from_energy_recharge: 'er',
};

/**
 * How strong one effect is **for this row**, for the non-stacking rule (owner ruling
 * 2026-11-15, `DECISIONS.md` §47): its resolved amount — the value times its stacks and its
 * teammate count, capped — and for a conversion, the amount it gives at the hit owner's
 * zero-artifact stat (`cappedAmount`, the same reading `formula:verify` freezes), or its
 * per-unit value when that stat is not known.
 */
function strengthOf(effect: FormulaEffect, amount: number, scope: HitScope): number {
  const reads = CONVERSION_READS[effect.stat];
  const cap = effect.cap ?? undefined;
  if (reads === undefined) return cap === undefined ? amount : Math.min(amount, cap);
  const stat = scope.zero?.[reads];
  if (stat === undefined) return amount;
  return cappedAmount(amount, stat, effect.threshold ?? undefined, cap);
}

/**
 * For each GO non-stacking buff name, the source GO itself would apply — kept to say so beside
 * ours (owner ruling 2026-11-15: the stronger applies, and the divergence is named).
 *
 * GO resolves `input.nonStacking[name]` with its `small` string accumulator over every member
 * whose write condition holds (`SheetUtil.tsx:102-117`, `uiData.ts:266-276`): **the writer whose
 * character key sorts first wins**, whatever its refinement. A source writes when one of its
 * effects of that name has every `when` holding under this row's state (GO gates the write by
 * the buff's own condition). A source with no rank sorts last; a tie keeps the first. It is
 * also the tie-break of our rule.
 */
function goNonStackWinners(
  sources: readonly FormulaSource[], rowState: ConditionState, teamState: ConditionState,
): Map<string, FormulaSource> {
  const out = new Map<string, FormulaSource>();
  const LAST = String.fromCharCode(0xffff);
  const rank = (s: FormulaSource): string => s.stack_rank ?? LAST;
  for (const source of sources) {
    const conditions = conditionsBy(source);
    for (const effect of source.bonus.effects) {
      if (!effect.non_stack) continue;
      const holds = effect.when.every((w) => {
        const condition = conditions.get(w.condition);
        if (condition === undefined) throw new Error(`${source.id}: no condition ${w.condition}`);
        return w.values.some((v) => v === valueOf(`${source.id}/${w.condition}`, condition,
          rowState, teamState));
      });
      if (!holds) continue;
      const held = out.get(effect.non_stack);
      if (held === undefined || rank(source) < rank(held)) out.set(effect.non_stack, source);
    }
  }
  return out;
}

/**
 * Apply every effect of `sources` to one hit under one row's conditional state.
 *
 * Returns the buffs and the assumptions their application rests on. Scoping is GO's: an
 * effect reaches a hit when the hit's element, move and reaction are each in its lists (an
 * absent list reaches everything), the wearer's weapon class is allowed, and every `when`
 * holds. The amount is the value, times a stack or number condition (`per`, or the
 * `by_stack` row when steps are not linear), times a teammate count.
 */
export function applySources(
  sources: readonly FormulaSource[],
  scope: HitScope,
  team: FormulaTeam,
  rowState: ConditionState,
  teamState: ConditionState,
): { buffs: Buffs; skipped: string[] } {
  const buffs = noBuffs();
  const skipped: string[] = [];
  const goWinners = goNonStackWinners(sources, rowState, teamState);
  // Every effect that reaches this hit, with its resolved amount, before the non-stacking rule
  // picks among them: the rule weighs what each would give **this row** (owner ruling
  // 2026-11-15), so it runs after scoping and before anything is added.
  const reaching: {
    source: FormulaSource; effect: FormulaEffect; amount: number;
    elements: Set<string> | null;
  }[] = [];
  for (const source of sources) {
    const conditions = conditionsBy(source);
    const state = (key: string): ConditionValue => {
      const condition = conditions.get(key);
      if (condition === undefined) throw new Error(`${source.id}: no condition ${key}`);
      return valueOf(`${source.id}/${key}`, condition, rowState, teamState);
    };
    for (const effect of source.bonus.effects) {
      if (effect.weapon_types && !effect.weapon_types.includes(team.weaponType)) continue;
      if (!effect.when.every((w) => w.values.some((v) => v === state(w.condition)))) continue;
      const elements = elementsOf(effect, team, state);
      if (elements !== null && !elements.has(scope.element)) continue;
      if ((scope.reactionRow || scope.procRow) && (effect.moves || effect.rows)) continue;
      if (effect.moves) {
        if (scope.move === null) {
          skipped.push(`${source.label}: ${effect.stat} for ${effect.moves.join('/')} not `
            + 'applied — the row\'s move is unknown');
          continue;
        }
        if (!effect.moves.includes(scope.move)) continue;
      }
      if (effect.rows) {
        if (scope.hit === null) {
          skipped.push(`${source.label}: ${effect.stat} for ${effect.rows.map((r) => r.label)
            .join('/')} not applied — the row's talent row is unknown`);
          continue;
        }
        const { talent, label } = scope.hit;
        if (!effect.rows.some((r) => r.talent === talent && r.label === label)) continue;
      }
      const reaction = scope.reaction === undefined ? scope.amplifying : scope.reaction;
      if (effect.reactions && !(reaction && effect.reactions.includes(reaction))) continue;

      let amount = effect.value;
      if (effect.per) {
        const n = Number(state(effect.per));
        amount = effect.by_stack
          ? (n > 0 ? effect.by_stack[Math.min(n, effect.by_stack.length) - 1] : 0)
          : effect.value * n;
      }
      if (effect.per_team) {
        amount *= Math.min(teamCount(effect.per_team, team), effect.per_team_max ?? Infinity);
      }
      if (amount === 0 && effect.stat !== 'dmg_bonus_from_energy_recharge') continue;
      reaching.push({ source, effect, amount, elements });
    }
  }

  // GO's non-stacking families (§45), **the stronger one applying** (owner ruling 2026-11-15,
  // `DECISIONS.md` §47): per family name — GO's families are per name and each is one stat —
  // the source whose effects of that name give this row the most; a tie falls back to GO's
  // rule. GO itself applies the wielder whose character key sorts first, whatever the
  // strength, and where that differs the loser's line says so.
  const strength = new Map<string, Map<FormulaSource, number>>();
  for (const { source, effect, amount } of reaching) {
    if (!effect.non_stack) continue;
    const bySource = strength.get(effect.non_stack) ?? new Map<FormulaSource, number>();
    bySource.set(source, (bySource.get(source) ?? 0) + strengthOf(effect, amount, scope));
    strength.set(effect.non_stack, bySource);
  }
  const LAST = String.fromCharCode(0xffff);
  const winners = new Map<string, { source: FormulaSource; tie: boolean }>();
  for (const [name, bySource] of strength) {
    let best: FormulaSource | null = null;
    let tie = false;
    for (const [source, value] of bySource) {
      const held = best === null ? undefined : bySource.get(best);
      if (best === null || held === undefined || value > held + 1e-12) {
        best = source;
        tie = false;
      } else if (Math.abs(value - held) <= 1e-12) {
        tie = true;
        if ((source.stack_rank ?? LAST) < (best.stack_rank ?? LAST)) best = source;
      }
    }
    if (best !== null) winners.set(name, { source: best, tie });
  }

  for (const { source, effect, amount, elements } of reaching) {
    {
      if (effect.non_stack && winners.get(effect.non_stack)?.source !== source) {
        const { source: winner, tie } = winners.get(effect.non_stack)!;
        const go = goWinners.get(effect.non_stack);
        skipped.push(`${source.label}: ${effect.stat} not applied — ${winner.label} holds the `
          + `same non-stacking buff (${effect.non_stack}) and is `
          + (tie
            ? 'as strong; on a tie the wielder whose character key sorts first applies, as in '
              + 'Genshin Optimizer'
            : 'stronger; the stronger applies (owner ruling 2026-11-15)')
          + (go && go !== winner
            ? `. Genshin Optimizer would apply ${go.label}'s, its wielder's character key `
              + 'sorting first'
            : ''));
        continue;
      }
      if ((effect.stat === 'dmg_bonus_from_em' || effect.stat === 'dmg_bonus_from_hp'
        || effect.stat === 'dmg_bonus_from_def')
        && elements === null && !effect.moves && !effect.rows) {
        // Not reachable from a sheet (Kazuha's A4 names its element, Alhaitham's and
        // Tighnari's their moves, Nahida's and Furina's their rows); refused rather than read as
        // "every hit", which would be the confident wrong number.
        throw new Error(`${source.id}: a DMG% conversion names the element, move or row it reaches`);
      }
      const limits = limitsOf(effect);

      switch (effect.stat) {
        case 'atk_pct': buffs.percent.atk += amount; break;
        case 'hp_pct': buffs.percent.hp += amount; break;
        case 'def_pct': buffs.percent.def += amount; break;
        case 'elemental_mastery': buffs.em += amount; break;
        case 'energy_recharge': buffs.er += amount; break;
        case 'crit_rate': buffs.critRate += amount; break;
        case 'crit_dmg': buffs.critDmg += amount; break;
        case 'dmg_bonus': buffs.dmgBonus += amount; break;
        case 'reaction_bonus': buffs.reactionBonus += amount; break;
        case 'enemy_res': buffs.resistance += amount; break;
        case 'flat_damage': buffs.flatDamage += amount; break;
        case 'flat_damage_from_atk': addFlatFrom(buffs, 'atk', amount, limits, source.id); break;
        case 'flat_damage_from_hp': addFlatFrom(buffs, 'hp', amount, limits, source.id); break;
        case 'flat_damage_from_def': addFlatFrom(buffs, 'def', amount, limits, source.id); break;
        case 'flat_damage_from_em': addFlatFrom(buffs, 'em', amount, limits, source.id); break;
        case 'flat_atk': buffs.flatAtk += amount; break;
        case 'dmg_bonus_from_em':
          // Uncapped (Kazuha's A4) stays the plain per-EM term; capped or thresholded is priced
          // alone, so two caps are never summed before they bind.
          if (isLimited(limits)) addStatConversion(buffs, 'bonusDmg', 'em', amount, limits);
          else buffs.bonusFromEm += amount;
          break;
        case 'dmg_bonus_from_hp': addStatConversion(buffs, 'bonusDmg', 'hp', amount, limits); break;
        case 'crit_rate_from_em':
          addStatConversion(buffs, 'critRate', 'em', amount, limits);
          break;
        // CRIT from the hit owner's own Max HP, each capped alone (Nilou's, Sigewinne's C6).
        case 'crit_rate_from_hp': addStatConversion(buffs, 'critRate', 'hp', amount, limits); break;
        case 'crit_dmg_from_hp': addStatConversion(buffs, 'critDmg', 'hp', amount, limits); break;
        // Not a stat: the row's multiplier is swapped for the raised one before this runs
        // (`raiseRow`, `DECISIONS.md` §42).
        case 'talent_level': break;
        case 'flat_def': buffs.flatDef += amount; break;
        case 'def_reduction': buffs.defReduction += amount; break;
        case 'def_ignore': buffs.defIgnore += amount; break;
        case 'flat_atk_from_def': addAtkFrom(buffs, 'def', amount, limits, source.id); break;
        case 'flat_atk_from_hp': addAtkFrom(buffs, 'hp', amount, limits, source.id); break;
        // The wielder conversions #389 withheld (owner approval 2026-11-14, §45).
        case 'flat_atk_from_em': addAtkFrom(buffs, 'em', amount, limits, source.id); break;
        case 'dmg_bonus_from_def':
          addStatConversion(buffs, 'bonusDmg', 'def', amount, limits);
          break;
        case 'em_from_hp': buffs.emFrom.push({ from: 'hp', perUnit: amount, ...limits }); break;
        case 'atk_pct_from_er':
          if (buffs.atkPctFromEr) throw new Error(`${source.id}: two ATK% from ER conversions`);
          buffs.atkPctFromEr = { perUnit: amount, ...limits };
          break;
        case 'base_atk': buffs.baseAtk += amount; break;
        case 'base_dmg_bonus': buffs.baseDmgBonus += amount; break;
        case 'reaction_crit_rate': buffs.reactionCritRate += amount; break;
        case 'reaction_crit_dmg': buffs.reactionCritDmg += amount; break;
        case 'lunar_base_dmg_bonus': buffs.lunarBaseDmgBonus += amount; break;
        case 'dmg_bonus_from_energy_recharge':
          if (buffs.erConversion) throw new Error('two Energy Recharge conversions on one hit');
          buffs.erConversion = { perUnit: amount, cap: effect.cap ?? 0 };
          break;
        default:
          // A stat this module does not know is refused, not dropped: dropping it would be
          // the silent zero this whole feature exists to remove.
          throw new Error(`${source.id}: unknown effect stat ${effect.stat}`);
      }
    }
  }
  return { buffs, skipped };
}

const elementOfQuantity = (quantity: string): string => quantity.replace(/_dmg_bonus$/, '');

/** The hit owner's totals at zero artifacts, for weighing a non-stacking conversion. */
function zeroTotals(
  base: Record<string, number | undefined>,
): Record<ConversionSource | 'er', number> {
  const b = (q: string): number => base[q] ?? 0;
  const total = (s: 'atk' | 'hp' | 'def'): number =>
    b(`base_${s}`) * (1 + b(`${s}_pct`)) + b(`flat_${s}`);
  return {
    atk: total('atk'), hp: total('hp'), def: total('def'),
    em: b('elemental_mastery'), er: b('energy_recharge'),
  };
}

/**
 * The recipe entries for one row under one set of sources.
 *
 * One entry per scaling term (see the module docstring); the count folded into `talent` and
 * `flatDamage`. Every term is the kernel's: `search.ts:score` sums the same pools, and
 * `damage.ts:computeDamage` multiplies the same factors.
 */
export function rowHits(
  row: FormulaRow,
  sources: readonly FormulaSource[],
  team: FormulaTeam,
  teamState: ConditionState,
  procRow = false,
): { hits: RecipeHit[]; skipped: string[] } {
  if (!(row.count > 0)) throw new Error(`row ${row.id}: a count must be positive`);
  if (row.reaction) return reactionRowHits(row, row.reaction, sources, team, teamState);
  if (row.proc) return procRowHits(row, row.proc, sources, team, teamState);
  const { base, hit, target, characterLevel, dmgBonusQuantity } = row.context;
  const element = elementOfQuantity(dmgBonusQuantity);
  const additive = additiveOf(row, element, hit.amplifying);
  const { buffs, skipped } = applySources(
    sources, {
      element, move: row.move, amplifying: hit.amplifying, hit: row.hit ?? null,
      reaction: hit.amplifying ?? additive?.reaction ?? null, procRow,
      zero: zeroTotals(base),
    }, team, row.conditionals ?? {}, teamState,
  );
  const flatSources = (Object.keys(buffs.flatFrom) as ConversionSource[])
    .filter((from) => buffs.flatFrom[from] !== 0);
  const converted = flatSources.length > 0;
  if (flatSources.length > 1) {
    // One resolved conversion per flat term (`recipe.ts:ResolvedConversion`).
    throw new Error(
      `row ${row.id}: flat damage converted from ${flatSources.join(' and ')} on one hit`,
    );
  }
  if (converted && (hit.flatDamage !== 0 || buffs.flatDamage !== 0)) {
    // `resolvedTerm` replaces a converted flat term wholesale, so both cannot ride on one.
    throw new Error(`row ${row.id}: a constant flat term and an ATK conversion on one hit`);
  }
  const b = (q: string): number => base[q] ?? 0;
  const calibratedBase = {
    atk: b('base_atk') + buffs.baseAtk, hp: b('base_hp'), def: b('base_def'),
  };
  const calibratedPercent = {
    atk: b('atk_pct') + buffs.percent.atk,
    hp: b('hp_pct') + buffs.percent.hp,
    def: b('def_pct') + buffs.percent.def,
  };
  const calibratedFlat = {
    atk: b('flat_atk') + buffs.flatAtk, hp: b('flat_hp'), def: b('flat_def') + buffs.flatDef,
  };
  const calibratedEm = b('elemental_mastery') + buffs.em;
  const reactionBonus = hit.reactionBonus + buffs.reactionBonus;

  if (buffs.baseDmgBonus !== 0 && (hit.extraTerms ?? []).length > 0) {
    // Which terms a base multiplier reaches on a mixed-stat hit is not something any sheet
    // has needed to say; refused rather than guessed.
    throw new Error(`row ${row.id}: a base-damage multiplier on a mixed-stat hit`);
  }
  const terms: { stat: ScalingStat; multiplier: number }[] = [
    {
      stat: hit.scalingStat,
      multiplier: hit.multiplier * (1 + hit.baseDamageBonus + buffs.baseDmgBonus),
    },
    ...(hit.extraTerms ?? []),
  ];
  // ATK from the hit owner's own DEF or HP lands in flat ATK beside its constants, resolved per
  // candidate (`recipe-eval.ts:resolvedTerm`), so every ATK-scaling term reads it — capped
  // where the kit caps it (Hu Tao's 400% of base ATK, `recipe.ts:cappedAmount`).
  const atkFrom = buffs.atkFrom !== null
    ? { ...buffs.atkFrom, offset: calibratedFlat.atk }
    : null;
  // The count folds into a flat conversion's slope **and** its cap: `n × min(k × s, c)` is
  // `min(n × k × s, n × c)`. A threshold is on the stat, so it does not scale.
  const flatLimits = converted ? buffs.flatLimits[flatSources[0]] ?? {} : {};
  const flatConversion = converted
    ? {
      from: flatSources[0],
      perUnit: buffs.flatFrom[flatSources[0]] * row.count,
      ...(flatLimits.threshold !== undefined ? { threshold: flatLimits.threshold } : {}),
      ...(flatLimits.cap !== undefined ? { cap: flatLimits.cap * row.count } : {}),
    }
    : null;
  const zeroTotal = (from: ConversionSource): number => (from === 'em'
    ? calibratedEm
    : calibratedBase[from] * (1 + calibratedPercent[from]) + calibratedFlat[from]);
  const hits = terms.map((term, i): RecipeHit => {
    const scaling = RECIPE_SCALING[term.stat];
    const total = scaling === 'em'
      ? calibratedEm
      : calibratedBase[scaling] * (1 + calibratedPercent[scaling]) + calibratedFlat[scaling]
        + (scaling === 'atk' && atkFrom
          ? cappedAmount(atkFrom.perUnit, zeroTotal(atkFrom.from), atkFrom.threshold, atkFrom.cap)
            + (atkFrom.extra ?? []).reduce((sum, p) => sum
              + cappedAmount(p.perUnit, zeroTotal(p.from), p.threshold, p.cap), 0)
          : 0);
    const flatDamage = i === 0 ? (hit.flatDamage + buffs.flatDamage) * row.count : 0;
    const out: RecipeHit = {
      abil: terms.length > 1 ? `${row.label} [${term.stat}]` : row.label,
      mine: true,
      owner: 0,
      attackTag: row.move === null ? -1 : ATTACK_TAG[row.move],
      element,
      talent: term.multiplier * row.count,
      scaling,
      flatDamage,
      conversions: {
        ...(i === 0 && flatConversion ? { flatDamage: flatConversion } : {}),
        ...(atkFrom ? { flatAtk: atkFrom } : {}),
      },
      constantTerms: [],
      calibratedScaling: total,
      calibratedBase,
      calibratedPercent,
      calibratedFlat,
      calibratedEm,
      bonusDmg: b(dmgBonusQuantity) + buffs.dmgBonus,
      critRate: b('crit_rate') + buffs.critRate,
      critDmg: b('crit_dmg') + buffs.critDmg,
      // A kit's DEF reduction and DEF ignore add to the target's own, into the same term
      // (`damage.ts:defMultiplier`, capped there as GO `enemy.def` and gcsim cap them).
      defMultiplier: defMultiplier(
        characterLevel, target.level, target.defReduction + buffs.defReduction,
        target.defIgnore + buffs.defIgnore,
      ),
      resMultiplier: resMultiplier(target.resistance + buffs.resistance),
      ampMultiplier: hit.amplifying === null
        ? 1
        : amplifyingMultiplier(hit.amplifying, calibratedEm, reactionBonus),
      gcsimAverageDamage: 0,
    };
    if (hit.amplifying !== null) out.amplifying = { reaction: hit.amplifying, reactionBonus };
    // The additive flat rides on the first term, as the hit's own flat damage does.
    if (additive && i === 0) out.additive = { ...additive, reactionBonus, count: row.count };
    if (row.move !== null) out.move = row.move;
    if (buffs.bonusFromEm !== 0) out.bonusFromEm = buffs.bonusFromEm;
    if (buffs.statConversions.length > 0) {
      out.statConversions = buffs.statConversions.map((c) => ({ ...c }));
    }
    if (buffs.erConversion) {
      out.bonusFromEnergyRecharge = {
        ...buffs.erConversion, calibratedEnergyRecharge: b('energy_recharge') + buffs.er,
      };
    }
    // The wielder conversions (owner approval 2026-11-14, §45), each per candidate.
    if (buffs.atkPctFromEr) {
      out.atkPercentFromEnergyRecharge = {
        ...buffs.atkPctFromEr, calibratedEnergyRecharge: b('energy_recharge') + buffs.er,
      };
    }
    if (buffs.emFrom.length > 0) out.emFrom = buffs.emFrom.map((c) => ({ ...c }));
    if (buffs.atkPctFromEr || buffs.emFrom.length > 0) {
      // The zero-artifact total the replay reads, now that a conversion moves it.
      out.calibratedScaling = scaling === 'em' ? emTotal(out, NO_STATS)
        : totalFor(out, NO_STATS, scaling);
    }
    // **What this hit deals at zero artifacts**, under the name the recipe type gives it. On a
    // synthetic recipe nothing was simulated; consumers that freeze a teammate's hit at this
    // value never see one, because every formula hit is `mine`.
    out.gcsimAverageDamage = evaluateHit(out, NO_STATS);
    return out;
  });
  return { hits, skipped };
}

// ── Reactions (math-fallback P3, task 13) ─────────────────────────────────────────────────
//
// Kept apart from `rowHits` on purpose: a reaction row shares nothing with a talent row but its
// context, and the additive term is one optional field on a talent row's hit.

/** The level multiplier a reaction row or an additive hit needs, or a refusal naming it. */
function levelBaseOf(row: FormulaRow): number {
  const value = row.context.reactionLevelMultiplier;
  if (value === undefined || !(value > 0)) {
    throw new Error(`row ${row.id}: no reaction level multiplier for the trigger's level`);
  }
  return value;
}

/** A talent row's additive reaction, checked against the hit's element. */
function additiveOf(
  row: FormulaRow, element: string, amplifying: Amplifying | null,
): { reaction: Additive; levelBase: number } | null {
  if (!row.additive) return null;
  const wanted = ADDITIVE[row.additive].element;
  if (element !== wanted) {
    throw new Error(`row ${row.id}: ${row.additive} is triggered by a ${wanted} hit, not ${element}`);
  }
  if (amplifying !== null) {
    throw new Error(`row ${row.id}: a hit amplifies or catalyzes, not both`);
  }
  return { reaction: row.additive, levelBase: levelBaseOf(row) };
}

const isTransformative = (r: string): r is Transformative => r in TRANSFORMATIVE;
const isLunar = (r: string): r is Lunar => r in LUNAR;

/** The display name of a reaction row, `swirl` with its element. */
export function reactionLabel(reaction: FormulaReaction): string {
  const name = reaction.reaction.replace(/_/g, ' ');
  return reaction.swirled ? `${name} (${reaction.swirled})` : name;
}

/**
 * One reaction row's recipe entry: `count` instances triggered by the optimized character.
 *
 * What reaches it is what reaches reaction damage in GO and gcsim and nothing else: EM, a bonus
 * naming this reaction, a RES shred on its element, the reaction's own CRIT (transformative,
 * only where it can crit) or the character's CRIT and a base DMG bonus (Lunar). A DMG%, an ATK%
 * or a move-scoped buff is computed and ignored — reaction damage takes none of them
 * (`reactions.py`).
 */
export function reactionRowHits(
  row: FormulaRow,
  reaction: FormulaReaction,
  sources: readonly FormulaSource[],
  team: FormulaTeam,
  teamState: ConditionState,
): { hits: RecipeHit[]; skipped: string[] } {
  const { base, target } = row.context;
  const name = reaction.reaction;
  let element: string;
  if (isTransformative(name)) {
    element = transformativeElement(name, reaction.swirled);
  } else if (isLunar(name)) {
    if (reaction.swirled) throw new Error(`row ${row.id}: only a swirl takes an element`);
    element = LUNAR[name].element;
  } else {
    throw new Error(`row ${row.id}: ${String(name)} is not a reaction the estimate prices`);
  }
  const levelBase = levelBaseOf(row);
  const { buffs, skipped } = applySources(
    sources, {
      element, move: null, amplifying: null, hit: null, reaction: name, reactionRow: true,
    }, team, row.conditionals ?? {}, teamState,
  );
  const b = (q: string): number => base[q] ?? 0;
  const calibratedEm = b('elemental_mastery') + buffs.em;
  let term: ReactionTerm;
  if (isTransformative(name)) {
    if (!TRANSFORMATIVE[name].crittable && (buffs.reactionCritRate || buffs.reactionCritDmg)) {
      throw new Error(`row ${row.id}: ${name} cannot crit, and a source gave it a CRIT`);
    }
    term = {
      kind: 'transformative', reaction: name, levelBase, reactionBonus: buffs.reactionBonus,
      critRate: buffs.reactionCritRate, critDmg: buffs.reactionCritDmg, count: row.count,
    };
  } else {
    const weight = reaction.weight ?? LUNAR_SOLO_WEIGHT;
    if (!(weight > 0 && weight <= 1)) throw new Error(`row ${row.id}: a weight is in (0, 1]`);
    term = {
      kind: 'lunar', reaction: name as Lunar, levelBase, reactionBonus: buffs.reactionBonus,
      baseDmgBonus: buffs.lunarBaseDmgBonus, weight, count: row.count,
    };
  }
  const zero = { atk: 0, hp: 0, def: 0 };
  const out: RecipeHit = {
    abil: row.label,
    mine: true,
    owner: 0,
    attackTag: -1,
    element,
    talent: 0,
    scaling: 'em',
    flatDamage: 0,
    conversions: {},
    constantTerms: [],
    calibratedScaling: calibratedEm,
    calibratedBase: zero,
    calibratedPercent: zero,
    calibratedFlat: zero,
    calibratedEm,
    bonusDmg: 0,
    // The character's CRIT, read only by a Lunar reaction (a transformative one crits with its
    // own, in the term).
    critRate: b('crit_rate') + buffs.critRate,
    critDmg: b('crit_dmg') + buffs.critDmg,
    // DEF is ignored by every reaction here (gcsim `IgnoreDefPercent: 1`).
    defMultiplier: 1,
    resMultiplier: resMultiplier(target.resistance + buffs.resistance),
    ampMultiplier: 1,
    gcsimAverageDamage: 0,
    reaction: term,
  };
  // EM converted from Max HP (Key of Khaj-Nisut on its wielder, §45) reaches reaction damage.
  if (buffs.emFrom.length > 0) {
    out.emFrom = buffs.emFrom.map((c) => ({ ...c }));
    out.calibratedBase = {
      atk: b('base_atk') + buffs.baseAtk, hp: b('base_hp'), def: b('base_def'),
    };
    out.calibratedPercent = {
      atk: b('atk_pct') + buffs.percent.atk, hp: b('hp_pct') + buffs.percent.hp,
      def: b('def_pct') + buffs.percent.def,
    };
    out.calibratedFlat = {
      atk: b('flat_atk') + buffs.flatAtk, hp: b('flat_hp'), def: b('flat_def') + buffs.flatDef,
    };
    out.calibratedScaling = emTotal(out, NO_STATS);
  }
  out.gcsimAverageDamage = evaluateHit(out, NO_STATS);
  return { hits: [out], skipped };
}

/**
 * One proc row's recipe entries (owner approval 2026-11-14, `DECISIONS.md` §45): `count`
 * instances of the subject's weapon's own damage instance.
 *
 * Priced as a talent hit of the proc's multiplier on ATK in the proc's element, through the
 * same `rowHits` — so DMG% for that element and every channel, CRIT, DEF, RES and every ATK
 * buff reach it exactly as they reach a talent hit — with no move and no talent row, so a
 * move- or row-scoped buff does not (GO `customDmgNode(…, 'elemental', {hit: {ele}})`,
 * `dataUtil.tsx:113-138`; gcsim `AttackTagWeaponSkill`). A proc of a weapon the run does not
 * carry — another weapon in a comparison — deals nothing, and the estimate says so.
 */
export function procRowHits(
  row: FormulaRow,
  ref: { source: string; key: string },
  sources: readonly FormulaSource[],
  team: FormulaTeam,
  teamState: ConditionState,
): { hits: RecipeHit[]; skipped: string[] } {
  const source = sources.find((s) => s.id === ref.source);
  const proc = source?.procs?.find((p) => p.key === ref.key);
  if (source === undefined || proc === undefined) {
    return {
      hits: [],
      skipped: [`${row.label}: not dealt — the optimized character's weapon in this run has no `
        + `such proc (${ref.source} ${ref.key})`],
    };
  }
  const synthetic: FormulaRow = {
    ...row,
    proc: null, reaction: null, additive: null, move: null, hit: null,
    context: {
      ...row.context,
      hit: {
        multiplier: proc.multiplier, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0,
        amplifying: null, reactionBonus: 0, extraTerms: [],
      },
      dmgBonusQuantity: `${proc.element}_dmg_bonus`,
    },
  };
  return rowHits(synthetic, sources, team, teamState, true);
}

/** The assumption sentences a target's proc rows add (§45). */
export function procAssumptions(
  rows: readonly FormulaRow[], sources: readonly FormulaSource[], subject: string,
): string[] {
  const who = subject || 'the optimized character';
  const out: string[] = [];
  for (const row of rows) {
    if (!row.proc) continue;
    const proc = sources.find((s) => s.id === row.proc?.source)?.procs
      ?.find((p) => p.key === row.proc?.key);
    if (proc === undefined) continue;
    out.push(`${row.count}× ${proc.label} dealt by ${who}: the count is your assumption (no `
      + `proc chance, cooldown or uptime is simulated); ${proc.multiplier * 100}% ATK, `
      + `${proc.element}, no move-scoped bonus.`);
    if (proc.stat_layer === 'premod') {
      out.push(`${proc.label}: Genshin Optimizer reads the wielder's pre-conversion ATK here; `
        + 'the estimate reads total ATK, which differs only when an ATK-from-another-stat '
        + 'buff is in play.');
    }
  }
  return out;
}

/**
 * The assumption sentences a target's reactions add: what each row counts, who triggers it,
 * and the recorded divergences from GO and gcsim (`reactions.py`).
 */
export function reactionAssumptions(rows: readonly FormulaRow[], subject: string): string[] {
  const reactionRows = rows.filter((r) => r.reaction);
  const additiveRows = rows.filter((r) => r.additive);
  if (!reactionRows.length && !additiveRows.length) {
    return ['No reaction rows: transformative, additive and Lunar reaction damage is not counted '
      + '(add a reaction row, or spread/aggravate on an ability).'];
  }
  const who = subject || 'the optimized character';
  const out: string[] = [];
  for (const row of reactionRows) {
    out.push(`${row.count}× ${reactionLabel(row.reaction!)} triggered by ${who}: the count is your `
      + `assumption (no gauge or ICD is simulated); ${who}'s EM and level apply.`);
  }
  for (const row of additiveRows) {
    out.push(`${row.label}: every hit counted as ${row.additive} (${row.count}×), triggered by ${who}.`);
  }
  if (reactionRows.some((r) => isTransformative(r.reaction!.reaction))) {
    out.push('Transformative reactions ignore DEF, as gcsim does; Genshin Optimizer\'s DEF term '
      + 'for them is about 1 - 1e-5, a recorded divergence.');
  }
  if (reactionRows.some((r) => isLunar(r.reaction!.reaction))) {
    out.push(`Lunar reactions: ${who}'s own contribution at gcsim's solo weight 0.6 (gcsim ranks `
      + 'every contributor 0.6/0.3/0.05/0.05); Genshin Optimizer prices the whole contribution, '
      + 'a recorded divergence.');
  }
  return out;
}

/**
 * Why a condition's default is what it is, in words: its curated note where it has one (a kit
 * condition's usual value and its source, or why it stays off), else the rule's reason.
 * `who` names who triggers a `self` condition: the wearer of a set, or a kit's character.
 */
export function defaultWhy(condition: FormulaCondition, who = 'the wearer triggers it'): string {
  if (condition.default_note) return condition.default_note;
  switch (condition.default_reason) {
    case 'self': return who;
    case 'teammate': return 'a teammate\'s buff, assumed up as they play it';
    case 'usual': return 'its usual value';
    default: return 'depends on the situation';
  }
}

/** The sentence a condition's current value becomes in the assumptions list. */
function describe(
  source: FormulaSource, condition: FormulaCondition, value: ConditionValue,
): string {
  const shown = condition.kind === 'toggle'
    ? (value ? 'on' : 'off')
    : condition.kind === 'choice' ? (value === '' ? 'none' : String(value)) : String(value);
  const why = value === condition.default ? `default — ${defaultWhy(condition)}` : 'set by you';
  return `${source.label}: ${condition.label} = ${shown} (${why})`;
}

/**
 * The assumption sentences about kits. Without coverage (P1 callers) the estimate models none;
 * with it, it names whose sheet is applied, whether each is verified, and who has none.
 */
export function kitAssumptions(coverage: KitCoverage | undefined): string[] {
  if (coverage === undefined) {
    return ['No kit buffs modelled: talents, passives, constellations and teammates\' buffs '
      + 'are absent.'];
  }
  const out: string[] = [];
  for (const giver of coverage.modelled) {
    out.push(`Kit buffs from ${giver.name}: ${giver.verified
      ? 'verified against Genshin Optimizer' : 'unverified (cited to Genshin Optimizer)'}.`);
  }
  for (const name of coverage.missing) out.push(`No kit buffs modelled for ${name}.`);
  return out;
}

/**
 * The assumption sentences about weapon passives (task 12): whose are applied, whether each is
 * verified, and which members' weapons have no passive data — those contribute their base ATK
 * and substat only.
 */
export function weaponAssumptions(coverage: KitCoverage | undefined): string[] {
  const weapons = coverage?.weapons;
  if (weapons === undefined) return ['No weapon passives modelled.'];
  const out: string[] = [];
  for (const w of weapons.modelled) {
    // A teammate's Homa or Aquila: every part is the wielder's own (found driving it).
    if (w.inert) {
      out.push(`${w.name}: no damage effect on the optimized character (the wielder's own).`);
      continue;
    }
    out.push(`Weapon passive ${w.name}: ${w.verified
      ? 'verified against Genshin Optimizer' : 'unverified (cited to Genshin Optimizer)'}.`);
  }
  for (const name of weapons.missing) {
    out.push(`No weapon passive modelled for ${name}: base ATK and substat only.`);
  }
  return out;
}

// ── A kit's talent-level raise (owner approval 2026-11-14, `DECISIONS.md` §42) ─────────────

const TALENT_NAME: Record<string, string> = {
  normal_attack: 'Normal Attack', elemental_skill: 'Elemental Skill',
  elemental_burst: 'Elemental Burst',
};

/**
 * A row read at the level the team's kits raise its talent to: Tartaglia's +1 Normal Attack,
 * Skirk's +1 Elemental Skill, Lohen's High Spirits.
 *
 * Every `talent_level` effect whose `when` holds **for this row** and whose talent is the row's
 * own is summed (the order is a sum: stored + constellation + kits, as GO and gcsim add them),
 * and the row's multiplier — and a mixed-stat row's other terms — are replaced by the ones
 * `raised` publishes at that raise, from the same parse `/search-context` used. Nothing else in
 * the row changes. A raise this row cannot take is never guessed at: an unknown talent row, a
 * raise past the table's last level, or no published row each leave the row unraised and say so.
 */
export function raiseRow(
  row: FormulaRow,
  sources: readonly FormulaSource[],
  teamState: ConditionState,
  raised: readonly FormulaRaisedTalent[] = [],
): { row: FormulaRow; notes: string[] } {
  const notes: string[] = [];
  let total = 0;
  const by: string[] = [];
  for (const source of sources) {
    const conditions = conditionsBy(source);
    for (const effect of source.bonus.effects) {
      if (effect.stat !== 'talent_level') continue;
      const holds = effect.when.every((w) => {
        const condition = conditions.get(w.condition);
        if (condition === undefined) throw new Error(`${source.id}: no condition ${w.condition}`);
        const value = valueOf(`${source.id}/${w.condition}`, condition, row.conditionals ?? {},
          teamState);
        return w.values.some((v) => v === value);
      });
      if (!holds) continue;
      const talent = effect.talent ?? '';
      if (!row.hit) {
        notes.push(`${source.label}: ${TALENT_NAME[talent] ?? talent} level +${effect.value} not `
          + `applied to ${row.label} — the row's talent row is unknown`);
        continue;
      }
      if (talent !== row.hit.talent) continue;
      total += effect.value;
      by.push(`${source.label.replace(/ \(kit\)$/, '')} +${effect.value}`);
    }
  }
  if (total === 0 || !row.hit) return { row, notes };
  const name = TALENT_NAME[row.hit.talent] ?? row.hit.talent;
  const talent = raised.find((t) => t.talent === row.hit?.talent);
  const index = row.hit.index ?? 0;
  const entry = talent?.rows.find((r) => r.label === row.hit?.label && r.index === index
    && r.raise_by === total);
  if (talent === undefined || entry === undefined) {
    const why = talent?.unavailable.find((u) => u.raise_by === total)?.reason
      ?? 'no row was published at that level';
    notes.push(`${row.label}: ${name} +${total} (${by.join(', ')}) not applied — ${why}`);
    return { row, notes };
  }
  if (entry.scaling_stat !== row.context.hit.scalingStat) {
    notes.push(`${row.label}: ${name} +${total} not applied — the raised row scales off `
      + `${entry.scaling_stat}, the row off ${row.context.hit.scalingStat}`);
    return { row, notes };
  }
  notes.push(`${row.label}: ${name} read at level ${talent.level + total} `
    + `(${talent.level} + ${by.join(', ')})`);
  return {
    row: {
      ...row,
      context: {
        ...row.context,
        hit: {
          ...row.context.hit,
          multiplier: entry.multiplier,
          extraTerms: entry.extra_terms.map((t) => ({
            stat: t.stat as ScalingStat, multiplier: t.multiplier,
          })),
        },
      },
    },
    notes,
  };
}

/** One recipe for one 4-piece state (or none), over every row. */
export function synthesizeRecipe(
  rows: readonly FormulaRow[],
  sources: readonly FormulaSource[],
  team: FormulaTeam,
  teamState: ConditionState = {},
  characters: string[] = [],
  kits?: KitCoverage,
  raised: readonly FormulaRaisedTalent[] = [],
): Recipe {
  if (rows.length === 0) throw new Error('a formula target needs at least one row');
  const ids = new Set(rows.map((r) => r.id));
  if (ids.size !== rows.length) throw new Error('row ids repeat');

  const hits: RecipeHit[] = [];
  const assumptions = new Set<string>([
    'Formula estimate: no simulation. Not calibrated by gcsim.',
    ...kitAssumptions(kits),
    ...weaponAssumptions(kits),
    ...reactionAssumptions(rows, characters[0] ?? ''),
    ...procAssumptions(rows, sources, characters[0] ?? ''),
  ]);
  for (const row of rows) {
    const lifted = raiseRow(row, sources, teamState, raised);
    lifted.notes.forEach((s) => assumptions.add(s));
    const made = rowHits(lifted.row, sources, team, teamState);
    hits.push(...made.hits);
    made.skipped.forEach((s) => assumptions.add(s));
    for (const source of sources) {
      for (const condition of source.bonus.conditions) {
        const value = valueOf(
          `${source.id}/${condition.key}`, condition, row.conditionals ?? {}, teamState,
        );
        const sentence = describe(source, condition, value);
        assumptions.add(rows.length > 1 && row.conditionals?.[`${source.id}/${condition.key}`]
          !== undefined ? `${row.label} — ${sentence}` : sentence);
      }
    }
  }
  for (const source of sources) {
    for (const part of source.bonus.unmodelled) {
      assumptions.add(`${source.label}: not applied — ${part.what} (${part.reason})`);
    }
  }

  const formula: FormulaProvenance = {
    kind: 'formula-estimate',
    comparator: 'genshin-optimizer',
    assumptions: [...assumptions],
    rows: rows.map((r) => ({ id: r.id, label: r.label, count: r.count, move: r.move })),
    sources: sources.map((s) => `${s.label}: ${s.citation}`),
  };
  return {
    hits,
    seed: 'formula',
    meta: {
      seed: 'formula',
      staleConversions: [],
      unstable: [],
      characters,
      // Empty: the static tiers of every set, the recipe's own 4-piece included, are left to
      // the search's set pools, and the conditional tier is in the hits. Nothing is in both.
      calibratedSetIds: [],
      minimumEnergyRecharge: null,
      formula,
    },
  };
}

const setSource = (tier: FormulaSetTier): FormulaSource => ({
  id: `set:${tier.set_id}:${tier.pieces}`,
  label: `${tier.set_name} ${tier.pieces}pc`,
  bonus: tier.bonus,
  citation: tier.citation,
});

/** `kit:<slug>`, in the shape `synthesizeRecipe` takes. */
export const kitSource = (k: FormulaKit): FormulaSource => ({
  id: k.id,
  label: k.label,
  bonus: k.bonus,
  citation: k.citation,
  // A weapon's non-stacking tie-break and its procs (§45); absent on a kit.
  ...(k.stack_rank ? { stack_rank: k.stack_rank } : {}),
  ...(k.procs?.length ? { procs: k.procs } : {}),
});

/** `resonance:<key>`, in the shape `synthesizeRecipe` takes. */
export const resonanceSource = (r: FormulaResonance): FormulaSource => ({
  id: `resonance:${r.key}`,
  label: r.name,
  bonus: r.bonus,
  citation: r.citation,
});

/**
 * A conditional 2-piece as a stat pool, under the team-level conditionals.
 *
 * A pool is row-independent, so a 2-piece cannot take per-row overrides; every one of the
 * nine is a move-scoped or all-channel DMG bonus (`set_effects.json`), which is exactly what a
 * pool can say. Anything else is refused rather than approximated.
 */
function twoPiecePool(
  tier: FormulaSetTier, team: FormulaTeam, teamState: ConditionState,
): SetBonus | null {
  const source = setSource(tier);
  const conditions = conditionsBy(source);
  const stats: Record<string, number> = {};
  for (const effect of tier.bonus.effects) {
    if (effect.stat !== 'dmg_bonus' || effect.elements || effect.element_from || effect.per) {
      throw new Error(`${source.id}: a 2-piece pool carries only a move or all-channel DMG bonus`);
    }
    if (effect.weapon_types && !effect.weapon_types.includes(team.weaponType)) continue;
    const holds = effect.when.every((w) => {
      const condition = conditions.get(w.condition)!;
      return w.values.includes(valueOf(`${source.id}/${w.condition}`, condition, {}, teamState));
    });
    if (!holds) continue;
    for (const quantity of effect.moves
      ? effect.moves.map((m) => `${FORMULA_MOVE_BONUS_PREFIX}${m}`)
      : [FORMULA_ALL_DMG_BONUS]) {
      stats[quantity] = (stats[quantity] ?? 0) + effect.value;
    }
  }
  return Object.keys(stats).length
    ? { setId: tier.set_id, piecesRequired: tier.pieces, stats }
    : null;
}

/**
 * The whole recipe set a formula search runs on: one recipe per 4-piece state the inventory
 * can reach, and the conditional 2-pieces as pools.
 *
 * A 4-piece whose tier is `stale` or `uncurated` is **withheld**, so `searchRecipe` reports
 * it as uncovered — the same treatment a set gcsim could not calibrate gets — rather than
 * scored as if its bonus were nothing. A tier that is `unmodelled` or has no damage effect is
 * scored with the parts it has (none), and its recipe says what is missing.
 */
export function synthesizeRecipeSet(input: FormulaInput): FormulaRecipeSet {
  const teamState = input.conditionals ?? {};
  const resonances = input.resonances.map(resonanceSource);
  const recipe = (extra: FormulaSource[]) => synthesizeRecipe(
    input.rows, [...resonances, ...extra], input.team, teamState, input.characters ?? [],
  );
  const fourPiece = new Map(
    input.setTiers.filter((t) => t.pieces === 4).map((t) => [t.set_id, t]),
  );

  const byFourPieceSet = new Map<number, Recipe>();
  const withheld: { setId: number; reason: string }[] = [];
  for (const setId of input.fourPieceSetIds) {
    const tier = fourPiece.get(setId);
    if (tier === undefined) {
      // No conditional 4-piece: a static one is in the pools already, so the state is the
      // no-set recipe plus whatever the pools add.
      byFourPieceSet.set(setId, recipe([]));
    } else if (tier.status === 'stale' || tier.status === 'uncurated') {
      withheld.push({ setId, reason: tier.problem ?? tier.status });
    } else {
      byFourPieceSet.set(setId, recipe([setSource(tier)]));
    }
  }

  const setBonuses = input.setTiers
    .filter((t) => t.pieces === 2 && t.status !== 'stale' && t.status !== 'uncurated')
    .map((t) => twoPiecePool(t, input.team, teamState))
    .filter((b): b is SetBonus => b !== null);

  return { recipes: { noFourPiece: recipe([]), byFourPieceSet }, setBonuses, withheld };
}

// ── Energy (math-fallback P3, task 14) ────────────────────────────────────────────────────

/**
 * The subject's total Energy Recharge before artifacts under these sources: the first row's
 * base (character, weapon, ascension, and any set statics folded into it) plus every kit ER
 * buff that reaches that row. The energy model (`formula-energy.ts`) adds a candidate's
 * artifact ER to this, the same `b('energy_recharge') + buffs.er` an ER conversion reads.
 */
export function subjectEnergyRecharge(
  rows: readonly FormulaRow[],
  sources: readonly FormulaSource[],
  team: FormulaTeam,
  teamState: ConditionState = {},
): number {
  return subjectBase(rows, sources, team, teamState).er;
}

/**
 * The subject's crit rate before artifacts under these sources, read the way
 * `subjectEnergyRecharge` reads ER: the first row's base plus every flat kit crit buff that
 * reaches it. A subject's own Favonius procs add a candidate's artifact crit to this
 * (owner ruling 2026-11-15, `DECISIONS.md` §49). Crit converted from another stat (EM, HP) is
 * not included — a stated simplification that can only under-count the procs.
 */
export function subjectCritRate(
  rows: readonly FormulaRow[],
  sources: readonly FormulaSource[],
  team: FormulaTeam,
  teamState: ConditionState = {},
): number {
  return subjectBase(rows, sources, team, teamState).critRate;
}

function subjectBase(
  rows: readonly FormulaRow[],
  sources: readonly FormulaSource[],
  team: FormulaTeam,
  teamState: ConditionState,
): { er: number; critRate: number } {
  const row = rows[0];
  if (!row) throw new Error('a formula target needs at least one row');
  const { base, hit, dmgBonusQuantity } = row.context;
  const { buffs } = applySources(
    sources, {
      element: elementOfQuantity(dmgBonusQuantity), move: row.move, amplifying: hit.amplifying,
      hit: row.hit ?? null, reaction: hit.amplifying ?? null,
      reactionRow: !!row.reaction, procRow: !!row.proc,
    }, team, row.conditionals ?? {}, teamState,
  );
  return {
    er: (base['energy_recharge'] ?? 0) + buffs.er,
    critRate: (base['crit_rate'] ?? 0) + buffs.critRate,
  };
}
