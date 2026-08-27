/**
 * Searching artifacts against a gcsim rotation instead of a single hit.
 *
 * `docs/DESIGN_gcsim_optimizer.md` §1. The existing search maximises **one hit**, which is a
 * proxy: the best five pieces for one Cutting DMG are not necessarily the best five for a
 * rotation. And the Chunk F chain does not model weapon passives, so for
 * `Redhorn Stonethresher` it will **never consider DEF** and returns a confident wrong answer.
 *
 * Scoring against a recipe fixes both, at **~1.05×** the per-combination cost — the stat
 * aggregation is shared across every hit, and `evaluateHit` is *cheaper* than `computeDamage`
 * because the DEF and RES multipliers are already published.
 *
 * **The single-hit search stays.** It answers a different, legitimate question in
 * microseconds, and OQ-W4 already settled the principle: deleting a fast honest answer because
 * a slow better one exists is a downgrade for whoever wanted the fast one.
 */

import type { Recipe } from './recipe';
import { evaluateRecipe, NO_STATS, type CandidateStats } from './recipe-eval';
import {
  SLOTS,
  bucketBySlot,
  paretoFilter,
  type Candidate,
  type ScoredBuild,
  type SearchResult,
  type SetBonus,
} from './search';

/** `cryo_dmg_bonus` → `cryo`. The kernel's vocabulary, gcsim's element names. */
const DMG_BONUS_SUFFIX = '_dmg_bonus';

export interface RecipeSearchContext {
  /**
   * **No `base`.** The single-hit search takes one; this deliberately does not.
   *
   * A recipe calibrated at zero artifact stats already carries the character, weapon, sets and
   * talent buffs — passing a base pool here would count all of it twice. The field existed in
   * the first draft, went unread, and a mutation that folded it into the candidate's stats
   * survived every test because they all passed `{}`. **An unread field is an invitation.**
   */
  recipe: Recipe;
  setBonuses?: readonly SetBonus[];
  topN?: number;
}

/** Sum one quantity across every stat pool, in f32 to match the GPU kernel. */
function sum(pools: readonly Readonly<Record<string, number>>[], quantity: string): number {
  let total = 0;
  for (const pool of pools) total = Math.fround(total + (pool[quantity] ?? 0));
  return total;
}

/**
 * Turn the kernel's stat pools into the shape a recipe evaluates against.
 *
 * **The base pool is excluded from the candidate's stats**, because the recipe already carries
 * it: a calibration at zero artifact stats has the character, weapon, sets and talent buffs
 * baked in. Adding the base again would count it twice.
 */
export function candidateStatsFrom(
  pools: readonly Readonly<Record<string, number>>[],
): CandidateStats {
  const elementBonus: Record<string, number> = {};
  for (const pool of pools) {
    for (const quantity of Object.keys(pool)) {
      if (!quantity.endsWith(DMG_BONUS_SUFFIX)) continue;
      const element = quantity.slice(0, -DMG_BONUS_SUFFIX.length);
      elementBonus[element] = sum(pools, quantity);
    }
  }
  return {
    ...NO_STATS,
    atkPercent: sum(pools, 'atk_pct'),
    atkFlat: sum(pools, 'flat_atk'),
    hpPercent: sum(pools, 'hp_pct'),
    hpFlat: sum(pools, 'flat_hp'),
    defPercent: sum(pools, 'def_pct'),
    defFlat: sum(pools, 'flat_def'),
    elementalMastery: sum(pools, 'elemental_mastery'),
    critRate: sum(pools, 'crit_rate'),
    critDmg: sum(pools, 'crit_dmg'),
    elementBonus,
  };
}

/**
 * The quantities that change a recipe's score, for the lossless Pareto layer.
 *
 * **Getting this wrong makes a lossless layer lossy**, silently: a piece dominated on the
 * quantities named here is discarded, and if the recipe reads one that is missing, the piece
 * that was better at it is gone before scoring.
 *
 * Derived from the recipe rather than assumed. A rotation reads: crit, every element it
 * actually deals damage in, every stat its abilities scale off, EM when any hit amplifies —
 * and **every stat a resolved conversion draws from**, which is the one a single-hit search
 * has no equivalent of and the reason a Redhorn build starts valuing DEF.
 */
