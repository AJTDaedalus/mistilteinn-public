import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { RotationsPage } from './rotations';
import { RotationsService, type RosterCharacter } from './rotations.service';

const ROSTER: RosterCharacter[] = [
  {
    nanoka_id: '10000002', name: 'Kamisato Ayaka', element: 'Cryo',
    // Keyed by **gcsim's action**, not by talent type. The first version of this fixture
    // used `elemental_skill` — the same wrong assumption the implementation had — so the
    // test passed against a feature that showed `skill` on every button. Caught by looking
    // at the page.
    abilities: { skill: 'Kamisato Art: Hyouka' },
    // The per-character vocabulary (T.3). Ayaka has no kit variant — gcsim's generated
    // validation table declares her no `hold` — which is exactly the fixture worth having
    // beside a character who does.
    actions: [
      { action: 'skill', base: 'skill', variant: null, name: 'Kamisato Art: Hyouka',
        icon: 'Skill_S_Ayaka_01' },
      { action: 'burst', base: 'burst', variant: null, name: 'Kamisato Art: Soumetsu',
        icon: 'Skill_E_Ayaka' },
      { action: 'attack', base: 'attack', variant: null, name: 'Kamisato Art: Kabuki',
        icon: 'Skill_A_01' },
      // One of the seven that are not talents: the key stands in for a name, and there is no
      // sprite. Owner ruling — words, not glyphs.
      { action: 'charge', base: 'charge', variant: null, name: 'charge', icon: null },
    ],
  },
  // No seeded talents: the editor falls back to the action key, which is the case worth
  // having a fixture for. And a hold-E, so the badge and the per-character offer have
  // somewhere to be tested.
  {
    nanoka_id: '10000014', name: 'Barbara', element: 'Hydro', abilities: {},
    actions: [
      { action: 'skill', base: 'skill', variant: null, name: 'skill', icon: null },
      { action: 'skill_hold', base: 'skill', variant: 'hold', name: 'skill', icon: null },
    ],
  },
];

const OPTIONS = {
  actions: ['skill', 'burst', 'attack'],
  teams: [
    { id: 'team-1', name: 'Party', characters: ROSTER },
    { id: 'team-2', name: 'Second', characters: [ROSTER[1]] },
  ],
};

function pageWith(service: Partial<RotationsService>) {
  TestBed.configureTestingModule({
    providers: [{ provide: RotationsService, useValue: service }],
  });
  return TestBed.runInInjectionContext(() => new RotationsPage());
}

function healthy(overrides: Partial<RotationsService> = {}) {
  return pageWith({
    options: vi.fn().mockResolvedValue(OPTIONS),
    list: vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 }),
    ...overrides,
  } as unknown as RotationsService);
}

