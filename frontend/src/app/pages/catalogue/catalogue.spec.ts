import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { ArtifactSetsPage } from './artifact-sets';
import { catalogueList } from './catalogue-list';
import { CatalogueService } from './catalogue.service';
import { EnemiesPage, resistancesOf } from './enemies';
import { WeaponsPage } from './weapons';
import { MAX_PAGE_LIMIT } from '../../api/page-size';

function pageWith<T>(ctor: new () => T, service: Partial<CatalogueService>): T {
  TestBed.configureTestingModule({
    providers: [{ provide: CatalogueService, useValue: service }],
  });
  return TestBed.runInInjectionContext(() => new ctor());
}

const EMPTY = { items: [], total: 0, offset: 0, limit: 300 };

/**
 * The three pages A.3 adds, plus the helper they share.
 *
 * The per-page tests are thin on purpose: the load/error/search behaviour lives in
 * `catalogueList` and is tested once, below. What each page is individually responsible for
 * is *which endpoint it calls* and *what it asks for*, so that is what is checked here.
 */
/**
 * The pages gather every page rather than one.
 *
 * 260 weapons and 360 enemies against a `limit` capped at 200: a single request returned 200
 * items beside a `total` of 360, and the page printed "360 matching" over the short list. Not
 * an error, no warning — the count and the content simply disagreed.
 */
describe('catalogueList', () => {
  it('reports a failure instead of rendering it as "no results"', async () => {
    // The distinction the whole helper exists for. An empty list and a failed request look
    // identical on screen, and only one of them means the search found nothing — a user told
    // "no matches" while the API is down will keep changing their search terms forever.
    const list = catalogueList(() => Promise.reject(new Error('boom')));

    await list.run('', 'weapon catalogue');

    expect(list.error()).toBe('Could not load the weapon catalogue.');
    expect(list.items()).toEqual([]);
    expect(list.loading()).toBe(false);
  });

  it('clears the previous results when a load fails', async () => {
    // Leaving stale rows under a fresh error shows old data as though it answered the new
    // search — worse than showing nothing, because it looks like an answer.
    const load = vi
      .fn()
      .mockResolvedValueOnce({ items: ['a', 'b'], total: 2 })
      .mockRejectedValueOnce(new Error('boom'));
    const list = catalogueList<string>(load);

    await list.run('', 'catalogue');
    expect(list.items()).toHaveLength(2);

    await list.run('', 'catalogue');
    expect(list.items()).toEqual([]);
    expect(list.total()).toBe(0);
  });

  it('takes total from the server rather than counting the rows it received', async () => {
    // Filtering is server-side, and the endpoint computes `total` with the same WHERE the
    // page asked for. Deriving it from items.length would disagree the moment paging exists.
    const list = catalogueList(() => Promise.resolve({ items: ['a'], total: 260 }));

    await list.run('', 'catalogue');

    expect(list.total()).toBe(260);
  });

  it('clears a previous error on a successful retry', async () => {
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ items: ['a'], total: 1 });
    const list = catalogueList<string>(load);

    await list.run('', 'catalogue');
    expect(list.error()).not.toBeNull();

    await list.run('', 'catalogue');
    expect(list.error()).toBeNull();
  });

  it('trims the search and omits it when blank', async () => {
    const load = vi.fn().mockResolvedValue({ items: [], total: 0 });
    const list = catalogueList(load);

    await list.run('  Mistsplitter  ', 'catalogue');
    expect(load).toHaveBeenCalledWith('Mistsplitter');

    await list.run('   ', 'catalogue');
    expect(load).toHaveBeenCalledWith(undefined);
  });
});

