import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { BuildsService } from '../builds/builds.service';
import { RotationsService } from '../rotations/rotations.service';
import { ComparePage } from './compare';
import { CompareService } from './compare.service';

/**
 * W.6 — the comparison page.
 *
 * The two behaviours worth pinning are the ones a user would be misled by rather than
 * blocked by: **a paginated rotations response read as an array** renders an empty picker
 * that looks exactly like "you have no rotations", and **a stale ranking left on screen**
 * sits under a new build's name describing weapons from the previous run.
 */

const BUILD = {
  id: 'b1', character_id: 'c1', weapon_id: 'w1', character_level: 90,
  ascension_phase: 6, weapon_level: 90, refinement: 1, constellation_level: 0,
  talent_levels: {}, notes: '',
  character: { id: 'c1', name: 'Kamisato Ayaka', element: 'Cryo' },
  weapon: { id: 'w1', name: 'Dull Blade' },
};

const ROTATIONS = {
  items: [{ id: 'r1', name: 'Burst', team_id: 't1', description: '', steps: [] }],
  total: 1, offset: 0, limit: 50,
};

const CONFIGS = {
  equipped: { weapon_id: 'w1', name: 'Dull Blade', config: 'cfg-worn' },
  candidates: [{ weapon_id: 'w2', name: 'Mistsplitter Reforged', config: 'cfg-mist' }],
  refused: [{ weapon_id: 'w9', reason: 'not in the catalogue' }],
  iterations: 100,
};

const RANKING = {
  rows: [
    {
      weaponId: 'w2', name: 'Mistsplitter Reforged', dpsMean: 900, dpsSd: 87,
      iterations: 100, rank: 1, standardError: 8.7, notSeparatedFrom: [],
    },
    {
      weaponId: 'w1', name: 'Dull Blade', dpsMean: 400, dpsSd: 87,
      iterations: 100, rank: 2, standardError: 8.7, notSeparatedFrom: [],
    },
  ],
  fullyOrdered: true,
  iterations: 100,
};

function setup(over: Partial<Record<string, unknown>> = {}) {
  const compare = {
    configs: vi.fn(async () => CONFIGS),
    simulate: vi.fn(async () => RANKING),
    ...over,
  };
  TestBed.configureTestingModule({
    providers: [
      { provide: CompareService, useValue: compare },
      { provide: BuildsService, useValue: { list: vi.fn(async () => [BUILD]) } },
      { provide: RotationsService, useValue: { list: vi.fn(async () => ROTATIONS) } },
    ],
  });
  const fixture = TestBed.createComponent(ComparePage);
  return { fixture, page: fixture.componentInstance as never, compare };
}

// `protected` members are reachable at runtime; the cast keeps the spec honest about that.
const at = (page: unknown, key: string) => (page as Record<string, never>)[key];

describe('ComparePage', () => {
  it('reads rotations out of the paginated envelope, not as an array', async () => {
    // `list()` returns `{items, total, ...}`. Treating it as an array leaves the picker
    // empty, which is indistinguishable from having authored no rotations.
    const { fixture, page } = setup();
    await (at(page, 'load') as () => Promise<void>).call(page);
    fixture.detectChanges();

    expect((at(page, 'rotations') as () => unknown[])()).toEqual([
      { id: 'r1', name: 'Burst' },
    ]);
    expect(at(page, 'rotationId')).toBe('r1');
  });

  it('splits the candidate ids and drops blanks', () => {
    const { page } = setup();
    (page as Record<string, unknown>)['weaponIds'] = ' w2 , ,w3, ';

    expect((at(page, 'parsedWeaponIds') as () => string[]).call(page)).toEqual(['w2', 'w3']);
  });

  it('does not call the API when no candidates were given', async () => {
    const { page, compare } = setup();
    (page as Record<string, unknown>)['buildId'] = 'b1';
    (page as Record<string, unknown>)['rotationId'] = 'r1';
    (page as Record<string, unknown>)['weaponIds'] = '   ';

    await (at(page, 'run') as () => Promise<void>).call(page);

    expect(compare.configs).not.toHaveBeenCalled();
  });

  it('clears the previous ranking before running a new one', async () => {
    // A stale ranking left up sits under a new build's name and describes weapons from the
    // previous run — a number that looks right and refers to something else.
    let seenDuringRun: unknown = 'unset';
    const { page } = setup({
      simulate: vi.fn(async () => {
        seenDuringRun = (at(page, 'ranking') as () => unknown)();
        return RANKING;
      }),
    });
    (page as Record<string, unknown>)['buildId'] = 'b1';
    (page as Record<string, unknown>)['rotationId'] = 'r1';
    (page as Record<string, unknown>)['weaponIds'] = 'w2';

    await (at(page, 'run') as () => Promise<void>).call(page);
    await (at(page, 'run') as () => Promise<void>).call(page);

    expect(seenDuringRun).toBeNull();
  });

  it('keeps the refusals so a missing candidate is visible', async () => {
    const { page } = setup();
    (page as Record<string, unknown>)['buildId'] = 'b1';
    (page as Record<string, unknown>)['rotationId'] = 'r1';
    (page as Record<string, unknown>)['weaponIds'] = 'w2';

    await (at(page, 'run') as () => Promise<void>).call(page);

    expect((at(page, 'configs') as () => typeof CONFIGS)().refused).toHaveLength(1);
  });

  it('names what a row was not separated from, rather than showing ids', async () => {
    const { page } = setup({
      simulate: vi.fn(async () => ({
        ...RANKING,
        fullyOrdered: false,
        rows: [
          { ...RANKING.rows[0], notSeparatedFrom: ['w1'] },
          { ...RANKING.rows[1], notSeparatedFrom: ['w2'] },
        ],
      })),
    });
    (page as Record<string, unknown>)['buildId'] = 'b1';
    (page as Record<string, unknown>)['rotationId'] = 'r1';
    (page as Record<string, unknown>)['weaponIds'] = 'w2';
    await (at(page, 'run') as () => Promise<void>).call(page);

    const named = at(page, 'notSeparatedNames') as (ids: string[]) => string;
    expect(named.call(page, ['w1'])).toBe('Dull Blade');
  });

  it('reports an error instead of a ranking when the run fails', async () => {
    const { page } = setup({
      configs: vi.fn(async () => { throw new Error('nope'); }),
    });
    (page as Record<string, unknown>)['buildId'] = 'b1';
    (page as Record<string, unknown>)['rotationId'] = 'r1';
    (page as Record<string, unknown>)['weaponIds'] = 'w2';

    await (at(page, 'run') as () => Promise<void>).call(page);

    expect((at(page, 'ranking') as () => unknown)()).toBeNull();
    expect((at(page, 'actionError') as () => unknown)()).toBeTruthy();
    expect((at(page, 'running') as () => boolean)()).toBe(false);
  });
});