describe('RotationsPage', () => {
  it('reports a failed load instead of rendering it as "you have no teams"', async () => {
    // The distinction: an empty editor and a broken one look identical on screen, and only
    // one of them means the account has nothing in it. The same failure the catalogue pages
    // were written against.
    const page = healthy({
      options: vi.fn().mockRejectedValue(new Error('boom')),
    } as unknown as RotationsService);

    await page['load']();

    expect(page['error']()).not.toBeNull();
    expect(page['teams']()).toEqual([]);
    expect(page['loading']()).toBe(false);
  });

  it('offers the actions the API published, not a list of its own', async () => {
    // A hardcoded vocabulary here would be a second copy of gcsim's `astr` at the pin, and
    // the copy that drifted would be the one offering something the backend then refused.
    const page = healthy();

    await page['load']();

    expect(page['actions']()).toEqual(OPTIONS.actions);
  });

  it('adds a step from the chosen team roster, never a hardcoded default', async () => {
    const page = healthy();
    await page['load']();

    page['addStep']();

    expect(page['steps']()).toEqual([
      { character: '10000002', action: 'skill', repeat: 1, note: '', group: '', group_repeat: 1 },
    ]);
  });

  it('refuses to add a step when the team holds nobody', async () => {
    const page = healthy({
      options: vi.fn().mockResolvedValue({ actions: OPTIONS.actions, teams: [
        { id: 'empty', name: 'Nobody', characters: [] },
      ] }),
    } as unknown as RotationsService);
    await page['load']();

    page['addStep']();

    expect(page['steps']()).toEqual([]);
  });

  it('clears the steps when the team changes', async () => {
    // Steps name characters on the *old* team. Carrying them over would build a rotation the
    // API refuses on save, citing the user's own selections back at them as invalid.
    const page = healthy();
    await page['load']();
    page['addStep']();

    page['selectTeam']('team-2');

    expect(page['steps']()).toEqual([]);
    expect(page['roster']()).toEqual([ROSTER[1]]);
  });

  it('reorders steps, and does nothing at the ends', async () => {
    const page = healthy();
    await page['load']();
    page['addStep']();
    page['addStep']();
    page['setStep'](1, { character: '10000014', action: 'burst' });

    page['move'](1, -1);
    expect(page['steps']().map((s) => s.character)).toEqual(['10000014', '10000002']);

    page['move'](0, -1);
    page['move'](1, 1);
    expect(page['steps']().map((s) => s.character)).toEqual(['10000014', '10000002']);
  });

  it('shows the API refusal verbatim rather than inventing its own', async () => {
    // The backend's 422 names the offending characters and lists who the team actually has.
    // Anything this page substituted would be strictly less useful.
    const detail = "these characters are not on that team: ['10000030'].";
    const page = healthy({
      create: vi.fn().mockRejectedValue({ detail }),
    } as unknown as RotationsService);
    await page['load']();
    page['addStep']();
    page['name'].set('Melt opener');

    await page['save']();

    expect(page['actionError']()).toBe(detail);
  });

  it('will not save without a name, a team and at least one step', async () => {
    const create = vi.fn();
    const page = healthy({ create } as unknown as RotationsService);
    await page['load']();

    page['name'].set('Named but empty');
    expect(page['canSave']()).toBe(false);
    await page['save']();
    expect(create).not.toHaveBeenCalled();

    page['addStep']();
    expect(page['canSave']()).toBe(true);
  });

  it('patches an existing rotation instead of creating a second one', async () => {
    const create = vi.fn();
    const update = vi.fn().mockResolvedValue({ id: 'rot-1' });
    const page = healthy({ create, update } as unknown as RotationsService);
    await page['load']();
    page['edit']({
      id: 'rot-1', name: 'Saved', team_id: 'team-1', description: '',
      steps: [{ character: '10000002', action: 'burst', repeat: 1, note: '', group: '', group_repeat: 1 }],
      visibility: 'private' as const,
    });
    page['name'].set('Renamed');

    await page['save']();

    expect(create).not.toHaveBeenCalled();
    expect(update).toHaveBeenCalledWith('rot-1', {
      name: 'Renamed',
      steps: [{ character: '10000002', action: 'burst', repeat: 1, note: '', group: '', group_repeat: 1 }],
    });
  });

  it('only compiles a saved rotation', async () => {
    // The endpoint reads the *stored* steps. Compiling an unsaved edit would print the
    // config for the last save while the screen showed something else.
    const compile = vi.fn().mockResolvedValue('active ayaka;\n');
    const page = healthy({ compile } as unknown as RotationsService);
    await page['load']();
    page['addStep']();

    await page['compile']();
    expect(compile).not.toHaveBeenCalled();
    expect(page['compiled']()).toBeNull();

    page['edit']({ id: 'rot-1', name: 'S', team_id: 'team-1', description: '', steps: [], visibility: 'private' as const });
    await page['compile']();
    expect(compile).toHaveBeenCalledWith('rot-1');
    expect(page['compiled']()).toBe('active ayaka;\n');
  });

  it('will not compile a saved rotation that has been edited since', async () => {
    // The hole the first version of this guard left open. `editing()` was set, so Compile
    // stayed enabled, and it would have printed the config for the *stored* steps beside a
    // screen showing different ones — the exact failure the guard was written to prevent.
    const compile = vi.fn().mockResolvedValue('active ayaka;\n');
    const page = healthy({ compile } as unknown as RotationsService);
    await page['load']();
    page['edit']({
      id: 'rot-1', name: 'Saved', team_id: 'team-1', description: '',
      steps: [{ character: '10000002', action: 'burst', repeat: 1, note: '', group: '', group_repeat: 1 }],
      visibility: 'private' as const,
    });
    expect(page['dirty']()).toBe(false);

    page['setStep'](0, { repeat: 4 });

    expect(page['dirty']()).toBe(true);
    await page['compile']();
    expect(compile).not.toHaveBeenCalled();
  });

  it('a rename alone is enough to make it dirty', async () => {
    const page = healthy();
    await page['load']();
    page['edit']({
      id: 'rot-1', name: 'Saved', team_id: 'team-1', description: '', steps: [],
      visibility: 'private' as const,
    });

    page['name'].set('Renamed');

    expect(page['dirty']()).toBe(true);
  });

  it('saving clears dirty, so Compile becomes available again', async () => {
    const page = healthy({
      update: vi.fn().mockResolvedValue({ id: 'rot-1' }),
    } as unknown as RotationsService);
    await page['load']();
    page['edit']({
      id: 'rot-1', name: 'Saved', team_id: 'team-1', description: '',
      steps: [{ character: '10000002', action: 'burst', repeat: 1, note: '', group: '', group_repeat: 1 }],
      visibility: 'private' as const,
    });
    page['setStep'](0, { repeat: 4 });

    await page['save']();

    expect(page['dirty']()).toBe(false);
  });

  it('drops a stale compiled config as soon as the steps change', async () => {
    const page = healthy({
      compile: vi.fn().mockResolvedValue('active ayaka;\n'),
    } as unknown as RotationsService);
    await page['load']();
    page['edit']({ id: 'rot-1', name: 'S', team_id: 'team-1', description: '', steps: [], visibility: 'private' as const });
    await page['compile']();
    expect(page['compiled']()).not.toBeNull();

    page['addStep']();

    expect(page['compiled']()).toBeNull();
  });
});


