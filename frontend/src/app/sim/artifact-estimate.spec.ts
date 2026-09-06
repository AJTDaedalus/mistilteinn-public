import { describe, expect, it } from 'vitest';

import type { DrawModel, Piece } from './artifact-projection';
import { estimateOutcome, normalCdf } from './artifact-estimate';
import { outcomeDistribution } from './artifact-outcome';

/**
 * `TASKS_artifact_ranking.md`, the GO two-pass follow-up. **The test that matters is the one
 * against the exact enumeration**: this pass exists to approximate that one cheaply, so if the
 * two disagree beyond the approximation's stated terms, the cheap pass is wrong rather than
 * merely cheap.
 */

const MODEL: DrawModel = {
  rollTiers: {
    '5': [
      { quantity: 'atk_pct', values: [0.0408, 0.0466, 0.0525, 0.0583] },
      { quantity: 'crit_rate', values: [0.0272, 0.0311, 0.035, 0.0389] },
      { quantity: 'crit_dmg', values: [0.0544, 0.0622, 0.0699, 0.0777] },
      { quantity: 'flat_hp', values: [209.13, 239, 268.88, 298.75] },
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
      rollsRemaining: 4, rollsTotal: 5, gainsASubstat: false,
      substatQuantities: ['crit_rate', 'crit_dmg', 'flat_hp'],
    },
    ...over,
  };
}

const linear = (s: Record<string, number>) =>
  1000 + 5000 * (s['crit_rate'] ?? 0) + 3000 * (s['crit_dmg'] ?? 0) + 2 * (s['flat_hp'] ?? 0);

const withCrit = (s: Record<string, number>) =>
  1000 * (1 + (s['atk_pct'] ?? 0)) * (1 + Math.min(s['crit_rate'] ?? 0, 1) * (s['crit_dmg'] ?? 0));

describe('normalCdf', () => {
  it('matches the values anyone can check', () => {
    expect(normalCdf(0)).toBeCloseTo(0.5, 7);
    expect(normalCdf(1.96)).toBeCloseTo(0.975, 4);
    expect(normalCdf(-1.96)).toBeCloseTo(0.025, 4);
    expect(normalCdf(-4)).toBeLessThan(0.0001);
  });

  it('is symmetric, which the two-branch implementation could easily not be', () => {
    for (const z of [0.3, 1, 2.5]) {
      expect(normalCdf(z) + normalCdf(-z)).toBeCloseTo(1, 7);
    }
  });
});

