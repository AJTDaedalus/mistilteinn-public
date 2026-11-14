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
 * move is unknown. No kit buffs (talents, passives, constellations, teammates' sheets) and no
 * weapon passives are modelled in P1, and the recipe says so.
 */

import {
  type Amplifying,
  amplifyingMultiplier,
  defMultiplier,
  resMultiplier,
  type ScalingStat,
} from './damage';
import {
  cappedAmount,
  type ConversionSource, type FormulaMove, type FormulaProvenance, type PercentTerm,
  type Recipe, type RecipeHit, type RecipeScaling, type StatConversion,
} from './recipe';
import { evaluateHit, NO_STATS } from './recipe-eval';
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
  default_reason: 'self' | 'situational';
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
}

/** Whose kits the estimate models, for its assumptions. */
export interface KitCoverage {
  /** Givers whose sheet is applied, with whether it is verified. */
  modelled: { name: string; verified: boolean }[];
  /** Members with no sheet: base stats, sets and resonance only. */
  missing: string[];
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
  hit?: { talent: string; label: string } | null;
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
}

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
  atkFrom: ({ from: 'def' | 'hp'; perUnit: number } & Limits) | null;
  /** Capped self-conversions into DMG% or CRIT Rate (Nahida's, Furina's, Alhaitham's A4). */
  statConversions: StatConversion[];
  /** Base ATK, before the percentage (Mavuika's C2). */
  baseAtk: number;
  /** Added to the talent term's base-damage multiplier (GO `baseMulti`). */
  baseDmgBonus: number;
}

/** A capped self-conversion's threshold and cap (`recipe.ts:cappedAmount`); absent is none. */
interface Limits {
  threshold?: number;
  cap?: number;
}

function noBuffs(): Buffs {
  return {
    percent: { atk: 0, hp: 0, def: 0 }, em: 0, er: 0, critRate: 0, critDmg: 0, dmgBonus: 0,
    reactionBonus: 0, resistance: 0, flatDamage: 0, flatFrom: { atk: 0, hp: 0, def: 0, em: 0 },
    flatLimits: {}, erConversion: null,
    flatAtk: 0, bonusFromEm: 0, flatDef: 0, defReduction: 0, defIgnore: 0,
    atkFrom: null, statConversions: [], baseAtk: 0, baseDmgBonus: 0,
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

/** Flat ATK from the hit owner's own DEF or HP: one per hit. */
function addAtkFrom(
  buffs: Buffs, from: 'def' | 'hp', amount: number, limits: Limits, source: string,
): void {
  if (buffs.atkFrom !== null) {
    if (buffs.atkFrom.from !== from || isLimited(limits) || isLimited(buffs.atkFrom)) {
      throw new Error(`${source}: two conversions into flat ATK on one hit`);
    }
    buffs.atkFrom.perUnit += amount;
    return;
  }
  buffs.atkFrom = { from, perUnit: amount, ...limits };
}

/** A conversion into DMG% or CRIT Rate, priced alone (`StatConversion`). */
function addStatConversion(
  buffs: Buffs, into: PercentTerm, from: ConversionSource, amount: number, limits: Limits,
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
      if (effect.reactions && !(scope.amplifying && effect.reactions.includes(scope.amplifying))) {
        continue;
      }

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
      if ((effect.stat === 'dmg_bonus_from_em' || effect.stat === 'dmg_bonus_from_hp')
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
        case 'flat_def': buffs.flatDef += amount; break;
        case 'def_reduction': buffs.defReduction += amount; break;
        case 'def_ignore': buffs.defIgnore += amount; break;
        case 'flat_atk_from_def': addAtkFrom(buffs, 'def', amount, limits, source.id); break;
        case 'flat_atk_from_hp': addAtkFrom(buffs, 'hp', amount, limits, source.id); break;
        case 'base_atk': buffs.baseAtk += amount; break;
        case 'base_dmg_bonus': buffs.baseDmgBonus += amount; break;
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
): { hits: RecipeHit[]; skipped: string[] } {
  if (!(row.count > 0)) throw new Error(`row ${row.id}: a count must be positive`);
  const { base, hit, target, characterLevel, dmgBonusQuantity } = row.context;
  const element = elementOfQuantity(dmgBonusQuantity);
  const { buffs, skipped } = applySources(
    sources, { element, move: row.move, amplifying: hit.amplifying, hit: row.hit ?? null }, team,
    row.conditionals ?? {}, teamState,
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
  const zeroTotal = (from: 'def' | 'hp'): number =>
    calibratedBase[from] * (1 + calibratedPercent[from]) + calibratedFlat[from];
  const hits = terms.map((term, i): RecipeHit => {
    const scaling = RECIPE_SCALING[term.stat];
    const total = scaling === 'em'
      ? calibratedEm
      : calibratedBase[scaling] * (1 + calibratedPercent[scaling]) + calibratedFlat[scaling]
        + (scaling === 'atk' && atkFrom
          ? cappedAmount(atkFrom.perUnit, zeroTotal(atkFrom.from), atkFrom.threshold, atkFrom.cap)
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
    // **What this hit deals at zero artifacts**, under the name the recipe type gives it. On a
    // synthetic recipe nothing was simulated; consumers that freeze a teammate's hit at this
    // value never see one, because every formula hit is `mine`.
    out.gcsimAverageDamage = evaluateHit(out, NO_STATS);
    return out;
  });
  return { hits, skipped };
}

/** The sentence a condition's current value becomes in the assumptions list. */
function describe(
  source: FormulaSource, condition: FormulaCondition, value: ConditionValue,
): string {
  const shown = condition.kind === 'toggle'
    ? (value ? 'on' : 'off')
    : condition.kind === 'choice' ? (value === '' ? 'none' : String(value)) : String(value);
  const why = value === condition.default
    ? `default — ${condition.default_reason === 'self'
      ? 'the wearer triggers it' : 'depends on the situation'}`
    : 'set by you';
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

/** One recipe for one 4-piece state (or none), over every row. */
export function synthesizeRecipe(
  rows: readonly FormulaRow[],
  sources: readonly FormulaSource[],
  team: FormulaTeam,
  teamState: ConditionState = {},
  characters: string[] = [],
  kits?: KitCoverage,
): Recipe {
  if (rows.length === 0) throw new Error('a formula target needs at least one row');
  const ids = new Set(rows.map((r) => r.id));
  if (ids.size !== rows.length) throw new Error('row ids repeat');

  const hits: RecipeHit[] = [];
  const assumptions = new Set<string>([
    'Formula estimate: no simulation. Not calibrated by gcsim.',
    ...kitAssumptions(kits),
    'No weapon passives modelled.',
    'Transformative, additive and Lunar reactions are not modelled.',
  ]);
  for (const row of rows) {
    const made = rowHits(row, sources, team, teamState);
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
