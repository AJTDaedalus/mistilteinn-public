/**
 * Driving gcsim's browser build — the second tier above the Chunk F damage chain.
 *
 * `docs/DESIGN_weapon_passives.md`. The chain scores an artifact search; **gcsim answers what
 * a build actually does over a rotation**, and it is the only thing here that knows weapon
 * passives: 242 of 260 weapons carry one and 5 are expressible in the chain, so a comparison
 * without gcsim ranks a stat-stick above the weapon whose passive is the entire reason anyone
 * equips it.
 *
 * `RESEARCH_gcsim_embed.md` §6 keeps this **out of the optimizer's inner loop** — 9,000
 * combinations at ~430× each. Nothing here should be called from a search.
 *
 * ## Two things about gcsim's API that read backwards
 *
 * Both cost real time during planning, and both are why `configError` and `run` exist rather
 * than callers driving `globalThis` themselves:
 *
 * 1. **`validateConfig` returns the parsed config on success.** Failure is signalled by
 *    `"error"` appearing *inside* the returned string. A truthy check inverts the meaning and
 *    rejects every valid config.
 * 2. **`iteration=N` in the config does not make `simulate()` run N times.** `simulate()` is
 *    one iteration; the caller loops and `aggregate()` accumulates. Timing a config across
 *    `iteration=1..100` therefore shows a flat ~210 ms and looks like a free lunch — it is
 *    measuring one iteration every time.
 */

/** The subset of gcsim's wasm exports this module drives. They land on `globalThis`. */
export interface GcsimModule {
  validateConfig(config: string): unknown;
  /**
   * A full per-frame log for one seed, as JSON.
   *
   * This is what a **recipe** is built from — `calc` events carry every term of the damage
   * calculation, which is why `docs/RESEARCH_gcsim_calibration.md` could prove the
   * decomposition exact rather than fitting it.
   */
  sample(config: string, seed: string): string;
  initializeAggregator(config: string): void;
  initializeWorker(config: string): void;
  simulate(): unknown;
  aggregate(result: unknown): void;
  flush(): string;
}

/** What one run reports. `dps` is null when the result carries no DPS block. */
export interface GcsimRun {
  iterations: number;
  totalDamage: number | null;
  dps: { mean: number; sd: number } | null;
  /** gcsim's own result object, unmodified — so a caller can read what this does not model. */
  raw: unknown;
}

/**
 * gcsim's complaint about a config, or `null` if it accepted it.
 *
 * **The check is for `"error"` inside the returned string, not for truthiness.** On success
 * `validateConfig` returns the *parsed config*, which is a large truthy object; treating that
 * as a failure rejects everything. `scripts/verify-gcsim-wasm.mjs` has always done it this
 * way and reading it first would have saved the discovery.
 */
export function configError(validated: unknown): string | null {
  if (typeof validated === 'string' && validated.includes('"error"')) return validated;
  return null;
}

/**
 * gcsim's complaint about a *run*, or `null` if it produced a result.
 *
 * Separate from `configError` because they fail differently: a rejected config comes back
 * from `validateConfig`, while a failed **run** comes back as the return value of
 * `simulate()` — a string where a `Uint8Array` was expected.
 */
export function simulationError(simulated: unknown): string | null {
  if (typeof simulated === 'string') return simulated;
  return null;
}

/**
 * Run one config for `iterations` Monte Carlo iterations.
 *
 * **The loop is here because gcsim does not loop.** `simulate()` produces one iteration and
 * `aggregate()` accumulates it; `iteration=N` in the config text does not drive this.
 *
 * `onProgress` exists because this is slow enough to need it: measured against the committed
 * browser build, a 100-iteration 90-second rotation is **7.84 s single-threaded**, so a
 * 59-candidate weapon comparison is minutes rather than seconds. **This is a job with
 * progress, never a request that blocks.**
 */
export function run(
  mod: GcsimModule,
  config: string,
  iterations: number,
  onProgress?: (done: number, total: number) => void,
): GcsimRun {
  if (!Number.isInteger(iterations) || iterations < 1) {
    throw new Error(`iterations must be a positive integer, got ${iterations}`);
  }
  const rejected = configError(mod.validateConfig(config));
  if (rejected !== null) throw new Error(`gcsim rejected the config: ${rejected}`);

  mod.initializeAggregator(config);
  mod.initializeWorker(config);
  for (let i = 0; i < iterations; i++) {
    const simulated = mod.simulate();
    // **`simulate()` reports failure by returning a string, not by throwing.** On success it
    // returns a `Uint8Array` of MessagePack. Passing the error string to `aggregate()`
    // instead — which the first version of this did — aggregates nothing, and `flush()` then
    // fails with `index out of range [0] with length 0`. The real message is discarded and
    // replaced by one that describes the empty aggregate rather than the cause.
    //
    // That cost real time: it hid `"requested next char X is not active and next action is
    // not swap"`, which is the reason multi-character rotations do not run in this build.
    const failure = simulationError(simulated);
    if (failure !== null) throw new Error(`gcsim failed to simulate: ${failure}`);
    mod.aggregate(simulated);
    onProgress?.(i + 1, iterations);
  }
  const flushed = JSON.parse(mod.flush()) as unknown;
  const flushFailure = (flushed as { error?: unknown })?.error;
  if (typeof flushFailure === 'string') {
    throw new Error(`gcsim failed to aggregate: ${flushFailure}`);
  }
  return { iterations, ...readResult(flushed) };
}

/**
 * Pull the two numbers a comparison needs out of gcsim's result.
 *
 * **Null rather than zero when a block is absent.** Zero damage is a real, meaningful answer —
 * a rotation that never connects — so collapsing "gcsim did not report this" into it would
 * hide a shape change in the result behind a plausible number, which is exactly how a ranking
 * comes out flat and looks deliberate.
 */
function readResult(out: unknown): Omit<GcsimRun, 'iterations'> {
  const stats = (out as { stats?: Record<string, unknown> })?.stats;
  const total = stats?.['total_damage'] as { mean?: number } | undefined;
  const dps = stats?.['dps'] as { mean?: number; sd?: number } | undefined;
  return {
    totalDamage: typeof total?.mean === 'number' ? total.mean : null,
    dps:
      typeof dps?.mean === 'number' && typeof dps?.sd === 'number'
        ? { mean: dps.mean, sd: dps.sd }
        : null,
    raw: out,
  };
}
