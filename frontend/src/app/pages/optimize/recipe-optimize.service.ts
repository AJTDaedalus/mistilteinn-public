import { InjectionToken, Injectable, inject } from '@angular/core';

import { injectApi } from '../../api/api.client';
import { calibrate } from '../../sim/calibrate';
import { run as runConfig, type GcsimModule } from '../../sim/gcsim';
import { SimRunsService } from '../../sim/sim-runs.service';
import { RotationsService } from '../rotations/rotations.service';
import { loadGcsim } from '../../sim/gcsim-loader';
import type { Recipe } from '../../sim/recipe';
import { pairKey } from '../../sim/recipe-search';
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
  /**
   * The sets to equip, as catalogue **uuids** — what `/calibrate` resolves.
   *
   * Length is the state: **0** the baseline, **1** a 4-piece, **2** a 2+2 pair. One list
   * rather than a field per shape, so adding the pair did not add a third way to say which
   * sets a calibration holds.
   */
  artifactSetIds: readonly string[];
  /**
   * The same sets as **catalogue (nanoka) ids**.
   *
   * Beside the uuids rather than instead of them, because the two are different numbers for
   * different jobs: `/calibrate` resolves the uuid, and the search counts set pieces by this
   * one. A recipe that recorded the uuid would match no combination.
   */
  setIds: readonly number[];
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
  /** Pair recipes, keyed by `pairKey`. */
  byPair: Map<string, Recipe>;
  noFourPiece: Recipe | null;
  caveats: CalibrationCaveats;
}

/** The seed every calibration uses, so a cached recipe and a fresh one are comparable. */
const SEED = '12345';

/**
 * Iterations for the aggregate run that measures stability and fills the corpus.
 *
 * **Measured against the owner's real four-character 90-second rotation** on the committed
 * browser build, 2026-08-29: `sample()` 4.13 s (and a calibration does two), `run(10)` 1.40 s,
 * `run(25)` 3.36 s, `run(100)` 11.56 s. The mean moved 49,069 → 49,214 between 25 and 100 —
 * 0.3 % — so the extra 8 s buys precision rather than a different answer.
 *
 * 100 anyway, because this runs **once per search** rather than once per calibration target,
 * and because the config's own `iteration=100` line then describes what actually happened.
 * A cached number is read many times and computed once; the cheap version would be the one
 * this repo regrets.
 */
const AGGREGATE_RUNS = 100;

/**
 * Per-character action counts from gcsim's aggregate, keyed `"<character> <action>"`.
 *
 * gcsim reports `character_actions` as a **positional list with no names in it**, which is why
 * `/calibrate` publishes the config's character order — two characters both have a `skill`,
 * and collapsing them would attribute one's instability to the other.
 *
 * `stats`, not `statistics`: the wasm build's `flush()` returns exactly one top-level key and
 * it is not the one the native CLI writes. Read off the committed `gcsim.wasm`, not assumed.
 */
