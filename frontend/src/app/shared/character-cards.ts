import type { CardFilter, CardOption } from './card-picker/card-picker';
import type { CharacterSummary } from '../pages/catalogue/catalogue.service';

/**
 * How a character grid is built, in one place.
 *
 * **Two pages now draw the same grid** — the build editor and the account page — and the
 * second was a verbatim copy of the first until this file existed. That shape is the one
 * `CLAUDE.md` records from the 2026-08-28 audit: *a pattern nothing owned, so every page
 * decided separately*. The concrete cost is a patch that adds an element or renames
 * `element_icon`: one call site gets fixed, the other keeps rendering chips with no icon, and
 * the page with the tests is the one that stays green.
 */

/**
 * One card per character.
 *
 * `tags` is what the filter chips match against, so it must agree with `characterFilters`
 * below — which is the whole reason they are neighbours rather than two private methods on
 * two components.
 */
export function characterCardOptions(characters: readonly CharacterSummary[]): CardOption[] {
  return characters.map((c) => ({
    value: c.id,
    label: c.name,
    icon: c.icon,
    detail: c.weapon_type_display,
    tags: { element: c.element ?? '', weapon: c.weapon_type ?? '' },
  }));
}

/**
 * The two axes a player narrows by: vision and weapon class.
 *
 * **Rarity is deliberately not one.** A 4★ character is not a worse subject, and offering
 * rarity as a filter implies it is.
 *
 * Derived from the characters actually present rather than from an enum, so a chip can never
 * offer a vision the list has none of — and the two unaligned rows, whose element is null,
 * contribute no chip while still being pickable.
 */
export function characterCardFilters(characters: readonly CharacterSummary[]): CardFilter[] {
  const elements = new Map<string, string | null>();
  const weapons = new Map<string, { label: string; icon: string }>();
  for (const c of characters) {
    if (c.element && !elements.has(c.element)) elements.set(c.element, c.element_icon ?? null);
    // **A class with no mark is not offered**, which is the rule this line states and the
    // whole of what it checks: a chip is a glyph, and a class with no sprite rendered as the
    // wide word CROSSBOW among five icons. `GET /weapon-classes` publishes five of six for
    // the same reason and `weapon_symbols.py` argues it at length.
    //
    // **It is not the #271 exclusion, and must not be read as one.** Hiding a class the game
    // has not shipped is `app/services/unreleased.py`, on the server, where the fact is named
    // once — `/characters` and the roster both filter there, so no crossbow row reaches this
    // function any more. Leaving that job to "has an icon" would be a fact guarded by a proxy:
    // a shipped class whose icon came back null for every row on screen would lose its whole
    // filter with nothing raised, which is the silent narrowing #271 was about.
    if (c.weapon_type && c.weapon_type_icon && !weapons.has(c.weapon_type)) {
      weapons.set(c.weapon_type, {
        label: c.weapon_type_display, icon: c.weapon_type_icon,
      });
    }
  }
  return [
    {
      group: 'element',
      label: 'Vision',
      options: [...elements].sort().map(([value, icon]) => ({ value, label: value, icon })),
    },
    {
      group: 'weapon',
      label: 'Weapon',
      options: [...weapons].sort().map(([value, { label, icon }]) => ({ value, label, icon })),
    },
  ];
}