describe('WeaponsPage', () => {
  it('asks the weapons endpoint, with the search term', async () => {
    const listWeapons = vi.fn().mockResolvedValue(EMPTY);
    const page = pageWith(WeaponsPage, { listWeapons } as unknown as CatalogueService);
    page['search'] = ' Mistsplitter ';

    await page['load']();

    expect(listWeapons).toHaveBeenCalledWith({ name: 'Mistsplitter', offset: 0, limit: MAX_PAGE_LIMIT });
  });

  it('names the weapon catalogue in its error, not a generic failure', async () => {
    const page = pageWith(WeaponsPage, {
      listWeapons: vi.fn().mockRejectedValue(new Error('boom')),
    } as unknown as CatalogueService);

    await page['load']();

    expect(page['list'].error()).toContain('weapon catalogue');
  });
});

describe('ArtifactSetsPage', () => {
  it('asks the artifact-sets endpoint', async () => {
    const listArtifactSets = vi.fn().mockResolvedValue(EMPTY);
    const page = pageWith(ArtifactSetsPage, {
      listArtifactSets,
    } as unknown as CatalogueService);

    await page['load']();

    expect(listArtifactSets).toHaveBeenCalledWith({ name: undefined, offset: 0, limit: MAX_PAGE_LIMIT });
  });
});

describe('EnemiesPage', () => {
  it('asks the enemies endpoint', async () => {
    const listEnemies = vi.fn().mockResolvedValue(EMPTY);
    const page = pageWith(EnemiesPage, { listEnemies } as unknown as CatalogueService);

    await page['load']();

    expect(listEnemies).toHaveBeenCalledWith({ name: undefined, offset: 0, limit: MAX_PAGE_LIMIT });
  });

  it('shapes the resistances once at load, not on every render', async () => {
    // A template method would rebuild 360 x 8 objects per change-detection pass and hand
    // `@for` a fresh array identity each time, so nothing could be reused.
    const page = pageWith(EnemiesPage, {
      listEnemies: vi.fn().mockResolvedValue({
        items: [{ id: 'e1', name: 'Hilichurl', cryo_res: 0.1 }],
        total: 1,
        offset: 0,
        limit: MAX_PAGE_LIMIT,
      }),
    } as unknown as CatalogueService);

    await page['load']();

    const [row] = page['list'].items();
    expect(row.resistances).toHaveLength(8);
    // Same array on a second read: the work happened once, at load.
    expect(page['list'].items()[0].resistances).toBe(row.resistances);
  });

  it('turns the eight resistance columns into percentages, in channel order', () => {
    const rows = resistancesOf({
      physical_res: 0.1,
      anemo_res: 0.1,
      cryo_res: -0.5,
      dendro_res: 0.1,
      electro_res: 0.1,
      geo_res: 0.1,
      hydro_res: 0.1,
      pyro_res: 0.1,
    } as never);

    expect(rows).toHaveLength(8);
    expect(rows.map((r) => r.channel)).toEqual([
      'physical', 'anemo', 'cryo', 'dendro', 'electro', 'geo', 'hydro', 'pyro',
    ]);
    // Fractions in, percentages out — `backend/CLAUDE.md`: 10% RES is stored as 0.1.
    expect(rows[0].percent).toBeCloseTo(10);
    // Negative resistance is real (it means the target takes *more*), and must survive
    // rather than being clamped into a plausible-looking zero.
    expect(rows[2].percent).toBeCloseTo(-50);
  });

  it('treats a missing resistance as zero rather than dropping the channel', () => {
    // All eight channels always appear: an absent one silently vanishing from the list
    // would read as "this enemy has no cryo resistance" rather than "we do not know".
    const rows = resistancesOf({ physical_res: 0.1 } as never);

    expect(rows).toHaveLength(8);
    expect(rows[1].percent).toBe(0);
  });

  // **The value that differs is the only one on the card worth reading**, and all eight were
  // drawn identically. `notable` is what the template emphasises.
  it('marks the resistances that differ from the rest of the same enemy', () => {
    const rows = resistancesOf({
      physical_res: 0.7,
      anemo_res: 0.1,
      cryo_res: 0.1,
      dendro_res: 0.1,
      electro_res: 0.1,
      geo_res: 0.1,
      hydro_res: 0.1,
      pyro_res: 0.1,
    } as never);

    expect(rows.filter((r) => r.notable).map((r) => r.channel)).toEqual(['physical']);
  });

  it('marks nothing when every channel agrees', () => {
    // Nothing about this enemy's resistances distinguishes it, so emphasising all eight
    // would be the same as emphasising none — and louder.
    const flat = Object.fromEntries(
      ['physical', 'anemo', 'cryo', 'dendro', 'electro', 'geo', 'hydro', 'pyro']
        .map((c) => [`${c}_res`, 0.1]),
    );

    expect(resistancesOf(flat as never).some((r) => r.notable)).toBe(false);
  });

  it('takes the baseline from the enemy rather than assuming 10%', () => {
    // An enemy whose floor is 50% would otherwise have all eight flagged, which is the same
    // as flagging none. Only the channel that departs from *this* enemy's own baseline is.
    const rows = resistancesOf({
      physical_res: 0.5,
      anemo_res: 0.5,
      cryo_res: 0.5,
      dendro_res: 0.5,
      electro_res: 0.5,
      geo_res: 0.5,
      hydro_res: 0.5,
      pyro_res: -0.2,
    } as never);

    expect(rows.filter((r) => r.notable).map((r) => r.channel)).toEqual(['pyro']);
  });
});


