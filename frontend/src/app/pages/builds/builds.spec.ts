import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { MAX_PAGE_LIMIT } from '../../api/page-size';
import { CatalogueService } from '../catalogue/catalogue.service';
import { BuildsPage, matchesBuild } from './builds';
import { BuildsService } from './builds.service';

const AYAKA = {
  id: 'char-ayaka', nanoka_id: '10000002', name: 'Kamisato Ayaka', element: 'Cryo',
  weapon_type: 'WEAPON_SWORD_ONE_HAND', weapon_type_display: 'Sword', rarity: 5, stars: 5,
  icon: 'UI_AvatarIcon_Ayaka', element_icon: 'Cryo', weapon_type_icon: 'Skill_A_01',
};
const GANYU = {
  id: 'char-ganyu', nanoka_id: '10000037', name: 'Ganyu', element: 'Cryo',
  weapon_type: 'WEAPON_BOW', weapon_type_display: 'Bow', rarity: 5, stars: 5,
  icon: 'UI_AvatarIcon_Ganyu', element_icon: 'Cryo', weapon_type_icon: 'Skill_A_02',
};
const SWORD = {
  id: 'w-mistsplitter', nanoka_id: 11509, name: 'Mistsplitter Reforged',
  weapon_type: 'WEAPON_SWORD_ONE_HAND', weapon_type_display: 'Sword', rarity: 5, stars: 5,
  icon: 'UI_EquipIcon_Sword_Narukami', sub_stat_display: 'CRIT DMG',
};

const OPTIONS = {
  talents: ['normal_attack', 'elemental_skill', 'elemental_burst'],
  max_talent_level: 15,
};

function pageWith(
  builds: Partial<BuildsService>,
  catalogue: Partial<CatalogueService> = {},
) {
  TestBed.configureTestingModule({
    providers: [
      { provide: BuildsService, useValue: builds },
      { provide: CatalogueService, useValue: catalogue },
    ],
  });
  return TestBed.runInInjectionContext(() => new BuildsPage());
}

function healthy(
  builds: Partial<BuildsService> = {},
  catalogue: Partial<CatalogueService> = {},
) {
  return pageWith(
    {
      options: vi.fn().mockResolvedValue(OPTIONS),
      list: vi.fn().mockResolvedValue([]),
      ...builds,
    } as unknown as BuildsService,
    {
      listCharacters: vi.fn().mockResolvedValue({ items: [AYAKA, GANYU], total: 2 }),
      listWeapons: vi.fn().mockResolvedValue({ items: [SWORD], total: 1 }),
      ...catalogue,
    } as unknown as CatalogueService,
  );
}

