import { describe, it, expect } from 'vitest';
import { fmtBasisPct, fmtFlat, fmtInt, fmtMultBp, fmtPctBp } from './format-helpers';

describe('fmtBasisPct', () => {
  it('formats positive bp as signed percent', () => {
    expect(fmtBasisPct(3000)).toBe('+30%');
  });
  it('formats negative bp', () => {
    expect(fmtBasisPct(-500)).toBe('-5%');
  });
  it('formats zero', () => {
    expect(fmtBasisPct(0)).toBe('+0%');
  });
});

describe('fmtFlat', () => {
  it('formats positive flat', () => {
    expect(fmtFlat(2450)).toBe('+2,450');
  });
  it('formats negative flat', () => {
    expect(fmtFlat(-1000)).toBe('-1,000');
  });
});

describe('fmtMultBp', () => {
  it('17500 → "×1.75"', () => {
    expect(fmtMultBp(17500)).toBe('×1.75');
  });
  it('5000 → "×0.50"', () => {
    expect(fmtMultBp(5000)).toBe('×0.50');
  });
  it('10000 → "×1.00"', () => {
    expect(fmtMultBp(10000)).toBe('×1.00');
  });
  it('6100 → "×0.61" (fractional bp)', () => {
    expect(fmtMultBp(6100)).toBe('×0.61');
  });
  it('18400 → "×1.84"', () => {
    expect(fmtMultBp(18400)).toBe('×1.84');
  });
  it('respects precision override', () => {
    expect(fmtMultBp(10000, 0)).toBe('×1');
  });
});

describe('fmtPctBp', () => {
  it('positive signed → "+30%"', () => {
    expect(fmtPctBp(3000)).toBe('+30%');
  });
  it('negative → "-5%"', () => {
    expect(fmtPctBp(-500)).toBe('-5%');
  });
  it('zero → "0%"', () => {
    expect(fmtPctBp(0)).toBe('0%');
  });
  it('unsigned positive → no prefix', () => {
    expect(fmtPctBp(25000, false)).toBe('250%');
  });
  it('unsigned zero → "0%"', () => {
    expect(fmtPctBp(0, false)).toBe('0%');
  });
  it('fractional bp rounds correctly', () => {
    expect(fmtPctBp(3333)).toBe('+33.33%');
  });
});

describe('fmtInt', () => {
  it('formats with locale grouping and no sign', () => {
    expect(fmtInt(2450)).toBe('2,450');
  });
  it('rounds fractional values', () => {
    expect(fmtInt(1999.6)).toBe('2,000');
  });
});
