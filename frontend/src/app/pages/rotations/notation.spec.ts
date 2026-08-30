import { describe, expect, it } from 'vitest';

import { actionLetter, humanise, moveLabel } from './notation';
import type { ActionOffer } from './rotations.service';

const offer = (o: Partial<ActionOffer>): ActionOffer => ({
  action: 'skill', base: 'skill', variant: null, name: 'skill', icon: null, ...o,
} as ActionOffer);

describe('actionLetter', () => {
  it('gives the four letters a rotation is written with', () => {
    expect([
      actionLetter('attack'), actionLetter('charge'),
      actionLetter('skill'), actionLetter('burst'),
    ]).toEqual(['N', 'C', 'E', 'Q']);
  });

  it('gives no letter where the community writes none', () => {
    // `P` would collide between the two plunges, and inventing `J` and `W` would be this repo
    // teaching people shorthand nobody else uses. Absent beats plausible.
    for (const action of ['high_plunge', 'low_plunge', 'aim', 'dash', 'jump', 'walk']) {
      expect(actionLetter(action)).toBeNull();
    }
  });
});

describe('humanise', () => {
  it('replaces every underscore, not just the first', () => {
    expect(humanise('high_plunge')).toBe('High plunge');
    expect(humanise('a_b_c')).toBe('A b c');
  });

  it('leaves a word that has none alone but for its first letter', () => {
    expect(humanise('dash')).toBe('Dash');
  });
});

describe('moveLabel', () => {
  it('writes the letter before the character own name for it', () => {
    expect(moveLabel(offer({ base: 'burst', action: 'burst', name: 'Illusory Heart' })))
      .toBe('Q - Illusory Heart');
  });

  it('keeps the variant, spelled out', () => {
    // The badge shows `h`; this is the channel that says what `h` means.
    expect(moveLabel(offer({
      action: 'skill_hold', base: 'skill', variant: 'hold', name: 'All Schemes to Know',
    }))).toBe('E - All Schemes to Know (hold)');
  });

  it('spells a short hold with a space, not an underscore', () => {
    expect(moveLabel(offer({
      action: 'skill_short_hold', base: 'skill', variant: 'short_hold', name: 'Radiant Psalter',
    }))).toBe('E - Radiant Psalter (short hold)');
  });

  it('humanises an action that has no talent name of its own', () => {
    // These fall back to the action key, which is where the underscores are.
    expect(moveLabel(offer({ action: 'high_plunge', base: 'high_plunge', name: 'high_plunge' })))
      .toBe('High plunge');
  });

  it('still writes the letter for a charged attack, which has no name either', () => {
    expect(moveLabel(offer({ action: 'charge', base: 'charge', name: 'charge' })))
      .toBe('C - Charge');
  });

  it('does not humanise a real ability name that happens to be one word', () => {
    // "Akara" is Nahida's normal attack and must not be touched; only the key fallback is.
    expect(moveLabel(offer({ action: 'attack', base: 'attack', name: 'Akara' })))
      .toBe('N - Akara');
  });
});
