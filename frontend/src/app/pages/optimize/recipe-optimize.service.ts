import { InjectionToken, Injectable, inject } from '@angular/core';

import { injectApi } from '../../api/api.client';
import { calibrate } from '../../sim/calibrate';
import { readResult, run as runConfig, type GcsimModule } from '../../sim/gcsim';
import { SimRunsService } from '../../sim/sim-runs.service';
import { RotationsService } from '../rotations/rotations.service';
import { loadGcsim } from '../../sim/gcsim-loader';
import type { Recipe } from '../../sim/recipe';
import { stabilityFrom } from '../../sim/recipe';
import type { EnergyObservation } from '../../sim/recipe-energy';
import { pairKey } from '../../sim/recipe-search';
import {
  browserStore,
  readRecipe,
  writeRecipe,
  type RecipeStore,
} from '../../sim/recipe-cache';
import { energyShortfall, type EnergyShortfall } from '../../sim/recipe-energy';
import { energyCost, subjectIsShort, type EnergyCost } from '../../sim/energy-delay';

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
/** Thrown by `calibrateAll` when its `shouldCancel` says stop. Nothing went wrong. */
export class CalibrationCancelled extends Error {
  constructor() {
    super('the calibration was cancelled');
  }
}

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
  /**
   * States whose rotation was not the same every iteration, **with the abilities that varied**.
   *
   * The names were computed all along — `stabilityFrom` returns them and `recipe.meta.unstable`
   * carries them through the cache — and the page threw them away, printing only "the rotation
   * did not run the same way every iteration". That tells a reader something is wrong and
   * nothing about what to change. Naming the ability points straight at it: a burst that fires
   * twice in some iterations and three times in others is an energy problem, and the reader is
   * the only one who can fix it.
   */
  unstable: { label: string; abilities: string[] }[];
  /**
   * What energy is costing the team, measured against the same rotation run with it free.
   *
   * Carried on `recipe.meta` as well, for the same reason `unstable` is: the aggregate that
   * measures it runs on a cache **miss**, so a hit would otherwise come back silent.
   */
  energyCost: EnergyCost | null;
  /**
   * The ER ladder itself, so a **row** can say how many bursts its own gear funds.
   *
   * `energyCost` is one sentence about the run; this is what makes the same question askable
   * per result. Every recipe carries the same ladder — `shareEnergyMeasurement` stamps the
   * baseline's onto all of them — so holding one copy here is not a third source of truth.
   */
  energySweep: readonly EnergyObservation[] | null;
  /** States carrying a conversion no probe could resolve, with the damage share affected. */
  staleConversions: { label: string; term: string; damageShare: number }[];
  /** States whose recipes were served from cache rather than recalculated. */
  fromCache: string[];
  /**
   * The subset of the above belonging to states that **did not score the ranking**.
   *
   * Only the baseline, today. It is calibrated because it is the run the energy measurement is
   * taken on — the aggregate, the free-energy counterfactual and the ER ladder, which
   * `shareEnergyMeasurement` then hands to every other recipe — but `searchRecipe` picks its
   * states from `fourPieceSets`, which never contains `null`, so no result row was ever scored
   * with it.
   *
   * It used to be justified by the per-slot upgrade list, which is gone (2026-09-01): on an
   * exact search that list was provably empty, because a single-slot swap keeping the same
   * 4-piece state is a combination the walk already scored and the winner already beat.
   *
   * **Reported apart because it was judging a ranking it took no part in.** Its instability
   * flipped the page to "Scoring unreliable", which is a claim about the order of the
   * results, and the baseline contributes nothing to that order. Owner ruling, 2026-08-31:
   * keep calibrating it, stop letting it judge.
   */
  unscoredLabels: string[];
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
 * The same config with gcsim told energy is free.
 *
 * `ignore_burst_energy` is a real config option (`pkg/gcs/parser/parseOptions.go`), and the
 * counterfactual gcsim's own substat optimizer measures against.
 */
function withFreeEnergy(config: string): string {
  return config.replace(/^options /m, 'options ignore_burst_energy=true ');
}

