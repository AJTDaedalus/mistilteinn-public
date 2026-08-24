import { describe, expect, it } from 'vitest';

import { CONTRACT } from './contract';
import { MAX_PAGE_LIMIT } from './page-size';

/**
 * The client's page-size cap must be the one the server publishes.
 *
 * This is the check that was missing when three pages shipped asking for 300 and 400 rows
 * from endpoints capped at 200. Every load 422'd; every test passed, because the page tests
 * mock `CatalogueService` and so never make the request that breaks.
 *
 * The committed contract is **imported**, not restated, so raising the server's cap fails
 * here rather than being silently left behind. `openapi.json` is the same file
 * `npm run codegen` builds `api.types.ts` from, and a backend test keeps it current.
 */
function schemaMaximum(path: string): number {
  const params = CONTRACT.paths[path]?.['get']?.parameters ?? [];
  const limit = params.find((p) => p.name === 'limit');
  expect(limit?.schema?.maximum, `${path} publishes no limit maximum`).toBeTypeOf('number');
  return limit!.schema!.maximum!;
}

describe('MAX_PAGE_LIMIT', () => {
  it.each([
    '/api/v1/characters',
    '/api/v1/weapons',
    '/api/v1/artifact-sets',
    '/api/v1/enemies',
    '/api/v1/builds',
  ])('does not exceed what %s accepts', (path) => {
    expect(MAX_PAGE_LIMIT).toBeLessThanOrEqual(schemaMaximum(path));
  });

  it('is not needlessly below it, or pages truncate for no reason', () => {
    expect(MAX_PAGE_LIMIT).toBe(schemaMaximum('/api/v1/characters'));
  });
});
