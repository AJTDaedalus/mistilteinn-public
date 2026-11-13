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

import { browserStore, type WebStorage } from '../shared/browser-store';
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
  /**
   * What the calibration's probe moved, as a stable string.
   *
   * **The probe decides which conversions the recipe can resolve**, so two recipes calibrated
   * with different probes are different recipes. It was missing from this key, and the
   * consequence was concrete: the probe was widened from one stat to three to fix conversions
   * that could never resolve, and every user with a warm cache was served the old recipe with
   * the old unresolved terms — the fix shipped and changed nothing they could see.
   *
   * Here rather than fixed by bumping `SCHEMA`: a version bump clears the stale entries once,
   * this stops the next probe change repeating the whole story.
   */
  probe: string;
  /**
   * The server's hash of everything that makes this simulation what it is — the build's level,
   * weapon and talents, the **rotation's steps**, the team, the target and the pin.
   *
   * **`rotationId` is an id, not a description.** Editing a rotation's steps leaves its id
   * alone, so a cached recipe for the old steps was still a hit: the owner changed their team
   * and rotation, pressed Optimize, and got the previous damage back. Same for changing who is
   * on the team — the rotation still points at the same team row.
   *
   * This is the third time this cache has served something its key did not describe
   * (`meta.unstable`, then the probe). All three are one shape: something that determines the
   * value, absent from what identifies it. A content hash ends the pattern rather than adding
   * a third field to remember.
   */
  context: string;
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
/**
 * The shape of what is stored, bumped whenever `RecipeMeta` gains a field a consumer indexes.
 *
 * **This exists because it was missing once and broke production.** `meta.unstable` was added
 * to the recipe while this cache was already full of recipes written without it, and
 * `recipe.meta.unstable.length` then threw `Cannot read properties of undefined` — for exactly
 * the users who had run a search before, and for nobody who had not.
 *
 * `gcsimPin` answers "a different simulator produced this". It does not answer "a different
 * version of this code wrote this", and those are separate questions: the pin can sit still
 * across a release that changes the schema, which is precisely what happened.
 *
 * Bumping it makes every older entry miss and recalibrate. That costs one calibration and is
 * the cheap direction; the other direction hands a caller half a recipe.
 */
// **3: the recipe carries what energy costs.** `meta` gained `energyCost`, `energySweep`,
// `calibratedEnergyDps` and `burstAttackTag`; a v2 entry has none of them, so a cache hit came
// back silent — no warning, and ER weighted at a flat ratio of 1. The owner ran a fresh
// optimize after the deploy and saw exactly nothing change.
//
// **This is the fourth time this cache served something its key did not describe** —
// `meta.unstable` (#195), the probe (#202), the rotation's steps (#207), and now a new field
// with no version behind it. The first three were keys that omitted an input; this is a
// *shape* change, which the version is what guards.
//
// **4: the ladder is on every recipe, not only the baseline.** A v3 entry for a 4-piece target
// has `energySweep` undefined — correctly, for how v3 was written — and a cache hit would keep
// serving that after the fix, so ER would go on being pruned and the owner would again run a
// fresh optimize and see nothing change. Same shape as 3, one layer further out: the field is
// present in both versions and what *populates* it changed.
//
// **5: the ladder is measured differently.** `meta` gained `calibratedEnergyRecharge`, the
// sweep gained a rung at the build's own ER, `ENERGY_LADDER_RUNS` went 20 → 60, and `dpsAt`
// now reads a running maximum. A v4 entry holds a 20-iteration sweep with no baseline rung, and
// `energyRatio` would fall back to the old denominator and quietly score on it.
//
// **6: `staleConversions` no longer counts teammates.** #227 restored the `mine` filter that
// `staleConversionsAfter` was missing, so a term belonging to a teammate's equipped gear is no
// longer reported as a conversion no probe could resolve. The list lives in `meta` and is read
// off the recipe *so that a cache hit reports it too* — which is exactly why the fix alone
// changed nothing the owner could see: every v5 entry still holds the old list, naming
// `flatAtk`, `flatHp` and `flatDef` against 96.6 % of the damage.
//
// **That is the fifth time, and the fourth of these entries says so.** The rule this file
// keeps rediscovering: fixing what *populates* a cached field is a change to the cached
// shape, whatever the field's type says. The type never changed here either.
//
// **7: a term the probe never moved is `constant`, not unresolved.** The matcher only ever
// considered stats the probe *moved*, so a term with a ratio of 1 matched nothing by
// construction and was filed as unresolvable — 183 of the subject's 198 flat-carrying hits on
// the owner's own team. `RecipeHit` gained `constantTerms`, and a v6 entry has none of them,
// so the warning would survive on every cached recipe exactly as it survived #227.
//
// **8: a hit carries its EM and its reaction.** `parseSample` now reads gcsim's `em`,
// `reaction_type`, `react_mult` and `react_bonus` into `calibratedEm` and `amplifying`, and an
// amplified hit's `gcsimAverageDamage` is the post-reaction average. A v7 entry has none of it,
// so a cache hit would go on scoring an EM-scaling hit off the candidate's EM alone and
// holding vaporize/melt at the calibration's multiplier — artifact EM worth nothing, the
// defect this version exists to retire, served to exactly the users who had searched before.
const SCHEMA = 8;

export function cacheKey(key: RecipeCacheKey): string {
  return [
    PREFIX,
    `v${SCHEMA}`,
    key.gcsimPin,
    key.buildId,
    key.rotationId,
    key.artifactSetId ?? 'none',
    // Fixed precision so 0.3 and 0.30 are the same key rather than two.
    key.energyRecharge.toFixed(4),
    key.seed,
    key.probe,
    key.context,
  ].join('|');
}

/** Where recipes are kept. Injectable so a test needs no browser. */
export type RecipeStore = WebStorage;

export { browserStore };

/**
 * Whether a parsed entry carries everything a consumer will index into.
 *
 * **A miss, never a repair.** The obvious fix for the production crash was to default the
 * missing lists to `[]` — and that would have re-created the bug #193 had just fixed. An
 * empty `unstable` is not "we do not know"; it is the affirmative claim *this rotation ran
 * the same way every iteration*, which is what the page prints as a ranking worth trusting.
 * Manufacturing it from a recipe that never said so is the green-by-absence failure this repo
 * treats as a defect, and it would be permanent, because the cache is persistent.
 *
 * Missing the entry costs one recalibration. Filling it in costs the reader a warning they
 * were owed and cannot get back.
 */
function isComplete(recipe: Recipe | null): boolean {
  if (recipe === null || typeof recipe !== 'object') return false;
  const meta = recipe.meta as Recipe['meta'] | undefined;
  return Array.isArray(recipe.hits)
    && meta !== undefined
    && Array.isArray(meta.unstable)
    && Array.isArray(meta.staleConversions)
    && Array.isArray(meta.calibratedSetIds);
}

/** A cached recipe, or `null`. Never throws: a cache that fails is a cache that misses. */
export function readRecipe(store: RecipeStore | null, key: RecipeCacheKey): Recipe | null {
  if (store === null) return null;
  try {
    const raw = store.getItem(cacheKey(key));
    if (raw === null) return null;
    const found = JSON.parse(raw) as Recipe;
    return isComplete(found) ? found : null;
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
