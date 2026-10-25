import { describe, expect, it } from 'vitest';

import { claimsAtQuantile, perRunSuccess, resinToUpgrade, setFactor } from './resin-to-upgrade';

const CLAIM = { fiveStarPerRun: 1.065, setShare: 0.5, slotShare: 0.2, resinPerRun: 20 };

/** `docs/TASKS_upgrade_estimator.md` Task 7. */
describe('resinToUpgrade', () => {
  it('matches the quantile formula against a brute-force cumulative sum', () => {
    const r = 0.013;
    for (const p of [0.25, 0.5, 0.75, 0.9]) {
      let k = 0;
      let cdf = 0;
      while (cdf < p) { k += 1; cdf = 1 - (1 - r) ** k; }
      expect(claimsAtQuantile(r, p)).toBe(k);
    }
  });

  it('says unreachable, never Infinity or NaN, when no drop can win', () => {
    const none = resinToUpgrade(0, 0.5, CLAIM);
    expect(none.unreachable).toBe(true);
    expect(none.median).toBeNull();
    expect(none.mean).toBeNull();
    // A non-zero baseline, so the test is not vacuous: a real chance gives real figures.
    const some = resinToUpgrade(0.01, 0.5, CLAIM);
    expect(some.unreachable).toBe(false);
    expect(Number.isFinite(some.median!)).toBe(true);
  });

  it('is KQM\'s E[N] = 1/p_tot, converted to claims, for small p', () => {
    // Hand check: a 4-piece slot, P(beat | slot drop) = 1%. One drop in 1/(½·⅕·0.01) = 1,000
    // is an upgrade (KQM's E[N] — RESEARCH §7), and a claim yields 1.065 drops, so the mean is
    // ≈ 1,000 / 1.065 ≈ 939 claims ≈ 18,780 resin.
    const found = resinToUpgrade(0.01, 0.5, CLAIM);
    expect(found.perDrop).toBeCloseTo(0.001, 15);
    expect(found.mean!).toBeGreaterThan(18_700);
    expect(found.mean!).toBeLessThan(18_800);
    expect(found.median!).toBeLessThan(found.mean!);
  });

  it('prices in whole claims of 20 resin', () => {
    const found = resinToUpgrade(0.2, 1, CLAIM);
    for (const v of [found.p25, found.median, found.p75, found.p90]) expect(v! % 20).toBe(0);
  });
});

describe('perRunSuccess', () => {
  it('is ≈ q · E[N] for small q, whatever the shape', () => {
    expect(perRunSuccess(1e-4, 1.065) / 1e-4).toBeCloseTo(1.065, 3);
  });
});

describe('setFactor', () => {
  it('is ½ for a slot inside a 4-piece (4+1)', () => {
    expect(setFactor(10, { 10: 4, 20: 1 }, 0.5)).toBe(0.5);
  });
  it('is 1 for the off-piece of a 4+1', () => {
    expect(setFactor(20, { 10: 4, 20: 1 }, 0.5)).toBe(1);
  });
  it('is ½ for each 2-piece of a 2+2+1, and 1 for its fifth piece', () => {
    const counts = { 10: 2, 20: 2, 30: 1 };
    expect(setFactor(10, counts, 0.5)).toBe(0.5);
    expect(setFactor(20, counts, 0.5)).toBe(0.5);
    expect(setFactor(30, counts, 0.5)).toBe(1);
  });
  it('is 1 everywhere on a rainbow build, and for a setless piece', () => {
    expect(setFactor(10, { 10: 1, 20: 1, 30: 1, 40: 1, 50: 1 }, 0.5)).toBe(1);
    expect(setFactor(null, { 10: 4 }, 0.5)).toBe(1);
  });
});
