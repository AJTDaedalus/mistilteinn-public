/**
 * The five-slot artifact search, in the browser.
 *
 * The **algorithms** are ported from `backend/app/services/artifact_optimizer.py` and
 * `artifact_prefilter.py` (G.1, G.3); the implementation is new. What ported is the
 * reasoning, not the code:
 *
 * - a bounded top-N heap, so a large inventory holds N builds rather than every build it has
 *   scored;
 * - the **lossless** Pareto layer — if a piece gives at least as much of every stat that can
 *   change this hit as another in the same slot and set, no combination containing the weaker
 *   one can win;
 * - `isExact`, which is False only when a *lossy* layer fired. Pareto pruning does not make
 *   an answer approximate, and saying it did would train a reader to ignore the flag on the
 *   runs where it means something.
 *
 * ## Budget-K is here now, and the reasoning that left it out was wrong
 *
 * This block used to read: *"Budget-K is deliberately not here. It exists in the Python
 * optimizer because a server is slow; DESIGN §2 expects the GPU to search exhaustively, so a
 * lossy layer would give up exactness to save time that is not being spent."*
 *
 * **The GPU searches nothing.** `sim/gpu.ts` exports `createGpuKernel` and, as of 2026-08-29,
 * **nothing in the app calls it** — every search runs this walk, on the main thread. So the
 * time was being spent after all.
 *
 * How much was measured rather than argued. On the owner's 2,370-piece inventory the lossless
 * layer removes 1,705 pieces and leaves buckets of **130 × 103 × 136 × 149 × 147**, which is
 * **3.99e10 combinations** — about **39 hours** at the cost measured below. The page did not
 * feel slow; it froze, for 227 seconds continuously before the measurement was abandoned,
 * because a synchronous walk cannot repaint.
 *
 * So the lossy layer ports, and `isExact` finally means something: it is the flag that tells
 * you the answer was bounded, and the day it is always true again will be the day the GPU is
 * wired up.
 */

import {
  type DamageInputs,
  type Hit,
  type ScalingStat,
  type Target,
  computeDamage,
  resolveStat,
} from './damage';

/** The five slots, in game order. Mirrors `artifact_optimizer.SLOTS`. */
export const SLOTS = [
  'equip_bracer',
  'equip_necklace',
  'equip_shoes',
  'equip_ring',
  'equip_dress',
] as const;

export type Slot = (typeof SLOTS)[number];

/** One owned piece. `stats` is a partial map of DAG quantity → value. */
export interface Candidate {
  id: string;
  slot: Slot;
  setId: number;
  stats: Readonly<Record<string, number>>;
}

/** One tier of one set's bonus, as `artifact_optimizer.SetBonus` stores it. */
export interface SetBonus {
  setId: number;
  piecesRequired: number;
  stats: Readonly<Record<string, number>>;
}

export interface SearchContext {
  /** The character-and-weapon half, already resolved. Does not vary across combinations. */
  base: Readonly<Record<string, number>>;
  hit: Hit;
  target: Target;
  characterLevel: number;
  /** Which damage-bonus quantity this hit reads, e.g. `cryo_dmg_bonus`. */
  dmgBonusQuantity: string;
  setBonuses?: readonly SetBonus[];
  topN?: number;
  /**
   * How many candidates per slot the lossy layer may keep.
   *
   * `undefined` or `null` means *decide* — search exactly if the inventory already fits the
   * wall-clock budget, otherwise keep the largest K that does. `EXACT` forces the full walk,
   * which on a real inventory is measured in hours; it exists so "prove it" is available, not
   * because anything should reach for it by default.
   */
  prefilterTopK?: number | null;
}

export interface ScoredBuild {
  damage: number;
  artifactIds: string[];
  setCounts: Record<number, number>;
  /**
   * The Energy Recharge this combination actually carries, set bonuses included.
   *
   * **Optional because only the recipe search can know it.** The kernel search below scores a
   * damage number and never resolves a stat block, so it leaves this undefined rather than
   * reporting a 0 that would read as "this build has no ER".
   *
   * Present so a row can say how many bursts it funds: a build that misses one is the whole
   * reason ER is weighed at all, and the rank alone cannot show it.
   */
  energyRecharge?: number;
}

