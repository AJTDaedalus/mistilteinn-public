import { describe, expect, it } from 'vitest';

import {
  energyShortfall,
  minimumEnergyRecharge,
  type EnergyObservation,
} from './recipe-energy';

/**
 * R.2a — the threshold below which a build is not performing the rotation.
 *
 * The sweep below is the shape of the real one, measured on the committed rotation: burst
 * count wobbles from +10 % to +25 % artifact ER and settles at 3.00 with sd 0 from +30 %.
 */

const point = (
  energyRecharge: number, burstInstances: number, standardDeviation: number,
): EnergyObservation => ({ energyRecharge, burstInstances, standardDeviation });

/** The measured sweep, rounded as `RESEARCH_recipe_risks.md` §3 records it. */
const MEASURED: EnergyObservation[] = [
  point(0.10, 2.11, 0.318),
  point(0.15, 2.46, 0.502),
  point(0.20, 2.74, 0.443),
  point(0.25, 2.95, 0.219),
  point(0.30, 3, 0),
  point(0.35, 3, 0),
  point(0.50, 3, 0),
];

describe('minimumEnergyRecharge', () => {
  it('finds the lowest ER that performs the calibrated rotation', () => {
    expect(minimumEnergyRecharge(MEASURED, 3)).toBeCloseTo(0.30, 9);
  });

  it('rejects a point whose burst count is right on average but varies', () => {
    // +25 % averages 2.95 — nearly 3 — but the burst fires 2 or 3 times depending on the seed.
    // A rotation that sometimes performs is not the rotation that was calibrated.
    expect(minimumEnergyRecharge([point(0.25, 3, 0.219), point(0.40, 3, 0)], 3))
      .toBeCloseTo(0.40, 9);
  });

  it('rejects a stable point at the wrong burst count', () => {
    // sd 0 at 2 bursts is a perfectly reproducible *different* rotation.
    expect(minimumEnergyRecharge([point(0.05, 2, 0), point(0.40, 3, 0)], 3))
      .toBeCloseTo(0.40, 9);
  });

  it('takes the minimum, not the first qualifying point', () => {
    // An unsorted sweep must not make the answer depend on iteration order.
    expect(minimumEnergyRecharge([point(0.50, 3, 0), point(0.30, 3, 0)], 3))
      .toBeCloseTo(0.30, 9);
  });

  it('returns null when the sweep never reaches the calibrated count', () => {
    expect(minimumEnergyRecharge([point(0.10, 2, 0)], 3)).toBeNull();
  });

  it('returns null for an empty sweep rather than throwing', () => {
    expect(minimumEnergyRecharge([], 3)).toBeNull();
  });
});

describe('energyShortfall', () => {
  it('reports nothing when the build clears the threshold', () => {
    expect(energyShortfall(0.45, 0.30)).toBeNull();
  });

  it('treats exactly meeting the threshold as clearing it', () => {
    expect(energyShortfall(0.30, 0.30)).toBeNull();
  });

  it('names what the build has, what it needs, and the gap', () => {
    // Two numbers are a puzzle; the gap is the thing a user acts on.
    expect(energyShortfall(0.12, 0.30)).toEqual({
      has: 0.12, needs: 0.30, shortfall: expect.closeTo(0.18, 9),
    });
  });

  it('reports nothing when the minimum was never measured', () => {
    // An unmeasured threshold is not a passed one — but blocking every build on a
    // measurement nobody took would be worse. The caller that skipped it has to say so.
    expect(energyShortfall(0.0, null)).toBeNull();
  });
});
