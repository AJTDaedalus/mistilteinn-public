/**
 * Scoring an artifact combination against a gcsim-derived recipe.
 *
 * `docs/DESIGN_gcsim_optimizer.md` §3. The recipe is calibrated **with zero artifact stats**,
 * so every term in it is character + weapon + set-bonus + talent buff. A candidate's own stats
 * then add on top — verified against gcsim: the same rotation calibrated at zero stats and at
 * `atk%=0.464 cd=0.62` produces an **identical ability sequence**, and predicting one from the
 * other matches to **1.986e-16** over 221 hits.
 *
 * ## Why this is affordable
 *
 * The expensive part of scoring a combination is aggregating its stats — ~4.9 µs against
 * ~0.02 µs to evaluate one hit. A recipe shares the aggregation across every hit, so a
 * 17-source four-character rotation costs about **1.05×** a single-hit score. gcsim never
 * enters the loop; it set the loop's question once.
 *
 * ## Why this does not call `computeDamage`, which G.4 said to reuse
 *
 * DESIGN §1 A6 forbids a second implementation of the damage chain, and that rule is right.
 * **This is not one.** `computeDamage` takes raw stats and a target and *derives* the DEF and
 * RES multipliers from levels and resistance. A recipe already has those — gcsim computed and
 * published them, and they do not vary with a candidate's artifacts. Feeding them back through
 * a function whose job is to derive them would mean re-deriving numbers we were handed.
 *
 * The duplication that remains is `(1 + bonus)` and `(1 + cr × cd)`, and the guard against it
 * drifting is stronger than sharing code: `scripts/verify-gcsim-recipe.mjs` binds this module
 * **to gcsim itself**, by predicting runs it was not calibrated on.
 */

import { amplifyingMultiplier } from './damage';
import {
  effectiveCritRate,
  type ConversionSource,
  type ConversionTerm,
  type FormulaMove,
  type Recipe,
  type RecipeHit,
} from './recipe';
import { dpsAt } from './recipe-energy';

/**
 * A candidate's artifact-borne stats, keyed the way `search.ts` keys them.
 *
 * `elementBonus` is keyed by gcsim's own element names, which is why `RecipeHit.element` has
 * to carry the name rather than gcsim's internal enum.
 */
export interface CandidateStats {
  atkPercent: number;
  atkFlat: number;
  hpPercent: number;
  hpFlat: number;
  defPercent: number;
  defFlat: number;
  elementalMastery: number;
  critRate: number;
  critDmg: number;
  /** Per-element damage bonus — `{cryo: 0.466}`. A goblet reaches only its own element. */
  elementBonus: Readonly<Record<string, number>>;
  /** A bonus that reaches every hit regardless of element. */
  allElementBonus: number;
  /**
   * Artifact-borne Energy Recharge, as a fraction — `0.30` is +30 %.
   *
   * **It multiplies nothing.** ER changes how often the burst is *cast*, not how hard a hit
   * lands, so it never enters the damage arithmetic below. `evaluateRecipe` uses it to look up
   * the burst count this candidate can afford, and scales burst-tagged hits by what it finds.
   *
   * That is the owner's stated ideal: worth nothing above the threshold where the character
   * bursts on time, and weighed against damage stats below it.
   */
  energyRecharge: number;
  /**
   * DMG% that reaches only one kind of move — a set bonus such as Gambler's 2-piece
   * (`skill`). Read only by a hit that declares its `move`, which only a formula recipe does,
   * so a gcsim recipe is untouched. Optional: absent is "none".
   */
  moveBonus?: Readonly<Partial<Record<FormulaMove, number>>>;
}

export const NO_STATS: CandidateStats = {
  atkPercent: 0, atkFlat: 0, hpPercent: 0, hpFlat: 0, defPercent: 0, defFlat: 0,
  elementalMastery: 0, critRate: 0, critDmg: 0, elementBonus: {}, allElementBonus: 0,
  energyRecharge: 0,
};