/**
 * The library, reached from inside an expanded team.
 *
 * Two things here would be wrong in ways nobody notices: a library that opens unfiltered (so
 * "rotations for this team" quietly means "all rotations"), and an optimistic like that stays
 * on screen after the request failed.
 */
describe('RotationsPage library', () => {
  const TEAM = OPTIONS.teams[0];
  const ROW = {
    id: 'lib-1', name: 'Freeze opener', description: '',
    steps: [{ character: '10000002', action: 'burst' as const, repeat: 1, note: '', group: '', group_repeat: 1 }],
    characters: ['10000002', '10000014'], like_count: 2, liked_by_me: false,
  };

  const withLibrary = (overrides: Partial<RotationsService> = {}) => healthy({
    library: vi.fn().mockResolvedValue({ items: [ROW], total: 1, offset: 0, limit: 50 }),
    setLiked: vi.fn().mockResolvedValue(undefined),
    copy: vi.fn().mockResolvedValue({ ...ROW, name: 'Freeze opener (copy)' }),
    ...overrides,
  } as unknown as RotationsService);

  it('opens filtered to the team it was opened from', async () => {
    // A library reached from inside a team is asking "what do people run on *this*". Opening
    // it unfiltered would make the button's own label untrue.
    const page = withLibrary();
    await page['load']();

    await page['openLibrary'](TEAM);

    const library = page['rotations'].library as ReturnType<typeof vi.fn>;
    expect(library).toHaveBeenCalledWith({ characters: ['10000002', '10000014'] });
    expect(page['libraryRows']()).toHaveLength(1);
  });

  it('widens to everything published without a character filter', async () => {
    const page = withLibrary();
    await page['load']();
    await page['openLibrary'](TEAM);

    await page['setLibraryScope'](false);

    const library = page['rotations'].library as ReturnType<typeof vi.fn>;
    expect(library).toHaveBeenLastCalledWith({ characters: undefined });
  });

  it('reports a failed load rather than showing it as an empty library', async () => {
    // An empty library and a broken one look identical, and only one of them means nobody has
    // published anything.
    const page = withLibrary({
      library: vi.fn().mockRejectedValue(new Error('boom')),
    } as unknown as RotationsService);
    await page['load']();

    await page['openLibrary'](TEAM);

    expect(page['libraryError']()).not.toBeNull();
    expect(page['libraryRows']()).toEqual([]);
  });

  it('moves the like count immediately, and puts it back when the save fails', async () => {
    // Optimistic because a like is a one-bit opinion and waiting a round trip to see it
    // register is the wrong trade. Reverted because a count that stayed after a failure would
    // be a number the server does not agree with.
    const page = withLibrary({
      setLiked: vi.fn().mockRejectedValue(new Error('offline')),
    } as unknown as RotationsService);
    await page['load']();
    await page['openLibrary'](TEAM);

    await page['toggleLike'](page['libraryRows']()[0]);

    expect(page['libraryRows']()[0]).toMatchObject({ liked_by_me: false, like_count: 2 });
    expect(page['libraryError']()).not.toBeNull();
  });

  it('keeps a successful like on screen', async () => {
    const page = withLibrary();
    await page['load']();
    await page['openLibrary'](TEAM);

    await page['toggleLike'](page['libraryRows']()[0]);

    expect(page['libraryRows']()[0]).toMatchObject({ liked_by_me: true, like_count: 3 });
  });

  it('copies onto the team the library was opened from, and says what it made', async () => {
    const page = withLibrary();
    await page['load']();
    await page['openLibrary'](TEAM);

    await page['copyFromLibrary'](page['libraryRows']()[0]);

    const copy = page['rotations'].copy as ReturnType<typeof vi.fn>;
    expect(copy).toHaveBeenCalledWith('lib-1', 'team-1');
    expect(page['libraryNote']()).toContain('Freeze opener (copy)');
  });

  it("shows the server's refusal verbatim, because it names what is missing", async () => {
    // "That team does not field 10000002" is actionable; "could not copy" is not.
    const page = withLibrary({
      copy: vi.fn().mockRejectedValue({ detail: 'That team does not field 10000002.' }),
    } as unknown as RotationsService);
    await page['load']();
    await page['openLibrary'](TEAM);

    await page['copyFromLibrary'](page['libraryRows']()[0]);

    expect(page['libraryError']()).toContain('10000002');
    expect(page['libraryNote']()).toBeNull();
  });

  it('survives an environment with no <dialog>', async () => {
    // jsdom has no `HTMLDialogElement`, so `showModal` is undefined and a bare call is a
    // TypeError thrown from inside a click handler — which takes the page out.
    const page = withLibrary();
    await page['load']();

    await expect(page['openLibrary'](TEAM)).resolves.toBeUndefined();
    expect(() => page['closeLibrary']()).not.toThrow();
  });
});