/**
 * The ER ladder the sweep walks, and how many iterations each rung gets.
 *
 * **Only walked when the rotation is already unstable**, which is the case that needs
 * diagnosing — a rotation that runs the same way every iteration has no threshold worth
 * finding, and charging every search for one would be a cost with no answer attached.
 *
 * Twenty iterations rather than a hundred: the question at each rung is "does the burst count
 * vary *at all*", and a non-zero `sd` shows up long before a mean settles. `probe:energy`
 * measured the boundary at 30 % on the committed gated rotation with forty, and the rungs
 * either side of it were unambiguous.
 */
const ENERGY_LADDER = [0.2, 0.3, 0.45, 0.6, 0.8, 1.0] as const;

/**
 * Iterations per rung.
 *
 * **Raised from 20 because the ladder was measuring its own noise.** On the owner's Furina the
 * 20-iteration sweep came back *non-monotonic* — 157,761 DPS at 0.45 ER against 154,314 at
 * 0.60, with the burst count falling 2.8 → 2.5 for more energy, which cannot happen. The whole
 * signal above 0.30 ER is +3.7 %, so 2.2 % of noise was over half of it.
 *
 * `AGGREGATE_RUNS = 100` is the calibrated figure and `CLAUDE.md` records the mean moving only
 * 0.3 % between 25 and 100 iterations, so the aggregate is not where precision was missing.
 * 60 is chosen against the cost: a rung of the owner's 90-second rotation is ~2.3 s at 20, so
 * the ladder goes from ~14 s to ~42 s inside a search that already takes minutes — and
 * `dpsAt`'s running maximum handles whatever noise is left rather than trusting it.
 */
const ENERGY_LADDER_RUNS = 60;

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
 * Give every recipe the one energy measurement the run made.
 *
 * **The measurement is taken on the set-free target only**, and deliberately: the aggregate is
 * offered to the run corpus, a `sim_run` row is keyed by context — character, weapon, team,
 * rotation, target — and *not* by artifacts, so running one per set would file set-specific
 * numbers under a set-independent key. One run answers for the whole search.
 *
 * But it was also *stored* on that target only, and that target is the baseline — the recipe
 * `unscoredLabels` exists to say nobody ranks on. Every 4-piece recipe, which is what actually
 * scores the ranking, came back with `energySweep` undefined and `calibratedEnergyDps`
 * undefined, so `energyRatio` returned 1 for every candidate and `liveQuantitiesFor` saw a flat
 * ladder. The measurement was correct, complete, and attached to the one recipe nothing reads.
 *
 * That is the second half of *"no ER sands were picked in any of the top optimizations"*: the
 * first half was the Pareto layer not knowing ER was live, and fixing that alone changes
 * nothing while the ladder never reaches the recipe being scored.
 *
 * Sharing is sound for the same reason taking one measurement is: the ladder varies the
 * *subject's ER on the calibration's own stats line* and reads team DPS. Nothing in it depends
 * on which artifact set the search is currently walking.
 *
 * A donor is whichever recipe carries a ladder — normally the set-free one. None means the
 * rotation is not energy-constrained (no ladder was swept), and nothing is stamped.
 */
export function shareEnergyMeasurement(recipes: readonly Recipe[]): void {
  // **Grouped by weapon, because a ladder is a property of one.** Sharing across *sets* is
  // sound: the sweep varies the subject's ER on the calibration's own stats line, and nothing
  // in it depends on which set the search is walking. Sharing across *weapons* is not, and
  // Favonius is the sharpest case available — it makes particles on crit, so its energy curve
  // is genuinely different from a stat-stick's. One donor for the run would price the weapon
  // the owner asked about using another weapon's energy behaviour.
  //
  // `weaponKey` is empty for a search over a single weapon, which is every search until the
  // weapon picker is opened — so this groups into one bucket and behaves exactly as before.
  const byWeapon = new Map<string, Recipe[]>();
  for (const recipe of recipes) {
    const key = recipe.meta.weaponKey ?? '';
    const bucket = byWeapon.get(key);
    if (bucket) bucket.push(recipe);
    else byWeapon.set(key, [recipe]);
  }
  for (const bucket of byWeapon.values()) shareWithinOneWeapon(bucket);
}


