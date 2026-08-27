/**
 * Keeping calibrated recipes between searches, and dropping them when they stop being true.
 *
 * `docs/TASKS_recipe_surface.md` R.4, **OQ-R2**. A calibration is ~3.2 s of gcsim per 4-piece
 * set, so a dozen sets is a job the user should not repeat on every search — and
 * `RESEARCH_calibration_cache.md` settled where it lives: **client-side**, because a recipe is
 * 30–70 KB and costs 3.2 s to regenerate in the browser where it is produced. A server cache
 * would buy that 3.2 s and cost an API, tenancy and invalidation.
 *
 * ## What makes a cached recipe stale
 *
 * Everything that changes what gcsim would produce. The key names all of it, so a mismatch is
 * a miss rather than a wrong answer:
 *
 * - the **gcsim pin** — a different simulator is a different recipe, and this is the one that
 *   would otherwise go unnoticed for months;
 * - the **build** and the **rotation** it was calibrated against;
 * - the **4-piece set** equipped, and the **ER** it was calibrated at;
 * - the **seed**, because a recipe carries one run's instance counts.
 *
 * ## Failure is not an error
 *
 * Browser storage can refuse — quota, a private window, a browser that blocks site data — and
 * a recipe is **derivable**. So every read and write is wrapped: a failed write means the next
 * search recalibrates, which is slow, not wrong. **Throwing here would turn a 3.2 s cost into
 * a broken page.**
 */

import type { Recipe } from './recipe';

/** Everything that changes what a calibration would produce. */
export interface RecipeCacheKey {
  gcsimPin: string;
  buildId: string;
  rotationId: string;
  /** The catalogue id of the 4-piece set, or `null` for the no-four-piece state. */
  artifactSetId: string | null;
  energyRecharge: number;
  seed: string;
}

/** Namespaced so clearing recipes cannot take unrelated keys with it. */
const PREFIX = 'mistilteinn:recipe:';

/**
 * The storage key.
 *
 * Every field is in it, in a fixed order. **A key that omitted the pin would serve a recipe
 * from a different simulator** — the exact shape of failure `verify-gcsim-recipe.mjs` exists
 * to prevent one layer down, and the one fairy shipped for months.
 */
export function cacheKey(key: RecipeCacheKey): string {
  return [
    PREFIX,
    key.gcsimPin,
    key.buildId,
    key.rotationId,
    key.artifactSetId ?? 'none',
    // Fixed precision so 0.3 and 0.30 are the same key rather than two.
    key.energyRecharge.toFixed(4),
    key.seed,
  ].join('|');
}

/** Where recipes are kept. Injectable so a test needs no browser. */
export interface RecipeStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  readonly length: number;
  key(index: number): string | null;
}

/** The browser's, or `null` where there is none (SSR, a locked-down browser). */
export function browserStore(): RecipeStore | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    // Accessing it can *throw* where site data is blocked, not merely return null.
    return null;
  }
}

/** A cached recipe, or `null`. Never throws: a cache that fails is a cache that misses. */
export function readRecipe(store: RecipeStore | null, key: RecipeCacheKey): Recipe | null {
  if (store === null) return null;
  try {
    const raw = store.getItem(cacheKey(key));
    return raw === null ? null : (JSON.parse(raw) as Recipe);
  } catch {
    return null;
  }
}

/**
 * Store a recipe. Returns whether it was kept.
 *
 * **A refusal is reported, not thrown.** A caller may want to say "this will recalibrate next
 * time"; none should have to handle an exception for a cache.
 */
export function writeRecipe(
  store: RecipeStore | null, key: RecipeCacheKey, recipe: Recipe,
): boolean {
  if (store === null) return false;
  try {
    store.setItem(cacheKey(key), JSON.stringify(recipe));
    return true;
  } catch {
    // Quota is the likely cause. Evicting this namespace and retrying once turns a full
    // cache into a slow search rather than a permanently broken one.
    try {
      evictRecipes(store);
      store.setItem(cacheKey(key), JSON.stringify(recipe));
      return true;
    } catch {
      return false;
    }
  }
}

/**
 * Drop every cached recipe.
 *
 * Only this namespace — a cache that cleared the whole of local storage would take a user's
 * unrelated settings with it.
 */
export function evictRecipes(store: RecipeStore | null): number {
  if (store === null) return 0;
  try {
    const doomed: string[] = [];
    for (let i = 0; i < store.length; i++) {
      const k = store.key(i);
      if (k !== null && k.startsWith(PREFIX)) doomed.push(k);
    }
    for (const k of doomed) store.removeItem(k);
    return doomed.length;
  } catch {
    return 0;
  }
}