/**
 * The builder's authoring surface — `DESIGN_rotation_builder.md` B.1, B.2, B.3, B.6.
 *
 * All four are about **cost**, not capability: the model is unchanged, and §1 of that document
 * is explicit that it must be. So these tests check that a step added the fast way is
 * identical to one added the slow way, which is the thing that would silently drift.
 */
describe('RotationsPage builder', () => {
  it('adds a step in two clicks, identical to the one the old path made', async () => {
    // B.2. Two entry points, one `appendStep`, because two `steps.update` calls would
    // eventually initialise a step differently and only one of them would be tested.
    //
    // Both paths on **one** page: `TestBed.configureTestingModule` refuses a second call once
    // the module is instantiated, so two `healthy()` pages in one test is not available here.
    const page = healthy();
    await page['load']();

    page['toggleAddingFor']('10000014');
    page['quickAdd']('burst');
    page['addStep']();
    page['setStep'](1, { character: '10000014', action: 'burst' });

    const [fast, slow] = page['steps']();
    expect(fast).toEqual(slow);
  });

  it('closes the action list after adding, so a second click is a second character', async () => {
    const page = healthy();
    await page['load']();

    page['toggleAddingFor']('10000014');
    page['quickAdd']('skill');

    expect(page['addingFor']()).toBeNull();
  });

  it("labels an action with the character's own name for it", async () => {
    // B.1. A gcsim config says `nahida skill`; the complaint that started this chunk was
    // about exactly that.
    const page = healthy();
    await page['load']();

    expect(page['abilityName']('10000002', 'skill')).toBe('Kamisato Art: Hyouka');
  });

  it('falls back to the action key rather than showing nothing', async () => {
    // Barbara has no seeded talents in the fixture, and `dash` is not an ability for anyone.
    const page = healthy();
    await page['load']();

    expect(page['abilityName']('10000014', 'skill')).toBe('skill');
    expect(page['abilityName']('10000002', 'dash')).toBe('dash');
    expect(page['abilityName']('nobody', 'skill')).toBe('skill');
  });

  it('duplicates a step immediately after itself, not at the end', async () => {
    // B.3. `DESIGN_rotation.md` §2 answers "repeat this section" with "write it three times…
    // a UI can duplicate a selection", and position is the whole value: appended to the end
    // it would be a different rotation.
    const page = healthy();
    await page['load']();
    page['addStep']();
    page['setStep'](0, { action: 'skill' });
    page['addStep']();
    page['setStep'](1, { action: 'burst' });

    page['duplicateStep'](0);

    expect(page['steps']().map((s) => s.action)).toEqual(['skill', 'skill', 'burst']);
  });

  it('duplicates by value, so editing the copy leaves the original alone', async () => {
    const page = healthy();
    await page['load']();
    page['addStep']();

    page['duplicateStep'](0);
    page['setStep'](1, { repeat: 4 });

    expect(page['steps']()[0].repeat).toBe(1);
    expect(page['steps']()[1].repeat).toBe(4);
  });

  it('keeps a per-step note, which the model has carried since R.4', async () => {
    // B.6. The field existed and no UI had ever shown it.
    const page = healthy();
    await page['load']();
    page['addStep']();

    page['setStep'](0, { note: 'after Furina stacks' });

    expect(page['steps']()[0].note).toBe('after Furina stacks');
  });
});


/**
 * Reordering by drag, and the live preview — `DESIGN_rotation_builder.md` B.4 and B.5.
 *
 * **Order is the rotation.** A reorder that lands a step one position out does not fail; it
 * produces a different, plausible rotation, which is the only kind of bug this list can have.
 */
