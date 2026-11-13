/**
 * What every caller of gcsim talks to: an **asynchronous** runner, so the simulator can live in
 * a Web Worker that a deadline is allowed to kill.
 *
 * ## Why the simulator moved off the main thread
 *
 * gcsim has **no watchdog** (`/root/CLAUDE.md` §gcsim): an action that can never become ready
 * — a burst its character can never fund, with no `.ready` gate — makes `actionReadyCheckPhase`
 * retry the same frame forever. Up to v2.47.2 that at least ended, because a per-frame stats
 * slice grew until the tab was killed at ~2.4 GB. **From v2.50.0 it does not end at all**: gcsim
 * `e4fe22e5b` (*Fix some stats logging OnTick*) stopped the growth, so the same config spins at
 * a flat ~23 MB indefinitely (`docs/RESEARCH_gcsim_repin_2026_11.md` §6, open question 1).
 *
 * A `simulate()` that never returns cannot be interrupted on the thread that called it — no
 * timer fires, no check between iterations is reached, and the page is frozen while it spins.
 * The only thing that can stop it is `Worker.terminate()` from another thread. So gcsim runs in
 * `gcsim.worker.ts`, `gcsim-worker-runner.ts` holds the deadline, and this interface is the
 * shape both it and the synchronous adapter below present.
 */

import { configError, run, type GcsimModule, type GcsimRun } from './gcsim';

export interface GcsimRunner {
  /** gcsim's complaint about `config`, or `null` if it accepted it. See `configError`. */
  validate(config: string): Promise<string | null>;
  /**
   * A full per-frame log for one seed, as gcsim's JSON string. Failure inside gcsim comes back
   * as the string `sampleError` reads, exactly as it did from the module directly.
   */
  sample(config: string, seed: string): Promise<string>;
  /** `run()` from `gcsim.ts`, with the same contract, the same result and the same progress. */
  run(
    config: string,
    iterations: number,
    onProgress?: (done: number, total: number) => void,
  ): Promise<GcsimRun>;
}

/**
 * A simulation that did not finish inside its deadline, and was killed.
 *
 * **Its own class, so a caller can tell a hang from a refusal.** A config gcsim rejects is a
 * fact about the config; a timeout is a fact about *this* run — and the energy ladder, which
 * treats a refused rung as a gap, must not treat a hang as one, or a search pays the deadline
 * once per rung and then reports a ladder with holes in it.
 */
export class GcsimTimeoutError extends Error {
  // A plain field rather than a parameter property: the Node verify scripts import this file
  // with type stripping only, which refuses parameter properties.
  readonly seconds: number;

  constructor(seconds: number) {
    super(
      `The simulation did not finish within ${seconds} s and was stopped. This usually means ` +
        `an action in the rotation can never become ready — most often a burst its ` +
        `character can never fund — so gcsim waits on it forever. Check the rotation's ` +
        `bursts and energy, then try again.`,
    );
    this.name = 'GcsimTimeoutError';
    this.seconds = seconds;
  }
}

/**
 * How long a job may take before it is treated as a hang, in milliseconds.
 *
 * **Scaled by the iteration count**, because one fixed number is either too short for a
 * 100-iteration aggregate on a slow laptop or so long that a 1-iteration sample sits frozen for
 * minutes before saying anything.
 *
 * ## The derivation
 *
 * Measured 2026-11-13 on the committed v2.50.0 browser build (`b107b5dc`), single-threaded
 * wasm in Node 24 — the same V8 the browser runs — on a 12-core host:
 *
 * | what | per iteration |
 * |---|---|
 * | every config in the gcsim database corpus gcsim accepts (500 of 501, `backend/var/gcsim_corpus`), host loaded to ~18 | median **25.6 ms**, p95 55.5, p99 76.7, worst **125.2 ms** |
 * | that worst config (Flins team, 1000-iteration share), host quiet | **75.0 ms** |
 * | `skirk_team` fixture, host quiet (the re-pin research measured 17.3) | 15.8 ms |
 *
 * So a 100-iteration run of the slowest real config is ~7.5 s quiet and ~12.5 s on a busy
 * machine. The old pin's 7.84 s for a 100-iteration rotation (`gcsim.ts`) was a *typical*
 * rotation at 2.4–4.2× today's cost; it is not the worst case any more and is not used here.
 *
 * The budget is **1 s per iteration — 13× the worst config quiet, 8× it loaded — plus a 15 s
 * floor** for validation, `initializeWorker`, and a slow tab. 100 iterations (the aggregate and
 * Calculate) get 115 s; 60 (an energy-ladder rung) get 75 s. A hang is not slow, it is infinite,
 * so headroom costs only the time it takes to notice one — while a false timeout on a real
 * search on a slow laptop is the worse failure by far.
 */
export const PER_ITERATION_BUDGET_MS = 1_000;
export const DEADLINE_FLOOR_MS = 15_000;

/**
 * `sample()` is one iteration with **full per-frame logging**, and that logging dominates:
 * measured on the same host, quiet, the worst corpus config samples in **3.78 s** (50× its
 * plain iteration) and `skirk_team` in 0.98 s. Forty iteration-equivalents gives a sample 55 s,
 * ~15× the worst measured.
 */
export const SAMPLE_ITERATION_EQUIVALENT = 40;

export function deadlineMs(iterations: number): number {
  return DEADLINE_FLOOR_MS + PER_ITERATION_BUDGET_MS * Math.max(0, iterations);
}

/**
 * A runner over a module on **this** thread — no deadline, because none is possible here.
 *
 * For the unit specs (which stub gcsim and have no Worker in jsdom) and the Node verify
 * scripts. The app never uses it: `gcsimRunner()` in `gcsim-worker-runner.ts` is the one that
 * can stop a hang.
 */
export function inlineRunner(mod: GcsimModule): GcsimRunner {
  return {
    validate: async (config) => configError(mod.validateConfig(config)),
    sample: async (config, seed) => mod.sample(config, seed),
    run: async (config, iterations, onProgress) => run(mod, config, iterations, onProgress),
  };
}
