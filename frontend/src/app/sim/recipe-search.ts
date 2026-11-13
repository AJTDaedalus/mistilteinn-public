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

import type { FormulaMove, Recipe } from './recipe';
import { evaluateRecipe, NO_STATS, type CandidateStats } from './recipe-eval';
import { dpsAt } from './recipe-energy';
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
  /**
   * Keyed by `pairKey(a, b)` — a recipe calibrated with **both** sets at two pieces.
   *
   * Separate from `byFourPieceSet` because a 2+2 is a different state, not a weaker 4-piece:
   * nine of the sixty 2-piece bonuses are conditional and six are ability-scoped, so only a
   * run holding both can score them (owner ruling 1, `docs/DECISIONS.md`).
   */
  byPair?: ReadonlyMap<string, Recipe>;
}

/**
 * The key a pair recipe is stored under — order-independent.
 *
 * `(7, 8)` and `(8, 7)` are the same five slots, and keying them apart would calibrate the
 * same state twice and let the two disagree.
 */
export function pairKey(a: number, b: number): string {
  return a < b ? `${a}+${b}` : `${b}+${a}`;
}

/** A recipe search's result — a `SearchResult` plus what it did not cover, and why. */
export interface RecipeSearchResult extends SearchResult {
  /**
   * Sets the inventory could field a 4-piece of that no searched recipe covers.
   *
   * **Reported rather than substituted.** Scoring a `Blizzard Strayer` build against the
   * no-set recipe would understate it by the whole 4-piece bonus and look like an ordinary
   * result — the exact failure this reporting exists to remove.
   *
   * Named per **set** rather than per combination. The earlier shape listed every unscorable
   * five-piece combination, which for a real inventory is thousands of rows all saying the one
   * thing a reader needs: *calibrate this set*.
   */
  uncoveredSets: number[];
  /** Pairs that were asked for and had no calibrated recipe. Reported, never substituted. */
  uncoveredPairs: string[];
  /** Combinations the bound proved could not reach the top N, so were never scored. */
  boundPruned: number;
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
  /**
   * Which 4-piece states to search. `null` means "no 4-piece at all".
   *
   * Defaults to every calibrated set plus `null`, which is the whole space. Narrowing it is
   * what makes the search finish: against a real 2,370-piece inventory the unrestricted space
   * is **4.26e10** combinations after Pareto, and pinning one set is **1e5**.
   * `docs/FINDINGS_shakedown.md` F2.
   */
  fourPieceSets?: readonly (number | null)[];
  /**
   * 2+2 states to search, as `[setA, setB]`.
   *
   * **Opt-in, and rare by owner ruling** — a pair is ~1e6 combinations and all
   * `C(35, 2) = 595` of them are not searchable. Empty by default.
   */
  twoPiecePairs?: readonly (readonly [number, number])[];
  /**
   * Force one slot to hold exactly this piece, and search the other four around it.
   *
   * `TASKS_artifact_ranking.md` A.11 — the engine behind issue #291's *"assume that you can
   * move other artifacts, so the best build with this artifact levelled up vs current"*. That
   * is **not** a single-slot swap: it is this search, with the piece nailed down.
   *
   * The candidate is used as given, so a caller ranking a *projected* piece passes the
   * projected stats rather than the ones the artifact has today. `id` still identifies the real
   * piece, so the result names something the user owns.
   */
  pinned?: Candidate;
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
  const moveBonus: Partial<Record<FormulaMove, number>> = {};
  for (const pool of pools) {
    for (const quantity of Object.keys(pool)) {
      // A formula set bonus scoped to a move (`formula:dmg_bonus:skill`). Checked first and
      // spelled so it cannot end in `_dmg_bonus`, which would file it under an element.
      if (quantity.startsWith(FORMULA_MOVE_BONUS_PREFIX)) {
        const move = quantity.slice(FORMULA_MOVE_BONUS_PREFIX.length) as FormulaMove;
        moveBonus[move] = sum(pools, quantity);
        continue;
      }
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
    // Summed like any other stat, and used unlike any other: ER buys bursts, not damage.
    energyRecharge: sum(pools, 'energy_recharge'),
    elementBonus,
    // Every channel, from a formula set bonus such as Obsidian Codex's 2-piece. Nothing a
    // gcsim search passes carries it, so it reads 0 there as it always has.
    allElementBonus: sum(pools, FORMULA_ALL_DMG_BONUS),
    moveBonus,
  };
}

/**
 * The pool quantity for DMG% that reaches every channel. A formula-only spelling: the kernel's
 * own vocabulary has per-channel bonuses and nothing generic.
 */
export const FORMULA_ALL_DMG_BONUS = 'formula:dmg_bonus';
/** `formula:dmg_bonus:<move>` — DMG% for one kind of move. */
export const FORMULA_MOVE_BONUS_PREFIX = 'formula:dmg_bonus:';

/** The 4-piece set a combination reaches, or `null` if it reaches none. */
export function fourPieceSetOf(setCounts: Readonly<Record<number, number>>): number | null {
  for (const [setId, count] of Object.entries(setCounts)) {
    if (count >= 4) return Number(setId);
  }
  return null;
}

/**
 * Whether more Energy Recharge could change this recipe's score at all.
 *
 * The ladder is a step function of team DPS against ER. If every rung reports the same DPS the
 * rotation already bursts on time at the lowest ER measured, `energyRatio` returns 1 whatever
 * the candidate wears, and ER is dead weight — the same answer as having no ladder.
 *
 * A rung with no `dps` is not a flat rung; it is an unmeasured one, and is skipped rather than
 * read as agreement.
 */
function energyLadderVaries(recipe: Recipe): boolean {
  const sweep = recipe.meta.energySweep ?? [];
  const ers = sweep.map((point) => point.energyRecharge);
  if (!ers.length) return false;
  // **Read through `dpsAt`, not off the rungs.** `dpsAt` takes a running maximum, because more
  // ER cannot buy less and a ladder that decreases is reporting its noise. Comparing the raw
  // rungs would call a genuinely flat ladder "varying" whenever two runs disagreed, and keep
  // ER live — and so unpruned — for every search where it buys nothing.
  const lo = dpsAt(sweep, Math.min(...ers));
  const hi = dpsAt(sweep, Math.max(...ers));
  return lo !== null && hi !== null && hi > lo;
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
 *
 * ## Energy Recharge, and the bug this docstring predicted
 *
 * Reported from production: *"I just tried an Optimize run on this team with Furina, but no ER
 * sands were picked in any of the top optimizations."* ER became a scoring quantity when
 * `evaluateRecipe` started scaling by the energy ladder — and this function did not know, so
 * **every ER sands dominated on crit and ATK was discarded before it was ever scored**. The
 * ladder was working; nothing it could have changed survived to be ranked. Exactly the failure
 * the paragraph above describes, arriving through a stat rather than through a set.
 *
 * It is added **only when the ladder is not flat**. Above the ER threshold every rung returns
 * the same DPS, `energyRatio` is 1 for every candidate, and ER genuinely cannot change an
 * order — pruning on a quantity that provably does nothing would cost every search for the
 * benefit of none. So the condition is the same one the scorer uses.
 */
export function liveQuantitiesFor(...recipes: readonly Recipe[]): string[] {
  const live = new Set<string>(['crit_rate', 'crit_dmg']);
  if (recipes.some(energyLadderVaries)) live.add('energy_recharge');
  const parts: Record<string, string[]> = {
    atk: ['base_atk', 'atk_pct', 'flat_atk'],
    hp: ['base_hp', 'hp_pct', 'flat_hp'],
    def: ['base_def', 'def_pct', 'flat_def'],
  };
  for (const hit of recipes.flatMap((recipe) => recipe.hits)) {
    live.add(`${hit.element}${DMG_BONUS_SUFFIX}`);
    if (hit.scaling === 'em') live.add('elemental_mastery');
    else for (const q of parts[hit.scaling]) live.add(q);
    if (hit.ampMultiplier !== 1 || hit.amplifying !== undefined) live.add('elemental_mastery');
    // A formula hit reads a move-scoped and an all-channel bonus from set pools, and Emblem
    // reads ER. Pieces never carry the first two, but the bound's optimistic set term is
    // built from this list — leave them out and it under-states, which prunes a winner.
    if (hit.move !== undefined) {
      live.add(`${FORMULA_MOVE_BONUS_PREFIX}${hit.move}`);
      live.add(FORMULA_ALL_DMG_BONUS);
    }
    if (hit.bonusFromEnergyRecharge !== undefined) live.add('energy_recharge');
    if (hit.bonusFromEm !== undefined) live.add('elemental_mastery');
    for (const conversion of Object.values(hit.conversions)) {
      for (const q of parts[conversion.from]) live.add(q);
    }
  }
  return [...live].sort();
}

/** Score one combination against the recipe. */
/**
 * Every stat pool a combination contributes under one recipe, set bonuses included.
 *
 * Split out of `score` so that reading a combination's Energy Recharge and scoring its damage
 * cannot disagree about which bonuses apply. The calibrated-set rule below is the subtle part,
 * and one copy of it is the point.
 */
function poolsFor(
  recipe: Recipe,
  combination: readonly Candidate[],
  setCounts: Record<number, number>,
  bonusesBySet: Map<number, SetBonus[]>,
): Readonly<Record<string, number>>[] {
  const pools: Readonly<Record<string, number>>[] = combination.map((c) => c.stats);
  for (const [setId, count] of Object.entries(setCounts)) {
    // **Skip the set the recipe was calibrated with.** Equipping a set to calibrate also
    // applies its 2-piece, so it is already in every term of the recipe — adding the tier here
    // lands it twice. Other sets in the combination are not in the calibration and do belong.
    if (recipe.meta.calibratedSetIds.includes(Number(setId))) continue;
    for (const tier of bonusesBySet.get(Number(setId)) ?? []) {
      if (count >= tier.piecesRequired) pools.push(tier.stats);
    }
  }
  return pools;
}


function score(
  recipe: Recipe,
  combination: readonly Candidate[],
  setCounts: Record<number, number>,
  bonusesBySet: Map<number, SetBonus[]>,
): number {
  return evaluateRecipe(
    recipe, candidateStatsFrom(poolsFor(recipe, combination, setCounts, bonusesBySet)),
  );
}

/**
 * The best `topN` combinations by the rotation's total damage.
 *
 * ## One 4-piece state at a time
 *
 * The search runs **per 4-piece state** — once per selected set, once for "no 4-piece" — and
 * merges the results. That is not only how a user thinks about artifacts; it is what makes the
 * bound below sound. Within a state the recipe is **fixed**, so an optimistic completion can
 * be scored with the same function that scores a real one.
 *
 * It also collapses the space. A five-slot combination holding four pieces of set S leaves at
 * most **one** other piece, and a lone piece grants no set bonus — so a state's walk is
 * *S's own pieces* in four slots and anything in the fifth, partitioned by which slot is free
 * so nothing is counted twice.
 *
 * ## The bound
 *
 * Every live quantity is a **benefit**: more ATK, crit, EM or elemental bonus never lowers a
 * hit. So completing a partial combination with, per remaining slot, the largest value of each
 * quantity still available yields a stat vector that **dominates every real completion**, and
 * scoring it is an upper bound on anything in that subtree. When it cannot beat the current
 * N-th best, the whole subtree is discarded.
 *
 * The bound is **admissible**, so this stays an exact search — `isExact` is still `true`, and
 * it is not a "pruned subset" in the sense the UI warns about. A combination it skips is one
 * it has *proved* cannot place, which is a different act from sampling.
 *
 * Buckets are walked best-first by a single-piece score so the threshold rises early; the
 * bound is worthless while the heap is short, and this is what fills it fast.
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

  // The **union**, pair recipes included: a piece dominated under one recipe can be the
  // winner under another, and intersecting would make a lossless layer silently lossy.
  const live = liveQuantitiesFor(
    context.recipes.noFourPiece,
    ...context.recipes.byFourPieceSet.values(),
    ...(context.recipes.byPair?.values() ?? []),
  );
  const { kept, removed } = paretoFilter(bucketBySlot(candidates), live);
  const slotBuckets = SLOTS.map((s) => kept.get(s) ?? []);

  // **Pinned after the Pareto filter, never before.** The filter drops candidates dominated
  // within their own set, and a pinned piece is very often one of them — that is usually the
  // whole reason someone is asking about it. Restricting the bucket first and filtering second
  // would let the pin be thrown away and the search would quietly answer a different question.
  if (context.pinned) {
    const slot = SLOTS.indexOf(context.pinned.slot);
    if (slot < 0) {
      throw new Error(
        `pinned piece is in slot ${context.pinned.slot}, which is not one of the five the `
        + 'kernel searches; a pin the walk cannot place would silently be ignored',
      );
    }
    slotBuckets[slot] = [context.pinned];
  }

  const states: readonly (number | null)[] =
    context.fourPieceSets ?? [null, ...context.recipes.byFourPieceSet.keys()];

  const best: ScoredBuild[] = [];
  let evaluated = 0;
  let boundPruned = 0;

  /** Insertion into a short sorted array beats a heap at these sizes. */
  const offer = (
    damage: number,
    combination: readonly Candidate[],
    setCounts: Record<number, number>,
    recipe: Recipe,
  ): void => {
    if (best.length < topN || damage > best[best.length - 1].damage) {
      const build: ScoredBuild = {
        damage,
        artifactIds: combination.map((c) => c.id),
        setCounts: { ...setCounts },
        // **Resolved here and not in the walk.** Every evaluated combination reaches `offer`;
        // only the few that beat the threshold reach this branch, so reading a stat block is
        // paid for once per surviving build rather than once per candidate.
        energyRecharge: candidateStatsFrom(
          poolsFor(recipe, combination, setCounts, bonusesBySet),
        ).energyRecharge,
      };
      let i = best.length;
      while (i > 0 && best[i - 1].damage < damage) i -= 1;
      best.splice(i, 0, build);
      if (best.length > topN) best.pop();
    }
  };

  /** The stats a set contributes at `count` pieces — the bound's optimistic set term. */
  const setPool = (setId: number, count: number): Record<string, number> => {
    const pool: Record<string, number> = {};
    for (const tier of bonusesBySet.get(setId) ?? []) {
      if (count < tier.piecesRequired) continue;
      for (const [q, v] of Object.entries(tier.stats)) pool[q] = (pool[q] ?? 0) + v;
    }
    return pool;
  };

  /**
   * One bounded exhaustive walk over fixed per-slot buckets against one fixed recipe.
   *
   * `optimistic` is whatever set-bonus stats `score` may add that the bound cannot see. It is
   * added to the upper bound only — over-stating it costs speed, **under**-stating it would
   * prune a build that could have won, so it errs high by construction.
   */
  const walkBounded = (
    buckets: readonly (readonly Candidate[])[],
    recipe: Recipe,
    optimistic: Record<string, number>,
    excludeFourPiece: boolean,
  ): void => {
    if (buckets.some((b) => b.length === 0)) return;

    // Per remaining slot, the largest value of each live quantity, summed as a suffix so a
    // bound at depth d is one lookup rather than a scan.
    const suffix: Record<string, number>[] = new Array(buckets.length + 1);
    suffix[buckets.length] = optimistic;
    for (let d = buckets.length - 1; d >= 0; d -= 1) {
      const acc: Record<string, number> = { ...suffix[d + 1] };
      for (const q of live) {
        let most = 0;
        for (const c of buckets[d]) most = Math.max(most, c.stats[q] ?? 0);
        acc[q] = (acc[q] ?? 0) + most;
      }
      suffix[d] = acc;
    }

    const combination: Candidate[] = new Array(buckets.length);
    const counts = new Map<number, number>();

    const walk = (depth: number): void => {
      if (depth === buckets.length) {
        evaluated += 1;
        const setCounts: Record<number, number> = {};
        for (const [setId, n] of counts) if (n > 0) setCounts[setId] = n;
        offer(
          score(recipe, combination, setCounts, bonusesBySet),
          combination, setCounts, recipe,
        );
        return;
      }

      // Worthless while the heap is short — there is no threshold to beat yet.
      if (best.length === topN) {
        const pools = combination.slice(0, depth).map((c) => c.stats);
        pools.push(suffix[depth]);
        if (evaluateRecipe(recipe, candidateStatsFrom(pools)) <= best[best.length - 1].damage) {
          boundPruned += 1;
          return;
        }
      }

      for (const candidate of buckets[depth]) {
        const now = (counts.get(candidate.setId) ?? 0) + 1;
        // A combination reaching a 4-piece belongs to that set's state, not to this one.
        if (excludeFourPiece && now >= 4) continue;
        counts.set(candidate.setId, now);
        combination[depth] = candidate;
        walk(depth + 1);
        counts.set(candidate.setId, now - 1);
      }
    };
    walk(0);
  };

  /**
   * Best-first, so the bound has a real threshold as early as possible.
   *
   * Each piece is scored **once** and sorted on the cached value. Scoring inside the
   * comparator instead costs O(n log n) evaluations per slot — across 35 states and a real
   * inventory that is ~378,000 recipe evaluations spent only on deciding an order.
   */
  const ordered = (recipe: Recipe): Candidate[][] =>
    slotBuckets.map((bucket) => {
      const solo = new Map(
        bucket.map((c) => [c.id, evaluateRecipe(recipe, candidateStatsFrom([c.stats]))]),
      );
      return [...bucket].sort((a, b) => solo.get(b.id)! - solo.get(a.id)!);
    });

  const searched = new Set<number>();
  const uncoveredPairs: string[] = [];

  // ── 2+2 states ───────────────────────────────────────────────────────────────────────
  //
  // Two slots of A, two of B, one free, partitioned by which slots hold what. A pair is
  // ~1e6 combinations against a real inventory; all 595 pairs are not searchable, which is
  // why this is opt-in.
  for (const [a, b] of context.twoPiecePairs ?? []) {
    const key = pairKey(a, b);
    const recipe = context.recipes.byPair?.get(key);
    if (recipe === undefined) {
      uncoveredPairs.push(key);
      continue;
    }
    const buckets = ordered(recipe);
    const ofSet = (setId: number) => buckets.map((bucket) =>
      bucket.filter((c) => c.setId === setId));
    const aPieces = ofSet(a);
    const bPieces = ofSet(b);
    // Both sets are inside the calibration, so `score` skips them; nothing else can reach a
    // bonus tier off one spare piece.
    const optimistic = {};

    for (const [aSlots, bSlots, free] of TWO_PLUS_TWO_ASSIGNMENTS) {
      // **The fifth piece may belong to A or B** — three of a 2-piece set is a legal build
      // and its bonuses are the pair's. Left unguarded it would also be reached by a second
      // assignment (the same five pieces with a different slot called "free"), so one
      // representative is chosen: the free slot must out-rank that set's own two.
      const spare = buckets[free].filter((c) => {
        if (c.setId === a) return free > aSlots[1];
        if (c.setId === b) return free > bSlots[1];
        return true;
      });
      walkBounded(
        SLOTS.map((_, i) =>
          (i === free ? spare : aSlots.includes(i) ? aPieces[i] : bPieces[i])),
        recipe, optimistic, false,
      );
    }
  }

  for (const state of states) {
    if (state === null) {
      walkBounded(ordered(context.recipes.noFourPiece), context.recipes.noFourPiece,
        // Without a 4-piece, at most two sets can reach a bonus tier (2+2+1, or 3+2), so
        // twice the richest set's sub-4-piece stats cannot be beaten by any real combination.
        twiceRichest(bonusesBySet, live), true);
      continue;
    }
    const recipe = context.recipes.byFourPieceSet.get(state);
    if (recipe === undefined) continue;
    searched.add(state);

    const buckets = ordered(recipe);
    const mine = buckets.map((b) => b.filter((c) => c.setId === state));
    const other = buckets.map((b) => b.filter((c) => c.setId !== state));
    // Already inside the recipe when it was calibrated with this set; otherwise the bound has
    // to allow for `score` adding it.
    const optimistic = recipe.meta.calibratedSetIds.includes(state)
      ? {}
      : setPool(state, 5);

    walkBounded(mine, recipe, optimistic, false);                       // five of the set
    for (let free = 0; free < SLOTS.length; free += 1) {                // four, one slot free
      walkBounded(mine.map((b, i) => (i === free ? other[i] : b)), recipe, optimistic, false);
    }
  }

  // A set the inventory could field a 4-piece of, that nothing searched covers. Computed from
  // the buckets rather than from combinations, so it is one row per set.
  const slotsPerSet = new Map<number, Set<number>>();
  slotBuckets.forEach((bucket, i) => {
    for (const c of bucket) {
      const seen = slotsPerSet.get(c.setId) ?? new Set<number>();
      seen.add(i);
      slotsPerSet.set(c.setId, seen);
    }
  });
  const uncoveredSets = [...slotsPerSet]
    .filter(([setId, slots]) => slots.size >= 4 && !searched.has(setId))
    .map(([setId]) => setId)
    .sort((a, b) => a - b);

  return {
    builds: best,
    evaluated,
    paretoRemoved: removed,
    // The bound is admissible — it discards only what it has proved cannot place — so the
    // answer is still exact. A lossy layer would be the thing that makes this false, and
    // **this search has none**: the branch-and-bound is what lets it stay exhaustive where the
    // single-hit walk had to take budget-K. Hence zero, null, and the honest space below.
    isExact: true,
    prefiltered: 0,
    effectiveK: null,
    totalSpace: slotBuckets.reduce((total, bucket) => total * bucket.length, 1),
    uncoveredSets,
    uncoveredPairs,
    boundPruned,
  };
}

/**
 * Every way five slots split into 2 of A, 2 of B and one free — `C(5,2) x C(3,2) = 30`.
 *
 * Built once rather than nested loops at the call site, so the partition can be *read* and
 * checked against 30. Each slot pair is sorted, which the canonical-representative rule for
 * the spare piece relies on.
 */
const TWO_PLUS_TWO_ASSIGNMENTS: readonly (readonly [
  readonly [number, number], readonly [number, number], number,
])[] = (() => {
  const out: [readonly [number, number], readonly [number, number], number][] = [];
  const n = SLOTS.length;
  for (let a1 = 0; a1 < n; a1 += 1) {
    for (let a2 = a1 + 1; a2 < n; a2 += 1) {
      const rest = [...Array(n).keys()].filter((i) => i !== a1 && i !== a2);
      for (let i = 0; i < rest.length; i += 1) {
        for (let j = i + 1; j < rest.length; j += 1) {
          const free = rest.find((slot) => slot !== rest[i] && slot !== rest[j])!;
          out.push([[a1, a2], [rest[i], rest[j]], free]);
        }
      }
    }
  }
  return out;
})();

/** Twice the richest set's sub-4-piece stats: the loosest bonus a no-4-piece build can hold. */
function twiceRichest(
  bonusesBySet: Map<number, SetBonus[]>,
  live: readonly string[],
): Record<string, number> {
  const most: Record<string, number> = {};
  for (const tiers of bonusesBySet.values()) {
    for (const q of live) {
      let mine = 0;
      for (const tier of tiers) if (tier.piecesRequired <= 3) mine += tier.stats[q] ?? 0;
      most[q] = Math.max(most[q] ?? 0, mine);
    }
  }
  for (const q of Object.keys(most)) most[q] *= 2;
  return most;
}