describe('RotationsPage reorder and preview', () => {
  const withSteps = async (page: ReturnType<typeof healthy>, ...actions: string[]) => {
    await page['load']();
    for (const action of actions) {
      page['appendStep']('10000002', action as never);
    }
    return page;
  };
  const order = (page: ReturnType<typeof healthy>) => page['steps']().map((s) => s.action);

  it('moves a step down to the index it was dropped on', async () => {
    const page = await withSteps(healthy(), 'skill', 'burst', 'attack');

    page['reorder'](0, 2);

    expect(order(page)).toEqual(['burst', 'attack', 'skill']);
  });

  it('moves a step up to the index it was dropped on', async () => {
    const page = await withSteps(healthy(), 'skill', 'burst', 'attack');

    page['reorder'](2, 0);

    expect(order(page)).toEqual(['attack', 'skill', 'burst']);
  });

  it('leaves the list alone for a drop on itself or out of range', async () => {
    const page = await withSteps(healthy(), 'skill', 'burst');

    page['reorder'](0, 0);
    page['reorder'](0, 5);
    page['reorder'](-1, 1);

    expect(order(page)).toEqual(['skill', 'burst']);
  });

  it('agrees with the arrows, which are the keyboard path', async () => {
    // Both exist on purpose: a drag has no keyboard equivalent. They must not disagree about
    // what "move this one down" means — a swap and a splice happen to coincide for ±1, and
    // that coincidence is the thing worth pinning.
    //
    // One page, because `TestBed.configureTestingModule` refuses a second call once the
    // module is instantiated.
    const page = await withSteps(healthy(), 'skill', 'burst', 'attack');

    page['move'](0, 1);
    const byArrow = order(page);
    page['steps'].set([]);
    for (const action of ['skill', 'burst', 'attack']) {
      page['appendStep']('10000002', action as never);
    }
    page['reorder'](0, 1);

    expect(byArrow).toEqual(['burst', 'skill', 'attack']);
    expect(order(page)).toEqual(byArrow);
  });

  it('drops nothing when no drag was in flight', async () => {
    const page = await withSteps(healthy(), 'skill', 'burst');

    page['onDrop'](1);

    expect(order(page)).toEqual(['skill', 'burst']);
  });

  it('compiles what is on screen, not what was saved', async () => {
    // The whole point of B.5: `compile()` reads the stored rotation, so a preview of unsaved
    // work built on it would show the saved version — worse than none, because it looks
    // current.
    const preview = vi.fn().mockResolvedValue('while 1 { }');
    const page = await withSteps(
      healthy({ preview } as unknown as RotationsService), 'skill',
    );
    page['teamId'].set('team-1');

    page['togglePreview']();
    await Promise.resolve();
    await Promise.resolve();

    expect(preview).toHaveBeenCalledWith('team-1', page['steps']());
  });

  it('shows a refusal rather than a stale config', async () => {
    // The refusal names the step that cannot compile. A previous config left beside the edit
    // that broke it would be the preview lying.
    const page = await withSteps(
      healthy({
        preview: vi.fn().mockRejectedValue({ detail: 'that team does not field 10000037' }),
      } as unknown as RotationsService),
      'skill',
    );
    page['teamId'].set('team-1');
    page['compiled'].set('stale');

    await page['refreshPreview']();

    expect(page['compiled']()).toBeNull();
    expect(page['previewError']()).toContain('10000037');
  });

  it('does not call the server while the preview is closed', async () => {
    const preview = vi.fn().mockResolvedValue('');
    const page = await withSteps(
      healthy({ preview } as unknown as RotationsService), 'skill',
    );

    page['schedulePreview']();

    expect(preview).not.toHaveBeenCalled();
  });
});

// ── the timeline's three levels: selection, copy/paste, groups, insert ───────
//
// `DESIGN_rotation_builder_gui.md` §2. One selection signal and three renderers, because the
// recurring failure in this repo is two representations that can disagree — #184 found every
// `<select>` in this very editor showing option zero, with 418 tests passing.

describe('RotationsPage — selection', () => {
  async function editing(steps: string[] = ['skill', 'burst', 'attack']) {
    const page = healthy();
    await page['load']();
    page['pickTeam'](['team-1']);
    for (const action of steps) page['appendStep']('10000002', action as 'skill');
    return page;
  }

  it('selects one step, and replaces the selection on a plain click', async () => {
    const page = await editing();

    page['onPick']({ index: 1, extend: false });
    page['onPick']({ index: 2, extend: false });

    expect(page['selection']()).toEqual({ start: 2, end: 2 });
  });

  it('extends from the anchor on shift-click, in either direction', async () => {
    const page = await editing();

    page['onPick']({ index: 2, extend: false });
    page['onPick']({ index: 0, extend: true });

    expect(page['selection']()).toEqual({ start: 0, end: 2 });
  });

  it('exposes the single selected step and nothing for a span', async () => {
    // Level three edits *one* move. A detail pane showing the first of five would be editing
    // something other than what the user has highlighted.
    const page = await editing();

    page['onPick']({ index: 1, extend: false });
    expect(page['selectedStep']()?.action).toBe('burst');

    page['onPick']({ index: 2, extend: true });
    expect(page['selectedStep']()).toBeNull();
  });

  it('clears the selection when a step is removed', async () => {
    // The indices moved. Keeping the span would leave it pointing at a different step, which
    // is the same class of error as a stale cached number.
    const page = await editing();
    page['onPick']({ index: 2, extend: false });

    page['removeStep'](2);

    expect(page['selection']()).toBeNull();
  });
});