export function instancesFrom(
  raw: unknown,
  characters: readonly string[],
): Record<string, { mean: number; sd: number }> {
  const perCharacter = (raw as {
    stats?: { character_actions?: { sources?: Record<string, { mean?: number; sd?: number }> }[] };
  })?.stats?.character_actions;
  if (!Array.isArray(perCharacter)) return {};

  const out: Record<string, { mean: number; sd: number }> = {};
  perCharacter.forEach((entry, index) => {
    // Falls back to the position when the order is short or absent. A number is a poor label
    // and an honest one; inventing a name would be worse.
    const who = characters[index] ?? `character ${index + 1}`;
    for (const [action, stat] of Object.entries(entry?.sources ?? {})) {
      if (typeof stat?.mean === 'number' && typeof stat?.sd === 'number') {
        out[`${who} ${action}`] = { mean: stat.mean, sd: stat.sd };
      }
    }
  });
  return out;
}

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
  private rotations = inject(RotationsService);
  private simRuns = inject(SimRunsService);

  /**
   * Calibrate one recipe per target, reusing cached ones.
   *
   * **A state that fails is skipped and named, not fatal.** One unsimulatable set should not
   * cost the user every other recipe in a run that took minutes — and a search that silently
   * dropped it would score that set's builds against the wrong recipe.
   */
  /**
   * `cacheEpoch` is any string that should invalidate cached recipes when it changes.
   *
   * **Not a gcsim pin, despite what it was called.** Calculate passes the real pin; the
   * optimizer passes the artifact inventory's snapshot version. Both are correct for a cache
   * key and neither is interchangeable with the other, which is exactly why the name mattered
   * the moment something tried to submit it as a pin.
   */
  async calibrateAll(
    buildId: string,
    rotationId: string,
    cacheEpoch: string,
    targets: readonly CalibrationTarget[],
    onProgress: (progress: CalibrationProgress) => void,
  ): Promise<CalibrationResult> {
    const byFourPieceSet = new Map<number, Recipe>();
    const byPair = new Map<string, Recipe>();
    let noFourPiece: Recipe | null = null;
    const caveats: CalibrationCaveats = {
      unstable: [], staleConversions: [], fromCache: [],
    };

    onProgress({ done: 0, total: targets.length, current: '', loading: true });
    const mod = await this.loadModule();

    for (const [index, target] of targets.entries()) {
      onProgress({ done: index, total: targets.length, current: target.label, loading: false });

      const configs = await this.configs(buildId, rotationId, target.artifactSetIds);
      const key = {
        // `RecipeCacheKey` still spells this field `gcsimPin`. Renaming it there would
        // change every persisted key and re-calibrate every cached recipe for a word, so
        // the honest name stops at this boundary and the mapping is explicit.
        gcsimPin: cacheEpoch, buildId, rotationId,
        // **Both sets, joined.** A pair keyed by only its first set would serve one pair's
        // recipe for every pair starting with it.
        artifactSetId: target.artifactSetIds.join('+') || null,
        energyRecharge: configs.energy_recharge,
        seed: SEED,
      };

      let recipe = readRecipe(this.store, key);
      if (recipe !== null) {
        caveats.fromCache.push(target.label);
      } else {
        // **The aggregate, once per search.** `stabilityFrom({})` returns `stable: true`, so
        // the "did not run the same way every iteration" warning was unreachable — the page
        // rendered a caveat nothing could produce. On the owner's real rotation it fires:
        // `skill`, `burst` and `swap` all vary by more than the 2 % tolerance.
        //
        // Only on the **set-free** target, because a `sim_run` is keyed by context — character,
        // weapon, team, rotation, target — and *not* by artifacts. One aggregate answers for
        // every target in the search; running one each would store a set-specific number under
        // a set-independent key.
        const wantsAggregate = target.artifactSetIds.length === 0;
        const aggregate = wantsAggregate ? runConfig(mod, configs.baseline, AGGREGATE_RUNS) : null;
        if (aggregate !== null) {
          // Offered to the cache, never awaited for correctness. `DECISIONS.md` §25: the
          // corpus accumulates from real searches, and a user whose search finished must not
          // be told otherwise because a cache write was refused.
          void this.cache(buildId, rotationId, configs.energy_recharge, aggregate.raw);
        }

        const calibrated = calibrate(
          {
            baseline: mod.sample(configs.baseline, SEED),
            probe: mod.sample(configs.probe, SEED),
            instances: aggregate ? instancesFrom(aggregate.raw, configs.characters) : {},
          },
          // **Not `[]` for a 4-piece target.** Equipping a set to calibrate also applies its
          // 2-piece, so a recipe that does not name it lets the search add that tier again —
          // the exact double-count `RESEARCH_recipe_risks.md` §2 records. This passed `null`
          // unconditionally and was harmless only while no set bonuses reached the search at
          // all; B.1 made them reach it.
          { setIds: target.setIds },
        );
        recipe = calibrated.recipe;
        writeRecipe(this.store, key, recipe);
      }

      // **Read off the recipe, so a cache hit reports it too.** This used to sit inside the
      // fresh-calibration branch above, so the second search over the same build served every
      // recipe from storage, found no instability, and the page called the ranking sound —
      // permanently, because the cache is persistent.
      if (recipe.meta.unstable.length > 0) caveats.unstable.push(target.label);

      for (const stale of recipe.meta.staleConversions) {
        caveats.staleConversions.push({
          label: target.label, term: stale.term, damageShare: stale.damageShare,
        });
      }
      // **Keyed by the catalogue id the search counts pieces with**, not by parsing a uuid:
      // `Number()` of one is `NaN`, and every recipe would land under a single key.
      if (target.setIds.length === 0) noFourPiece = recipe;
      else if (target.setIds.length === 1) byFourPieceSet.set(target.setIds[0], recipe);
      else byPair.set(pairKey(target.setIds[0], target.setIds[1]), recipe);
    }

    onProgress({ done: targets.length, total: targets.length, current: '', loading: false });
    return { byFourPieceSet, byPair, noFourPiece, caveats };
  }

  /** Whether this build can perform the rotation these recipes describe. */
  shortfall(recipe: Recipe, buildEnergyRecharge: number): EnergyShortfall | null {
    return energyShortfall(buildEnergyRecharge, recipe.meta.minimumEnergyRecharge);
  }

  /**
   * Offer one finished aggregate to the run corpus.
   *
   * **Everything it needs comes from the server**, deliberately: the context key is a hash the
   * client has no business computing, the rotation signature comes back pre-hashed so no
   * second implementation of that digest exists, and the ER bucket width is published rather
   * than restated because `er_bucket` rounds *down* and a client rounding differently would
   * write rows nothing ever looks up.
   *
   * Swallows every failure. A cache that could not be written is the next search being slower,
   * not this one being wrong.
   */
  private async cache(
    buildId: string,
    rotationId: string,
    energyRecharge: number,
    raw: unknown,
  ): Promise<void> {
    try {
      const key = await this.rotations.contextKey(rotationId, buildId);
      const percent = Math.round(energyRecharge * 100);
      await this.simRuns.store({
        contextKey: key.context_key,
        erBucket: percent - (percent % key.er_bucket_percent),
        // **The server's pin, not the caller's.** `calibrateAll`'s third argument is a cache
        // epoch, and the optimizer passes the *inventory snapshot version* through it — a
        // perfectly good discriminator for the recipe cache and not a gcsim commit at all.
        // Submitting it produced a 422 on a field validated as 40 hex characters, which is
        // the endpoint doing its job. The pin comes back with the context key it belongs to.
        gcsimPin: key.gcsim_pin,
        result: raw,
        rotationId,
        rotationSignature: key.rotation_signature,
      });
    } catch {
      // See the docstring: not being cached is not a failed search.
    }
  }

  private async configs(
    buildId: string, rotationId: string, artifactSetIds: readonly string[],
  ) {
    const { data, error } = await this.api.POST('/api/v1/builds/{build_id}/calibrate', {
      params: { path: { build_id: buildId } },
      body: {
        rotation_id: rotationId,
        // One set is a 4-piece; two are a 2+2, which the endpoint refuses to combine with a
        // 4-piece because five slots cannot hold both.
        artifact_set_id: artifactSetIds.length === 1 ? artifactSetIds[0] : null,
        two_piece_set_ids: artifactSetIds.length === 2 ? [...artifactSetIds] : [],
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
    return data as {
      baseline: string; probe: string; energy_recharge: number; characters: string[];
    };
  }
}

/** Re-exported so a caller can drive gcsim without importing two modules. */
export { runConfig };
