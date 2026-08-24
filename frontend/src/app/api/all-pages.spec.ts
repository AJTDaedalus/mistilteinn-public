import { describe, expect, it, vi } from 'vitest';

import { MAX_ROWS, allPages } from './all-pages';
import { MAX_PAGE_LIMIT } from './page-size';

/** A fake endpoint holding `total` rows and honouring offset/limit, as the real ones do. */
function endpoint(total: number) {
  const rows = Array.from({ length: total }, (_, i) => i);
  return vi.fn(async (offset: number, limit: number) => ({
    items: rows.slice(offset, offset + limit),
    total,
  }));
}

describe('allPages', () => {
  it('gathers every row when there are more than one page holds', async () => {
    // The real case: 360 enemies against a cap of 200. One request returned 200 items beside
    // a total of 360, and the page printed the total over the short list.
    const fetchPage = endpoint(360);

    const result = await allPages(fetchPage);

    expect(result.items).toHaveLength(360);
    expect(result.total).toBe(360);
    expect(result.truncated).toBe(false);
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });

  it('makes one request when one page is enough', async () => {
    const fetchPage = endpoint(150);

    const result = await allPages(fetchPage);

    expect(result.items).toHaveLength(150);
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it('asks for the next page from where the last one ended', async () => {
    const fetchPage = endpoint(260);

    await allPages(fetchPage);

    expect(fetchPage.mock.calls).toEqual([
      [0, MAX_PAGE_LIMIT],
      [MAX_PAGE_LIMIT, MAX_PAGE_LIMIT],
    ]);
  });

  it('keeps the server total rather than counting what it gathered', async () => {
    // Deriving `total` from `items.length` would make the count and the list agree by making
    // the count meaningless. The server computes it with the same WHERE the page asked for.
    const fetchPage = endpoint(260);

    const result = await allPages(fetchPage);

    expect(result.total).toBe(260);
  });

  it('stops at the row cap and says it stopped', async () => {
    // A cap nobody is told about is the same failure this function exists to fix, one layer
    // up.
    const fetchPage = endpoint(MAX_ROWS + 500);

    const result = await allPages(fetchPage);

    expect(result.items.length).toBeGreaterThanOrEqual(MAX_ROWS);
    expect(result.truncated).toBe(true);
    expect(result.total).toBe(MAX_ROWS + 500);
  });

  it('stops rather than spinning when a page comes back empty', async () => {
    // A server claiming 500 rows and returning none is disagreeing with itself. Looping on
    // that would hang the page with no error anywhere.
    const fetchPage = vi.fn(async () => ({ items: [] as number[], total: 500 }));

    const result = await allPages(fetchPage);

    expect(result.items).toEqual([]);
    expect(result.truncated).toBe(true);
    // Twice, not once: the first fetch is outside the loop, so one more call is what
    // *discovers* the emptiness. The claim being made is that it terminates — this bound is
    // what fails if the break is removed, rather than the test hanging until the runner
    // gives up and reports something unrelated.
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });
});
