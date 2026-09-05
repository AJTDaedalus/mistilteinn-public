import { describe, expect, it } from 'vitest';

import type { DrawModel, Piece } from './artifact-projection';
import { projectPiece } from './artifact-projection';
import { outcomeDistribution } from './artifact-outcome';

/**
 * `TASKS_artifact_ranking.md` A.14 — the distribution over damage, and the identity that checks
 * it against A.5.
 *
 * The evaluator is a stand-in rather than a recipe: what is under test is the enumeration and
 * the bookkeeping, and a real recipe would make a failure ambiguous between the two.
 */

const MODEL: DrawModel = {
  rollTiers: {
    '5': [
      { quantity: 'atk_pct', values: [0.04, 0.05, 0.06, 0.07] },
      { quantity: 'crit_rate', values: [0.02, 0.03, 0.035, 0.039] },
      { quantity: 'crit_dmg', values: [0.05, 0.06, 0.07, 0.078] },
      { quantity: 'flat_hp', values: [200, 230, 260, 300] },
    ],
  },
  substatWeights: { atk_pct: 4, crit_rate: 3, crit_dmg: 3, flat_hp: 6 },
  weightsCaveat: 'cited, not derived',
};

function piece(over: Partial<Piece> = {}): Piece {
  return {
    rarity: 5,
    stats: { atk_pct: 0.466, crit_rate: 0.039, crit_dmg: 0.078, flat_hp: 300 },
    mainStatQuantity: 'atk_pct',
    potential: {
      rollsRemaining: 3, rollsTotal: 5, gainsASubstat: false,
      substatQuantities: ['crit_rate', 'crit_dmg', 'flat_hp'],
    },
    ...over,
  };
}

/** Strictly linear in the stats — so `E[f(X)]` and `f(E[X])` must agree exactly. */
const linear = (stats: Record<string, number>) =>
  1000 + 5000 * (stats['crit_rate'] ?? 0) + 3000 * (stats['crit_dmg'] ?? 0)
  + 2 * (stats['flat_hp'] ?? 0) + 400 * (stats['atk_pct'] ?? 0);

/** Multiplicative the way real damage is: crit rate times crit damage. */
const withCrit = (stats: Record<string, number>) =>
  1000 * (1 + (stats['atk_pct'] ?? 0))
  * (1 + Math.min(stats['crit_rate'] ?? 0, 1) * (stats['crit_dmg'] ?? 0));