describe('BuildsPage', () => {
  it('reports a failed load instead of rendering it as "you have no builds"', async () => {
    const page = healthy({
      options: vi.fn().mockRejectedValue(new Error('boom')),
    } as unknown as BuildsService);

    await page['load']();

    expect(page['error']()).not.toBeNull();
    expect(page['builds']()).toEqual([]);
    expect(page['loading']()).toBe(false);
  });

  it('draws talent inputs from the API, not a list of its own', async () => {
    // A hardcoded list here would be a third copy of `LEVELLED_TALENTS`, after the validator
    // and the gcsim renderer — and a misspelled key renders as level 1 rather than erroring.
    const page = healthy();

    await page['load']();

    expect(page['talents']()).toEqual(OPTIONS.talents);
    expect(page['maxTalent']()).toBe(15);
  });

  it('asks the server for weapons of the chosen character class', async () => {
    // Server-side, because T.1 refuses a mismatched class. A client-side filter would be a
    // second copy of that rule, free to drift toward offering what the API then refuses.
    const listWeapons = vi.fn().mockResolvedValue({ items: [SWORD], total: 1 });
    const page = healthy({}, { listWeapons } as unknown as CatalogueService);
    await page['load']();

    await page['selectCharacter']('char-ayaka');

    expect(listWeapons).toHaveBeenCalledWith({
      weapon_type: 'WEAPON_SWORD_ONE_HAND',
      offset: 0,
      limit: MAX_PAGE_LIMIT,
    });
  });

  it('passes the character class through rather than translating it', async () => {
    // `weapon_type` is the source's internal spelling and `weapon_type_display` is the label.
    // Deriving one from the other here would be a copy of `WeaponType.display`.
    const listWeapons = vi.fn().mockResolvedValue({ items: [], total: 0 });
    const page = healthy({}, { listWeapons } as unknown as CatalogueService);
    await page['load']();

    await page['selectCharacter']('char-ganyu');

    expect(listWeapons.mock.calls[0][0].weapon_type).toBe('WEAPON_BOW');
  });

  it('gathers every character, not the first page', async () => {
    // 150 today against a cap of 200, so this is latent rather than broken. When it lands the
    // picker quietly loses the *newest* characters, which are exactly the ones someone opens
    // this page to build — the worst version of a silent truncation.
    const rows = Array.from({ length: 260 }, (_, i) => ({ ...AYAKA, id: `c${i}` }));
    const listCharacters = vi.fn(async (p: { offset?: number; limit?: number }) => ({
      items: rows.slice(p.offset ?? 0, (p.offset ?? 0) + (p.limit ?? 200)),
      total: rows.length,
    }));
    const page = healthy({}, { listCharacters } as unknown as CatalogueService);

    await page['load']();

    expect(page['characters']()).toHaveLength(260);
    expect(listCharacters).toHaveBeenCalledTimes(2);
  });

  it('clears the chosen weapon when the character changes', async () => {
    // The weapon belonged to the old character's class, so keeping it would build something
    // the API refuses on save — the user's own selection cited back at them as invalid.
    const page = healthy();
    await page['load']();
    await page['selectCharacter']('char-ayaka');
    page['weaponId'].set('w-mistsplitter');

    await page['selectCharacter']('char-ganyu');

    expect(page['weaponId']()).toBeNull();
  });

  it('will not save without a character', async () => {
    const create = vi.fn();
    const page = healthy({ create } as unknown as BuildsService);
    await page['load']();

    expect(page['canSave']()).toBe(false);
    await page['save']();

    expect(create).not.toHaveBeenCalled();
  });

  it('sends a build with no weapon as null rather than omitting it', async () => {
    // `weapon_id` is nullable by design (OQ-T3). Omitting it on a patch would mean "leave it
    // as it was", which is a different instruction from "unequip".
    const create = vi.fn().mockResolvedValue({ id: 'b1' });
    const page = healthy({ create } as unknown as BuildsService);
    await page['load']();
    await page['selectCharacter']('char-ayaka');

    await page['save']();

    expect(create.mock.calls[0][0].weapon_id).toBeNull();
  });

  it('patches without a character_id, which the API refuses', async () => {
    // `BuildUpdate` has no such field and now refuses one rather than dropping it silently.
    const update = vi.fn().mockResolvedValue({ id: 'b1' });
    const page = healthy({ update } as unknown as BuildsService);
    await page['load']();
    await page['edit']({
      id: 'b1', character_id: 'char-ayaka', weapon_id: 'w-mistsplitter',
      character_level: 90, ascension_phase: 6, weapon_level: 90, refinement: 1,
      constellation_level: 2, talent_levels: { elemental_burst: 9 }, notes: '',
      character: AYAKA, weapon: SWORD,
    } as never);

    await page['save']();

    expect(update).toHaveBeenCalledTimes(1);
    expect(update.mock.calls[0][1]).not.toHaveProperty('character_id');
    expect(update.mock.calls[0][1].constellation_level).toBe(2);
  });

  it('saves every talent level, not only the ones the stored build carried', async () => {
    // A build saved before a talent was set has no key for it, and `gcsim_config._talents`
    // reads a missing key as level 1. Sending the partial map back would leave the stored
    // build stating one talent and *implying* two — level 1 by convention rather than by
    // statement, which is the "absent is absent" rule read backwards.
    const update = vi.fn().mockResolvedValue({ id: 'b1' });
    const page = healthy({ update } as unknown as BuildsService);
    await page['load']();

    await page['edit']({
      id: 'b1', character_id: 'char-ayaka', weapon_id: null,
      character_level: 90, ascension_phase: 6, weapon_level: 90, refinement: 1,
      constellation_level: 0, talent_levels: { elemental_burst: 9 }, notes: '',
      character: AYAKA, weapon: null,
    } as never);
    await page['save']();

    expect(page['talentLevel']('elemental_burst')).toBe(9);
    expect(update.mock.calls[0][1].talent_levels).toEqual({
      normal_attack: 1, elemental_skill: 1, elemental_burst: 9,
    });
  });

  it('stays in the build it just saved', async () => {
    // Found by the test above: `save` reset the form unconditionally, so saving an edit threw
    // the user out of what they were editing. On screen that is indistinguishable from the
    // edit having vanished.
    const saved = { id: 'b1', character_id: 'char-ayaka' };
    const page = healthy({
      update: vi.fn().mockResolvedValue(saved),
      list: vi.fn().mockResolvedValue([saved]),
    } as unknown as BuildsService);
    await page['load']();
    await page['edit']({
      id: 'b1', character_id: 'char-ayaka', weapon_id: null,
      character_level: 90, ascension_phase: 6, weapon_level: 90, refinement: 1,
      constellation_level: 0, talent_levels: {}, notes: '',
      character: AYAKA, weapon: null,
    } as never);

    await page['save']();

    expect(page['editing']()?.id).toBe('b1');
  });

  it('clears the form after creating, so the next build starts fresh', async () => {
    const page = healthy({
      create: vi.fn().mockResolvedValue({ id: 'b2' }),
    } as unknown as BuildsService);
    await page['load']();
    await page['selectCharacter']('char-ayaka');

    await page['save']();

    expect(page['editing']()).toBeNull();
    expect(page['characterId']()).toBe('');
  });

  it('shows the API refusal verbatim rather than inventing its own', async () => {
    // The 422 names both weapon classes, or the three talent keys. Anything substituted here
    // would be strictly less useful.
    const detail = 'Kamisato Ayaka wields a Sword and Amos\' Bow is a Bow.';
    const page = healthy({
      create: vi.fn().mockRejectedValue({ detail }),
    } as unknown as BuildsService);
    await page['load']();
    await page['selectCharacter']('char-ayaka');

    await page['save']();

    expect(page['actionError']()).toBe(detail);
  });

  it('surfaces a failed weapon load without wiping the page', async () => {
    const page = healthy({}, {
      listWeapons: vi.fn().mockRejectedValue(new Error('boom')),
    } as unknown as CatalogueService);
    await page['load']();

    await page['selectCharacter']('char-ayaka');

    expect(page['actionError']()).not.toBeNull();
    expect(page['error']()).toBeNull();
    expect(page['characters']()).toHaveLength(2);
  });
});


