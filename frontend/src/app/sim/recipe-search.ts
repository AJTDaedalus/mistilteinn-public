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

/**
 * The recipes a search can score against, one per 4-piece state.
 *
 * `docs/RESEARCH_conditional_sets.md`: **every 4-piece bonus in the game is conditional**, and
 * only a calibration that equipped the set can hold it. So a combination reaching 4 pieces of
 * set X must be scored against X's recipe — and a five-slot combination reaches **at most
 * one** 4-piece, which is what keeps this a map rather than a product.
 */
export interface RecipeSet {
  /** Keyed by the catalogue set id a 4-piece of which this recipe was calibrated with. */
  byFourPieceSet: ReadonlyMap<number, Recipe>;
  /** For a combination that reaches no 4-piece at all. */
  noFourPiece: Recipe;
}

/** Why a combination could not be scored. Reported, never silently substituted. */
export interface UnscorableCombination {
  artifactIds: string[];
  reason: string;
}

/** A recipe search's result — a `SearchResult` plus what it could not score. */
export interface RecipeSearchResult extends SearchResult {
  /**
   * Combinations no recipe covered.
   *
   * **Reported rather than substituted.** Scoring a `Blizzard Strayer` build against the
   * no-set recipe would understate it by the whole 4-piece bonus and look like an ordinary
   * result — the exact failure this chunk exists to remove.
   */
  unscorable: UnscorableCombination[];
}

export interface RecipeSearchContext {
  /** One recipe per 4-piece state. */
  recipes: RecipeSet;
  /**
   * **No `base`.** The single-hit search takes one; this deliberately does not.
   *
   * A recipe calibrated at zero artifact stats already carries the character, weapon and
   * talent buffs — passing a base pool here would count all of it twice. The field existed in
   * the first draft, went unread, and a mutation that folded it into the candidate's stats
   * survived every test because they all passed `{}`. **An unread field is an invitation.**
   */
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

/** The 4-piece set a combination reaches, or `null` if it reaches none. */
export function fourPieceSetOf(setCounts: Readonly<Record<number, number>>): number | null {
  for (const [setId, count] of Object.entries(setCounts)) {
    if (count >= 4) return Number(setId);
  }
  return null;
}

/**
 * The quantities that change a recipe's score, for the lossless Pareto layer.
 *
 * **Getting this wrong makes a lossless layer lossy**, silently: a piece dominated on the
 * quantities named here is discarded, and if the recipe reads one that is missing, the piece
 * that was better at it is gone before scoring.
 *
 * Derived from the recipes rather than assumed. A rotation reads: crit, every element it
 * actually deals damage in, every stat its abilities scale off, EM when any hit amplifies —
 * and **every stat a resolved conversion draws from**, which is the one a single-hit search
 * has no equivalent of and the reason a Redhorn build starts valuing DEF.
 *
 * ## The union, not the intersection
 *
 * A search scores against several recipes — one per 4-piece set — and the live set must be the
 * **union** of theirs. A piece dominated under one recipe may be the **winner** under another:
 * DEF is dead weight for a `Gladiator's Finale` build and decisive for a `Redhorn` one, and
 * pruning it on the first would remove the winner of the second **before it was ever scored**.
 *
 * Intersecting would make a layer that advertises itself as lossless **silently lossy**, and
 * the result would still look like a complete ranking. `docs/TASKS_recipe_surface.md` R.6.
 */
export function liveQuantitiesFor(...recipes: readonly Recipe[]): string[] {
  const live = new Set<string>(['crit_rate', 'crit_dmg']);
  const parts: Record<string, string[]> = {
    atk: ['base_atk', 'atk_pct', 'flat_atk'],
    hp: ['base_hp', 'hp_pct', 'flat_hp'],
    def: ['base_def', 'def_pct', 'flat_def'],
  };
  for (const hit of recipes.flatMap((recipe) => recipe.hits)) {
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
  recipe: Recipe,
  combination: readonly Candidate[],
  setCounts: Record<number, number>,
  bonusesBySet: Map<number, SetBonus[]>,
): number {
  const pools: Readonly<Record<string, number>>[] = combination.map((c) => c.stats);
  for (const [setId, count] of Object.entries(setCounts)) {
    // **Skip the set the recipe was calibrated with.** Equipping a set to calibrate also
    // applies its 2-piece, so it is already in every term of the recipe — adding the tier here
    // lands it twice. Other sets in the combination are not in the calibration and do belong.
    if (Number(setId) === recipe.meta.calibratedSetId) continue;
    for (const tier of bonusesBySet.get(Number(setId)) ?? []) {
      if (count >= tier.piecesRequired) pools.push(tier.stats);
    }
  }
  return evaluateRecipe(recipe, candidateStatsFrom(pools));
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
): RecipeSearchResult {
  const topN = context.topN ?? 10;
  if (topN <= 0) throw new Error(`topN must be at least 1; got ${topN}`);

  const bonusesBySet = new Map<number, SetBonus[]>();
  for (const bonus of context.setBonuses ?? []) {
    const tiers = bonusesBySet.get(bonus.setId);
    if (tiers) tiers.push(bonus);
    else bonusesBySet.set(bonus.setId, [bonus]);
  }

  const { kept, removed } = paretoFilter(
    bucketBySlot(candidates),
    liveQuantitiesFor(context.recipes.noFourPiece, ...context.recipes.byFourPieceSet.values()),
  );
  const buckets = SLOTS.map((s) => kept.get(s) ?? []);

  const best: ScoredBuild[] = [];
  const unscorable: UnscorableCombination[] = [];
  let evaluated = 0;
  const combination: Candidate[] = new Array(SLOTS.length);

  const walk = (depth: number): void => {
    if (depth === SLOTS.length) {
      evaluated += 1;
      const setCounts: Record<number, number> = {};
      for (const c of combination) setCounts[c.setId] = (setCounts[c.setId] ?? 0) + 1;

      // A combination reaching 4 pieces of a set must be scored against *that set's* recipe:
      // its 4-piece bonus is conditional and lives only inside a calibration that equipped it.
      const fourPiece = fourPieceSetOf(setCounts);
      const recipe = fourPiece === null
        ? context.recipes.noFourPiece
        : context.recipes.byFourPieceSet.get(fourPiece);

      // **Reported, never substituted.** Scoring a Blizzard Strayer build against the no-set
      // recipe is precisely the wrong answer this chunk exists to stop — and it would look
      // like a perfectly ordinary result.
      if (recipe === undefined) {
        unscorable.push({
          artifactIds: combination.map((c) => c.id),
          reason: `no recipe calibrated for the 4-piece set ${fourPiece}`,
        });
        return;
      }

      const damage = score(recipe, combination, setCounts, bonusesBySet);
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

  return { builds: best, evaluated, paretoRemoved: removed, isExact: true, unscorable };
}
