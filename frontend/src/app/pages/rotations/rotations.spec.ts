import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { RotationsPage } from './rotations';
import { RotationsService } from './rotations.service';

const ROSTER = [
  { nanoka_id: '10000002', name: 'Kamisato Ayaka', element: 'Cryo' },
  { nanoka_id: '10000014', name: 'Barbara', element: 'Hydro' },
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
      { character: '10000002', action: 'skill', repeat: 1, note: '' },
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
      steps: [{ character: '10000002', action: 'burst', repeat: 1, note: '' }],
      visibility: 'private' as const,
    });
    page['name'].set('Renamed');

    await page['save']();

    expect(create).not.toHaveBeenCalled();
    expect(update).toHaveBeenCalledWith('rot-1', {
      name: 'Renamed',
      steps: [{ character: '10000002', action: 'burst', repeat: 1, note: '' }],
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
      steps: [{ character: '10000002', action: 'burst', repeat: 1, note: '' }],
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
      steps: [{ character: '10000002', action: 'burst', repeat: 1, note: '' }],
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
    steps: [{ character: '10000002', action: 'burst' as const, repeat: 1, note: '' }],
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
