/**
 * Scoring an artifact combination against a gcsim-derived recipe.
 *
 * `docs/DESIGN_gcsim_optimizer.md` §3. The recipe is calibrated **with zero artifact stats**,
 * so every term in it is character + weapon + set-bonus + talent buff. A candidate's own
 * stats then add on top — verified against gcsim: the same rotation calibrated at zero stats
 * and at `atk%=0.464 cd=0.62` produces an **identical ability sequence**, with `atk_per`
 * 0 → 0.464, `total_scaling` 1016.36 → 1487.95 and `cd` +0.62, and nothing else moved.
 *
 * ## Why this is affordable
 *
 * The expensive part of scoring a combination is aggregating its stats — ~4.9 µs against
 * **0.020 µs** to evaluate one hit, measured. A recipe shares the aggregation across every
 * hit, so a 17-source four-character rotation costs **1.05×** a single-hit score. gcsim never
 * enters the loop; it set the loop's question once.
 *
 * ## Why this does not call `computeDamage`, which G.4 said to reuse
 *
 * DESIGN §1 A6 forbids a second implementation of the damage chain, and that rule is right.
 * **This is not one.** `computeDamage` takes raw stats and a target, and *derives* the DEF and
 * RES multipliers from levels and resistance. A recipe already has those — gcsim computed them
 * and published them as `def_mod` and `res_mod`, and they do not vary with a candidate's
 * artifacts. Feeding them back through a function whose job is to derive them would mean
 * re-deriving a number we were handed, and the only way to do it would be to invert the curve.
 *
 * That is why `evaluateHit` is **3× faster** than `computeDamage`: it does strictly less.
 *
 * The duplication that remains is `(1 + bonus)` and `(1 + cr × cd)`, and the guard against it
 * drifting is stronger than sharing code would be: `scripts/verify-gcsim-recipe.mjs` binds
 * this function **to gcsim itself**, by predicting a run it was not calibrated on and checking
 * against that run's own numbers.
 */

import { effectiveCritRate, type Recipe, type RecipeHit } from './recipe';

/**
 * A candidate's artifact-borne stats, keyed the way `search.ts` keys them.
 *
 * Only the quantities a recipe hit consumes. `elementBonus` is keyed by gcsim's own element
 * names, which is why `RecipeHit.element` has to carry the name rather than gcsim's internal
 * enum.
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
}

export const NO_STATS: CandidateStats = {
  atkPercent: 0, atkFlat: 0, hpPercent: 0, hpFlat: 0, defPercent: 0, defFlat: 0,
  elementalMastery: 0, critRate: 0, critDmg: 0, elementBonus: {}, allElementBonus: 0,
};

/** The percentage and flat additions a candidate makes to this hit's scaling stat. */
function scalingParts(
  hit: RecipeHit, stats: CandidateStats,
): { percent: number; flat: number } {
  switch (hit.scaling) {
    case 'hp':
      return { percent: stats.hpPercent, flat: stats.hpFlat };
    case 'def':
      return { percent: stats.defPercent, flat: stats.defFlat };
    case 'em':
      // EM is a flat quantity with no percentage form; a hit scaling off it takes the whole
      // value rather than a multiple of a base.
      return { percent: 0, flat: stats.elementalMastery };
    default:
      return { percent: stats.atkPercent, flat: stats.atkFlat };
  }
}

/**
 * One hit's average damage with a candidate's stats applied.
 *
 * **`flatDamage` is not scaled by the candidate.** It is baked in at calibration, and for a
 * conversion passive like `Redhorn Stonethresher` — flat damage from DEF — that makes it
 * **stale** the moment the candidate's DEF differs. `staleConversions` on the recipe is how a
 * caller finds out; this function does not silently pretend otherwise.
 */
export function evaluateHit(hit: RecipeHit, stats: CandidateStats): number {
  const parts = scalingParts(hit, stats);
  const scaling = hit.scaling === 'em'
    ? hit.baseStat + parts.flat
    : hit.baseStat * (1 + parts.percent) + parts.flat;

  const base = hit.talent * scaling + hit.flatDamage;
  const bonus = hit.bonusDmg + (stats.elementBonus[hit.element] ?? 0) + stats.allElementBonus;
  const preCrit = base * (1 + bonus) * hit.defMultiplier * hit.resMultiplier;
  const crit = 1 + effectiveCritRate(hit.critRate + stats.critRate) * (hit.critDmg + stats.critDmg);
  return preCrit * crit * hit.ampMultiplier;
}

/**
 * The rotation's total damage for a candidate.
 *
 * Summed rather than averaged: the recipe already carries one entry per landed hit, so a
 * count is not a weight to apply here.
 */
export function evaluateRecipe(recipe: Recipe, stats: CandidateStats): number {
  let total = 0;
  for (const hit of recipe.hits) total += evaluateHit(hit, stats);
  return total;
}
