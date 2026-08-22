import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { CatalogueService } from './catalogue.service';
import { CharactersPage } from './characters';

function pageWith(service: Partial<CatalogueService>) {
  TestBed.configureTestingModule({
    providers: [{ provide: CatalogueService, useValue: service }],
  });
  return TestBed.runInInjectionContext(() => new CharactersPage());
}

describe('CharactersPage', () => {
  it('shows what the API returned', async () => {
    const page = pageWith({
      listCharacters: vi.fn().mockResolvedValue({
        items: [{ id: 'a', nanoka_id: '10000002', name: 'Ayaka', element: 'Cryo' }],
        total: 1,
        offset: 0,
        limit: 200,
      }),
    } as unknown as CatalogueService);

    await page['load']();

    expect(page['characters']()).toHaveLength(1);
    expect(page['total']()).toBe(1);
    expect(page['error']()).toBeNull();
  });

  it('reports a failed load instead of rendering it as "no results"', async () => {
    // The distinction this test exists for: an empty list and a failed request look
    // identical on screen, and only one of them means the search found nothing. A user
    // told "no characters match" when the API is down will change their search terms
    // forever and never find out.
    const page = pageWith({
      listCharacters: vi.fn().mockRejectedValue(new Error('boom')),
    } as unknown as CatalogueService);

    await page['load']();

    expect(page['error']()).not.toBeNull();
    expect(page['characters']()).toEqual([]);
    expect(page['loading']()).toBe(false);
  });

  it('sends the search term to the server, not a client-side filter', async () => {
    // Server-side, because the endpoint's `total` is computed with the same WHERE the page
    // used. Filtering here would page over an unfiltered list and print a total that
    // disagreed with what is on screen.
    const listCharacters = vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200 });
    const page = pageWith({ listCharacters } as unknown as CatalogueService);
    page['search'] = '  Ayaka  ';

    await page['load']();

    expect(listCharacters).toHaveBeenCalledWith({ name: 'Ayaka', limit: 200 });
  });

  it('omits an empty search rather than sending a blank filter', async () => {
    const listCharacters = vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200 });
    const page = pageWith({ listCharacters } as unknown as CatalogueService);
    page['search'] = '   ';

    await page['load']();

    expect(listCharacters).toHaveBeenCalledWith({ name: undefined, limit: 200 });
  });
});
