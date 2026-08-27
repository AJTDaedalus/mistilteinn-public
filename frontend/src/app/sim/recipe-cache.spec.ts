import { describe, expect, it } from 'vitest';

import {
  browserStore,
  cacheKey,
  evictRecipes,
  readRecipe,
  writeRecipe,
  type RecipeCacheKey,
  type RecipeStore,
} from './recipe-cache';
import type { Recipe } from './recipe';

/**
 * R.4 / OQ-R2 — what makes a cached recipe stale, and what happens when storage refuses.
 *
 * The load-bearing test is `a different gcsim pin is a miss`. A recipe served from a different
 * simulator is the failure `verify-gcsim-recipe.mjs` guards one layer down, and the one fairy
 * shipped for months.
 */

const KEY: RecipeCacheKey = {
  gcsimPin: 'abc123', buildId: 'b1', rotationId: 'r1',
  artifactSetId: 's1', energyRecharge: 0.3, seed: '12345',
};

const RECIPE = {
  hits: [], seed: '12345',
  meta: { seed: '12345', staleConversions: [], calibratedSetId: 1, minimumEnergyRecharge: 0.3 },
} as unknown as Recipe;

/** An in-memory store, so a test needs no browser. */
function memory(over: Partial<RecipeStore> = {}): RecipeStore {
  const map = new Map<string, string>();
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
    get length() { return map.size; },
    key: (i) => [...map.keys()][i] ?? null,
    ...over,
  };
}

describe('cacheKey', () => {
  it.each([
    ['gcsimPin', { gcsimPin: 'different' }],
    ['buildId', { buildId: 'other' }],
    ['rotationId', { rotationId: 'other' }],
    ['artifactSetId', { artifactSetId: 's2' }],
    ['energyRecharge', { energyRecharge: 0.4 }],
    ['seed', { seed: '99' }],
  ] as const)('changes when %s changes', (_name, over) => {
    expect(cacheKey({ ...KEY, ...over })).not.toBe(cacheKey(KEY));
  });

  it('treats a no-four-piece calibration as its own key, not as a missing one', () => {
    // `null` is a real state — the recipe a 2+2 split is scored against — and must not
    // collide with a set whose id happens to stringify oddly.
    expect(cacheKey({ ...KEY, artifactSetId: null })).toContain('none');
    expect(cacheKey({ ...KEY, artifactSetId: null })).not.toBe(cacheKey(KEY));
  });

  it('treats 0.3 and 0.30 as the same ER', () => {
    expect(cacheKey({ ...KEY, energyRecharge: 0.3 }))
      .toBe(cacheKey({ ...KEY, energyRecharge: 0.30 }));
  });

  it('is namespaced, so eviction cannot take unrelated keys', () => {
    expect(cacheKey(KEY).startsWith('mistilteinn:recipe:')).toBe(true);
  });
});

describe('readRecipe / writeRecipe', () => {
  it('round-trips a recipe', () => {
    const store = memory();
    expect(writeRecipe(store, KEY, RECIPE)).toBe(true);

    expect(readRecipe(store, KEY)).toEqual(RECIPE);
  });

  it('misses when the gcsim pin differs', () => {
    // The one that would otherwise go unnoticed: a recipe from a different simulator.
    const store = memory();
    writeRecipe(store, KEY, RECIPE);

    expect(readRecipe(store, { ...KEY, gcsimPin: 'moved' })).toBeNull();
  });

  it('misses rather than throwing on unparseable content', () => {
    const store = memory();
    store.setItem(cacheKey(KEY), 'not json');

    expect(readRecipe(store, KEY)).toBeNull();
  });

  it('reports a refusal rather than throwing', () => {
    // A cache that fails is a slow search, not a broken page.
    const store = memory({ setItem: () => { throw new Error('QuotaExceeded'); } });

    expect(writeRecipe(store, KEY, RECIPE)).toBe(false);
  });

  it('evicts and retries once when storage is full', () => {
    // Turns a full cache into a slow search rather than a permanently broken one.
    let full = true;
    const map = new Map<string, string>();
    const store: RecipeStore = {
      getItem: (k) => map.get(k) ?? null,
      setItem: (k, v) => {
        if (full) throw new Error('QuotaExceeded');
        map.set(k, v);
      },
      removeItem: (k) => { full = false; map.delete(k); },
      get length() { return map.size; },
      key: (i) => [...map.keys()][i] ?? null,
    };
    map.set(cacheKey({ ...KEY, seed: 'old' }), '{}');

    expect(writeRecipe(store, KEY, RECIPE)).toBe(true);
  });

  it('reads and writes nothing when there is no store', () => {
    expect(readRecipe(null, KEY)).toBeNull();
    expect(writeRecipe(null, KEY, RECIPE)).toBe(false);
  });
});

describe('evictRecipes', () => {
  it('drops only this namespace', () => {
    // Clearing the whole of local storage would take a user's unrelated settings with it.
    const store = memory();
    writeRecipe(store, KEY, RECIPE);
    store.setItem('someone-elses-key', 'keep me');

    expect(evictRecipes(store)).toBe(1);
    expect(store.getItem('someone-elses-key')).toBe('keep me');
    expect(readRecipe(store, KEY)).toBeNull();
  });

  it('returns zero without a store rather than throwing', () => {
    expect(evictRecipes(null)).toBe(0);
  });
});

describe('browserStore', () => {
  it('returns something or null, never throws', () => {
    // Accessing localStorage *throws* where site data is blocked, rather than returning null.
    expect(() => browserStore()).not.toThrow();
  });
});