/**
 * The saved column's filter. A GOOD import makes one build per equipped character — 75 on the
 * owner's account — against a column that shows about nine at a time, so this is the
 * difference between a list and a scroll.
 */
describe('matchesBuild', () => {
  const build = (
    name: string, element: string | null, weapon: string | null,
    weapon_type = 'WEAPON_SWORD_ONE_HAND', stars = 5,
  ) => ({
    character: { name, element, weapon_type, stars },
    weapon: weapon === null ? null : { name: weapon },
  });

  const roster = [
    build('Nahida', 'Dendro', 'Mappa Mare', 'WEAPON_CATALYST', 5),
    build('Kaedehara Kazuha', 'Anemo', 'Freedom-Sworn', 'WEAPON_SWORD_ONE_HAND', 5),
    build('Beidou', 'Electro', null, 'WEAPON_CLAYMORE', 4),
  ];

  const kept = (search: string, element = '', weaponType = '', stars = '') =>
    roster.filter(matchesBuild(search, element, weaponType, stars))
      .map((b) => b.character.name);

  it('keeps everything when nothing is asked', () => {
    expect(kept('')).toEqual(['Nahida', 'Kaedehara Kazuha', 'Beidou']);
  });

  it('matches a character by part of their name, in any case', () => {
    expect(kept('nahi')).toEqual(['Nahida']);
    expect(kept('KAZUHA')).toEqual(['Kaedehara Kazuha']);
  });

  it('does not match a weapon, by owner ruling', () => {
    // It used to, on the argument that "who has Freedom-Sworn" is as ordinary a question as
    // "where's Nahida". The owner's audit reverses it, and the reason shows once the filters
    // are chips: typing "sword" matched every build holding one, so a search for a *character*
    // returned a wall of weapons. The weapon question is a filter, and now it is one.
    expect(kept('freedom')).toEqual([]);
  });

  it('does not fall over on a build with no weapon', () => {
    // "Beidou C5 · no weapon" is a real row in the owner's account.
    expect(kept('beidou')).toEqual(['Beidou']);
  });

  it('filters by weapon class', () => {
    expect(kept('', '', 'WEAPON_CLAYMORE')).toEqual(['Beidou']);
  });

  it('filters by the character\'s rarity, not the weapon\'s', () => {
    // These cards are character-first: the art, the name and the vision are all theirs, so a
    // rarity chip beside them that meant the weapon's would be reading the wrong number off
    // the same card.
    expect(kept('', '', '', '4')).toEqual(['Beidou']);
  });

  it('narrows across filters rather than widening', () => {
    // Two chips are an AND, which is what a filter bar means everywhere else in this app.
    expect(kept('', 'Electro', 'WEAPON_CATALYST')).toEqual([]);
  });

  it('filters by vision', () => {
    expect(kept('', 'Dendro')).toEqual(['Nahida']);
  });

  it('applies the vision and the text together, not either', () => {
    // Both narrow. Treating them as alternatives would *widen* the result as the user adds a
    // filter, which is the opposite of what pressing one means.
    expect(kept('nahida', 'Anemo')).toEqual([]);
    expect(kept('nahida', 'Dendro')).toEqual(['Nahida']);
  });

  it('ignores surrounding whitespace so a stray space does not empty the list', () => {
    expect(kept('  nahida  ')).toEqual(['Nahida']);
  });
});


