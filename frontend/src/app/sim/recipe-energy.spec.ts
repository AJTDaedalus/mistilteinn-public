import { describe, expect, it } from 'vitest';

import {
  burstsAt,
  dpsAt,
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


describe('burstsAt and dpsAt', () => {
  const SWEEP = [
    { energyRecharge: 0.0, burstInstances: 2, standardDeviation: 0, dps: 150000 },
    { energyRecharge: 0.2, burstInstances: 3, standardDeviation: 0, dps: 170000 },
    { energyRecharge: 0.4, burstInstances: 4, standardDeviation: 0, dps: 190000 },
  ];

  it('reads the ladder as a step function, because each rung is a run', () => {
    expect(burstsAt(SWEEP, 0.39)).toBe(3);
    expect(dpsAt(SWEEP, 0.39)).toBe(170000);
  });

  it('holds the floor below the ladder and the ceiling above it', () => {
    expect(dpsAt(SWEEP, -1)).toBe(150000);
    expect(dpsAt(SWEEP, 9)).toBe(190000);
  });

  it('says nothing when the ladder was never measured', () => {
    expect(burstsAt([], 0.4)).toBeNull();
    expect(dpsAt([], 0.4)).toBeNull();
  });

  it('says nothing when the ladder carries no DPS', () => {
    // An older recipe, from before the rungs were priced.
    const bare = SWEEP.map(({ dps: _dps, ...rest }) => rest);
    expect(dpsAt(bare, 0.4)).toBeNull();
    expect(burstsAt(bare, 0.4)).toBe(4);
  });
});


describe('dpsAt — more ER cannot buy less', () => {
  /**
   * The owner's real ladder, 2026-09-01, at the 20 iterations per rung this was measured with.
   * It is **non-monotonic in both columns**: 157,761 DPS at 0.45 ER against 154,314 at 0.60,
   * with the burst count falling 2.8 → 2.5 for *more* energy. Neither can happen — every burst
   * is gated on `.ready`, so extra energy brings a cast forward or changes nothing.
   *
   * Kept as the fixture because it is the measurement that motivated the running maximum, and
   * a synthetic ladder would not have the shape that caused the bug.
   */
  const owners = [
    { energyRecharge: 0.2, burstInstances: 2, standardDeviation: 0, dps: 142380 },
    { energyRecharge: 0.3, burstInstances: 2, standardDeviation: 0, dps: 152589 },
    { energyRecharge: 0.45, burstInstances: 2.8, standardDeviation: 0.41, dps: 157761 },
    { energyRecharge: 0.6, burstInstances: 2.5, standardDeviation: 0.51, dps: 154314 },
    { energyRecharge: 0.8, burstInstances: 3, standardDeviation: 0, dps: 158306 },
    { energyRecharge: 1.0, burstInstances: 3, standardDeviation: 0, dps: 156188 },
  ];

  /**
   * **The ladder's top rung is what makes the running max safe**, and this pins it.
   *
   * "More ER cannot buy less" was the original justification and it is false: measured
   * natively on the same team, team DPS falls 11.5 % between 1.5 and 2.0 artifact ER, and at
   * 3.0 Furina's two extra bursts cost Skirk one of his — a `while 1` rotation runs for a
   * fixed duration, so a cast that becomes affordable consumes time somebody else was using.
   *
   * The running max is safe only because `ENERGY_LADDER` stops at 1.0, inside the monotone
   * region. If that constant is ever raised past ~1.5 this test should start failing, which is
   * the point of it.
   */
  it('never reads a rung the candidate cannot pay for, and flattens one it can', () => {
    const displacing = [
      { energyRecharge: 1.0, burstInstances: 3, standardDeviation: 0, dps: 157471 },
      { energyRecharge: 2.0, burstInstances: 3, standardDeviation: 0, dps: 139387 },
    ];
    // Sound half: a build at 1.0 is never credited a rung above it.
    expect(dpsAt(displacing, 1.0)).toBe(157471);
    // **The limitation, asserted rather than hidden.** A build at 2.0 is handed 1.0's number,
    // because the running max refuses the decline — and here the decline was *real*. This is
    // exactly why `ENERGY_LADDER` stopping at 1.0 is load-bearing: no such rung exists, so the
    // case never arises in production. Raise that constant past ~1.5 and this becomes a build
    // scored on a peak it does not have.
    expect(dpsAt(displacing, 2.0)).toBe(157471);
  });

  it('does not let a noisy dip cost a candidate that paid more', () => {
    // Without the running max this returned 154,314 — scoring a build with 0.60 ER 2.2 % below
    // one with 0.45, for no reason but which side of a coin flip its gcsim run fell.
    expect(dpsAt(owners, 0.6)).toBe(157761);
    expect(dpsAt(owners, 1.0)).toBe(158306);
  });

  it('still steps, rather than interpolating', () => {
    // Between two rungs the honest answer is the lower one's: each is a measurement, and a
    // point between them is not.
    expect(dpsAt(owners, 0.44)).toBe(152589);
    expect(dpsAt(owners, 0.3)).toBe(152589);
  });

  it('reads the lowest rung for a build below the whole ladder', () => {
    // Returning null here would disable ER weighting for exactly the builds shortest of it.
    expect(dpsAt(owners, 0.05)).toBe(142380);
  });

  it('is null only when nothing was measured', () => {
    expect(dpsAt([], 0.5)).toBeNull();
    expect(dpsAt([{ energyRecharge: 0.2, burstInstances: 2, standardDeviation: 0 }], 0.5))
      .toBeNull();
  });
});
