import { type Recipe } from './recipe';
import { evaluateRecipe } from './recipe-eval';
import { candidateStatsFrom } from './recipe-search';

/** One artifact's stat contribution, keyed the way the kernel keys quantities. */
export type StatPool = Readonly<Record<string, number>>;

export interface ArtifactScore {
  /** Damage over the rotation with this piece in its slot. */
  damage: number;
  /** Damage with whatever occupies that slot now. */
  current: number;
  /**
   * `damage - current`. **Positive means an upgrade**, and this is the number a player is
   * actually asking for.
   *
   * The hands-on Fribbels audit names its equivalent — a signed `Δ Reroll Avg` column — as the
   * single thing that turns a sortable list into a decidable one: a score says how good a
   * piece is, a delta says whether to keep it.
   */
  delta: number;
}

/**
 * What one artifact is worth to one build, over its rotation.
 *
 * **The engine is the recipe evaluator, by owner ruling** (`DECISIONS.md` §22): *"how much
 * potential does this artifact have given this character in this team with this rotation?"*
 * A single-hit derivative cannot see a team buff or a rotation's shape, and those decide most
 * of whether Energy Recharge or CRIT DMG is worth more on a given piece.
 *
 * It is affordable because a recipe is calibrated **once**, after which evaluating a candidate
 * is closed-form arithmetic: measured at **0.048 µs per hit**, so a 245-hit rotation scores a
 * whole 2,370-piece inventory in about **28 ms**. That measurement is why nothing here caches.
 *
 * ## What this does not model, and says so
 *
 * **Set bonuses.** Swapping a piece can change which 4-piece a build fields, and that changes
 * which *recipe* applies — not just the stats fed to one. This scores stat-for-stat **within a
 * single calibrated recipe**, which is the honest answer for a piece of the same set and an
 * understatement for one that would complete a different set.
 *
 * The caller owns that distinction because the caller knows which recipes it holds:
 * `searchRecipe` already picks a recipe per 4-piece state and reports `uncoveredSets` for the
 * ones it has none for. A function that silently scored across sets would produce the failure
 * that reporting exists to prevent — a confident number for a build nobody calibrated.
 */
export function scoreArtifact(
  recipe: Recipe,
  equipped: readonly StatPool[],
  candidate: StatPool,
  slot: number,
): ArtifactScore {
  if (slot < 0 || slot >= equipped.length) {
    throw new RangeError(
      `slot ${slot} is outside the ${equipped.length} equipped pieces; a score for a slot the `
      + 'build does not have would be a number about nothing',
    );
  }

  const current = evaluateRecipe(recipe, candidateStatsFrom(equipped));
  // **A copy, not a splice.** Mutating the caller's array would leave the build wearing the
  // last piece scored — and every subsequent score would be measured against it, so an
  // inventory sweep would drift piece by piece with nothing reporting a problem.
  const swapped = [...equipped];
  swapped[slot] = candidate;
  const damage = evaluateRecipe(recipe, candidateStatsFrom(swapped));

  return { damage, current, delta: damage - current };
}

/**
 * Score many candidates for one slot, against one recipe.
 *
 * The build's own damage is computed **once** rather than per candidate — it does not change
 * as candidates do, and recomputing it per piece would double the cost of a sweep for an answer
 * that is identical every time.
 */
export function scoreForSlot(
  recipe: Recipe,
  equipped: readonly StatPool[],
  candidates: readonly { id: string; stats: StatPool }[],
  slot: number,
): { id: string; score: ArtifactScore }[] {
  if (slot < 0 || slot >= equipped.length) {
    throw new RangeError(`slot ${slot} is outside the ${equipped.length} equipped pieces`);
  }
  const current = evaluateRecipe(recipe, candidateStatsFrom(equipped));
  const swapped = [...equipped];

  return candidates.map(({ id, stats }) => {
    swapped[slot] = stats;
    const damage = evaluateRecipe(recipe, candidateStatsFrom(swapped));
    return { id, score: { damage, current, delta: damage - current } };
  });
}
