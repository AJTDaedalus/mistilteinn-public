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
    page['name'] = 'Melt opener';

    await page['save']();

    expect(page['actionError']()).toBe(detail);
  });

  it('will not save without a name, a team and at least one step', async () => {
    const create = vi.fn();
    const page = healthy({ create } as unknown as RotationsService);
    await page['load']();

    page['name'] = 'Named but empty';
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
    });
    page['name'] = 'Renamed';

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

    page['edit']({ id: 'rot-1', name: 'S', team_id: 'team-1', description: '', steps: [] });
    await page['compile']();
    expect(compile).toHaveBeenCalledWith('rot-1');
    expect(page['compiled']()).toBe('active ayaka;\n');
  });

  it('drops a stale compiled config as soon as the steps change', async () => {
    const page = healthy({
      compile: vi.fn().mockResolvedValue('active ayaka;\n'),
    } as unknown as RotationsService);
    await page['load']();
    page['edit']({ id: 'rot-1', name: 'S', team_id: 'team-1', description: '', steps: [] });
    await page['compile']();
    expect(page['compiled']()).not.toBeNull();

    page['addStep']();

    expect(page['compiled']()).toBeNull();
  });
});