export interface SearchResult {
  builds: ScoredBuild[];
  evaluated: number;
  paretoRemoved: number;
  /**
   * True when these builds are the true optimum over the inventory as given.
   *
   * **Only the lossy layer can make this false.** `paretoRemoved` deliberately does not feed
   * it: calling a Pareto-pruned search inexact would train a reader to ignore the flag on the
   * runs where it means something — `artifact_prefilter.PrefilterReport.is_exact` says the
   * same thing in the same words.
   */
  isExact: boolean;
  /** Candidates the lossy layer dropped. Removing them **can** change the answer. */
  prefiltered: number;
  /** The K budget-K used, or null when the search was exhaustive. */
  effectiveK: number | null;
  /** Combinations the buckets held before either layer ran. */
  totalSpace: number;
}

/** `prefilterTopK: EXACT` forces the exhaustive walk however long it will take. */
export const EXACT = -1;

/**
 * Wall-clock the automatic budget aims to keep a search under.
 *
 * **A policy choice, not a measurement** — the measurement is `SECONDS_PER_COMBINATION`.
 *
 * Five seconds, where the Python optimizer allows 300. The difference is not timidity: this
 * walk is synchronous on the main thread, so the budget is not "how long until an answer" but
 * *how long the page is dead* — no repaint, no progress, no cancel. A server can spend five
 * minutes in the background; a tab cannot spend five seconds of it lightly.
 */
export const COMBINATION_BUDGET_SECONDS = 5;

/**
 * Measured cost of one scored combination, in seconds.
 *
 * Produced by `scripts/bench-search.mjs` against the owner's real 2,370-piece inventory,
 * 2026-08-29: **3.301e-6** over 292,032 combinations and **3.493e-6** over 1,156,680. The
 * higher is taken, because the budget is a promise about wall-clock and a search that prunes
 * slightly early says so in its result while one that runs twice as long as promised does not.
 *
 * **Not borrowed from the server's 5.5e-4.** That is a different evaluator in a different
 * language, and `artifact_prefilter.py` states the rule this obeys: a borrowed timing is a
 * fabricated measurement.
 */
export const SECONDS_PER_COMBINATION = 3.5e-6;

/** How many combinations fit in the wall-clock target, from the measured per-combination cost. */
export function automaticBudget(): number {
  return Math.max(1, Math.floor(COMBINATION_BUDGET_SECONDS / SECONDS_PER_COMBINATION));
}

/** Size of the Cartesian product over the buckets. */
export function combinationCount(buckets: Iterable<readonly unknown[]>): number {
  let total = 1;
  for (const bucket of buckets) total *= bucket.length;
  return total;
}

/**
 * The K budget-K should use, or null to search exhaustively.
 *
 * A caller's explicit K wins, `EXACT` forces the full search, and `null` means *decide* — in
 * which case an inventory that already fits inside the budget is searched exactly, and one
 * that does not gets the **largest** K that fits, found by bisection rather than a fixed step
 * so the search gives up as little as the budget allows. Ported from
 * `artifact_prefilter.budget_k`, reasoning included.
 */
export function budgetK(
  buckets: readonly (readonly unknown[])[],
  requested: number | null | undefined,
  budget: number,
): number | null {
  if (requested === EXACT) return null;
  if (requested !== null && requested !== undefined) return requested;
  if (combinationCount(buckets) <= budget) return null;

  const sizes = buckets.map((b) => b.length);
  let low = 1;
  let high = Math.max(...sizes, 1);
  while (low < high) {
    const mid = Math.floor((low + high + 1) / 2);
    let product = 1;
    for (const size of sizes) product *= Math.min(size, mid);
    if (product <= budget) low = mid;
    else high = mid - 1;
  }
  return low;
}

/** Quantities that feed the resolved stats the chain reads. */
const SCALING_PARTS = {
  atk: ['base_atk', 'atk_pct', 'flat_atk'],
  hp: ['base_hp', 'hp_pct', 'flat_hp'],
  def: ['base_def', 'def_pct', 'flat_def'],
} as const;

function sum(pools: readonly Readonly<Record<string, number>>[], quantity: string): number {
  let total = 0;
  for (const pool of pools) total = Math.fround(total + (pool[quantity] ?? 0));
  return total;
}