describe('RotationsPage — copy and paste', () => {
  async function withSteps() {
    const page = healthy();
    await page['load']();
    page['pickTeam'](['team-1']);
    page['appendStep']('10000002', 'skill');
    page['appendStep']('10000002', 'burst');
    return page;
  }

  it('keeps DESIGN_rotation.md §2 promise that a UI can duplicate a selection', async () => {
    // §2 refused nesting *and* offered this instead — "the list is short and a UI can
    // duplicate a selection" — and no UI had ever done it.
    const page = await withSteps();
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 1, extend: true });

    page['copySelection']();
    page['pasteClipboard']();

    expect(page['steps']().map((s) => s.action)).toEqual(['skill', 'burst', 'skill', 'burst']);
  });

  it('pastes after the selection and selects what it pasted', async () => {
    const page = await withSteps();
    page['onPick']({ index: 0, extend: false });
    page['copySelection']();

    page['pasteClipboard']();

    expect(page['steps']().map((s) => s.action)).toEqual(['skill', 'skill', 'burst']);
    expect(page['selection']()).toEqual({ start: 1, end: 1 });
  });

  it('pastes at the end when nothing is selected', async () => {
    const page = await withSteps();
    page['onPick']({ index: 0, extend: false });
    page['copySelection']();
    page['selection'].set(null);

    page['pasteClipboard']();

    expect(page['steps']()).toHaveLength(3);
  });

  it('drops the group id off a pasted fragment', async () => {
    // A fragment lifted out of a group is not that group. Carrying the id would silently
    // extend a repeat the user did not ask for — or split one, which the API refuses on save.
    const page = await withSteps();
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 1, extend: true });
    page['groupSelection'](3);
    page['copySelection']();
    page['selection'].set(null);

    page['pasteClipboard']();

    expect(page['steps']().slice(2).map((s) => s.group)).toEqual(['', '']);
  });

  it('keeps a pasted step for a character this team lacks, and says so', async () => {
    // `DESIGN_rotation.md` OQ-R2's ruling for every unresolvable reference in this repo:
    // kept and flagged. Dropping it would delete the user's work to make a save succeed.
    const page = await withSteps();
    page['clipboard'].set([
      { character: 'nobody', action: 'skill', repeat: 1, note: '', group: '', group_repeat: 1 },
    ]);

    page['pasteClipboard']();

    expect(page['steps']().some((s) => s.character === 'nobody')).toBe(true);
    expect(page['actionError']()).toContain('this team does not have');
  });

  it('does nothing when the clipboard is empty', async () => {
    const page = await withSteps();

    page['pasteClipboard']();

    expect(page['steps']()).toHaveLength(2);
  });

  it('leaves a chord alone while the user is typing in a field', async () => {
    // Copying a rotation when they meant to copy the text of a note would be the editor
    // overriding the browser.
    const page = await withSteps();
    page['onPick']({ index: 0, extend: false });
    const input = document.createElement('input');

    page['onEditorKey']({
      ctrlKey: true, key: 'c', target: input, preventDefault: () => undefined,
    } as unknown as KeyboardEvent);

    expect(page['clipboard']()).toEqual([]);
  });

  it('copies on ctrl+c outside a field', async () => {
    const page = await withSteps();
    page['onPick']({ index: 0, extend: false });

    page['onEditorKey']({
      ctrlKey: true, key: 'c', target: document.createElement('div'),
      preventDefault: () => undefined,
    } as unknown as KeyboardEvent);

    expect(page['clipboard']()).toHaveLength(1);
  });
});

describe('RotationsPage — groups', () => {
  async function withThree() {
    const page = healthy();
    await page['load']();
    page['pickTeam'](['team-1']);
    for (const action of ['skill', 'burst', 'attack']) {
      page['appendStep']('10000002', action as 'skill');
    }
    return page;
  }

  it('wraps a span in a group that repeats', async () => {
    const page = await withThree();
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 1, extend: true });

    page['groupSelection'](3);

    const steps = page['steps']();
    expect(steps.map((s) => s.group)).toEqual(['g1', 'g1', '']);
    expect(steps.map((s) => s.group_repeat)).toEqual([3, 3, 1]);
  });

  it('refuses to group a single step', async () => {
    // A group of one repeats one step, which `repeat` already does — and it would put two
    // ways to say the same thing on screen.
    const page = await withThree();
    page['onPick']({ index: 0, extend: false });

    expect(page['canGroup']()).toBe(false);
  });

  it('refuses to group a span that already contains a group', async () => {
    // No group inside a group. Part of the owner's ruling, not implementation detail.
    const page = await withThree();
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 1, extend: true });
    page['groupSelection'](2);
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 2, extend: true });

    expect(page['canGroup']()).toBe(false);
  });

  it('picks an id nothing else is using', async () => {
    const page = await withThree();
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 1, extend: true });
    page['groupSelection'](2);
    page['appendStep']('10000002', 'skill');
    page['appendStep']('10000002', 'burst');
    page['onPick']({ index: 3, extend: false });
    page['onPick']({ index: 4, extend: true });

    page['groupSelection'](2);

    expect(new Set(page['steps']().map((s) => s.group))).toEqual(new Set(['g1', '', 'g2']));
  });

  it('ungroups the whole group, not only the selected part', async () => {
    const page = await withThree();
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 1, extend: true });
    page['groupSelection'](2);
    page['onPick']({ index: 0, extend: false });

    page['ungroupSelection']();

    expect(page['steps']().every((s) => s.group === '')).toBe(true);
  });

  it('changes the repeat on every member, because the compiler reads one of them', async () => {
    const page = await withThree();
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 1, extend: true });
    page['groupSelection'](2);
    page['onPick']({ index: 0, extend: false });

    page['setGroupRepeat'](5);

    expect(page['steps']().slice(0, 2).map((s) => s.group_repeat)).toEqual([5, 5]);
  });

  it('bounds the repeat to what the API accepts', async () => {
    // MAX_REPEAT is 20. A number the field would let through and the save would refuse is
    // the picker and the validator disagreeing.
    const page = await withThree();
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 1, extend: true });
    page['groupSelection'](2);
    page['onPick']({ index: 0, extend: false });

    page['setGroupRepeat'](999);

    expect(page['steps']()[0].group_repeat).toBe(20);
  });
});

