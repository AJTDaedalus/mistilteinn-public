import { describe, expect, it } from 'vitest';

import {
  EXACT,
  SLOTS,
  type Candidate,
  type SearchContext,
  type Slot,
  applyBudgetK,
  automaticBudget,
  budgetK,
  search,
  soloScores,
} from './search';

/**
 * Budget-K in the browser search.
 *
 * **The layer exists because the exhaustive walk cannot finish.** Measured on the owner's
 * 2,370-piece inventory: the lossless layer leaves 130 × 103 × 136 × 149 × 147 — 3.99e10
 * combinations, about 39 hours at 3.5 µs each — and because the walk is synchronous the page
 * does not go slow, it goes dead. A headless browser could not repaint for 227 seconds.
 *
 * These tests are about the two things that would go wrong quietly: a search that says it is
 * exact when it pruned, and a K chosen without regard to the budget it exists to respect.
 */

const CONTEXT: SearchContext = {
  base: { base_atk: 1000, base_hp: 20000, base_def: 800, crit_rate: 0.05, crit_dmg: 0.5 },
  hit: {
    multiplier: 2, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0,
    amplifying: null, reactionBonus: 0,
  },
  target: { level: 90, resistance: 0.1, defReduction: 0, defIgnore: 0 },
  characterLevel: 90,
  dmgBonusQuantity: 'hydro_dmg_bonus',
  setBonuses: [],
  topN: 5,
};

/** `n` pieces per slot, each strictly better than the last on ATK. */
function inventory(n: number): Candidate[] {
  return SLOTS.flatMap((slot: Slot) =>
    Array.from({ length: n }, (_, i) => ({
      id: `${slot}-${i}`,
      slot,
      setId: 0,
      stats: { flat_atk: i + 1 },
    })),
  );
}

/**
 * `n` pieces per slot that **trade off**, so the lossless layer removes none of them.
 *
 * `inventory` above is a ladder — each piece dominates the one below, and Pareto correctly
 * flattens every bucket to one. That is the right fixture for the ranking tests and the wrong
 * one for anything about the search *space*, which is a mistake worth leaving a fixture behind
 * to prevent: the first draft of these tests asserted a 243-combination space against a search
 * that had honestly reduced it to 1.
 */
function tradeoffs(n: number): Candidate[] {
  return SLOTS.flatMap((slot: Slot) =>
    Array.from({ length: n }, (_, i) => ({
      id: `${slot}-${i}`,
      slot,
      setId: 0,
      stats: { flat_atk: i + 1, crit_rate: (n - i) / 100 },
    })),
  );
}

describe('budgetK', () => {
  const buckets = [Array(10).fill(0), Array(10).fill(0), Array(10).fill(0)];

  it('searches exhaustively when the inventory already fits', () => {
    // 1,000 combinations against a budget of 5,000. Pruning here would give up exactness to
    // save time that is not being spent — the exact argument the old docstring made about the
    // whole layer, which is right at this scale and wrong at a real one.
    expect(budgetK(buckets, undefined, 5_000)).toBeNull();
  });

  it('takes the largest K that fits, not a round number', () => {
    // Bisection rather than a fixed step, so the search gives up as little as the budget
    // allows: 7^3 = 343 fits under 400 and 8^3 = 512 does not.
    expect(budgetK(buckets, undefined, 400)).toBe(7);
  });

  it("honours a caller's explicit K over the budget", () => {
    expect(budgetK(buckets, 3, 5_000)).toBe(3);
  });

  it('forces the full walk on EXACT, however long that is', () => {
    // "Prove it" has to remain available, or the flag saying the answer is unproven is a dead
    // end rather than a caveat.
    expect(budgetK(buckets, EXACT, 1)).toBeNull();
  });

  it('never returns zero, which would search nothing at all', () => {
    expect(budgetK(buckets, undefined, 1)).toBe(1);
  });

  it('derives its budget from the measured per-combination cost', () => {
    // A budget hardcoded as a count would silently mean a different wall-clock the moment the
    // hot loop changed. `scripts/bench-search.mjs` re-derives the cost.
    expect(automaticBudget()).toBeGreaterThan(1_000_000);
    expect(automaticBudget()).toBeLessThan(2_000_000);
  });
});

