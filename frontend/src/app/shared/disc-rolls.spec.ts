import { describe, expect, it } from 'vitest';

import { totalRolls } from './disc-rolls';

describe('totalRolls', () => {
  it('returns the given roll count unchanged', () => {
    expect(totalRolls(3)).toBe(3);
    expect(totalRolls(1)).toBe(1);
  });

  it('defaults to 1 (the guaranteed initial roll) when rolls is undefined', () => {
    expect(totalRolls(undefined)).toBe(1);
  });
});
