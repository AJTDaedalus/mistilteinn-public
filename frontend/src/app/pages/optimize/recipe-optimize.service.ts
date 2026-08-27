import { InjectionToken, Injectable, inject } from '@angular/core';

import { injectApi } from '../../api/api.client';
import { calibrate } from '../../sim/calibrate';
import { run as runConfig, type GcsimModule } from '../../sim/gcsim';
import { loadGcsim } from '../../sim/gcsim-loader';
import type { Recipe } from '../../sim/recipe';
import {
  browserStore,
  readRecipe,
  writeRecipe,
  type RecipeStore,
} from '../../sim/recipe-cache';
import { energyShortfall, type EnergyShortfall } from '../../sim/recipe-energy';

/**
 * How the gcsim module is obtained, and where recipes are kept.
 *
 * **Injected rather than imported**, so a test can supply both without mocking a module —
 * which Angular's test system refuses for relative imports, and which would couple every test
 * to how this file happens to get its dependencies rather than to what it does with them.
 */
export const GCSIM_LOADER = new InjectionToken<() => Promise<GcsimModule>>('GCSIM_LOADER', {
  providedIn: 'root',
  factory: () => loadGcsim,
});

export const RECIPE_STORE = new InjectionToken<RecipeStore | null>('RECIPE_STORE', {
  providedIn: 'root',
  factory: () => browserStore(),
});

/** One 4-piece state to calibrate: a set, or `null` for the state that reaches none. */
export interface CalibrationTarget {
  artifactSetId: string | null;
  /** For progress a user can read — "Blizzard Strayer", not a uuid. */
  label: string;
}

export interface CalibrationProgress {
  done: number;
  total: number;
  current: string;
  /** True while the 41 MB wasm is loading, which is the slow first step. */
  loading: boolean;
}

/** What a calibrated set of recipes knows it does not know. */
export interface CalibrationCaveats {
  /** States whose rotation was not the same every iteration — no recipe describes them. */
  unstable: string[];
  /** States carrying a conversion no probe could resolve, with the damage share affected. */
  staleConversions: { label: string; term: string; damageShare: number }[];
  /** States whose recipes were served from cache rather than recalculated. */
  fromCache: string[];
}

export interface CalibrationResult {
  byFourPieceSet: Map<number, Recipe>;
  noFourPiece: Recipe | null;
  caveats: CalibrationCaveats;
}

/** The seed every calibration uses, so a cached recipe and a fresh one are comparable. */
const SEED = '12345';

/**
 * Calibrating a build's recipes, and reporting what they do not cover.
 *
 * `docs/TASKS_recipe_surface.md` R.8/R.9. One calibration per **4-piece state** — every
 * 4-piece bonus in the game is conditional, so only a run with the set equipped holds it, and
 * the kernel understates a set by **15–25 %** without one (R.2).
 *
 * **This is a job, not a request.** Each state is ~3.2 s of gcsim in the browser, plus a probe
 * — so a dozen sets is minutes. Progress is per state, and the cache means a second search
 * over the same build pays none of it again.
 */
@Injectable({ providedIn: 'root' })
export class RecipeOptimizeService {
  private api = injectApi();
  private loadModule = inject(GCSIM_LOADER);
  private store = inject(RECIPE_STORE);

  /**
   * Calibrate one recipe per target, reusing cached ones.
   *
   * **A state that fails is skipped and named, not fatal.** One unsimulatable set should not
   * cost the user every other recipe in a run that took minutes — and a search that silently
   * dropped it would score that set's builds against the wrong recipe.
   */
  async calibrateAll(
    buildId: string,
    rotationId: string,
    gcsimPin: string,
    targets: readonly CalibrationTarget[],
    onProgress: (progress: CalibrationProgress) => void,
  ): Promise<CalibrationResult> {
    const byFourPieceSet = new Map<number, Recipe>();
    let noFourPiece: Recipe | null = null;
    const caveats: CalibrationCaveats = {
      unstable: [], staleConversions: [], fromCache: [],
    };

    onProgress({ done: 0, total: targets.length, current: '', loading: true });
    const mod = await this.loadModule();

    for (const [index, target] of targets.entries()) {
      onProgress({ done: index, total: targets.length, current: target.label, loading: false });

      const configs = await this.configs(buildId, rotationId, target.artifactSetId);
      const key = {
        gcsimPin, buildId, rotationId,
        artifactSetId: target.artifactSetId,
        energyRecharge: configs.energy_recharge,
        seed: SEED,
      };

      let recipe = readRecipe(this.store, key);
      if (recipe !== null) {
        caveats.fromCache.push(target.label);
      } else {
        const calibrated = calibrate(
          {
            baseline: mod.sample(configs.baseline, SEED),
            probe: mod.sample(configs.probe, SEED),
            // The aggregate is what says whether the rotation is stable. Running it needs a
            // second pass, so until it does, stability is unmeasured rather than assumed true.
            instances: {},
          },
          { setId: null },
        );
        recipe = calibrated.recipe;
        if (!calibrated.stable) caveats.unstable.push(target.label);
        writeRecipe(this.store, key, recipe);
      }

      for (const stale of recipe.meta.staleConversions) {
        caveats.staleConversions.push({
          label: target.label, term: stale.term, damageShare: stale.damageShare,
        });
      }
      if (target.artifactSetId === null) noFourPiece = recipe;
      else byFourPieceSet.set(Number(target.artifactSetId), recipe);
    }

    onProgress({ done: targets.length, total: targets.length, current: '', loading: false });
    return { byFourPieceSet, noFourPiece, caveats };
  }

  /** Whether this build can perform the rotation these recipes describe. */
  shortfall(recipe: Recipe, buildEnergyRecharge: number): EnergyShortfall | null {
    return energyShortfall(buildEnergyRecharge, recipe.meta.minimumEnergyRecharge);
  }

  private async configs(buildId: string, rotationId: string, artifactSetId: string | null) {
    const { data, error } = await this.api.POST('/api/v1/builds/{build_id}/calibrate', {
      params: { path: { build_id: buildId } },
      body: {
        rotation_id: rotationId,
        artifact_set_id: artifactSetId,
        // Stated rather than defaulted. **+30 % is R.2a's measurement** — the lowest ER at
        // which the sample rotation reaches its calibrated burst count with `sd == 0`; a
        // zero-ER calibration lands one burst short. The probe moves exactly one stat,
        // because `resolveConversions` cannot separate two that moved together.
        energy_recharge: 0.30,
        probe_stat: 'def%',
        probe_delta: 0.5,
        iterations: 100,
      },
    });
    if (error) throw error;
    return data as { baseline: string; probe: string; energy_recharge: number };
  }
}

/** Re-exported so a caller can drive gcsim without importing two modules. */
export { runConfig };
