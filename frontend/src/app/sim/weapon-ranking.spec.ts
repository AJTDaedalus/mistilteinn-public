import { describe, expect, it } from 'vitest';

import {
  areSeparated,
  rank,
  standardError,
  type RankedCandidate,
} from './weapon-ranking';

/**
 * W.5 — the ranking, and the thing it is not allowed to claim.
 *
 * The load-bearing test is `two candidates inside one standard error come back marked
 * not-separated, not merely ordered`. Everything else here supports it.
 */

function c(over: Partial<RankedCandidate> & { weaponId: string }): RankedCandidate {
  return {
    name: over.weaponId,
    dpsMean: 700,
    dpsSd: 87,
    iterations: 100,
    ...over,
  };
}

describe('standardError', () => {
  it('is sd over root n, not sd', () => {
    // The distinction is the whole feature: sd 87 at 100 iterations is a 1.2% standard
    // error, not a 12% one. Confusing them makes every weapon inseparable from every other.
    expect(standardError(c({ weaponId: 'a', dpsSd: 87, iterations: 100 }))).toBeCloseTo(8.7);
  });

  it('reports zero rather than dividing by zero', () => {
    expect(standardError(c({ weaponId: 'a', iterations: 0 }))).toBe(0);
  });
});

describe('areSeparated', () => {
  it('separates candidates whose gap clears the combined error', () => {
    const a = c({ weaponId: 'a', dpsMean: 800 });
    const b = c({ weaponId: 'b', dpsMean: 700 });
    expect(areSeparated(a, b)).toBe(true);
  });

  it('does not separate candidates inside the noise', () => {
    // 707 vs 700 is 1%, against a ~1.2% standard error each. This is the pair the whole
    // feature exists to refuse to order.
    expect(areSeparated(c({ weaponId: 'a', dpsMean: 707 }), c({ weaponId: 'b' }))).toBe(false);
  });

  it('is symmetric', () => {
    const a = c({ weaponId: 'a', dpsMean: 760 });
    const b = c({ weaponId: 'b' });
    expect(areSeparated(a, b)).toBe(areSeparated(b, a));
  });

  it('treats a zero-width interval as certainty only about a real gap', () => {
    // sd 0 is either deterministic or unmeasured and this cannot tell them apart, so equal
    // means stay inseparable rather than becoming infinitely confident.
    const a = c({ weaponId: 'a', dpsSd: 0, dpsMean: 700 });
    const b = c({ weaponId: 'b', dpsSd: 0, dpsMean: 700 });
    expect(areSeparated(a, b)).toBe(false);
    expect(areSeparated(a, { ...b, dpsMean: 700.001 })).toBe(true);
  });

  it('widens with z, so a stricter threshold separates less', () => {
    const a = c({ weaponId: 'a', dpsMean: 730 });
    const b = c({ weaponId: 'b' });
    expect(areSeparated(a, b, 1)).toBe(true);
    expect(areSeparated(a, b, 6)).toBe(false);
  });
});

describe('rank', () => {
  it('marks two candidates inside one standard error as not separated', () => {
    // W.5's acceptance criterion, stated as the plan states it.
    const out = rank([c({ weaponId: 'a', dpsMean: 705 }), c({ weaponId: 'b', dpsMean: 700 })]);

    expect(out.rows[0].notSeparatedFrom).toEqual(['b']);
    expect(out.rows[1].notSeparatedFrom).toEqual(['a']);
    expect(out.fullyOrdered).toBe(false);
  });

  it('reports a clean ranking as fully ordered', () => {
    const out = rank([
      c({ weaponId: 'a', dpsMean: 900 }),
      c({ weaponId: 'b', dpsMean: 700 }),
      c({ weaponId: 'c', dpsMean: 500 }),
    ]);

    expect(out.fullyOrdered).toBe(true);
    expect(out.rows.every((r) => r.notSeparatedFrom.length === 0)).toBe(true);
    expect(out.rows.map((r) => r.weaponId)).toEqual(['a', 'b', 'c']);
  });

  it('orders by mean descending and numbers ranks from one', () => {
    const out = rank([c({ weaponId: 'lo', dpsMean: 100 }), c({ weaponId: 'hi', dpsMean: 900 })]);
    expect(out.rows.map((r) => [r.rank, r.weaponId])).toEqual([[1, 'hi'], [2, 'lo']]);
  });

  it('breaks mean ties by name so two runs of one dataset agree', () => {
    // An unstable sort would make the same data rank differently on re-run, which reads as
    // simulation noise rather than as an arbitrary sort.
    const forward = rank([c({ weaponId: 'zeta' }), c({ weaponId: 'alpha' })]);
    const backward = rank([c({ weaponId: 'alpha' }), c({ weaponId: 'zeta' })]);
    expect(forward.rows.map((r) => r.weaponId)).toEqual(['alpha', 'zeta']);
    expect(backward.rows.map((r) => r.weaponId)).toEqual(['alpha', 'zeta']);
  });

  it('does not transitively close inseparability', () => {
    // A~B and B~C while A and C are cleanly apart is a real state, and collapsing it into
    // one group would discard a distinction the run actually made.
    const out = rank([
      c({ weaponId: 'a', dpsMean: 740 }),
      c({ weaponId: 'b', dpsMean: 720 }),
      c({ weaponId: 'c', dpsMean: 700 }),
    ]);
    const by = Object.fromEntries(out.rows.map((r) => [r.weaponId, r.notSeparatedFrom]));
    expect(by['a']).toEqual(['b']);
    expect(by['c']).toEqual(['b']);
    expect(by['b'].sort()).toEqual(['a', 'c']);
  });

  it('does not mutate the array it was given', () => {
    const input = [c({ weaponId: 'lo', dpsMean: 1 }), c({ weaponId: 'hi', dpsMean: 9 })];
    rank(input);
    expect(input.map((x) => x.weaponId)).toEqual(['lo', 'hi']);
  });

  it('reports the shared iteration count when every row agrees', () => {
    expect(rank([c({ weaponId: 'a' }), c({ weaponId: 'b' })]).iterations).toBe(100);
  });

  it('reports null rather than one row’s count when the counts differ', () => {
    // A cached run beside a fresh one is exactly how mixed counts arise. Stamping the first
    // row's count on the whole ranking is one number describing several things.
    const out = rank([
      c({ weaponId: 'a', iterations: 100 }),
      c({ weaponId: 'b', iterations: 25 }),
    ]);
    expect(out.iterations).toBeNull();
    expect(out.rows.map((r) => r.iterations).sort((x, y) => x - y)).toEqual([25, 100]);
  });

  it('handles an empty candidate list without inventing a ranking', () => {
    expect(rank([])).toEqual({ rows: [], fullyOrdered: true, iterations: null });
  });
});