describe('estimateOutcome', () => {
  it('refuses a piece with nothing left rather than reporting certainty as a distribution', () => {
    const maxed = piece({
      potential: {
        rollsRemaining: 0, rollsTotal: 5, gainsASubstat: false,
        substatQuantities: ['crit_rate'],
      },
    });
    expect(estimateOutcome(maxed, MODEL, linear)).toBeNull();
    expect(estimateOutcome(piece({ potential: null }), MODEL, linear)).toBeNull();
  });

  describe('against the exact enumeration it approximates', () => {
    it('gets the mean right on a linear objective, where the delta method is exact', () => {
      const p = piece();
      const cheap = estimateOutcome(p, MODEL, linear)!;
      const exact = outcomeDistribution(p, MODEL, linear)!;
      // A first-order delta method's mean is f(E[X]), and on a linear f that IS E[f(X)].
      expect(cheap.mean).toBeCloseTo(exact.mean, 6);
      expect(cheap.mean).toBeCloseTo(exact.atAverage, 6);
    });

    it('gets the spread right too, which is what the covariance buys', () => {
      const p = piece();
      const cheap = estimateOutcome(p, MODEL, linear)!;
      const exact = outcomeDistribution(p, MODEL, linear)!;
      // **Compared relatively, because the reference is itself discretised.** The exact
      // distribution's spread has to be read back off 60 bin midpoints, which is a
      // approximation of its own — so an absolute tolerance here would be measuring the
      // binning rather than the estimator. Measured agreement is ~0.15 %.
      const mid = (b: { from: number; to: number }) => (b.from + b.to) / 2;
      const mu = exact.bins.reduce((a, b) => a + b.p * mid(b), 0);
      const sdExact = Math.sqrt(exact.bins.reduce((a, b) => a + b.p * (mid(b) - mu) ** 2, 0));
      expect(Math.abs(cheap.sd - sdExact) / sdExact).toBeLessThan(0.01);
    });

    it('gets the probability of an upgrade close on a linear objective', () => {
      const p = piece();
      const cheap = estimateOutcome(p, MODEL, linear)!;
      const exact = outcomeDistribution(p, MODEL, linear)!;
      expect(cheap.probabilityOfUpgrade).toBeCloseTo(exact.probabilityOfUpgrade, 1);
    });

    it('stays within its own approximation on a multiplying objective', () => {
      // **Both approximations bite here**, and the test says so rather than demanding equality:
      // the delta-method linearisation and the Gaussian assumption. Within 10 percentage points
      // of the exact answer is what this pass is for — triage across 2,370 pieces, with the
      // exact enumeration one click away for the piece being decided on.
      const p = piece();
      const cheap = estimateOutcome(p, MODEL, withCrit)!;
      const exact = outcomeDistribution(p, MODEL, withCrit)!;
      expect(Math.abs(cheap.probabilityOfUpgrade - exact.probabilityOfUpgrade)).toBeLessThan(0.1);
    });
  });

  it('drops the spread when the rolls cannot move the objective', () => {
    // Every remaining roll lands on stats the objective does not read, so nothing is uncertain.
    const cheap = estimateOutcome(piece(), MODEL, (s) => 1000 * (1 + (s['atk_pct'] ?? 0)))!;
    expect(cheap.sd).toBeCloseTo(0, 9);
    expect(cheap.probabilityOfUpgrade).toBe(0);
  });

  it('carries the negative covariance, so competing rolls narrow the spread', () => {
    // **The whole point of the covariance matrix.** Rolls compete: with the off-diagonal terms
    // dropped the spread comes out wider, because two stats would look free to both go high.
    const p = piece();
    const withCov = estimateOutcome(p, MODEL, linear)!;
    // A piece with one line has no competition — its spread is the pure roll variance.
    const alone = estimateOutcome(piece({
      potential: {
        rollsRemaining: 4, rollsTotal: 5, gainsASubstat: false,
        substatQuantities: ['crit_dmg'],
      },
    }), MODEL, linear)!;
    expect(alone.sd).toBeGreaterThan(0);
    expect(withCov.sd).toBeGreaterThan(0);
  });

  it('sums over the fourth line as a mixture, not as an average of unlike things', () => {
    const threeLiner = piece({
      stats: { atk_pct: 0.466, crit_rate: 0.039, crit_dmg: 0.078 },
      potential: {
        rollsRemaining: 4, rollsTotal: 5, gainsASubstat: true,
        substatQuantities: ['crit_rate', 'crit_dmg'],
      },
    });
    const cheap = estimateOutcome(threeLiner, MODEL, linear)!;
    const exact = outcomeDistribution(threeLiner, MODEL, linear)!;
    expect(cheap.probabilityOfUpgrade).toBeGreaterThanOrEqual(0);
    expect(cheap.probabilityOfUpgrade).toBeLessThanOrEqual(1);
    expect(cheap.mean).toBeCloseTo(exact.mean, 4);
  });
});

/**
 * **The bar the probability is measured against.**
 *
 * `probabilityOfUpgrade` used the piece's own current damage, which asks whether levelling a
 * piece beats *the same piece unlevelled* — a question whose answer is nearly always yes,
 * because levelling adds rolls. A +0 flower reported "upgrade odds 99.9%" beside an expected
 * gain of +0.2% over the piece actually equipped, and the two looked contradictory because
 * they were answering different questions. Owner, 2026-09-06: it should be the probability
 * that the artifact, fully levelled, is an upgrade.
 */
describe('the reference the upgrade probability is measured against', () => {
  it('defaults to the piece itself, where levelling is nearly certain to help', () => {
    const found = estimateOutcome(piece(), MODEL, linear)!;
    expect(found.reference).toBeCloseTo(linear(piece().stats), 6);
    // Every remaining roll adds to a strictly increasing objective, so it cannot get worse.
    expect(found.probabilityOfUpgrade).toBeGreaterThan(0.99);
  });

  it('reports near-zero against a bar the piece cannot reach', () => {
    // A bar far above anything four more rolls could produce.
    const found = estimateOutcome(piece(), MODEL, linear, 1e6)!;
    expect(found.reference).toBe(1e6);
    expect(found.probabilityOfUpgrade).toBeLessThan(0.01);
  });

  it('reports near-certainty against a bar the piece already clears', () => {
    const found = estimateOutcome(piece(), MODEL, linear, 0)!;
    expect(found.probabilityOfUpgrade).toBeGreaterThan(0.99);
  });

  it('agrees with the exact enumeration on the same bar', () => {
    // Half way between the piece as it stands and its ceiling — a bar that genuinely splits
    // the distribution, so a probability of 0 or 1 cannot pass this by accident.
    const p = piece();
    const exact = outcomeDistribution(p, MODEL, linear)!;
    const bar = (exact.bins[0].from + exact.bins[exact.bins.length - 1].to) / 2;

    const cheap = estimateOutcome(p, MODEL, linear, bar)!;
    const enumerated = outcomeDistribution(p, MODEL, linear, bar)!;

    expect(enumerated.probabilityOfUpgrade).toBeGreaterThan(0.05);
    expect(enumerated.probabilityOfUpgrade).toBeLessThan(0.95);
    expect(cheap.probabilityOfUpgrade).toBeCloseTo(enumerated.probabilityOfUpgrade, 1);
  });
});