describe('RotationsPage — inserting at a position', () => {
  async function withTwo() {
    const page = healthy();
    await page['load']();
    page['pickTeam'](['team-1']);
    page['appendStep']('10000002', 'skill');
    page['appendStep']('10000002', 'burst');
    return page;
  }

  it('inserts rather than appends', async () => {
    const page = await withTwo();

    page['insertStep'](1, '10000002', 'attack');

    expect(page['steps']().map((s) => s.action)).toEqual(['skill', 'attack', 'burst']);
  });

  it('gives the drag path and the keyboard path the same result', async () => {
    // T.6's acceptance criterion. A drag has no keyboard equivalent, so without the second
    // path, inserting anywhere but the end would be mouse-only.
    const dragged = await withTwo();
    dragged['dragOffer'].set({ character: '10000002', action: 'attack' });
    dragged['onTimelineDrop'](1);

    // `TestBed` cannot be reconfigured once a component is instantiated, and this test needs
    // two pages to compare. Resetting is the supported way to get a second one.
    TestBed.resetTestingModule();
    const typed = await withTwo();
    typed['onPick']({ index: 1, extend: false });
    typed['addingFor'].set('10000002');
    typed['addOffer']('attack');

    expect(typed['steps']()).toEqual(dragged['steps']());
  });

  it('moves an existing tile when no palette drag is in flight', async () => {
    // Two drag sources over one list, and which is in flight is the only thing that decides.
    const page = await withTwo();
    page['onDragStart'](0);

    page['onTimelineDrop'](1);

    expect(page['steps']().map((s) => s.action)).toEqual(['burst', 'skill']);
  });

  it('clamps an insert past the end rather than leaving a hole', async () => {
    const page = await withTwo();

    page['insertStep'](99, '10000002', 'attack');

    expect(page['steps']().map((s) => s.action)).toEqual(['skill', 'burst', 'attack']);
  });
});

describe('RotationsPage — the measured timeline goes stale', () => {
  it('drops to the authored view the instant a step changes', async () => {
    // The owner's ruling. Nothing on screen is ever untrue — the same rule the gcsim preview
    // has followed since #184, which refuses to leave a stale config beside an edit that
    // broke it.
    const page = healthy();
    await page['load']();
    page['pickTeam'](['team-1']);
    page['appendStep']('10000002', 'skill');
    page['measured'].set([{ character: 0, key: 'ayaka', start: 1, end: 60, actions: 3 }]);

    page['setStep'](0, { repeat: 2 });

    expect(page['measured']()).toBeNull();
  });

  it('drops it when a different rotation is opened', async () => {
    const page = healthy();
    await page['load']();
    page['measured'].set([{ character: 0, key: 'ayaka', start: 1, end: 60, actions: 3 }]);

    page['newRotation']();

    expect(page['measured']()).toBeNull();
  });
});

// ── what the review found ────────────────────────────────────────────────────

describe('RotationsPage — a failed run is not an empty one', () => {
  it('reports a gcsim failure rather than "nothing executed"', async () => {
    // `sample()` reports failure by **returning** `{"error": …}`, not by throwing — so
    // `JSON.parse` succeeds, the object has no `logs`, and `onFieldIntervals` returns `[]`.
    // Setting that on `measured` puts the timeline into measured mode saying every gate
    // stayed closed, about a run that never started.
    const page = healthy({
      preview: vi.fn().mockResolvedValue('options iteration=1;'),
    } as unknown as RotationsService);
    await page['load']();
    page['pickTeam'](['team-1']);
    page['appendStep']('10000002', 'skill');
    page['measured'].set(null);

    // The module is loaded through `loadGcsim`, which the page calls; stubbing the page's own
    // seam is enough to fix the behaviour under test without a wasm binary in a unit test.
    const failing = {
      validateConfig: () => ({}),
      sample: () => '{"error":"requested next char 1 is not active and next action is not swap"}',
    };
    await page['runSampleWith'](failing as never);

    expect(page['measured']()).toBeNull();
    expect(page['sampleError']()).toContain('not active');
  });

  it('shows an Error message rather than two braces', async () => {
    // `apiErrorMessage` understands FastAPI's `{detail}` and otherwise falls through to
    // `JSON.stringify`, whose answer for an `Error` is `"{}"` — its properties are not
    // enumerable. Every gcsim failure rendered as an empty object in a red box.
    const page = healthy({
      preview: vi.fn().mockResolvedValue('options iteration=1;'),
    } as unknown as RotationsService);
    await page['load']();
    page['pickTeam'](['team-1']);
    page['appendStep']('10000002', 'skill');

    await page['runSampleWith']({
      validateConfig: () => '{"error":"unrecognized weapon"}',
      sample: () => '{}',
    } as never);

    expect(page['sampleError']()).toContain('unrecognized weapon');
    expect(page['sampleError']()).not.toBe('{}');
  });
});

