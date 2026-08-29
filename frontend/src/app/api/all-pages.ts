import { MAX_PAGE_LIMIT } from './page-size';

/** One page of results, in the shape every paginated endpoint returns. */
export interface Page<T> {
  items: T[];
  total: number;
}

/**
 * How many rows a page will gather before it stops and says so.
 *
 * Well above the catalogue's largest table (360 enemies) and well below anything that would
 * make a page unusable. It exists so the loop cannot run away against a table that grows, not
 * because any current view needs bounding.
 *
 * **Raised from 2,000 to match the server's own `INVENTORY_CAP`.** The two disagreed, and a
 * real account fell in the gap: the owner's export holds 2,370 artifacts, so `/inventory`
 * loaded 2,000 and said "the rest was not loaded" while the API would happily have served
 * all of them. Two caps for one limit means the tighter one is enforced somewhere nobody is
 * looking — here, in a shared paginator, for every page that uses it.
 *
 * At 200 rows a request this is 100 requests in the worst case. That is slow and it is
 * bounded, which is the right trade against silently answering with a prefix — the
 * `truncated` flag still exists for anyone past even this.
 */
export const MAX_ROWS = 20_000;

/**
 * Every row, gathered a page at a time — and honest when it stops early.
 *
 * The endpoints cap `limit` at 200, and two tables are larger: 260 weapons and 360 enemies.
 * A single request therefore returned 200 items **beside a `total` of 360**, and the page
 * printed "360 matching" over a list of 200 with no way to reach the rest. Not an error, no
 * warning: the count and the content simply disagreed, and the only clue was arithmetic
 * nobody does.
 *
 * `total` comes from the server throughout, computed with the same `WHERE` the page asked
 * for. Deriving it from `items.length` would make the two agree by making the number
 * meaningless.
 *
 * If `MAX_ROWS` is reached the result says `truncated`, because a cap nobody is told about
 * is the same failure one layer up.
 */
export async function allPages<T>(
  fetchPage: (offset: number, limit: number) => Promise<Page<T>>,
): Promise<Page<T> & { truncated: boolean }> {
  const first = await fetchPage(0, MAX_PAGE_LIMIT);
  const items = [...first.items];

  while (items.length < first.total && items.length < MAX_ROWS) {
    const next = await fetchPage(items.length, MAX_PAGE_LIMIT);
    // An endpoint that returns nothing would otherwise spin here forever. A page short of
    // `total` is a server that disagrees with itself, and stopping is the honest response.
    if (next.items.length === 0) break;
    items.push(...next.items);
  }

  return { items, total: first.total, truncated: items.length < first.total };
}
