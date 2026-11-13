import { describe, expect, it } from 'vitest';

import { critMultiplier, defMultiplier, resMultiplier, resolveStat } from './damage';

/**
 * C.3 — the kernel's individual terms.
 *
 * The **2,000-case differential sweep is not here**: it reads
 * `backend/tests/fixtures/kernel/cases.json`, and Angular's test builder targets the browser,
 * where `node:fs` does not exist. It lives in `scripts/verify-kernel.mjs` and runs as its own
 * CI step — the same shape as the gcsim verifiers, and for the same reason: a gate that needs
 * a real Node host should not be wedged into a browser test environment.
 *
 * What is left here is the per-term behaviour a reader would want to see asserted next to the
 * code, each one a formula divergence the sweep measures in aggregate.
 */

describe('the individual terms', () => {
  it('clamps crit rate, as gcsim does', () => {
    expect(critMultiplier(1.5, 2.0)).toBeCloseTo(3.0, 6);
    expect(critMultiplier(1.0, 2.0)).toBeCloseTo(3.0, 6);
    expect(critMultiplier(-0.5, 2.0)).toBeCloseTo(1.0, 6);
  });

  it('takes the diminishing branch at exactly 0.75', () => {
    // The documented divergence from gcsim, whose `>` sends this to the negative branch and
    // returns 0.625. Getting it wrong is a 1.5 relative difference.
    expect(resMultiplier(0.75)).toBeCloseTo(0.25, 6);
    expect(resMultiplier(-0.5)).toBeCloseTo(1.25, 6);
    expect(resMultiplier(0.1)).toBeCloseTo(0.9, 6);
  });

  it('resolves a stat as base * (1 + pct) + flat, in one stage', () => {
    // Single-stage, cited to gcsim `stats.go:49-51`. Applying the percentage after the flat
    // would give 2200 here rather than 2100 — a 5% error that no rounding tolerance hides.
    expect(resolveStat(1000, 1.0, 100)).toBeCloseTo(2100, 4);
  });

  it('multiplies the two DEF mechanics separately', () => {
    // Adding them would give the same answer only when one is zero, which is why the sweep
    // has 13% of cases with both.
    const separate = defMultiplier(90, 90, 0.2, 0.3);
    const added = defMultiplier(90, 90, 0.5, 0);
    expect(separate).not.toBeCloseTo(added, 6);
  });
});
