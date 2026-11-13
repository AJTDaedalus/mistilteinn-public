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
  probe: 'atk%=0.5,def%=0.7,hp%=0.3',
  context: 'ctx-abc123',
};

const RECIPE = {
  hits: [], seed: '12345',
  meta: {
    seed: '12345', staleConversions: [], characters: [], unstable: [],
    calibratedSetIds: [1], minimumEnergyRecharge: 0.3,
  },
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
    ['probe', { probe: 'def%=0.5' }],
    ['context', { context: 'ctx-different' }],
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

describe('a formula estimate never enters the gcsim recipe cache (math-fallback P1, task 8)', () => {
  const FORMULA = {
    ...RECIPE,
    seed: 'formula',
    meta: {
      ...RECIPE.meta,
      seed: 'formula',
      formula: {
        kind: 'formula-estimate', comparator: 'genshin-optimizer', assumptions: [],
        rows: [], sources: [],
      },
    },
  } as unknown as Recipe;

  it('refuses to write one', () => {
    const store = memory();
    expect(writeRecipe(store, KEY, FORMULA)).toBe(false);
    expect(store.length).toBe(0);
  });

  it('misses on one found under a gcsim key, rather than serving it', () => {
    // Planted directly, as a stale build or a bug elsewhere could have left it.
    const store = memory();
    store.setItem(cacheKey(KEY), JSON.stringify(FORMULA));
    expect(readRecipe(store, KEY)).toBeNull();
  });
});

describe('browserStore', () => {
  it('returns something or null, never throws', () => {
    // Accessing localStorage *throws* where site data is blocked, rather than returning null.
    expect(() => browserStore()).not.toThrow();
  });
});

describe('a rotation is its steps, not its id', () => {
  /**
   * **Reported from production:** *"I changed my team and rotation, but when I clicked
   * optimize it didn't recompute. It just gave me the same damage back."*
   *
   * `rotationId` is an id. Editing a rotation's steps, or changing who is on its team, leaves
   * it unchanged — so the recipe calibrated for the old rotation was still a hit. The context
   * hash covers the steps, the team, the build's level, weapon and talents, the target and the
   * pin.
   *
   * The third time this cache served something its key did not describe, after `meta.unstable`
   * and the probe. All three are one shape: something that determines the value, absent from
   * what identifies it.
   */
  it('misses when the rotation behind the same id has changed', () => {
    const store = memory();
    writeRecipe(store, KEY, RECIPE);

    expect(readRecipe(store, { ...KEY, context: 'ctx-after-an-edit' })).toBeNull();
  });

  it('still hits when nothing about the simulation changed', () => {
    // A key so specific that nothing ever hits would turn every search into a full
    // recalibration — six seconds a set, which is the cost this cache exists to avoid.
    const store = memory();
    writeRecipe(store, KEY, RECIPE);

    expect(readRecipe(store, { ...KEY })).toEqual(RECIPE);
  });
});

describe('the probe is part of what identifies a recipe', () => {
  /**
   * **Reported from production, after a fix that appeared to do nothing.** The probe was
   * widened from one stat to three so ATK- and HP-derived conversions could resolve at all.
   * The probe was not in this key, so every user with a warm cache was served the old recipe
   * with the old unresolved terms — the deploy landed and the warnings did not move.
   *
   * A `SCHEMA` bump would clear the stale entries once. This stops the next probe change
   * repeating the story.
   */
  it('misses a recipe calibrated with a different probe', () => {
    const store = memory();
    writeRecipe(store, KEY, RECIPE);

    expect(readRecipe(store, { ...KEY, probe: 'def%=0.5' })).toBeNull();
  });

  it('hits when the probe is the same', () => {
    // The other half: a key so specific that nothing ever hits would turn every search into
    // a full recalibration.
    const store = memory();
    writeRecipe(store, KEY, RECIPE);

    expect(readRecipe(store, { ...KEY })).toEqual(RECIPE);
  });
});

describe('a cached recipe written before a field existed', () => {
  /**
   * **Reported from production: `Cannot read properties of undefined (reading 'length')`.**
   *
   * `meta.unstable` was added after this cache shipped, and the cache is persistent with no
   * schema in its key — so every recipe stored before that change came back missing the
   * field, and `recipe.meta.unstable.length` threw. It broke the optimizer for exactly the
   * people who had used it before, and worked perfectly for anyone who had not.
   */
  it('misses a recipe stored under an older schema rather than returning half of one', () => {
    const store = memory();
    // What the previous version wrote: the same key inputs, no `unstable`.
    store.setItem(
      [
        'mistilteinn:recipe:', KEY.gcsimPin, KEY.buildId, KEY.rotationId,
        KEY.artifactSetId, KEY.energyRecharge.toFixed(4), KEY.seed,
      ].join('|'),
      JSON.stringify({ hits: [], seed: '12345', meta: { seed: '12345' } }),
    );

    expect(readRecipe(store, KEY)).toBeNull();
  });

  it('misses an entry missing the lists a consumer indexes, rather than repairing it', () => {
    // Belt and braces behind the key: the version stops *known* old shapes loading, this
    // stops an unknown one — a truncated write, a hand-edited entry — reaching a caller that
    // reads `.length` off it.
    const store = memory();
    store.setItem(cacheKey(KEY), JSON.stringify({ hits: [], seed: '12345', meta: {} }));

    expect(readRecipe(store, KEY)).toBeNull();
  });

  it('does not manufacture an empty `unstable`, which would claim the rotation was stable', () => {
    // **The fix that would have re-created the bug #193 closed.** Defaulting the field is not
    // "we do not know" — an empty list is the affirmative claim that the rotation ran the same
    // way every iteration, which is what the page prints as a ranking worth trusting.
    const store = memory();
    store.setItem(cacheKey(KEY), JSON.stringify({
      hits: [], seed: '12345',
      meta: { seed: '12345', staleConversions: [], characters: [], calibratedSetIds: [] },
    }));

    expect(readRecipe(store, KEY)).toBeNull();
  });
});

describe('what the cache must carry', () => {
  it('round-trips a recipe unstable ability list', () => {
    // **The reason this field is on `RecipeMeta` at all.** `calibrate` returned `stable`
    // beside the recipe, and only the recipe is persisted — so a second search over the same
    // build served every recipe from storage with its instability forgotten, and the page then
    // affirmatively called the ranking sound. Permanently, because the cache is persistent.
    const store = memory();
    const recipe = {
      ...RECIPE,
      meta: { ...RECIPE.meta, unstable: ['Skirk: burst'] },
    } as unknown as Recipe;

    writeRecipe(store, KEY, recipe);

    expect(readRecipe(store, KEY)?.meta.unstable).toEqual(['Skirk: burst']);
  });
});
