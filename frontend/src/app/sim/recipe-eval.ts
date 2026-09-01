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

import {
  effectiveCritRate,
  type ConversionSource,
  type ConversionTerm,
  type Recipe,
  type RecipeHit,
} from './recipe';
import { burstsAt } from './recipe-energy';

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
  const scaling = hit.scaling === 'em'
    ? stats.elementalMastery
    : totalFor(hit, stats, hit.scaling);

  const base = hit.talent * scaling + resolvedTerm(hit, 'flatDamage', hit.flatDamage, stats);
  const bonus = hit.bonusDmg + (stats.elementBonus[hit.element] ?? 0) + stats.allElementBonus;
  const preCrit = base * (1 + bonus) * hit.defMultiplier * hit.resMultiplier;
  const crit = 1 + effectiveCritRate(hit.critRate + stats.critRate) * (hit.critDmg + stats.critDmg);
  return preCrit * crit * hit.ampMultiplier;
}

/**
 * The rotation's total damage for a candidate.
 *
 * Summed rather than averaged: the recipe already carries one entry per landed hit, so a count
 * is not a weight to apply here.
 */
export function evaluateRecipe(recipe: Recipe, stats: CandidateStats): number {
  const ratio = burstRatio(recipe, stats);
  let total = 0;
  for (const hit of recipe.hits) {
    const damage = evaluateHit(hit, stats);
    // **Only burst hits move with the burst count.** Scaling everything would charge a
    // character's normals for a burst they could not afford, which is a different and much
    // larger claim than the ladder measured.
    total += ratio !== 1 && hit.mine && hit.attackTag === recipe.meta.burstAttackTag
      ? damage * ratio
      : damage;
  }
  return total;
}

/**
 * How many bursts this candidate's Energy Recharge buys, against the calibration's own count.
 *
 * **1 when the ladder cannot answer**, which is the honest default: no sweep was measured, or
 * the recipe does not know which hits are bursts, so nothing is scaled and the ranking is
 * exactly what it was before ER entered it.
 *
 * Above the threshold the ladder returns the same count and the ratio is 1 — ER stops being
 * worth anything, which is the behaviour the owner described. Below it, a candidate that
 * cannot cast the burst the recipe was calibrated for stops being scored as though it could.
 */
export function burstRatio(recipe: Recipe, stats: CandidateStats): number {
  const sweep = recipe.meta.energySweep;
  const calibrated = recipe.meta.calibratedBurstInstances;
  if (!sweep?.length || !calibrated || recipe.meta.burstAttackTag === undefined) return 1;
  const affordable = burstsAt(sweep, stats.energyRecharge);
  if (affordable === null) return 1;
  return affordable / calibrated;
}
