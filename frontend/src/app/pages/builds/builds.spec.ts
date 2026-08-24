import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { MAX_PAGE_LIMIT } from '../../api/page-size';
import { CatalogueService } from '../catalogue/catalogue.service';
import { BuildsPage } from './builds';
import { BuildsService } from './builds.service';

const AYAKA = {
  id: 'char-ayaka', nanoka_id: '10000002', name: 'Kamisato Ayaka', element: 'Cryo',
  weapon_type: 'WEAPON_SWORD_ONE_HAND', weapon_type_display: 'Sword', rarity: 5,
};
const GANYU = {
  id: 'char-ganyu', nanoka_id: '10000037', name: 'Ganyu', element: 'Cryo',
  weapon_type: 'WEAPON_BOW', weapon_type_display: 'Bow', rarity: 5,
};
const SWORD = {
  id: 'w-mistsplitter', nanoka_id: 11509, name: 'Mistsplitter Reforged',
  weapon_type: 'WEAPON_SWORD_ONE_HAND', weapon_type_display: 'Sword', rarity: 5,
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
