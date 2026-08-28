/**
 * Producing a recipe from gcsim, end to end.
 *
 * `docs/TASKS_recipe_surface.md` R.4. Three gcsim runs per recipe — a baseline, a probe that
 * identifies stat conversions, and an aggregate that says whether the rotation is stable —
 * then one `Recipe` with everything a search needs to know what it does *not* know.
 *
 * ## Why this exists rather than callers doing it themselves
 *
 * `Recipe.meta.calibratedSetIds` decides whether the search skips a set's bonuses. A recipe
 * built without it silently double-counts the 2-piece — **15–25 % on the set the user most
 * likely cares about** — and a `null` id is indistinguishable from a genuine no-set
 * calibration, so nothing can detect the omission after the fact.
 *
 * **This function is the only place a recipe is born**, so there is no window in which one
 * exists without knowing what it was calibrated with.
 */

import {
  parseSample,
  resolveConversions,
  stabilityFrom,
  type Recipe,
} from './recipe';
import { minimumEnergyRecharge, type EnergyObservation } from './recipe-energy';

/** What one gcsim call produced, so this module needs no opinion about how it was made. */
export interface CalibrationRuns {
  /** `sample()` at the calibration's own stats. */
  baseline: string;
  /** `sample()` at a perturbed stat, for `resolveConversions`. */
  probe: string;
  /**
   * Instance counts from an **aggregate** run, keyed by ability.
   *
   * From the aggregate rather than the sample deliberately: one seed's counts carry that
   * seed's timing jitter, and it is the aggregate's `sd` that says whether the rotation is
   * the same every iteration at all.
   */
  instances: Readonly<Record<string, { mean: number; sd: number }>>;
  /** An ER sweep, if one was run. Without it the recipe has no minimum and says so. */
  energySweep?: readonly EnergyObservation[];
}

export interface CalibrationRequest {
  /**
   * Catalogue ids of the sets equipped: one for a 4-piece, two for a 2+2, none for the
   * baseline. A caller passing `null` means "no set", which is the empty list here.
   */
  setIds: readonly number[];
  /** Which ability's instance count defines "performs as calibrated". */
  burstAbility?: string;
}

export interface Calibrated {
  recipe: Recipe;
  /** Whether the rotation is the same every iteration. False means no recipe describes it. */
  stable: boolean;
  /** The abilities whose counts varied, named rather than counted. */
  unstable: string[];
  resolved: number;
  unresolved: number;
}

/**
 * Build a recipe from a set of gcsim runs.
 *
 * **Stability is reported, not enforced.** An unstable rotation still produces a recipe —
 * refusing to build one would leave a caller unable to say *why* it has no answer, and the
 * flag plus the offending ability names are more useful than an exception. It is the caller's
 * job not to rank on it.
 */
export function calibrate(runs: CalibrationRuns, request: CalibrationRequest): Calibrated {
  const recipe = parseSample(runs.baseline);
  const { resolved, unresolved } = resolveConversions(recipe, parseSample(runs.probe));

  recipe.meta.calibratedSetIds = request.setIds;

  const burst = request.burstAbility;
  const calibratedBursts = burst === undefined
    ? undefined
    : recipe.hits.filter((hit) => hit.abil === burst).length;
  recipe.meta.minimumEnergyRecharge =
    runs.energySweep === undefined || calibratedBursts === undefined
      ? null
      : minimumEnergyRecharge(runs.energySweep, calibratedBursts);

  const { stable, unstable } = stabilityFrom(runs.instances);
  return { recipe, stable, unstable, resolved, unresolved };
}