/** The original rule, now scoped to the weapon whose ladder it is. */
function shareWithinOneWeapon(recipes: readonly Recipe[]): void {
  const donor = recipes.find((r) => r.meta.energySweep?.length);
  if (!donor) return;
  for (const recipe of recipes) {
    if (recipe === donor) continue;
    recipe.meta.energySweep = donor.meta.energySweep;
    recipe.meta.calibratedEnergyDps = donor.meta.calibratedEnergyDps;
    recipe.meta.calibratedEnergyRecharge = donor.meta.calibratedEnergyRecharge;
    // The warning is a property of the team and the rotation, so it belongs on all of them —
    // `caveats.energyCost` already reports it once for the run rather than once per set.
    recipe.meta.energyCost ??= donor.meta.energyCost;
  }
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
    /**
     * A weapon to calibrate with instead of the build's own, as a catalogue id.
     *
     * **A weapon is a recipe, not a re-score.** Different base ATK, different passive — so
     * every set state has to be calibrated again for it, and `context_key` on the server has
     * always included the weapon, which is what makes each weapon's cache entry its own.
     * `undefined` calibrates the build as it stands, which is every search that is not
     * comparing weapons.
     */
    weaponId?: string,
    /**
     * Hold the simulation when a burst cannot be paid for, rather than skipping it.
     *
     * **The two models disagree by a factor of six**, so a recipe calibrated under one is not
     * the other's — see the cache key below, and #240 for what happens when a client-side
     * option never reaches it.
     */
    waitForEnergy = false,
    /**
     * Checked between targets. A target is one gcsim calibration (~3 s cold), so a cancel lands
     * within one — without it, Cancel and leaving the page did nothing until every set had run.
     */
    shouldCancel?: () => boolean,
  ): Promise<CalibrationResult> {
    const byFourPieceSet = new Map<number, Recipe>();
    const byPair = new Map<string, Recipe>();
    let noFourPiece: Recipe | null = null;
    /** Every recipe this run produced, so the energy measurement can reach all of them. */
    const calibrated: Recipe[] = [];
    const caveats: CalibrationCaveats = {
      unstable: [], staleConversions: [], fromCache: [], unscoredLabels: [],
      energyCost: null, energySweep: null,
    };

    onProgress({ done: 0, total: targets.length, current: '', loading: true });
    const mod = await this.loadModule();

    // **What the cache is actually keyed on.** `rotationId` is an id: editing a rotation's
    // steps, or changing who is on its team, leaves it unchanged, and the recipe for the old
    // rotation stayed a hit. This hash covers the steps, the team, the build's level, weapon
    // and talents, the target and the pin.
    //
    // A failure here disables the cache for this run rather than falling back to the id.
    // Recalibrating costs seconds; serving a recipe for a rotation the user has since changed
    // costs them a wrong answer they have no way to spot.
    let context: string | null;
    try {
      context = (await this.rotations.contextKey(rotationId, buildId)).context_key;
    } catch {
      context = null;
    }

    for (const [index, target] of targets.entries()) {
      if (shouldCancel?.()) throw new CalibrationCancelled();
      onProgress({ done: index, total: targets.length, current: target.label, loading: false });

      const configs = await this.configs(
        buildId, rotationId, target.artifactSetIds, weaponId,
      );
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
        // Sorted, so the same probe always produces the same key regardless of how the
        // server happened to order the map.
        probe: Object.entries(configs.probe_deltas ?? {})
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([stat, delta]) => `${stat}=${delta}`)
          .join(','),
        // **The weapon is part of what makes this simulation what it is**, and the server's
        // own `context_key` has always said so — but this client asks for that key once, per
        // build, before the weapon loop. Without the weapon here every weapon shares one cache
        // entry, so the second reads the first's recipe and the ranking comes back *flat*:
        // every candidate scoring the worn weapon's number, which reads as "these weapons are
        // equivalent" rather than as a bug.
        //
        // Measured before the fix, on a real two-weapon run: Azurelight and Haran Geppaku
        // Futsu both 1,376,712.1, to the decimal.
        // **#240's lesson, applied before it bites.** A client-side option that never
        // reaches the cache key produces two identical answers, which reads as the
        // models agreeing rather than as the option doing nothing.
        context: `${context ?? ''}${weaponId ? `|weapon=${weaponId}` : ''}`
          + (waitForEnergy ? '|waiting' : ''),
      };

      // No context hash means no cache: see above. `readRecipe` is skipped rather than given
      // a key that cannot tell two rotations apart.
      let recipe = context === null ? null : readRecipe(this.store, key);
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
        // **Local cache, then the corpus, then simulate.** `readRecipe` above answers in
        // microseconds and is checked first; this is a request, so it is checked second; and
        // gcsim is the last resort. A corpus hit is what makes the run store cross-device and
        // cross-user rather than a write-only log.
        const corpusRaw = wantsAggregate
          ? await this.fromCorpus(buildId, rotationId, configs.energy_recharge)
          : null;
        const aggregate = !wantsAggregate
          ? null
          : corpusRaw !== null
            // Read with `readResult`, the same function a fresh run uses. A second parser
            // would eventually disagree with it about what a cached run scored.
            ? { iterations: AGGREGATE_RUNS, ...readResult(corpusRaw) }
            : runConfig(mod, configs.baseline, AGGREGATE_RUNS);
        // **The same run with energy free, because a gated rotation hides the shortfall.**
        // The compiler gates every step on `.ready`, so gcsim never *attempts* an unaffordable
        // burst and records no `insufficient_energy` — measured at 0 for all four characters
        // on a team plainly starved, where the ungated community config reported 67.1 s.
        // Comparing against `ignore_burst_energy` is what gcsim's own substat optimizer does,
        // and it is the only way a gated rotation can say what energy costs.
        const freeEnergy = aggregate
          ? runConfig(mod, withFreeEnergy(configs.baseline), AGGREGATE_RUNS)
          : null;
        // Offered to the cache, never awaited for correctness. `DECISIONS.md` §25: the
        // corpus accumulates from real searches, and a user whose search finished must not be
        // told otherwise because a cache write was refused. **Skipped on a corpus hit** —
        // writing back what was just read would be a no-op request per search.
        if (aggregate !== null && corpusRaw === null) {
          void this.cache(buildId, rotationId, configs.energy_recharge, aggregate.raw);
        }

        const instances = aggregate ? instancesFrom(aggregate.raw, configs.characters) : {};

        // What energy costs, measured rather than inferred — and the trigger for the ladder
        // below.
        //
        // **Display names, not gcsim keys.** The message reaches a person, and `furina` beside
        // `kaedeharakazuha` is the raw-key ugliness this repo keeps fixing one field at a time.
        // The list is still positional against gcsim's own order, which is what indexes every
        // per-character array.
        const keys = configs.characters ?? [];
        const party = configs.character_names?.length ? configs.character_names : keys;
        const cost = aggregate && freeEnergy
          ? energyCost(aggregate.raw, freeEnergy.raw, party, configs.burst_energy_costs ?? [])
          : null;
        // Only the optimized character's own shortfall triggers their ladder — see
        // `subjectIsShort`. Index 0 is the subject of the config.
        const subjectShort = subjectIsShort(cost, party[0] ?? '');
        const { burst, sweep } = this.energySweep(mod, configs, instances, subjectShort);

        // Names for `RecipeHit.owner`, so a result can show the damage share per character.
        // Set before `calibrate` writes the recipe to the cache, or a cache hit comes back
        // with indices and no names — the shape `meta.unstable` was added to avoid.
        const named = (recipe: Recipe) => {
          // `?? []` because a server that does not publish the order is a recipe with indices
          // and no names, which `damageShare` renders as "character 2" — worse than names and
          // far better than a throw inside a calibration the user is waiting on.
          // Display names when the server sends them, gcsim keys when it does not: a raw
          // `kaedeharakazuha` reads badly, and a wrong name reads as right.
          recipe.meta.characters = [
            ...(configs.character_names?.length ? configs.character_names : configs.characters ?? []),
          ];
          // **Paired against gcsim's own key order, not the display names.** `failed_actions`
          // is indexed positionally by `configs.characters`; passing the display list would
          // still line up today and would blame the wrong character the moment the two orders
          // diverge, silently and plausibly. So the keys index it, and the names label it.
          //
          // **Teammates only, and that is a correctness limit rather than a choice.** The
          // aggregate runs `configs.baseline`, which strips the optimized character's
          // artifacts down to `er=0` — so *their* wait in this run is an artefact of the
          // calibration, not their build. Teammates carry their real gear, so theirs is real.
          //
          // The optimized character's own energy is already covered, properly, by
          // `minimumEnergyRecharge` and `energyShortfall`, which the ER sweep measures against
          // their actual ER.
          //
          // **Every character now, and the optimized one included.** The seconds-based figure
          // had to skip them, because the baseline strips their artifacts to `er=0` and their
          // wait was an artefact. A burst *count* does not care: the baseline is the same
          // config in both runs, so the difference is energy and nothing else.
          recipe.meta.energyCost = cost;
          // **The ladder rides with the recipe**, because scoring needs it and a cache hit
          // must not come back without it — the same argument `meta.unstable` makes.
          recipe.meta.energySweep = sweep;
          // The calibration's own DPS, which every rung is measured against.
          recipe.meta.calibratedEnergyDps = aggregate?.dps?.mean ?? undefined;
          // The ER the ladder's own baseline rung sits at — see `calibratedEnergyRecharge`.
          recipe.meta.calibratedEnergyRecharge = configs.energy_recharge;
          // **On the recipe, so the energy ladder knows whose it is.** Grouping in
          // `shareEnergyMeasurement` reads this; without it every weapon would be
          // handed the first one's sweep.
          recipe.meta.weaponKey = weaponId;
          return recipe;
        };

        const calibrated = calibrate(
          {
            baseline: mod.sample(configs.baseline, SEED),
            probe: mod.sample(configs.probe, SEED),
            instances,
            energySweep: sweep,
          },
          // **Not `[]` for a 4-piece target.** Equipping a set to calibrate also applies its
          // 2-piece, so a recipe that does not name it lets the search add that tier again —
          // the exact double-count `RESEARCH_recipe_risks.md` §2 records. This passed `null`
          // unconditionally and was harmless only while no set bonuses reached the search at
          // all; B.1 made them reach it.
          { setIds: target.setIds, burstAbility: burst ?? undefined },
        );
        recipe = named(calibrated.recipe);
        if (context !== null) writeRecipe(this.store, key, recipe);
      }

      // A target with no set ids is the baseline: calibrated, never searched. See
      // `unscoredLabels`.
      if (target.setIds.length === 0) caveats.unscoredLabels.push(target.label);

      // **Read off the recipe, so a cache hit reports it too.** This used to sit inside the
      // fresh-calibration branch above, so the second search over the same build served every
      // recipe from storage, found no instability, and the page called the ranking sound —
      // permanently, because the cache is persistent.
      if (recipe.meta.unstable.length > 0) {
        caveats.unstable.push({ label: target.label, abilities: recipe.meta.unstable });
      }
      // Reported once for the run, not once per target: the wait is a property of the team and
      // the rotation, and repeating it per artifact set would read as several problems.
      if (recipe.meta.energySweep?.length && !caveats.energySweep) {
        caveats.energySweep = recipe.meta.energySweep;
      }
      if (recipe.meta.energyCost?.characters.length && !caveats.energyCost) {
        caveats.energyCost = recipe.meta.energyCost;
      }

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
      calibrated.push(recipe);
    }

    shareEnergyMeasurement(calibrated);

    onProgress({ done: targets.length, total: targets.length, current: '', loading: false });
    return { byFourPieceSet, byPair, noFourPiece, caveats };
  }

  /** Whether this build can perform the rotation these recipes describe. */
  shortfall(recipe: Recipe, buildEnergyRecharge: number): EnergyShortfall | null {
    return energyShortfall(buildEnergyRecharge, recipe.meta.minimumEnergyRecharge);
  }

  /**
   * Ask the corpus whether this run already exists, before simulating it.
   *
   * **The read half of the corpus, which was built and had no caller.** `POST /sim-runs` sat
   * in that state until #183; `GET /sim-runs/retrieve` — endpoint, ER bucketing, neighbour
   * rule and stated-reason outcome — was still in it. Calling it is what makes the corpus
   * **cross-device and cross-user** instead of a write-only log: two people with the same
   * character, weapon, talents, rotation and gcsim pin produce the same calibration, and
   * `context_key` already says so.
   *
   * It does **not** replace `recipe-cache.ts`. That one is local and answers in microseconds;
   * this is a request. The order is local first, server second, simulate last — and until
   * the hit rate is measured (`DESIGN_account_tracking.md` OQ-A3) the local cache is a
   * correctness-neutral optimisation that stays.
   *
   * Returns `null` for anything that is not a usable hit, including a failure: a corpus that
   * cannot be read is a slower search, not a failed one.
   */
  private async fromCorpus(
    buildId: string,
    rotationId: string,
    energyRecharge: number,
  ): Promise<unknown | null> {
    try {
      const key = await this.rotations.contextKey(rotationId, buildId);
      return await this.simRuns.retrieve(key.context_key, energyRecharge);
    } catch {
      return null;
    }
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

  /**
   * Walk an ER ladder and report what the burst did at each rung — §8/§9.
   *
   * **Only when the rotation is already unstable, and only when a *burst* is what varied.**
   * `probe:energy` measured the mechanism: the compiler gates every action on `.ready`, gcsim's
   * particle generation carries RNG, so an energy-marginal burst fires on some iterations and
   * not others. A rotation whose counts are steady has no threshold to find, and one whose
   * instability is somewhere other than a burst is not an energy problem — sweeping either
   * would spend gcsim runs to produce a number about nothing.
   *
   * Returns the burst's key as well, because `calibrate` needs to know which ability's count
   * defines "performs as calibrated" and `stabilityFrom` is the only thing that knows which
   * one moved.
   */
  private energySweep(
    mod: GcsimModule,
    configs: { baseline: string; energy_recharge: number; characters: string[] },
    instances: Readonly<Record<string, { mean: number; sd: number }>>,
    shortOfEnergy = false,
  ): { burst: string | null; sweep: EnergyObservation[] | undefined } {
    // **Unstable *or* short.** The original trigger was instability alone — a burst count that
    // varies between iterations. That misses the commonest case entirely: the owner's Furina
    // casts exactly 2 bursts every single iteration where free energy casts 5. Perfectly
    // stable, perfectly starved, and `minimumEnergyRecharge` was null for precisely the builds
    // that need it.
    //
    // `shortOfEnergy` comes from the free-energy counterfactual, which detects the condition
    // directly rather than through its symptom.
    const { unstable } = stabilityFrom(instances);
    const burst = unstable.find((name) => name.endsWith('burst'))
      ?? (shortOfEnergy ? Object.keys(instances).find((name) => name.endsWith('burst')) : undefined)
      ?? null;
    if (burst === null) return { burst: null, sweep: undefined };

    const sweep: EnergyObservation[] = [];
    // **The calibration's own ER is a rung.** Without it the baseline is floored onto whatever
    // rung sits below — 0.279 onto 0.20 for the owner's Furina — so `energyRatio`'s denominator
    // described a build with 8 % less ER than the one being optimized, and every candidate on
    // the same rung was compared against it rather than against itself.
    const rungs = [...new Set([...ENERGY_LADDER, configs.energy_recharge])]
      .sort((a, b) => a - b);
    for (const energyRecharge of rungs) {
      // The same config with a different ER on the calibration's own stats line — the shape
      // `_config`'s `extra` already produces server-side, applied here because a sweep is a
      // client decision made after seeing the aggregate.
      const text = configs.baseline.replace(
        `add stats er=${configs.energy_recharge}`,
        `add stats er=${energyRecharge}`,
      );
      if (text === configs.baseline && energyRecharge !== configs.energy_recharge) {
        // The substitution found nothing, so every rung would be the same run. Reported by
        // returning no sweep rather than by six identical observations, which would look like
        // a measurement and be one config repeated.
        return { burst, sweep: undefined };
      }
      let counts: Record<string, { mean: number; sd: number }>;
      let rungDps: number | null;
      try {
        const run = runConfig(mod, text, ENERGY_LADDER_RUNS);
        counts = instancesFrom(run.raw, configs.characters);
        // **What the rung is actually for.** The burst *count* is not what ER buys: the owner's
        // Furina is 98.3 % skill damage and 1.5 % burst, because her burst buffs the team and
        // removes the delay rather than hitting hard. DPS at each rung carries all of that.
        rungDps = run.dps?.mean ?? null;
      } catch {
        // A rung gcsim refuses is a gap in the ladder, not a failed search.
        continue;
      }
      const at = counts[burst];
      if (at) {
        sweep.push({
          energyRecharge,
          dps: rungDps ?? undefined,
          burstInstances: at.mean,
          standardDeviation: at.sd,
        });
      }
    }
    return { burst, sweep: sweep.length > 0 ? sweep : undefined };
  }

  private async configs(
    buildId: string,
    rotationId: string,
    artifactSetIds: readonly string[],
    weaponId?: string,
    waitForEnergy = false,
  ) {
    const { data, error } = await this.api.POST('/api/v1/builds/{build_id}/calibrate', {
      params: { path: { build_id: buildId } },
      body: {
        rotation_id: rotationId,
        // Omitted rather than sent as null when there is none, so a search over the
        // build's own weapon puts nothing new in the request it has always sent.
        ...(weaponId ? { weapon_id: weaponId } : {}),
        // Always stated rather than omitted when false: the request says which of the two
        // energy models produced the recipe, and a number whose meaning depends on an
        // unstated assumption is the shape this repo refuses.
        wait_for_energy: waitForEnergy,
        // One set is a 4-piece; two are a 2+2, which the endpoint refuses to combine with a
        // 4-piece because five slots cannot hold both.
        artifact_set_id: artifactSetIds.length === 1 ? artifactSetIds[0] : null,
        two_piece_set_ids: artifactSetIds.length === 2 ? [...artifactSetIds] : [],
        // Stated rather than defaulted. **+30 % is R.2a's measurement** — the lowest ER at
        // which the sample rotation reaches its calibrated burst count with `sd == 0`; a
        // zero-ER calibration lands one burst short. The probe moves exactly one stat,
        // because `resolveConversions` cannot separate two that moved together.
        energy_recharge: 0.30,
        // **All three, by different amounts.** This moved only `def%` until 2026-08-31, on
        // the reasoning that the matcher cannot separate two stats that move together — true
        // of two moving by the *same factor*, not of two moving at all. A DEF-only probe can
        // resolve only DEF-derived conversions, so on an ATK scaler every flat term stayed
        // frozen and was reported as "a conversion no probe could resolve".
        probe_deltas: { 'atk%': 0.5, 'hp%': 0.3, 'def%': 0.7 },
        iterations: 100,
      },
    });
    if (error) throw error;
    return data as {
      baseline: string; probe: string; energy_recharge: number; characters: string[];
      // Echoed by the endpoint so the cache key can name what the recipe was probed with.
      probe_deltas: Record<string, number>;
      /** The same characters as `characters`, as a player reads them. */
      character_names?: string[];
      /**
       * Positional against `characters`, `null` where the burst costs no energy at all.
       *
       * Skirk's burst spends Serpent's Subtlety, and the free-energy counterfactual moves the
       * whole team's timing, so her burst count changes for reasons that are not hers. Without
       * this the warning named her as short of energy.
       */
      burst_energy_costs?: (number | null)[];
    };
  }
}

/** Re-exported so a caller can drive gcsim without importing two modules. */
export { runConfig };
