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

  // `it('offers the actions the API published')` lived here and is deliberately gone: the
  // page no longer holds a global action list, because T.3 made the vocabulary per character.
  // What replaced it is `editor.spec.ts`'s per-character offers and the backend's
  // `test_every_offered_action_can_actually_be_saved`, which posts every one of them.

  it('groups saved rotations under the team they belong to', async () => {
    // A flat list mixes rotations for teams that share no characters, and the first thing
    // anyone does with it is look for the ones belonging to a team.
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [
          { id: 'r1', name: 'One', team_id: 'team-1', description: '', steps: [] },
          { id: 'r2', name: 'Two', team_id: 'team-2', description: '', steps: [] },
          { id: 'r3', name: 'Three', team_id: 'team-1', description: '', steps: [] },
        ],
        total: 3, offset: 0, limit: 50,
      }),
    } as unknown as RotationsService);

    await page['load']();

    expect(page['byTeam']().map((g) => [g.team.name, g.rotations.length]))
      .toEqual([['Party', 2], ['Second', 1]]);
  });

  it('searches teams by name and by who is on them', async () => {
    // "Which of my teams has Ayaka" is how someone looks for a team they named "Bloom 2".
    const page = healthy();
    await page['load']();

    page['teamSearch'].set('ayaka');

    expect(page['byTeam']().map((g) => g.team.name)).toEqual(['Party']);
  });

  it('says how many steps and actions a rotation holds, not how many hits', async () => {
    // The audit asks for "x hits, y seconds"; a step's `repeat` is the closest thing this
    // model holds, and actual hits and seconds need a run. Naming it "steps" rather than
    // "hits" is the difference between a summary and a claim.
    const page = healthy();

    const summary = page['summarise']({
      id: 'r', name: 'n', team_id: 't', description: '',
      steps: [
        { character: 'a', action: 'attack', repeat: 3, note: '', group: '', group_repeat: 1 },
        { character: 'a', action: 'burst', repeat: 1, note: '', group: '', group_repeat: 1 },
      ],
    } as never);

    expect(summary).toBe('2 steps · 4 actions');
  });

  it('reloads the list after a delete, and forgets the row it was editing', async () => {
    const remove = vi.fn().mockResolvedValue(undefined);
    const page = healthy({ remove } as unknown as RotationsService);
    await page['load']();
    page['editing'].set('r1');

    await page['remove']({ id: 'r1', name: 'One' } as never);

    expect(remove).toHaveBeenCalledWith('r1');
    expect(page['editing']()).toBeNull();
  });

  it('reports a failed delete rather than leaving the row looking gone', async () => {
    const page = healthy({
      remove: vi.fn().mockRejectedValue({ detail: 'nope' }),
    } as unknown as RotationsService);
    await page['load']();

    await page['remove']({ id: 'r1', name: 'One' } as never);

    expect(page['actionError']()).toContain('nope');
  });

  it('reports a reload that failed after a save, rather than showing the old list', async () => {
    // `refreshList` is fired from the template — `(saved)="refreshList()"` — so nothing
    // awaits it. Before this it had no `try`, and a failed reload was an unhandled rejection
    // with the list quietly still showing the state before the save.
    const page = healthy();
    await page['load']();
    page['rotations'].list = vi.fn().mockRejectedValue({ detail: 'gone' });

    await page['refreshList']();

    expect(page['actionError']()).toContain('gone');
  });
});

describe('RotationsPage — rendered', () => {
  /**
   * The page in a fixture rather than a bare instance.
   *
   * **Because a signal nobody renders is green and unreachable.** `actionError` survived the
   * split into the editor's template and left the page setting a message with nowhere to show
   * it: a failed delete left the row in the list saying nothing at all, and the test above
   * passed the whole time because it asserted the signal.
   */
  function rendered(overrides: Partial<RotationsService> = {}) {
    TestBed.configureTestingModule({
      providers: [{
        provide: RotationsService,
        useValue: {
          options: vi.fn().mockResolvedValue(OPTIONS),
          list: vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 }),
          ...overrides,
        } as unknown as RotationsService,
      }],
    });
    const fixture = TestBed.createComponent(RotationsPage);
    fixture.detectChanges();
    return fixture;
  }

  it('shows a failed delete on the page', async () => {
    const fixture = rendered({
      remove: vi.fn().mockRejectedValue({ detail: 'that rotation is gone' }),
    } as unknown as RotationsService);
    await fixture.componentInstance['load']();

    await fixture.componentInstance['remove']({ id: 'r1', name: 'One' } as never);
    fixture.detectChanges();

    const alert = fixture.nativeElement.querySelector('[role="alert"]') as HTMLElement | null;
    expect(alert?.textContent).toContain('that rotation is gone');
  });
});