describe('outcomeDistribution', () => {
  it('refuses a piece the schedule cannot answer for', () => {
    // Not a one-outcome distribution: "no schedule" is not an outcome.
    expect(outcomeDistribution(piece({ potential: null }), MODEL, linear)).toBeNull();
  });

  it('is a probability distribution', () => {
    const found = outcomeDistribution(piece(), MODEL, linear)!;
    const total = found.bins.reduce((a, b) => a + b.p, 0);
    expect(total).toBeCloseTo(1, 10);
    expect(found.outcomes).toBeGreaterThan(1);
  });

  it('bins ascending and contiguously, so the chart cannot show a gap that is not there', () => {
    const found = outcomeDistribution(piece(), MODEL, linear)!;
    for (let i = 1; i < found.bins.length; i += 1) {
      expect(found.bins[i].from).toBeCloseTo(found.bins[i - 1].to, 9);
      expect(found.bins[i].to).toBeGreaterThan(found.bins[i].from);
    }
  });

  describe('the identity that checks this against A.5', () => {
    it('agrees with the projection exactly when damage is linear in the stats', () => {
      // **This is the real check.** The expected stat pool is linear in the rolls, so the
      // distribution's mean pool IS artifact-projection's `average` pool — and where the
      // objective is linear too, the two damage numbers must coincide with no tolerance to
      // argue about.
      const found = outcomeDistribution(piece(), MODEL, linear)!;
      expect(found.mean).toBeCloseTo(found.atAverage, 8);
      expect(found.curvature).toBeCloseTo(0, 8);
    });

    it('reproduces artifact-projection.average, which is where atAverage comes from', () => {
      const p = piece();
      const projected = projectPiece(p, MODEL)!;
      const found = outcomeDistribution(p, MODEL, linear)!;
      expect(found.atAverage).toBeCloseTo(linear(projected.average), 6);
    });

    it('separates from it once the objective multiplies, and the gap is signed', () => {
      // **DESIGN §5's "the two cannot disagree" is true of stats and false of damage.**
      //
      // And the sign is not the obvious one. `cr * cd` is a saddle, not a convex function, so
      // Jensen alone says nothing — what decides it is that the rolls **compete**: a roll on
      // CRIT Rate is a roll not on CRIT DMG, so their counts are negatively correlated under
      // the multinomial and `E[cr·cd] < E[cr]·E[cd]`.
      //
      // So the point estimate **overstates** expected damage, and A.5's `average` is optimistic
      // by exactly the covariance it cannot see. That is worth reporting rather than tuning
      // away.
      const found = outcomeDistribution(piece(), MODEL, withCrit)!;
      expect(found.curvature).not.toBeCloseTo(0, 6);
      expect(found.mean).toBeLessThan(found.atAverage);
    });
  });

  describe('probability of upgrade', () => {
    it('is 1 when every outcome adds something and the objective rewards it', () => {
      // Three rolls left, all landing somewhere the linear objective pays for.
      const found = outcomeDistribution(piece(), MODEL, linear)!;
      expect(found.probabilityOfUpgrade).toBeCloseTo(1, 10);
    });

    it('is 0 for a piece with nothing left, because nothing can change', () => {
      const maxed = piece({
        potential: {
          rollsRemaining: 0, rollsTotal: 5, gainsASubstat: false,
          substatQuantities: ['crit_rate', 'crit_dmg', 'flat_hp'],
        },
      });
      const found = outcomeDistribution(maxed, MODEL, linear)!;
      expect(found.probabilityOfUpgrade).toBe(0);
      expect(found.mean).toBeCloseTo(found.current, 9);
    });

    it('ignores stats the objective does not read', () => {
      // A piece whose only remaining rolls land on a stat worth nothing cannot become an
      // upgrade, and a model that said otherwise would be recommending resin for no damage.
      const hpOnly = piece({
        stats: { flat_hp: 300 },
        mainStatQuantity: 'flat_hp',
        potential: {
          rollsRemaining: 3, rollsTotal: 5, gainsASubstat: false,
          substatQuantities: ['flat_hp'],
        },
      });
      const found = outcomeDistribution(hpOnly, MODEL, (s) => 1000 * (1 + (s['atk_pct'] ?? 0)))!;
      expect(found.probabilityOfUpgrade).toBe(0);
    });
  });

  describe('a piece that will gain a fourth line', () => {
    const threeLiner = (over: Partial<Piece> = {}) => piece({
      stats: { atk_pct: 0.466, crit_rate: 0.039, crit_dmg: 0.078 },
      potential: {
        rollsRemaining: 3, rollsTotal: 5, gainsASubstat: true,
        substatQuantities: ['crit_rate', 'crit_dmg'],
      },
      ...over,
    });

    it('spends one of its rolls creating the line, so it has fewer free ones', () => {
      // **Not "more outcomes".** The first draft of this test assumed a three-liner enumerates
      // more than a four-liner because the new line is uncertain — but it also has one fewer
      // free roll, and with this model's pool exactly one candidate for the line. Fewer.
      const four = outcomeDistribution(piece(), MODEL, linear)!;
      const three = outcomeDistribution(threeLiner(), MODEL, linear)!;
      expect(three.outcomes).toBeLessThan(four.outcomes);
      expect(three.bins.reduce((a, b) => a + b.p, 0)).toBeCloseTo(1, 10);
    });

    it('sums over every substat the line could be', () => {
      // **The same piece, two pools.** Comparing differently shaped pieces confounds the pool
      // with the line count — which is what the first two drafts of this test did. Holding the
      // piece fixed and widening only what the fourth line could be isolates the sum.
      const narrowModel: DrawModel = {
        ...MODEL,
        // Only flat_hp is left once the main stat and existing lines are removed.
        substatWeights: { atk_pct: 4, crit_rate: 3, crit_dmg: 3, flat_hp: 6 },
      };
      const widerModel: DrawModel = {
        ...MODEL,
        rollTiers: {
          '5': [
            ...MODEL.rollTiers['5'],
            { quantity: 'energy_recharge', values: [0.045, 0.052, 0.058, 0.065] },
          ],
        },
        substatWeights: { ...MODEL.substatWeights, energy_recharge: 4 },
      };
      const narrow = outcomeDistribution(threeLiner(), narrowModel, linear)!;
      const wider = outcomeDistribution(threeLiner(), widerModel, linear)!;

      expect(wider.outcomes).toBeGreaterThan(narrow.outcomes);
      expect(wider.bins.reduce((a, b) => a + b.p, 0)).toBeCloseTo(1, 10);
    });
  });
});