/** One scaling stat's resolved value over the pools — EM is a plain sum, the rest compose. */
function scalingValueOf(stat: ScalingStat, pools: readonly Readonly<Record<string, number>>[]): number {
  if (stat === 'elemental_mastery') return sum(pools, 'elemental_mastery');
  const [base, pct, flat] = SCALING_PARTS[stat];
  return resolveStat(sum(pools, base), sum(pools, pct), sum(pools, flat));
}

/**
 * Which quantities can change this hit's damage.
 *
 * Projected rather than compared in full, for the reason `artifact_prefilter` gives: with
 * every stat in the comparison, one more point of a dead stat makes two pieces incomparable
 * and the lossless layer prunes almost nothing.
 *
 * Derived from the hit rather than probed. The Python version probes with the real evaluator
 * because a build can carry scope-gated contributions it cannot see statically; the kernel
 * has no scope-gated anything — the base is already resolved — so the live set is exactly
 * the scaling stat's parts, crit, EM when a reaction is involved, and the hit's own channel.
 */
export function liveQuantities(context: SearchContext): string[] {
  const live = new Set<string>(['crit_rate', 'crit_dmg', context.dmgBonusQuantity]);
  // Every term's stat, not only the first: a mixed-stat hit (`# ATK+# Elemental Mastery`)
  // gains from EM even though its first term is ATK, and pruning on ATK alone would drop
  // the piece that wins.
  for (const stat of [context.hit.scalingStat, ...(context.hit.extraTerms ?? []).map((t) => t.stat)]) {
    if (stat === 'elemental_mastery') live.add('elemental_mastery');
    else for (const q of SCALING_PARTS[stat]) live.add(q);
  }
  // EM only matters to damage when a reaction reads it.
  if (context.hit.amplifying !== null) live.add('elemental_mastery');
  return [...live].sort();
}

function vector(candidate: Candidate, quantities: readonly string[]): number[] {
  return quantities.map((q) => candidate.stats[q] ?? 0);
}

/**
 * Whether `a` makes `b` redundant: at least as much of everything, more of something.
 *
 * An exact tie qualifies too, with the lower id kept — otherwise two identical pieces each
 * dominate the other and **both** are removed, which is the one way this layer could lose a
 * build it exists to preserve.
 */
function dominates(a: number[], b: number[], aId: string, bId: string): boolean {
  let strictly = false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] < b[i]) return false;
    if (a[i] > b[i]) strictly = true;
  }
  return strictly || aId < bId;
}

/**
 * Drop candidates dominated within their `(slot, set)` group.
 *
 * Grouping by set as well as slot is what keeps this lossless: a strictly weaker piece of a
 * *different* set is not redundant, because it may complete a bonus worth more than the stats
 * it gives up.
 */
export function paretoFilter(
  bySlot: Map<Slot, Candidate[]>,
  quantities: readonly string[],
): { kept: Map<Slot, Candidate[]>; removed: number } {
  const kept = new Map<Slot, Candidate[]>();
  let removed = 0;

  for (const [slot, bucket] of bySlot) {
    const groups = new Map<number, Candidate[]>();
    for (const c of bucket) {
      const group = groups.get(c.setId);
      if (group) group.push(c);
      else groups.set(c.setId, [c]);
    }

    const dominated = new Set<string>();
    for (const group of groups.values()) {
      const vectors = new Map(group.map((c) => [c.id, vector(c, quantities)]));
      for (const c of group) {
        const mine = vectors.get(c.id)!;
        for (const other of group) {
          if (other.id === c.id) continue;
          if (dominates(vectors.get(other.id)!, mine, other.id, c.id)) {
            dominated.add(c.id);
            break;
          }
        }
      }
    }

    const survivors = bucket.filter((c) => !dominated.has(c.id));
    removed += bucket.length - survivors.length;
    kept.set(slot, survivors);
  }
  return { kept, removed };
}

/**
 * Group candidates by slot.
 *
 * Exported for `recipe-search.ts`, which runs the **same** exhaustive walk and the same
 * lossless Pareto layer over a different objective. Duplicating the bucketing there would be
 * two ways to decide what a slot is.
 */