/**
 * The two pickers and the grid's own chips.
 *
 * The owner's audit asks for card grids *everywhere* a drop-down offers things with pictures,
 * and the risk in adopting one page at a time is that each surface decides the filters
 * separately. These tests pin the decisions this page made, so the next adoption can copy them
 * deliberately rather than by eye.
 */
describe('BuildsPage pickers', () => {
  it('offers every character as a card, with the art and the class', async () => {
    const page = healthy();

    await page['load']();

    expect(page['characterOptions']()).toEqual([
      {
        value: 'char-ayaka', label: 'Kamisato Ayaka', icon: 'UI_AvatarIcon_Ayaka',
        detail: 'Sword', tags: { element: 'Cryo', weapon: 'WEAPON_SWORD_ONE_HAND' },
      },
      {
        value: 'char-ganyu', label: 'Ganyu', icon: 'UI_AvatarIcon_Ganyu',
        detail: 'Bow', tags: { element: 'Cryo', weapon: 'WEAPON_BOW' },
      },
    ]);
  });

  it('filters the character grid by vision and class, and by nothing else', async () => {
    // Not by rarity: a 4★ character is not a worse build subject, and offering the filter
    // implies it is.
    const page = healthy();

    await page['load']();

    expect(page['characterFilters']().map((f) => f.group)).toEqual(['element', 'weapon']);
    // One vision between them, so one chip — the two Cryo characters do not make two.
    expect(page['characterFilters']()[0].options.map((o) => o.value)).toEqual(['Cryo']);
    expect(page['characterFilters']()[1].options.map((o) => o.label)).toEqual(['Bow', 'Sword']);
  });

  it('offers no weapon-class chip, because the list is already one class', async () => {
    // The server filtered it by the chosen character's class, so a "Bow" chip on a Sword
    // character would filter to nothing — a control whose only outcome is an empty grid.
    const page = healthy();
    await page['load']();

    await page['selectCharacter']('char-ayaka');

    expect(page['weaponFilters']()).toEqual([]);
    expect(page['weaponOptions']()).toEqual([{
      value: 'w-mistsplitter', label: 'Mistsplitter Reforged',
      icon: 'UI_EquipIcon_Sword_Narukami', detail: '5★ · CRIT DMG', tags: { stars: '5' },
    }]);
  });

  it('offers a rarity chip once the list has more than one rarity', async () => {
    const page = healthy({}, {
      listCharacters: vi.fn().mockResolvedValue({ items: [AYAKA], total: 1 }),
      listWeapons: vi.fn().mockResolvedValue({
        items: [SWORD, { ...SWORD, id: 'w-favonius', name: 'Favonius Sword', stars: 4 }],
        total: 2,
      }),
    } as unknown as CatalogueService);
    await page['load']();

    await page['selectCharacter']('char-ayaka');

    expect(page['weaponFilters']()[0].options.map((o) => o.label)).toEqual(['5★', '4★']);
  });

  it('draws the grid chips from the saved builds, never from the catalogue', async () => {
    // A vision nobody has built for is a chip whose only possible outcome is an empty grid.
    const build = {
      id: 'b1', character_id: 'char-ganyu', weapon_id: null,
      character_level: 90, ascension_phase: 6, weapon_level: 90, refinement: 1,
      constellation_level: 0, talent_levels: {}, notes: '', weapon_display: null,
      character: GANYU, weapon: null,
    };
    const page = healthy({
      list: vi.fn().mockResolvedValue([build]),
    } as unknown as BuildsService);

    await page['load']();

    expect(page['elementsPresent']()).toEqual([{ element: 'Cryo', icon: 'Cryo' }]);
    // Ayaka is in the catalogue and holds a sword; no build does, so there is no sword chip.
    expect(page['weaponTypesPresent']().map((w) => w.label)).toEqual(['Bow']);
    expect(page['starsPresent']()).toEqual(['5']);
  });

  it('survives an environment with no <dialog>', async () => {
    // `HTMLDialogElement` is absent in jsdom, so `showModal` is undefined and a bare call is a
    // TypeError thrown from inside a click handler — which takes the page out rather than
    // failing the one control. The same is true of any browser without <dialog>.
    const page = healthy();
    await page['load']();

    expect(() => page['startNew']()).not.toThrow();
    expect(() => page['closeEditor']()).not.toThrow();
    expect(page['editing']()).toBeNull();
  });
});
