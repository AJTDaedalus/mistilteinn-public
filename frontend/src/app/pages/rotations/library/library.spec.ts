import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { RotationLibrary } from './library';
import { RotationsService, type RosterCharacter } from '../rotations.service';

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

function libraryWith(overrides: Partial<RotationsService> = {}) {
  TestBed.configureTestingModule({
    providers: [{
      provide: RotationsService,
      useValue: {
        library: vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 }),
        ...overrides,
      } as unknown as RotationsService,
    }],
  });
  const fixture = TestBed.createComponent(RotationLibrary);
  fixture.detectChanges();
  return fixture.componentInstance;
}

describe('RotationLibrary', () => {
  const TEAM = OPTIONS.teams[0];
  const ROW = {
    id: 'lib-1', name: 'Freeze opener', description: '',
    steps: [{ character: '10000002', action: 'burst' as const, repeat: 1, note: '', group: '', group_repeat: 1, group_condition: '' }],
    characters: ['10000002', '10000014'], like_count: 2, liked_by_me: false,
  };

  const withLibrary = (overrides: Partial<RotationsService> = {}) => libraryWith({
    library: vi.fn().mockResolvedValue({ items: [ROW], total: 1, offset: 0, limit: 50 }),
    setLiked: vi.fn().mockResolvedValue(undefined),
    copy: vi.fn().mockResolvedValue({ ...ROW, name: 'Freeze opener (copy)' }),
    ...overrides,
  } as unknown as RotationsService);

  it('opens filtered to the team it was opened from', async () => {
    // A library reached from inside a team is asking "what do people run on *this*". Opening
    // it unfiltered would make the button's own label untrue.
    const page = withLibrary();

    await page['open'](TEAM);

    const library = page['rotations'].library as ReturnType<typeof vi.fn>;
    expect(library).toHaveBeenCalledWith({ characters: ['10000002', '10000014'] });
    expect(page['rows']()).toHaveLength(1);
  });

  it('widens to everything published without a character filter', async () => {
    const page = withLibrary();
    await page['open'](TEAM);

    await page['setScope'](false);

    const library = page['rotations'].library as ReturnType<typeof vi.fn>;
    expect(library).toHaveBeenLastCalledWith({ characters: undefined });
  });

  it('reports a failed load rather than showing it as an empty library', async () => {
    // An empty library and a broken one look identical, and only one of them means nobody has
    // published anything.
    const page = withLibrary({
      library: vi.fn().mockRejectedValue(new Error('boom')),
    } as unknown as RotationsService);

    await page['open'](TEAM);

    expect(page['error']()).not.toBeNull();
    expect(page['rows']()).toEqual([]);
  });

  it('moves the like count immediately, and puts it back when the save fails', async () => {
    // Optimistic because a like is a one-bit opinion and waiting a round trip to see it
    // register is the wrong trade. Reverted because a count that stayed after a failure would
    // be a number the server does not agree with.
    const page = withLibrary({
      setLiked: vi.fn().mockRejectedValue(new Error('offline')),
    } as unknown as RotationsService);
    await page['open'](TEAM);

    await page['toggleLike'](page['rows']()[0]);

    expect(page['rows']()[0]).toMatchObject({ liked_by_me: false, like_count: 2 });
    expect(page['error']()).not.toBeNull();
  });

  it('keeps a successful like on screen', async () => {
    const page = withLibrary();
    await page['open'](TEAM);

    await page['toggleLike'](page['rows']()[0]);

    expect(page['rows']()[0]).toMatchObject({ liked_by_me: true, like_count: 3 });
  });

  it('copies onto the team the library was opened from, and says what it made', async () => {
    const page = withLibrary();
    await page['open'](TEAM);

    await page['copy'](page['rows']()[0]);

    const copy = page['rotations'].copy as ReturnType<typeof vi.fn>;
    expect(copy).toHaveBeenCalledWith('lib-1', 'team-1');
    expect(page['note']()).toContain('Freeze opener (copy)');
  });

  it("shows the server's refusal verbatim, because it names what is missing", async () => {
    // "That team does not field 10000002" is actionable; "could not copy" is not.
    const page = withLibrary({
      copy: vi.fn().mockRejectedValue({ detail: 'That team does not field 10000002.' }),
    } as unknown as RotationsService);
    await page['open'](TEAM);

    await page['copy'](page['rows']()[0]);

    expect(page['error']()).toContain('10000002');
    expect(page['note']()).toBeNull();
  });

  it('survives an environment with no <dialog>', async () => {
    // jsdom has no `HTMLDialogElement`, so `showModal` is undefined and a bare call is a
    // TypeError thrown from inside a click handler — which takes the page out.
    const page = withLibrary();

    await expect(page['open'](TEAM)).resolves.toBeUndefined();
    expect(() => page['close']()).not.toThrow();
  });
});


/**
 * The builder's authoring surface — `DESIGN_rotation_builder.md` B.1, B.2, B.3, B.6.
 *
 * All four are about **cost**, not capability: the model is unchanged, and §1 of that document
 * is explicit that it must be. So these tests check that a step added the fast way is
 * identical to one added the slow way, which is the thing that would silently drift.
 */