describe('RotationsPage — a group cannot be split by an edit', () => {
  async function grouped() {
    const page = healthy();
    await page['load']();
    page['pickTeam'](['team-1']);
    for (const a of ['skill', 'burst', 'attack']) page['appendStep']('10000002', a as 'skill');
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 1, extend: true });
    page['groupSelection'](2);
    return page;
  }

  it('a step dropped inside a group joins it', async () => {
    // Otherwise `[g1, '', g1]` — a group in two places, which the save refuses with a 422 the
    // user cannot trace back to a drag, and which the preview compiles as the chunk twice.
    const page = await grouped();

    page['insertStep'](1, '10000002', 'attack');

    expect(page['steps']().map((s) => s.group)).toEqual(['g1', 'g1', 'g1', '']);
  });

  it('a step inserted at the edge of a group stays out of it', async () => {
    const page = await grouped();

    page['insertStep'](0, '10000002', 'attack');

    expect(page['steps']()[0].group).toBe('');
  });

  it('dragging a member out releases the members it left behind', async () => {
    // Keeping the first run and releasing the rest, rather than gathering them: the user moved
    // that step deliberately, and moving it back would undo the edit they just made.
    const page = await grouped();

    page['reorder'](0, 2);

    const groups = page['steps']().map((s) => s.group);
    expect(groups.filter((g) => g === 'g1').length).toBeLessThan(2);
  });

  it('shows the selected group repeat, which the detail pane cannot', async () => {
    // `selectedStep()` is null for a span, and a group needs a span — so the one control that
    // edits this value could never display it. It read 1 while the badge read what you set.
    const page = await grouped();

    expect(page['selectedGroupRepeat']()).toBe(2);
  });
});

describe('RotationsPage — Ctrl+C leaves the browser alone', () => {
  it('does not cancel a copy when text is selected', async () => {
    // The compiled gcsim config is a `<pre>` in this same dialog and is the page's main
    // artifact. Cancelling the browser's copy and overwriting the clipboard with step JSON is
    // the worst of both, and left no keyboard way to copy the config at all.
    const page = healthy();
    await page['load']();
    page['pickTeam'](['team-1']);
    page['appendStep']('10000002', 'skill');
    page['onPick']({ index: 0, extend: false });

    const host = document.createElement('div');
    host.textContent = 'some config text';
    document.body.append(host);
    const range = document.createRange();
    range.selectNodeContents(host);
    document.getSelection()?.removeAllRanges();
    document.getSelection()?.addRange(range);

    let prevented = false;
    page['onEditorKey']({
      ctrlKey: true, key: 'c', target: document.createElement('div'),
      preventDefault: () => { prevented = true; },
    } as unknown as KeyboardEvent);

    expect(prevented).toBe(false);
    expect(page['clipboard']()).toEqual([]);
    document.getSelection()?.removeAllRanges();
    host.remove();
  });
});

describe('RotationsPage — pasting into a group', () => {
  it('releases the host group rather than leaving it in two places', async () => {
    // Same shape as the drag: a fragment pasted into the middle of `g1` leaves `[g1, '', g1]`,
    // which the save refuses and the preview compiles as the chunk twice. The fragment stays
    // ungrouped — joining would silently extend a repeat nobody asked for — so the host is
    // what gets released.
    const page = healthy();
    await page['load']();
    page['pickTeam'](['team-1']);
    for (const a of ['skill', 'burst', 'attack']) page['appendStep']('10000002', a as 'skill');
    page['onPick']({ index: 0, extend: false });
    page['onPick']({ index: 1, extend: true });
    page['groupSelection'](2);
    page['clipboard'].set([
      { character: '10000002', action: 'attack', repeat: 1, note: '', group: '', group_repeat: 1 },
    ]);
    page['onPick']({ index: 0, extend: false });

    page['pasteClipboard']();

    const groups = page['steps']().map((s) => s.group);
    expect(groups.filter((g) => g === 'g1').length).toBeLessThan(2);
  });
});
