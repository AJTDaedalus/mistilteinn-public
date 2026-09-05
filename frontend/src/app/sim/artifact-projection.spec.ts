/**
 * `TASKS_artifact_ranking.md` A.5 — the projection, checked against hand-worked cases.
 *
 * Offline and deterministic on purpose: no recipe, no evaluator, no fixtures pulled from a
 * simulator. Every expected number below is one that can be worked out on paper from the
 * committed schedule and a ladder, which is what makes a failure here point at this module
 * rather than at whatever it was joined to.
 */

import { describe, expect, it } from 'vitest';
import {
  type DrawModel,
  type Piece,
  eligibleNewLines,
  projectPiece,
} from './artifact-projection';

/**
 * A deliberately round stand-in for the committed ladders.
 *
 * Values 1/2/3/4 rather than Genshin's real ones so that "mid tier" is exactly 2.5 and "all
 * five rolls at top tier" is exactly 20 — an expectation a reader can check without a
 * calculator, and one that would not survive a wrong tier being picked.
 */
const MODEL: DrawModel = {
  rollTiers: {
    '5': [
      { quantity: 'crit_dmg', values: [1, 2, 3, 4] },
      { quantity: 'crit_rate', values: [1, 2, 3, 4] },
      { quantity: 'atk_pct', values: [1, 2, 3, 4] },
      { quantity: 'flat_atk', values: [10, 20, 30, 40] },
      { quantity: 'energy_recharge', values: [1, 2, 3, 4] },
      { quantity: 'flat_hp', values: [1, 2, 3, 4] },
    ],
  },
  substatWeights: {
    crit_dmg: 3, crit_rate: 3, atk_pct: 4, flat_atk: 6, energy_recharge: 4, flat_hp: 6,
  },
  weightsCaveat: 'cited, not derived',
};

function piece(over: Partial<Piece> = {}): Piece {
  return {
    rarity: 5,
    stats: { crit_dmg: 100, crit_rate: 50, atk_pct: 10, flat_atk: 200 },
    mainStatQuantity: 'flat_atk',
    potential: {
      rollsRemaining: 5,
      rollsTotal: 5,
      gainsASubstat: false,
      substatQuantities: ['crit_dmg', 'crit_rate', 'atk_pct', 'flat_atk'],
    },
    ...over,
  };
}

