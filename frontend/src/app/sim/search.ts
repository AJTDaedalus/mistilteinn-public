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
 * Budget-K is deliberately **not** here. It exists in the Python optimizer because a server
 * is slow; DESIGN §2 expects the GPU to search exhaustively, so a lossy layer would give up
 * exactness to save time that is not being spent. `isExact` is kept anyway — a flag that is
 * always true today is still the flag that tells you about the day it is not.
 */

import { type DamageInputs, type Hit, type Target, computeDamage, resolveStat } from './damage';

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
}

export interface ScoredBuild {
  damage: number;
  artifactIds: string[];
  setCounts: Record<number, number>;
}

export interface SearchResult {
  builds: ScoredBuild[];
  evaluated: number;
  paretoRemoved: number;
  /** True when these builds are the true optimum over the inventory as given. */
  isExact: boolean;
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
  if (context.hit.scalingStat === 'elemental_mastery') {
    live.add('elemental_mastery');
  } else {
    for (const q of SCALING_PARTS[context.hit.scalingStat]) live.add(q);
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

/** Score one combination through the same chain a single build's figure uses. */
function score(
  context: SearchContext,
  combination: readonly Candidate[],
  bonusesBySet: Map<number, SetBonus[]>,
): { damage: number; setCounts: Record<number, number> } {
  const setCounts: Record<number, number> = {};
  for (const c of combination) setCounts[c.setId] = (setCounts[c.setId] ?? 0) + 1;

  const pools: Readonly<Record<string, number>>[] = [context.base, ...combination.map((c) => c.stats)];
  for (const [setId, count] of Object.entries(setCounts)) {
    for (const tier of bonusesBySet.get(Number(setId)) ?? []) {
      if (count >= tier.piecesRequired) pools.push(tier.stats);
    }
  }

  const scalingValue =
    context.hit.scalingStat === 'elemental_mastery'
      ? sum(pools, 'elemental_mastery')
      : resolveStat(
          sum(pools, SCALING_PARTS[context.hit.scalingStat][0]),
          sum(pools, SCALING_PARTS[context.hit.scalingStat][1]),
          sum(pools, SCALING_PARTS[context.hit.scalingStat][2]),
        );

  const inputs: DamageInputs = {
    hit: context.hit,
    scalingValue,
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

  const { kept, removed } = paretoFilter(bucketBySlot(candidates), liveQuantities(context));
  const buckets = SLOTS.map((s) => kept.get(s)!);

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
    // Only a lossy layer can make this false, and there is none here — see the module
    // docstring on why budget-K did not port.
    isExact: true,
  };
}