export function liveQuantitiesFor(recipe: Recipe): string[] {
  const live = new Set<string>(['crit_rate', 'crit_dmg']);
  const parts: Record<string, string[]> = {
    atk: ['base_atk', 'atk_pct', 'flat_atk'],
    hp: ['base_hp', 'hp_pct', 'flat_hp'],
    def: ['base_def', 'def_pct', 'flat_def'],
  };
  for (const hit of recipe.hits) {
    live.add(`${hit.element}${DMG_BONUS_SUFFIX}`);
    if (hit.scaling === 'em') live.add('elemental_mastery');
    else for (const q of parts[hit.scaling]) live.add(q);
    if (hit.ampMultiplier !== 1) live.add('elemental_mastery');
    for (const conversion of Object.values(hit.conversions)) {
      for (const q of parts[conversion.from]) live.add(q);
    }
  }
  return [...live].sort();
}

/** Score one combination against the recipe. */
function score(
  context: RecipeSearchContext,
  combination: readonly Candidate[],
  bonusesBySet: Map<number, SetBonus[]>,
): { damage: number; setCounts: Record<number, number> } {
  const setCounts: Record<number, number> = {};
  for (const c of combination) setCounts[c.setId] = (setCounts[c.setId] ?? 0) + 1;

  const pools: Readonly<Record<string, number>>[] = combination.map((c) => c.stats);
  for (const [setId, count] of Object.entries(setCounts)) {
    for (const tier of bonusesBySet.get(Number(setId)) ?? []) {
      if (count >= tier.piecesRequired) pools.push(tier.stats);
    }
  }
  return {
    damage: evaluateRecipe(context.recipe, candidateStatsFrom(pools)),
    setCounts,
  };
}

/**
 * The best `topN` combinations by the rotation's total damage.
 *
 * The same exhaustive walk and lossless Pareto layer as the single-hit search; only the
 * objective differs. `isExact` stays true for the same reason it does there — there is no
 * lossy layer here.
 */
export function searchRecipe(
  candidates: readonly Candidate[],
  context: RecipeSearchContext,
): SearchResult {
  const topN = context.topN ?? 10;
  if (topN <= 0) throw new Error(`topN must be at least 1; got ${topN}`);

  const bonusesBySet = new Map<number, SetBonus[]>();
  for (const bonus of context.setBonuses ?? []) {
    const tiers = bonusesBySet.get(bonus.setId);
    if (tiers) tiers.push(bonus);
    else bonusesBySet.set(bonus.setId, [bonus]);
  }

  const { kept, removed } = paretoFilter(
    bucketBySlot(candidates), liveQuantitiesFor(context.recipe),
  );
  const buckets = SLOTS.map((s) => kept.get(s) ?? []);

  const best: ScoredBuild[] = [];
  let evaluated = 0;
  const combination: Candidate[] = new Array(SLOTS.length);

  const walk = (depth: number): void => {
    if (depth === SLOTS.length) {
      evaluated += 1;
      const { damage, setCounts } = score(context, combination, bonusesBySet);
      if (best.length < topN || damage > best[best.length - 1].damage) {
        const build: ScoredBuild = {
          damage,
          artifactIds: combination.map((c) => c.id),
          setCounts: { ...setCounts },
        };
        let i = best.length;
        while (i > 0 && best[i - 1].damage < damage) i -= 1;
        best.splice(i, 0, build);
        if (best.length > topN) best.pop();
      }
      return;
    }
    for (const candidate of buckets[depth]) {
      combination[depth] = candidate;
      walk(depth + 1);
    }
  };
  walk(0);

  return { builds: best, evaluated, paretoRemoved: removed, isExact: true };
}