describe('projectPiece', () => {
  it('returns null for a piece the schedule cannot answer for', () => {
    // Not a projection with zero rolls: zero is the honest answer for a maxed piece, so
    // collapsing the two would report a broken row as finished.
    expect(projectPiece(piece({ potential: null }), MODEL)).toBeNull();
  });

  it('projects a maxed piece to itself rather than treating it as an edge case', () => {
    const projected = projectPiece(
      piece({
        potential: {
          rollsRemaining: 0,
          rollsTotal: 5,
          gainsASubstat: false,
          substatQuantities: ['crit_dmg'],
        },
      }),
      MODEL,
    )!;
    expect(projected.average).toEqual(projected.current);
    expect(projected.bestCandidates[0].stats).toEqual(projected.current);
  });

  describe('a +0 five-star with four lines — five rolls, all of them deepening', () => {
    const projected = projectPiece(piece(), MODEL)!;

    it('spreads the average evenly over the four, at mid tier', () => {
      // Five rolls over four lines is 1.25 each; mid tier on a 1/2/3/4 ladder is 2.5.
      // Uniform per line, NOT weighted: which line an upgrade enhances is uniform over the
      // four, and only the *creation* draw is weighted.
      expect(projected.average.crit_dmg).toBeCloseTo(100 + 1.25 * 2.5, 10);
      expect(projected.average.crit_rate).toBeCloseTo(50 + 1.25 * 2.5, 10);
      // The flat ladder is ten times the others, and the same 1.25 rolls apply to it.
      expect(projected.average.flat_atk).toBeCloseTo(200 + 1.25 * 25, 10);
    });

    it('offers one best candidate per line, each with every roll at top tier', () => {
      expect(projected.bestCandidates).toHaveLength(4);
      expect(projected.bestCandidates.every((c) => c.newLine === null)).toBe(true);
      const onCritDmg = projected.bestCandidates.find((c) => c.target === 'crit_dmg')!;
      expect(onCritDmg.stats.crit_dmg).toBe(100 + 5 * 4);
      // Nothing else moved. A candidate that quietly improved another line would make every
      // "best" flattering by the same invisible amount.
      expect(onCritDmg.stats.crit_rate).toBe(50);
    });

    it('mirrors the worst case at the bottom tier', () => {
      const onCritDmg = projected.worstCandidates.find((c) => c.target === 'crit_dmg')!;
      expect(onCritDmg.stats.crit_dmg).toBe(100 + 5 * 1);
    });

    it('brackets the average between worst and best on every line', () => {
      for (const quantity of ['crit_dmg', 'crit_rate', 'atk_pct']) {
        const best = Math.max(...projected.bestCandidates.map((c) => c.stats[quantity] ?? 0));
        const worst = Math.min(...projected.worstCandidates.map((c) => c.stats[quantity] ?? 0));
        expect(projected.average[quantity]).toBeGreaterThanOrEqual(worst);
        expect(projected.average[quantity]).toBeLessThanOrEqual(best);
      }
    });
  });

  describe('a +0 five-star with three lines — one of the five creates the fourth', () => {
    const threeLiner = piece({
      stats: { crit_dmg: 100, crit_rate: 50, flat_atk: 200 },
      potential: {
        rollsRemaining: 5,
        rollsTotal: 5,
        gainsASubstat: true,
        substatQuantities: ['crit_dmg', 'crit_rate', 'flat_atk'],
      },
    });

    it('excludes the main stat and the existing lines from what the fourth could be', () => {
      // mainStatQuantity is flat_atk, which is also a line here; the pool is what is left.
      expect(eligibleNewLines(threeLiner, MODEL).sort()).toEqual([
        'atk_pct', 'energy_recharge', 'flat_hp',
      ]);
    });

    it('spends one roll creating the line and four deepening', () => {
      const projected = projectPiece(threeLiner, MODEL)!;
      const best = projected.bestCandidates.find(
        (c) => c.newLine === 'atk_pct' && c.target === 'atk_pct',
      )!;
      // One roll makes the line, the four free ones pile onto it: five top-tier rolls.
      expect(best.stats.atk_pct).toBe(5 * 4);

      const elsewhere = projected.bestCandidates.find(
        (c) => c.newLine === 'atk_pct' && c.target === 'crit_dmg',
      )!;
      // The line still appears and still costs its roll, even when nothing else lands there.
      expect(elsewhere.stats.atk_pct).toBe(4);
      expect(elsewhere.stats.crit_dmg).toBe(100 + 4 * 4);
    });

    it('enumerates every fourth line crossed with every target', () => {
      const projected = projectPiece(threeLiner, MODEL)!;
      // 3 candidate new lines x (3 existing + the new one) = 12.
      expect(projected.bestCandidates).toHaveLength(12);
    });

    it('charges the fourth line by weight, because that draw is the weighted one', () => {
      const projected = projectPiece(threeLiner, MODEL)!;
      // Pool is atk_pct (4), energy_recharge (4), flat_hp (6) = 14. Each gets its share of one
      // creating roll plus its share of the four free ones spread over four lines.
      const expected = (weight: number, mid: number) =>
        (weight / 14) * mid * (1 + 4 / 4);
      expect(projected.average.atk_pct).toBeCloseTo(expected(4, 2.5), 10);
      expect(projected.average.flat_hp).toBeCloseTo(expected(6, 2.5), 10);
      // Heavier stat, larger expected contribution — the ordering the weights exist to produce.
      expect(projected.average.flat_hp!).toBeGreaterThan(projected.average.atk_pct!);
    });

    it('is worth more than the same piece frozen at three lines', () => {
      // The point of the whole three-vs-four distinction: a three-liner has a line coming.
      const frozen = projectPiece(
        piece({
          stats: threeLiner.stats,
          potential: { ...threeLiner.potential!, gainsASubstat: false },
        }),
        MODEL,
      )!;
      const projected = projectPiece(threeLiner, MODEL)!;
      expect(frozen.average.atk_pct ?? 0).toBe(0);
      expect(projected.average.atk_pct!).toBeGreaterThan(0);
      // And the free rolls spread over the lines that exist, not over a hardcoded four. Five
      // rolls over three lines is 5/3 each, not 5/4 — a mutation to the divisor survived every
      // other assertion here, which is why this one is spelled out.
      expect(frozen.average.crit_dmg).toBeCloseTo(100 + (5 / 3) * 2.5, 10);
      expect(frozen.average.flat_atk).toBeCloseTo(200 + (5 / 3) * 25, 10);
    });
  });

  it('handles a three-star, which caps at +12 and gets three rolls', () => {
    const projected = projectPiece(
      piece({
        rarity: 3,
        stats: { crit_dmg: 10 },
        mainStatQuantity: 'flat_hp',
        potential: {
          rollsRemaining: 3,
          rollsTotal: 3,
          gainsASubstat: false,
          substatQuantities: ['crit_dmg'],
        },
      }),
      { ...MODEL, rollTiers: { '3': [{ quantity: 'crit_dmg', values: [1, 2, 3, 4] }] } },
    )!;
    expect(projected.bestCandidates[0].stats.crit_dmg).toBe(10 + 3 * 4);
  });

  it('skips a line with no ladder rather than treating it as worth zero', () => {
    // A quantity the rarity's table does not carry is a gap in the data, and silently adding
    // zero for it would make an unprojectable line look like a line with nothing to gain.
    const projected = projectPiece(
      piece({
        stats: { crit_dmg: 100, shield_strength: 5 },
        potential: {
          rollsRemaining: 5,
          rollsTotal: 5,
          gainsASubstat: false,
          substatQuantities: ['crit_dmg', 'shield_strength'],
        },
      }),
      MODEL,
    )!;
    expect(projected.bestCandidates.map((c) => c.target)).toEqual(['crit_dmg']);
    expect(projected.average.shield_strength).toBe(5);
  });
});
