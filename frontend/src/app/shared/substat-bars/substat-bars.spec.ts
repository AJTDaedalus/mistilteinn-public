import { describe, expect, it } from 'vitest';

import { barsTitle, rollBars, rollValuePercent, substatReadings } from './substat-bars';
import type { SubstatReading } from './substat-bars';

function reading(over: Partial<SubstatReading> = {}): SubstatReading {
  return {
    label: 'CRIT DMG 24.9%',
    rolls: 2, tiers: [2, 3], tiersExact: true, estimated: false, rollValue: 1.9,
    ...over,
  };
}

describe('rollBars', () => {
  it('draws one bar per roll at its tier', () => {
    expect(rollBars(reading())).toEqual([2, 3]);
  });

  it('draws `-1` per roll when the tiers are unknown, never tier 0', () => {
    // "The worst roll" and "we do not know which roll" are different claims. Colouring the
    // second as the first calls a line bad on no evidence.
    expect(rollBars(reading({ tiers: null, rolls: 3 }))).toEqual([-1, -1, -1]);
  });

  it('draws nothing when even the count is unsettled', () => {
    expect(rollBars(reading({ tiers: null, rolls: null }))).toEqual([]);
  });
});

describe('barsTitle', () => {
  it('says nothing when there is nothing to claim', () => {
    expect(barsTitle(reading({ rolls: null, tiers: null }))).toBeNull();
  });

  it('puts the estimate caveat ahead of the tier wording', () => {
    // Checking `tiers` first returned the confident wording for a guessed count — the one
    // case that most needs the caveat was the one that lost it.
    expect(barsTitle(reading({ estimated: true, tiersExact: false })))
      .toContain('likeliest reading');
  });

  it('marks a tie as one reading of several', () => {
    expect(barsTitle(reading({ tiersExact: false })))
      .toBe('2 rolls, shaded by one reading of several that fit');
  });

  it('is unqualified only when exactly one decomposition fits', () => {
    expect(barsTitle(reading())).toBe('2 rolls, shaded by how high each rolled');
  });

  it('says a single roll in the singular', () => {
    expect(barsTitle(reading({ rolls: 1, tiers: [3] }))).toBe(
      '1 roll, shaded by how high each rolled',
    );
  });
});

describe('rollValuePercent', () => {
  it('renders a ratio as a percentage', () => {
    expect(rollValuePercent(reading({ rollValue: 3.2046 }))).toBe(320);
  });

  it('keeps null distinct from zero', () => {
    expect(rollValuePercent(reading({ rollValue: null }))).toBeNull();
  });
});

describe('substatReadings', () => {
  const label = (stat: string, value: unknown) => `${stat} ${String(value)}`;

  it('pairs each substat with the analysis at the same index', () => {
    const got = substatReadings(
      [{ stat: 'a', value: 1 }, { stat: 'b', value: 2 }],
      [{ rolls: 1, roll_tiers: [3], roll_tiers_exact: true },
       { rolls: 2, roll_tiers: [0, 1], roll_tiers_exact: false }],
      label,
    );

    expect(got.map((r) => r.label)).toEqual(['a 1', 'b 2']);
    expect(got[1].tiers).toEqual([0, 1]);
    expect(got[1].tiersExact).toBe(false);
  });

  it('defaults an absent exactness flag to true and an absent estimate to false', () => {
    // The two defaults point opposite ways on purpose: an older payload with no flags is the
    // always-exact contract, so defaulting `tiersExact` to false would caveat every line in
    // the inventory, and defaulting `estimated` to true would do the same in the other
    // direction.
    const [only] = substatReadings([{ stat: 'a', value: 1 }], [{ rolls: 1 }], label);

    expect(only.tiersExact).toBe(true);
    expect(only.estimated).toBe(false);
  });

  it('keeps a line the server could not read, with nulls rather than dropped', () => {
    // A missing line would shift every later substat onto the wrong analysis.
    const got = substatReadings(
      [{ stat: 'a', value: 1 }, { stat: 'b', value: 2 }],
      [null, { rolls: 2, roll_tiers: [1, 1] }],
      label,
    );

    expect(got).toHaveLength(2);
    expect(got[0].rolls).toBeNull();
    expect(got[1].rolls).toBe(2);
  });

  it('survives an analysis array the server omitted entirely', () => {
    const got = substatReadings([{ stat: 'a', value: 1 }], undefined, label);

    expect(got).toHaveLength(1);
    expect(got[0].tiers).toBeNull();
  });
});