/** Which frozen flat-stat term belongs to which stat. */
const FLAT_TERM = { atk: 'flatAtk', hp: 'flatHp', def: 'flatDef' } as const;

/** The candidate's own percentage and flat additions for one stat. */
function candidateParts(
  stats: CandidateStats, stat: ConversionSource,
): { percent: number; flat: number } {
  switch (stat) {
    case 'hp':
      return { percent: stats.hpPercent, flat: stats.hpFlat };
    case 'def':
      return { percent: stats.defPercent, flat: stats.defFlat };
    default:
      return { percent: stats.atkPercent, flat: stats.atkFlat };
  }
}

/**
 * A stat's total **without** resolving any conversion into its flat part.
 *
 * The source of a conversion is measured this way so that a conversion drawing from a stat
 * that is itself converted cannot recurse. A two-point probe cannot separate a chain anyway,
 * and pretending otherwise would be a confident guess.
 */
function rawTotal(hit: RecipeHit, stats: CandidateStats, stat: ConversionSource): number {
  const mine = candidateParts(stats, stat);
  return hit.calibratedBase[stat] * (1 + hit.calibratedPercent[stat] + mine.percent)
    + hit.calibratedFlat[stat] + mine.flat;
}

/**
 * A frozen term's value for this candidate.
 *
 * Rescaled from the candidate's own total when a probe identified the source, and **left at
 * the calibration's value when it did not** — inventing a scaling for a term whose source was
 * never identified would put a confident wrong number in every hit that carries it.
 */
function resolvedTerm(
  hit: RecipeHit, term: ConversionTerm, frozen: number, stats: CandidateStats,
): number {
  const conversion = hit.conversions[term];
  if (conversion === undefined) return frozen;
  return conversion.perUnit * rawTotal(hit, stats, conversion.from);
}

/**
 * A stat's total for this candidate, with any conversion into its flat part resolved.
 *
 * **The percentages add.** `base × (1 + calibrated% + candidate%) + flat` is gcsim's own
 * formula. Applying the candidate's percentage to the calibration's *total* would compound the
 * calibration's own buffs — invisible whenever the calibration has none, which is exactly the
 * fixture that was passing at 1e-16 while a second one was 79 % out.
 */
export function totalFor(
  hit: RecipeHit, stats: CandidateStats, stat: ConversionSource,
): number {
  const mine = candidateParts(stats, stat);
  const flat = resolvedTerm(hit, FLAT_TERM[stat], hit.calibratedFlat[stat], stats);
  return hit.calibratedBase[stat] * (1 + hit.calibratedPercent[stat] + mine.percent)
    + flat + mine.flat;
}

/** One hit's average damage with a candidate's stats applied. */
export function evaluateHit(hit: RecipeHit, stats: CandidateStats): number {
  // **A teammate's hit does not respond to this build's artifacts.** Only the optimized
  // character's gear changes during a search, so a teammate's damage is a constant and
  // `gcsimAverageDamage` is what gcsim measured it to be.
  //
  // Without this the candidate's ATK%, CRIT rate and CRIT DMG were added to *every* hit,
  // including Furina's own ATK and crit. Measured on the owner's Skirk rotation: teammates are
  // 90.9% of the damage, and 78.4% of the gain a candidate appeared to provide was applied to
  // damage that cannot move — so the ranking was driven mostly by a number no artifact affects.
  if (!hit.mine) return hit.gcsimAverageDamage;

  // EM has no base or percentage form; a hit scaling off it takes the whole value.
  //
  // `calibratedEm` is the EM a formula recipe's hit carries before artifacts. A gcsim recipe
  // has none (`?? 0`), which keeps its arithmetic exactly what it was.
  const em = (hit.calibratedEm ?? 0) + stats.elementalMastery;
  const scaling = hit.scaling === 'em' ? em : totalFor(hit, stats, hit.scaling);

  const base = hit.talent * scaling + resolvedTerm(hit, 'flatDamage', hit.flatDamage, stats);
  const bonus = hit.bonusDmg + (stats.elementBonus[hit.element] ?? 0) + stats.allElementBonus
    + (hit.move === undefined ? 0 : (stats.moveBonus?.[hit.move] ?? 0))
    + energyRechargeBonus(hit, stats);
  const preCrit = base * (1 + bonus) * hit.defMultiplier * hit.resMultiplier;
  const crit = 1 + effectiveCritRate(hit.critRate + stats.critRate) * (hit.critDmg + stats.critDmg);
  // A formula recipe's amplifying multiplier follows the candidate's EM, through the same
  // function the single-hit kernel calls. A gcsim recipe keeps its frozen total.
  const amp = hit.amplifying === undefined
    ? hit.ampMultiplier
    : amplifyingMultiplier(hit.amplifying.reaction, em, hit.amplifying.reactionBonus);
  return preCrit * crit * amp;
}