describe('a catalogue page larger than one API page', () => {
  it('shows every row, not the first 200', async () => {
    // The real shape: 360 enemies, `limit` capped at 200. Before `allPages` this rendered 200
    // rows under the heading "360 matching".
    const rows = Array.from({ length: 360 }, (_, i) => ({ id: `e${i}`, name: `Enemy ${i}` }));
    const listEnemies = vi.fn(async (params: { offset?: number; limit?: number }) => ({
      items: rows.slice(params.offset ?? 0, (params.offset ?? 0) + (params.limit ?? 200)),
      total: rows.length,
      offset: params.offset ?? 0,
      limit: params.limit ?? 200,
    }));
    TestBed.configureTestingModule({
      providers: [{ provide: CatalogueService, useValue: { listEnemies } as unknown as CatalogueService }],
    });
    const page = TestBed.runInInjectionContext(() => new EnemiesPage());

    await page['load']();

    expect(page['list'].items()).toHaveLength(360);
    expect(page['list'].total()).toBe(360);
    expect(page['list'].truncated()).toBe(false);
    expect(listEnemies).toHaveBeenCalledTimes(2);
  });
});


describe('catalogueList truncation', () => {
  it('passes a short list through to the page', async () => {
    // The mutation that survived first time: nothing in the page tests had `truncated` true,
    // so hardcoding it to `false` changed no answer. This is the wiring the templates read to
    // print "showing 200 of 360" instead of "360 matching" over 200 rows.
    const list = catalogueList<number>(async () => ({
      items: [1, 2, 3],
      total: 360,
      truncated: true,
    }));

    await list.run('', 'test catalogue');

    expect(list.truncated()).toBe(true);
    expect(list.total()).toBe(360);
    expect(list.items()).toHaveLength(3);
  });

  it('reports a complete list as complete', async () => {
    const list = catalogueList<number>(async () => ({ items: [1], total: 1, truncated: false }));

    await list.run('', 'test catalogue');

    expect(list.truncated()).toBe(false);
  });

  it('clears truncation on failure, so a stale flag cannot outlive its list', async () => {
    let truncated = true;
    const list = catalogueList<number>(async () => {
      if (truncated) {
        truncated = false;
        return { items: [1], total: 99, truncated: true };
      }
      throw new Error('boom');
    });
    await list.run('', 'test catalogue');
    expect(list.truncated()).toBe(true);

    await list.run('', 'test catalogue');

    expect(list.error()).not.toBeNull();
    expect(list.truncated()).toBe(false);
  });
});
