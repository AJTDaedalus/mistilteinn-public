import { describe, expect, it } from 'vitest';

import { scalingLabel } from './scaling-label';

describe('scalingLabel', () => {
  it('says nothing for a plain ATK hit', () => {
    expect(scalingLabel({ scaling_stat: 'atk', extra_terms: [] })).toBe('');
  });

  it("names an HP, DEF or EM hit's stat in the game's words", () => {
    expect(scalingLabel({ scaling_stat: 'hp', extra_terms: [] })).toBe('Max HP');
    expect(scalingLabel({ scaling_stat: 'def', extra_terms: [] })).toBe('DEF');
    expect(scalingLabel({ scaling_stat: 'elemental_mastery', extra_terms: [] })).toBe(
      'Elemental Mastery',
    );
  });

  it('names every term of a mixed-stat hit, ATK included', () => {
    expect(
      scalingLabel({ scaling_stat: 'atk', extra_terms: [{ stat: 'elemental_mastery' }] }),
    ).toBe('ATK + Elemental Mastery');
  });
});