export function bucketBySlot(candidates: readonly Candidate[]): Map<Slot, Candidate[]> {
  const bySlot = new Map<Slot, Candidate[]>(SLOTS.map((s) => [s, []]));
  for (const c of candidates) {
    const bucket = bySlot.get(c.slot);
    if (!bucket) throw new Error(`${c.id} is in slot ${c.slot}; the five are ${SLOTS.join(', ')}`);
    bucket.push(c);
  }
  const empty = SLOTS.filter((s) => bySlot.get(s)!.length === 0);
  if (empty.length > 0) {
    // The product of an empty bucket is empty, so the search would return no builds and no
    // reason. A user missing a goblet should be told that.
    throw new Error(`no candidates for ${empty.join(', ')}; every slot needs at least one`);
  }
  return bySlot;
}

/**
 * Score one combination through the same chain a single build's figure uses.
 *
 * `extra` is a stat pool that is not any piece's — the solo-scoring filler, and nothing else.
 * The walk never passes it, so the hot loop is unchanged.
 */
function score(
  context: SearchContext,
  combination: readonly Candidate[],
  bonusesBySet: Map<number, SetBonus[]>,
  extra?: Readonly<Record<string, number>>,
): { damage: number; setCounts: Record<number, number> } {
  const setCounts: Record<number, number> = {};
  for (const c of combination) setCounts[c.setId] = (setCounts[c.setId] ?? 0) + 1;

  const pools: Readonly<Record<string, number>>[] = [context.base, ...combination.map((c) => c.stats)];
  if (extra) pools.push(extra);
  for (const [setId, count] of Object.entries(setCounts)) {
    for (const tier of bonusesBySet.get(Number(setId)) ?? []) {
      if (count >= tier.piecesRequired) pools.push(tier.stats);
    }
  }

  const inputs: DamageInputs = {
    hit: context.hit,
    scalingValue: scalingValueOf(context.hit.scalingStat, pools),
    extraScalingValues: (context.hit.extraTerms ?? []).map((t) => scalingValueOf(t.stat, pools)),
    dmgBonus: sum(pools, context.dmgBonusQuantity),
    critRate: sum(pools, 'crit_rate'),
    critDmg: sum(pools, 'crit_dmg'),
    elementalMastery: sum(pools, 'elemental_mastery'),
    characterLevel: context.characterLevel,
    target: context.target,
  };
  return { damage: computeDamage(inputs), setCounts };
}

/**
 * The average inventory piece, scaled to the **four** slots a candidate does not fill.
 *
 * Solo scores are only ever compared with each other, so what matters is that every candidate
 * is valued at a realistic operating point rather than against a bare character. CRIT DMG on a
 * build with no CRIT Rate is worth nothing, and ranking pieces in that context would put every
 * CRIT DMG goblet at the bottom of the list.
 *
 * Four, not five: the candidate being scored fills the fifth slot itself, and scaling to five
 * would count it twice. `artifact_prefilter._reference_filler` makes the same argument, and
 * names the ZZZ version's factor of five as the thing it is not doing.
 */
function referenceFiller(
  buckets: readonly (readonly Candidate[])[],
  quantities: readonly string[],
): Record<string, number> {
  const totals: Record<string, number> = {};
  let count = 0;
  for (const bucket of buckets) {
    for (const candidate of bucket) {
      count += 1;
      for (const quantity of quantities) {
        totals[quantity] = (totals[quantity] ?? 0) + (candidate.stats[quantity] ?? 0);
      }
    }
  }
  if (!count) return {};
  const scale = 4 / count;
  const filler: Record<string, number> = {};
  for (const [quantity, total] of Object.entries(totals)) {
    if (total) filler[quantity] = total * scale;
  }
  return filler;
}

/**
 * Rank each candidate by what it is worth on an average build. O(inventory).
 *
 * **This is the heuristic, and it is why the result is disclosed rather than assumed.** It
 * cannot see set bonuses — they need four other pieces this scoring does not have — so a piece
 * that is only good because it completes a 4-piece ranks on its stats alone.
 */