describe('applyBudgetK', () => {
  it('keeps the best K per slot and reports how many it dropped', () => {
    const buckets = SLOTS.map((slot) =>
      inventory(6).filter((c) => c.slot === slot),
    );
    const scores = soloScores(buckets, CONTEXT, ['flat_atk']);

    const { kept, removed } = applyBudgetK(buckets, 2, scores);

    expect(kept.map((b) => b.length)).toEqual([2, 2, 2, 2, 2]);
    expect(removed).toBe(20);
    // The two highest-ATK pieces, and in the bucket's original order — a run has to be
    // reproducible and a diff of two runs readable.
    expect(kept[0].map((c) => c.id)).toEqual(['equip_bracer-4', 'equip_bracer-5']);
  });

  it('leaves a bucket smaller than K alone', () => {
    const buckets = [inventory(2).filter((c) => c.slot === 'equip_bracer')];
    const scores = soloScores(buckets, CONTEXT, ['flat_atk']);

    expect(applyBudgetK(buckets, 5, scores).removed).toBe(0);
  });
});

describe('search with the budget layer', () => {
  it('stays exact, and says so, when nothing was pruned by rank', () => {
    const result = search(tradeoffs(3), CONTEXT);

    expect(result.isExact).toBe(true);
    expect(result.prefiltered).toBe(0);
    expect(result.effectiveK).toBeNull();
    expect(result.evaluated).toBe(3 ** 5);
  });

  it('reports the space it did not search rather than only that it pruned', () => {
    // "Not exact" alone invites a reader to assume a rounding. The count is the claim, and
    // `totalSpace` is the raw product **before either layer**, which is the number a user is
    // being told was not searched.
    const result = search(tradeoffs(4), { ...CONTEXT, prefilterTopK: 2 });

    expect(result.isExact).toBe(false);
    expect(result.effectiveK).toBe(2);
    expect(result.prefiltered).toBe(10);
    expect(result.totalSpace).toBe(4 ** 5);
    expect(result.evaluated).toBe(2 ** 5);
  });

  it('does not call a Pareto-pruned search inexact', () => {
    // Two identical-by-domination pieces per slot: the lossless layer removes one of each and
    // the answer is unchanged. Reporting that as inexact would train a reader to ignore the
    // flag on the runs where it means something.
    const candidates = SLOTS.flatMap((slot: Slot) => [
      { id: `${slot}-weak`, slot, setId: 0, stats: { flat_atk: 1 } },
      { id: `${slot}-strong`, slot, setId: 0, stats: { flat_atk: 100 } },
    ]);

    const result = search(candidates, CONTEXT);

    expect(result.paretoRemoved).toBeGreaterThan(0);
    expect(result.isExact).toBe(true);
  });

  it('can never beat the exhaustive answer, only fail to reach it', () => {
    // The invariant that actually holds. The layer is lossy by construction, so asserting the
    // same winner would be asserting the heuristic is right — which is the one thing a lossy
    // layer does not promise. What it may never do is *exceed* the true optimum, because it
    // searches a subset of the same space with the same evaluator.
    const exact = search(tradeoffs(4), { ...CONTEXT, prefilterTopK: EXACT });
    const bounded = search(tradeoffs(4), { ...CONTEXT, prefilterTopK: 2 });

    expect(bounded.builds[0].damage).toBeLessThanOrEqual(exact.builds[0].damage);
  });

  it('finds the obvious winner when one piece per slot is strictly best', () => {
    // A ladder inventory: the lossless layer alone reduces every bucket to its best piece, so
    // the budget layer never fires and the answer is exact and obvious. A search that lost
    // this would be broken rather than approximate.
    const result = search(inventory(4), CONTEXT);

    expect(result.isExact).toBe(true);
    expect(result.builds[0].artifactIds.every((id) => id.endsWith('-3'))).toBe(true);
  });
});

describe('soloScores', () => {
  it('values every candidate at a realistic operating point, not against a bare character', () => {
    // CRIT DMG on a build with no CRIT Rate is worth nothing, so scoring a piece alone would
    // put every CRIT DMG goblet at the bottom of the list. The filler is the average inventory
    // piece scaled to the four slots the candidate does not fill.
    const buckets = SLOTS.map((slot) => [
      { id: `${slot}-crit`, slot, setId: 0, stats: { crit_dmg: 0.5 } },
      { id: `${slot}-rate`, slot, setId: 0, stats: { crit_rate: 0.2 } },
    ] as Candidate[]);

    const scores = soloScores(buckets, CONTEXT, ['crit_rate', 'crit_dmg']);

    // With CRIT Rate in the filler, the CRIT DMG piece is worth something rather than nothing.
    expect(scores.get('equip_bracer-crit')).toBeGreaterThan(0);
    expect(scores.size).toBe(10);
  });
});
