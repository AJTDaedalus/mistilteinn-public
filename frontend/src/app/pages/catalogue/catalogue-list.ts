import { signal } from '@angular/core';

import type { Page } from '../../api/all-pages';

export type { Page };

/**
 * The load/search/error state every catalogue page shares — **one implementation, not four**.
 *
 * The four pages differ only in which endpoint they call and how a row is drawn. What they
 * have in common is the part worth getting right once:
 *
 * - **an error is surfaced, never swallowed.** An empty list and a failed request look
 *   identical on screen, and only one of them means "no matches". A page that quietly renders
 *   nothing on a 500 tells a user their account is empty.
 * - **`total` comes from the server**, because filtering is server-side (G.6a) and the
 *   endpoint computes its count with the same `WHERE` the page asked for. A count derived from
 *   `items.length` would disagree with it the moment paging appears.
 * - **a short list says it is short.** `total` disagreeing with what is on screen is the
 *   failure this nearly shipped as: the endpoints cap `limit` at 200, two tables are larger,
 *   and the pages printed "360 matching" over 200 rows with no clue but arithmetic. Loaders
 *   gather every page now (`allPages`), and `truncated` is for the case where even that
 *   stops early.
 * - **the list is cleared on failure.** Leaving the previous results up under a fresh error
 *   message shows stale data as though it answered the new search.
 *
 * Copied into four components, that discipline lasts until the first page someone writes in a
 * hurry. Here it is structural.
 */
export function catalogueList<T>(
  load: (name?: string) => Promise<Page<T> & { truncated?: boolean }>,
) {
  const items = signal<T[]>([]);
  const total = signal(0);
  const loading = signal(false);
  const error = signal<string | null>(null);
  const truncated = signal(false);

  return {
    items: items.asReadonly(),
    total: total.asReadonly(),
    loading: loading.asReadonly(),
    error: error.asReadonly(),
    /** The list is shorter than `total` and the rest was not fetched. Say so on screen. */
    truncated: truncated.asReadonly(),

    async run(search: string, whatFailed: string): Promise<void> {
      loading.set(true);
      error.set(null);
      try {
        const page = await load(search.trim() || undefined);
        items.set(page.items);
        total.set(page.total);
        truncated.set(page.truncated ?? false);
      } catch {
        error.set(`Could not load the ${whatFailed}.`);
        items.set([]);
        total.set(0);
        truncated.set(false);
      } finally {
        loading.set(false);
      }
    },
  };
}
