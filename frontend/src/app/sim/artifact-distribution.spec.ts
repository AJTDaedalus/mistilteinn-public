import { describe, expect, it } from 'vitest';

import {
  lineOutcomes,
  quadrinomialRow,
  rollSplits,
  tierSums,
} from './artifact-distribution';

/**
 * `TASKS_artifact_ranking.md` A.13 — the probability model, checked by hand.
 *
 * Every expectation here is either a closed form anyone can verify (`(1+x+x²+x³)ⁿ`, a
 * multinomial, a draw without replacement) or a total that must be 1. Nothing is compared
 * against a simulator, because there is no Monte Carlo in the model to compare to.
 */

const sum = (values: readonly number[]) => values.reduce((a, b) => a + b, 0);

describe('quadrinomialRow', () => {
  it('is the coefficients of (1 + x + x^2 + x^3)^n', () => {
    expect(quadrinomialRow(0)).toEqual([1]);
    expect(quadrinomialRow(1)).toEqual([1, 1, 1, 1]);
    // (1+x+x²+x³)² = 1 + 2x + 3x² + 4x³ + 3x⁴ + 2x⁵ + x⁶ — OEIS A008287 row 2.
    expect(quadrinomialRow(2)).toEqual([1, 2, 3, 4, 3, 2, 1]);
    expect(quadrinomialRow(3)).toEqual([1, 3, 6, 10, 12, 12, 10, 6, 3, 1]);
  });

  it('has 3n + 1 terms summing to 4^n, which is every ordering accounted for', () => {
    for (const n of [1, 3, 6, 9]) {
      const row = quadrinomialRow(n);
      expect(row).toHaveLength(3 * n + 1);
      expect(sum(row)).toBe(4 ** n);
    }
  });
});

describe('tierSums', () => {
  it('treats no rolls as one certain outcome of nothing', () => {
    // Not an empty list: a maxed piece is the common case on an equipped build, and no outcomes
    // would make the distribution vanish rather than collapse onto a point.
    expect(tierSums(0)).toEqual([{ tenths: 0, multiple: 0, p: 1 }]);
  });

  it('spans 70% to 100% of a max roll for one roll, uniformly', () => {
    const one = tierSums(1);
    expect(one.map((t) => t.multiple)).toEqual([0.7, 0.8, 0.9, 1]);
    expect(one.every((t) => t.p === 0.25)).toBe(true);
  });

  it('gives two rolls 7 totals with the 1/2/3/4/3/2/1 shape', () => {
    const two = tierSums(2);
    expect(two).toHaveLength(7);
    expect(two[0]).toMatchObject({ tenths: 14, p: 1 / 16 });
    // The mode: 4 of 16 orderings sum to 1.7 max rolls.
    expect(two[3]).toMatchObject({ tenths: 17, p: 4 / 16 });
    expect(two[6]).toMatchObject({ tenths: 20, p: 1 / 16 });
  });

  it('is a probability distribution for every roll count a piece can have', () => {
    // Six is the ceiling: one initial roll plus five upgrades all landing on one line.
    for (const rolls of [0, 1, 2, 3, 4, 5, 6]) {
      expect(sum(tierSums(rolls).map((t) => t.p))).toBeCloseTo(1, 12);
    }
  });

  it('has a mean of 0.85 max rolls per roll, which is the tiers unweighted', () => {
    // `subMuVar` takes an unweighted mean over 0.7/0.8/0.9/1.0. If this drifts, `average` in
    // artifact-projection.ts and this distribution's mean have stopped describing one model.
    for (const rolls of [1, 3, 5]) {
      const mean = tierSums(rolls).reduce((acc, t) => acc + t.p * t.multiple, 0);
      expect(mean).toBeCloseTo(0.85 * rolls, 10);
    }
  });
});

describe('rollSplits', () => {
  it('enumerates C(n + lines - 1, lines - 1) splits', () => {
    // 5 rolls over 4 lines is C(8,3) = 56.
    expect(rollSplits(5, 4)).toHaveLength(56);
    expect(rollSplits(3, 4)).toHaveLength(20);
  });

  it('is a multinomial with p = 1/lines, not weighted by anything', () => {
    // **The distinction the whole model rests on.** Which line an upgrade enhances is uniform;
    // only the draw that *creates* a line is weighted. Conflating them overstates CRIT DMG.
    const splits = rollSplits(2, 4);
    const allOnOne = splits.find((s) => s.counts[0] === 2)!;
    const oneEach = splits.find((s) => s.counts[0] === 1 && s.counts[1] === 1)!;
    expect(allOnOne.p).toBeCloseTo(1 / 16, 12);
    // Two orderings reach one-each, so it is twice as likely as both landing on the same line.
    expect(oneEach.p).toBeCloseTo(2 / 16, 12);
  });

  it('sums to one for every case a real piece reaches', () => {
    for (const n of [0, 1, 2, 3, 4, 5]) {
      expect(sum(rollSplits(n, 4).map((s) => s.p))).toBeCloseTo(1, 12);
    }
  });

  it('puts every roll on the only line there is', () => {
    expect(rollSplits(5, 1)).toEqual([{ counts: [5], p: 1 }]);
  });
});

describe('lineOutcomes', () => {
  const pool = { crit_dmg: 3, crit_rate: 3, atk_pct: 4, flat_hp: 6 };

  it('treats a four-line piece as having nothing to draw', () => {
    expect(lineOutcomes(pool, 0)).toEqual([{ added: [], p: 1 }]);
  });

  it('draws one line in proportion to weight', () => {
    const one = lineOutcomes(pool, 1);
    const total = 3 + 3 + 4 + 6;
    expect(one).toHaveLength(4);
    expect(one.find((o) => o.added[0] === 'flat_hp')!.p).toBeCloseTo(6 / total, 12);
    expect(one.find((o) => o.added[0] === 'crit_dmg')!.p).toBeCloseTo(3 / total, 12);
  });

  it('renormalises after each draw, which is what "without replacement" means', () => {
    // P(flat_hp then crit_dmg) = 6/16 x 3/10. An independent-weights approximation would say
    // 6/16 x 3/16, which overstates two heavy stats appearing together.
    const two = lineOutcomes(pool, 2);
    const path = two.find((o) => o.added[0] === 'flat_hp' && o.added[1] === 'crit_dmg')!;
    expect(path.p).toBeCloseTo((6 / 16) * (3 / 10), 12);
  });

  it('sums to one at every draw count the pool can support', () => {
    for (const draws of [0, 1, 2, 3, 4]) {
      expect(sum(lineOutcomes(pool, draws).map((o) => o.p))).toBeCloseTo(1, 12);
    }
  });

  it('returns nothing when more lines are asked for than exist', () => {
    // Honest rather than clamped: there is no such artifact, and a clamped answer would be a
    // probability distribution over an impossible piece.
    expect(lineOutcomes(pool, 5)).toEqual([]);
  });

  it('is unaffected by the order the pool happens to be keyed in', () => {
    const reversed = {
      flat_hp: 6, atk_pct: 4, crit_rate: 3, crit_dmg: 3,
    };
    const byKey = (outcomes: { added: string[]; p: number }[]) =>
      new Map(outcomes.map((o) => [o.added.join('>'), o.p]));
    const a = byKey(lineOutcomes(pool, 2));
    const b = byKey(lineOutcomes(reversed, 2));
    expect(a.size).toBe(b.size);
    for (const [key, p] of a) expect(b.get(key)).toBeCloseTo(p, 12);
  });
});