export function soloScores(
  buckets: readonly (readonly Candidate[])[],
  context: SearchContext,
  quantities: readonly string[],
): Map<string, number> {
  const filler = referenceFiller(buckets, quantities);
  const scores = new Map<string, number>();
  for (const bucket of buckets) {
    for (const candidate of bucket) {
      // The real evaluator, not a proxy for it. The Python version probes because its chain
      // can carry scope-gated contributions; here the base is already resolved, so scoring a
      // candidate is the same call the walk makes.
      const { damage } = score(context, [candidate], new Map(), filler);
      scores.set(candidate.id, damage);
    }
  }
  return scores;
}

/**
 * Keep each slot's best K by solo score.
 *
 * Original bucket order is preserved, so a run is reproducible and a diff of two runs is
 * readable — `artifact_prefilter.apply_budget_k` does the same and for the same reason.
 *
 * **No floor-stat exception here, because this search has no floors.** The Python version
 * keeps the best piece for each floor quantity regardless of its damage rank, since a piece
 * can rank last on damage and still be the only one that gets a build over an Energy Recharge
 * floor. `SearchContext` carries no such constraint, so there is nothing to protect — and
 * adding the machinery for a constraint that cannot be expressed would be dead code claiming
 * to guard something.
 */
export function applyBudgetK(
  buckets: readonly (readonly Candidate[])[],
  k: number,
  scores: ReadonlyMap<string, number>,
): { kept: Candidate[][]; removed: number } {
  const kept: Candidate[][] = [];
  let removed = 0;
  for (const bucket of buckets) {
    if (bucket.length <= k) {
      kept.push([...bucket]);
      continue;
    }
    const survivors = new Set(
      [...bucket]
        .sort((a, b) => (scores.get(b.id) ?? 0) - (scores.get(a.id) ?? 0))
        .slice(0, k)
        .map((c) => c.id),
    );
    const ordered = bucket.filter((c) => survivors.has(c.id));
    removed += bucket.length - ordered.length;
    kept.push(ordered);
  }
  return { kept, removed };
}

/**
 * Search every allowed five-piece combination and return the best.
 *
 * The bounded top-N is a **memory** property, not a pruning heuristic: a search over a large
 * inventory holds N builds rather than every build it has scored. It changes nothing about
 * which build wins.
 */
export function search(candidates: readonly Candidate[], context: SearchContext): SearchResult {
  const topN = context.topN ?? 10;
  if (topN <= 0) throw new Error(`topN must be at least 1; got ${topN}`);

  const bonusesBySet = new Map<number, SetBonus[]>();
  for (const bonus of context.setBonuses ?? []) {
    const tiers = bonusesBySet.get(bonus.setId);
    if (tiers) tiers.push(bonus);
    else bonusesBySet.set(bonus.setId, [bonus]);
  }

  const bySlot = bucketBySlot(candidates);
  const totalSpace = combinationCount(SLOTS.map((s) => bySlot.get(s)!));
  const { kept, removed } = paretoFilter(bySlot, liveQuantities(context));
  // Lossless first: it shrinks the buckets the budget estimator then sizes K against. Running
  // the lossy layer first would spend the budget on candidates Pareto was about to remove for
  // free — `artifact_prefilter` opens with the same sentence.
  let buckets = SLOTS.map((s) => kept.get(s)!);

  const k = budgetK(buckets, context.prefilterTopK, automaticBudget());
  let prefiltered = 0;
  if (k !== null) {
    const scores = soloScores(buckets, context, liveQuantities(context));
    const applied = applyBudgetK(buckets, k, scores);
    buckets = applied.kept;
    prefiltered = applied.removed;
  }

  const best: ScoredBuild[] = [];
  let evaluated = 0;

  const combination: Candidate[] = new Array(SLOTS.length);
  const walk = (depth: number): void => {
    if (depth === SLOTS.length) {
      evaluated += 1;
      const { damage, setCounts } = score(context, combination, bonusesBySet);
      // Insertion into a small sorted array beats a heap at these sizes and keeps the result
      // ordered without a final sort.
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

  return {
    builds: best,
    evaluated,
    paretoRemoved: removed,
    // Only the lossy layer can make this false. Pareto pruning does not.
    isExact: prefiltered === 0,
    prefiltered,
    effectiveK: prefiltered === 0 ? null : k,
    totalSpace,
  };
}