/** Emblem's `min(cap, rate × ER)`, ER being the hit's own plus the candidate's. */
function energyRechargeBonus(hit: RecipeHit, stats: CandidateStats): number {
  const conversion = hit.bonusFromEnergyRecharge;
  if (conversion === undefined) return 0;
  const er = conversion.calibratedEnergyRecharge + stats.energyRecharge;
  return Math.min(conversion.cap, conversion.perUnit * er);
}

/**
 * The rotation's total damage for a candidate.
 *
 * Summed rather than averaged: the recipe already carries one entry per landed hit, so a count
 * is not a weight to apply here.
 */
export function evaluateRecipe(recipe: Recipe, stats: CandidateStats): number {
  // **One factor for the whole character, not per hit.** What Energy Recharge buys is a burst
  // that lands on time — and a burst's worth is rarely its own damage. Measured on the owner's
  // Furina: **98.3 % of her damage is skill-tagged and 1.5 % is burst**, because her burst
  // buffs the team and removes the delay the rotation spends waiting for it. Scaling
  // burst-tagged hits therefore moved 1.5 % of the damage on the character the feature exists
  // for.
  //
  // The ladder measures team DPS at each ER instead, which carries the buff, the delay and the
  // damage together without attributing any of them to a hit.
  const ratio = energyRatio(recipe, stats);
  let total = 0;
  for (const hit of recipe.hits) total += evaluateHit(hit, stats);
  return ratio === 1 ? total : total * ratio;
}

/**
 * What this candidate's Energy Recharge does to the rotation, against the calibration's.
 *
 * **1 when the ladder cannot answer** — no sweep, or no calibration DPS to compare against —
 * which is the honest default: nothing is scaled and the ranking is what it was before ER
 * entered it.
 *
 * Above the threshold the ladder returns the same DPS and the ratio is 1, so ER stops being
 * worth anything. Below it, a candidate that cannot cast the burst on time is scored for the
 * rotation it actually performs rather than the one the recipe was calibrated for.
 */
export function energyRatio(recipe: Recipe, stats: CandidateStats): number {
  const sweep = recipe.meta.energySweep;
  if (!sweep?.length) return 1;
  // **Both sides off the same ladder.** The denominator used to be `calibratedEnergyDps`, a
  // 100-iteration aggregate, against a numerator floored onto a 20-iteration rung — so the
  // ratio at the calibration's own ER was 0.928 rather than 1, and the two measurements'
  // noise added instead of cancelling. `calibratedEnergyRecharge` is read through the same
  // `dpsAt`, which makes the ratio exactly 1 there whatever the rungs happen to say.
  const baseline = recipe.meta.calibratedEnergyRecharge !== undefined
    ? dpsAt(sweep, recipe.meta.calibratedEnergyRecharge)
    : recipe.meta.calibratedEnergyDps ?? null;
  if (!baseline) return 1;
  const at = dpsAt(sweep, stats.energyRecharge);
  return at === null ? 1 : at / baseline;
}
