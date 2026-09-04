import { describe, expect, it } from 'vitest';

import { characterCardFilters, characterCardOptions } from './character-cards';
import type { CharacterSummary } from '../pages/catalogue/catalogue.service';

const character = (over: Partial<CharacterSummary>): CharacterSummary => ({
  id: 'x', name: 'X', icon: null, element: 'Cryo', element_icon: null,
  weapon_type: 'WEAPON_SWORD_ONE_HAND', weapon_type_display: 'Sword', weapon_type_icon: null,
  ...over,
} as CharacterSummary);

/**
 * The builder two pages share.
 *
 * It exists because the account page was a verbatim copy of the build editor's private
 * version, so the assertions worth having are the ones that would have diverged silently:
 * the tag keys the chips match on, and what happens to a character with no vision.
 */
describe('character cards', () => {
  it('tags each card with the two axes the chips filter on', () => {
    // The tag keys and the filter groups must agree, and this is the only place both are
    // visible at once. A rename on one side and not the other filters to nothing.
    const [card] = characterCardOptions([character({ id: 'a', name: 'Nahida',
      element: 'Dendro', weapon_type: 'WEAPON_CATALYST', weapon_type_display: 'Catalyst' })]);

    expect(card).toMatchObject({
      value: 'a', label: 'Nahida', detail: 'Catalyst',
      tags: { element: 'Dendro', weapon: 'WEAPON_CATALYST' },
    });
  });

  it('offers only visions the list actually contains', () => {
    // Derived from the characters present, never from an enum: a chip for a vision nothing
    // in the grid has filters to an empty wall and reads as broken.
    const filters = characterCardFilters([
      character({ element: 'Cryo' }), character({ element: 'Cryo' }),
    ]);

    expect(filters[0].options.map((o) => o.value)).toEqual(['Cryo']);
  });

  it('keeps a character with no vision pickable and gives it no chip', () => {
    // Two catalogue rows carry a null element. They contribute no filter chip — and they are
    // still cards, because `CardPicker` only excludes when a chip in that group is active.
    const unaligned = [character({ id: 'u', name: 'Unaligned', element: null })];

    expect(characterCardFilters(unaligned)[0].options).toEqual([]);
    expect(characterCardOptions(unaligned)[0].tags)
      .toEqual({ element: '', weapon: 'WEAPON_SWORD_ONE_HAND' });
  });
});
