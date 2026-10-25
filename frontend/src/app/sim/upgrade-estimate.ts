/**
 * `P(a fresh domain 5-star, levelled to +20, beats what this slot wears)` — exactly.
 *
 * `docs/TASKS_upgrade_estimator.md` Task 6; `docs/DESIGN_upgrade_estimator.md` §5. Joins the
 * fresh-drop prior (`fresh-drop.ts`) to an evaluator the caller owns — in the app, the build's
 * recipe with the candidate in one slot and the other four unchanged.
 *
 * ## Why exact, and why that is affordable
 *
 * The probabilities this exists for are small: a good piece is often beaten by one drop in
 * thousands or tens of thousands. A Gaussian's tail at 10⁻⁴ is a statement about the normal
 * distribution, not about artifacts, and a Monte Carlo cannot see it at all. Brute force is
 * ~10⁷ evaluations per slot. Three reductions make it interactive, **each exact**:
 *
 * 1. **Dead stats collapse.** A substat the recipe never reads (`liveQuantitiesFor`) cannot
 *    change the damage, so it is not enumerated: it only decides how many rolls the live lines
 *    get. Cells whose live lines and live roll counts agree are merged before anything is
 *    evaluated — `{CR, CD, DEF, HP}` and `{CR, CD, DEF%, HP%}` are one question for an ATK
 *    scaler.
 * 2. **Branch and bound.** Damage is monotone non-decreasing in every substat (a spec checks
 *    it). So at each step of the enumeration, if every remaining line at its top total still
 *    cannot clear the bar, the branch contributes nothing; if every remaining line at its bottom
 *    total clears it, the branch contributes all of its mass. This is also how "no drop can beat
 *    this" is **proved** rather than estimated.
 * 3. **Binary search on the last line.** With the other lines fixed, damage is monotone in the
 *    last one, so the threshold is found in `log m` evaluations rather than `m`.
 *
 * ## The cache is the sensitivity analysis
 *
 * `P(beat | live lines and their roll counts)` does not depend on the substat **weights** — only
 * the cell probabilities do. So `BeatCache` is shared across calls, and re-running with each
 * weight nudged (DESIGN §10) costs a re-weighting, not a re-enumeration.
 */

import { type StatPool } from './artifact-score';
import { rollSplits, rollTotals } from './artifact-distribution';
import { freshDropCells, rollBudgets, LINES } from './fresh-drop';

/** The tables and the bar. Everything here is the same for every main stat of one slot. */
export interface SlotBeatInput {
  /** Kernel quantity → probability, for this slot. Sums to 1. */
  mainStatProbabilities: Readonly<Record<string, number>>;
  /** Kernel quantity → the main stat's 5-star +20 value. */
  mainStatValues: Readonly<Record<string, number>>;
  substatWeights: Readonly<Record<string, number>>;
  /** Kernel quantity → the four 5-star roll values, any order. */
  ladders: Readonly<Record<string, readonly number[]>>;
  fourLineShare: number;
  /** Quantities the evaluator reads. Anything else is a dead stat — reduction 1. */
  live: ReadonlySet<string>;
  /** Damage with this stat pool in the slot and the other four unchanged. Monotone. */
  evaluate: (piece: StatPool) => number;
  /** The damage to beat: the build as it stands, times `1 + θ`. A drop must exceed it. */
  threshold: number;
}

export interface MainStatBeat {
  main: string;
  pMain: number;
  /** `P(beat | this main stat)`. */
  pBeat: number;
}

export interface SlotBeat {
  /** `P(beat)` for a drop **in this slot**: `Σ P(main) · P(beat | main)`. */
  pBeat: number;
  byMain: MainStatBeat[];
  /** Evaluations spent, so the measurement in Task 1 can name its cost. */
  evaluations: number;
  /** Distinct (main, live lines, live roll counts) questions asked after merging. */
  questions: number;
}

/**
 * What a slot's enumeration learned that does not depend on the substat weights, shared across
 * calls. See the module docs.
 *
 * `answers` maps a question to `P(beat)`; `cellQuestions` maps a (main, four substats) cell to
 * the questions it contributes to and with what factor (roll budget × roll split). Neither
 * involves a weight, so a re-weighting reads both and evaluates nothing.
 */
export interface BeatCache {
  answers: Map<string, number>;
  cellQuestions: Map<string, { key: string; main: string; lines: [string, number][]; factor: number }[]>;
}

export function newBeatCache(): BeatCache {
  return { answers: new Map(), cellQuestions: new Map() };
}

interface LineTotals {
  quantity: string;
  /** Distinct totals, ascending. */
  values: number[];
  /** `suffix[i]` = P(total ≥ values[i]). `suffix[length]` = 0. */
  suffix: number[];
}

function totalsFor(ladder: readonly number[], rolls: number, quantity: string): LineTotals {
  const merged = new Map<number, number>();
  for (const { value, p } of rollTotals(ladder, rolls)) {
    // Rounded so float noise cannot split one total into two keys.
    const key = Math.round(value * 1e9) / 1e9;
    merged.set(key, (merged.get(key) ?? 0) + p);
  }
  const rows = [...merged].sort((a, b) => a[0] - b[0]);
  const suffix = new Array<number>(rows.length + 1).fill(0);
  for (let i = rows.length - 1; i >= 0; i -= 1) suffix[i] = suffix[i + 1] + rows[i][1];
  return { quantity, values: rows.map((r) => r[0]), suffix };
}

/**
 * `P(evaluate(base + lines) > threshold)` over every total the live lines can reach.
 *
 * Recursive over lines with the bounds of reduction 2 at every level, and a binary search on
 * the last line (reduction 3).
 */
function exactBeat(
  base: StatPool,
  lines: readonly LineTotals[],
  evaluate: (piece: StatPool) => number,
  threshold: number,
  counter: { evaluations: number },
): number {
  const stats: Record<string, number> = { ...base };
  const score = (): number => {
    counter.evaluations += 1;
    return evaluate(stats);
  };
  const setRest = (from: number, pick: 'min' | 'max'): void => {
    for (let j = from; j < lines.length; j += 1) {
      const values = lines[j].values;
      stats[lines[j].quantity] = (base[lines[j].quantity] ?? 0)
        + (pick === 'max' ? values[values.length - 1] : values[0]);
    }
  };

  const walk = (index: number): number => {
    setRest(index, 'max');
    if (score() <= threshold) return 0;
    setRest(index, 'min');
    if (score() > threshold) return 1;

    const line = lines[index];
    const own = base[line.quantity] ?? 0;
    if (index === lines.length - 1) {
      // Smallest total that clears the bar; everything at or above it does too.
      let lo = 0;
      let hi = line.values.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        stats[line.quantity] = own + line.values[mid];
        if (score() > threshold) hi = mid;
        else lo = mid + 1;
      }
      return line.suffix[lo];
    }
    let p = 0;
    for (let i = 0; i < line.values.length; i += 1) {
      const mass = line.suffix[i] - line.suffix[i + 1];
      stats[line.quantity] = own + line.values[i];
      p += mass * walk(index + 1);
    }
    return p;
  };

  if (!lines.length) {
    return score() > threshold ? 1 : 0;
  }
  return walk(0);
}

/**
 * How the live roll counts of `k` live lines fall, for each roll budget — merged over which of
 * the four positions are live, because the uniform split is exchangeable.
 *
 * `[counts, factor]`: each live line gets `1 + count` rolls, with probability `factor` summed
 * over both budgets. Computed once per `k` rather than per cell.
 */
function liveCountTable(k: number, fourLineShare: number): [number[], number][] {
  const merged = new Map<string, [number[], number]>();
  for (const budget of rollBudgets(fourLineShare)) {
    for (const split of rollSplits(budget.upgrades, LINES)) {
      const counts = split.counts.slice(0, k).map((c) => 1 + c);
      const key = counts.join(',');
      const found = merged.get(key);
      if (found) found[1] += budget.p * split.p;
      else merged.set(key, [counts, budget.p * split.p]);
    }
  }
  return [...merged.values()];
}

/**
 * The enumeration as a generator that yields after each unit of work, so a synchronous caller
 * runs it straight through and an asynchronous one can hand the thread back between units.
 *
 * A unit is one cell merged or one question answered. There are hundreds to thousands of each
 * per slot, which is what makes yielding here fine-grained — unlike `artifact-outcome.ts`,
 * whose four-line case is one branch that cannot yield inside itself.
 */
function* slotBeatSteps(input: SlotBeatInput, cache: BeatCache): Generator<void, SlotBeat> {
  const cells = freshDropCells(input.mainStatProbabilities, input.substatWeights);
  const counter = { evaluations: 0 };
  const tables = new Map<number, [number[], number][]>();
  const tableFor = (k: number) => {
    let found = tables.get(k);
    if (!found) {
      found = liveCountTable(k, input.fourLineShare);
      tables.set(k, found);
    }
    return found;
  };

  // Reduction 1: merge cells into questions keyed by main stat, live lines and live roll counts.
  const questions = new Map<string, { main: string; lines: [string, number][]; p: number }>();
  for (const cell of cells) {
    const cellKey = `${cell.main}#${cell.subs.join('|')}`;
    let contributions = cache.cellQuestions.get(cellKey);
    if (!contributions) {
      const liveLines = cell.subs.filter((q) => input.live.has(q));
      contributions = tableFor(liveLines.length).map(([counts, factor]) => {
        const lines = liveLines.map((q, i) => [q, counts[i]] as [string, number]);
        const key = `${cell.main}#${lines.map(([q, n]) => `${q}:${n}`).join(',')}`;
        return { key, main: cell.main, lines, factor };
      });
      cache.cellQuestions.set(cellKey, contributions);
    }
    for (const { key, main, lines, factor } of contributions) {
      const p = cell.p * factor;
      const found = questions.get(key);
      if (found) found.p += p;
      else questions.set(key, { main, lines, p });
    }
    yield;
  }

  const totalsCache = new Map<string, LineTotals>();
  const totals = (quantity: string, rolls: number): LineTotals => {
    const key = `${quantity}:${rolls}`;
    let found = totalsCache.get(key);
    if (!found) {
      const ladder = input.ladders[quantity];
      if (!ladder?.length) throw new Error(`no roll ladder for ${quantity}`);
      found = totalsFor(ladder, rolls, quantity);
      totalsCache.set(key, found);
    }
    return found;
  };

  const byMain = new Map<string, number>();
  for (const [key, question] of questions) {
    let answer = cache.answers.get(key);
    if (answer === undefined) {
      const value = input.mainStatValues[question.main];
      if (value === undefined) throw new Error(`no +20 value for main stat ${question.main}`);
      // A dead main stat is still carried: it costs nothing and keeps the pool honest.
      const base: StatPool = { [question.main]: value };
      answer = exactBeat(
        base,
        question.lines.map(([q, n]) => totals(q, n)),
        input.evaluate,
        input.threshold,
        counter,
      );
      cache.answers.set(key, answer);
      yield;
    }
    byMain.set(question.main, (byMain.get(question.main) ?? 0) + question.p * answer);
  }

  const rows: MainStatBeat[] = Object.entries(input.mainStatProbabilities)
    .filter(([, pMain]) => pMain > 0)
    .map(([main, pMain]) => ({ main, pMain, pBeat: (byMain.get(main) ?? 0) / pMain }));
  return {
    pBeat: rows.reduce((sum, row) => sum + row.pMain * row.pBeat, 0),
    byMain: rows,
    evaluations: counter.evaluations,
    questions: questions.size,
  };
}

/**
 * `P(beat)` for one slot, every main stat, every substat set, every roll.
 *
 * Pass the same `cache` to repeat the question with different weights — the threshold,
 * evaluator, ladders, live set and line share must be the same, and the cache key does not
 * check that, so a caller changing those passes a fresh cache.
 */
export function slotBeatProbability(
  input: SlotBeatInput,
  cache: BeatCache = newBeatCache(),
): SlotBeat {
  const steps = slotBeatSteps(input, cache);
  for (;;) {
    const next = steps.next();
    if (next.done) return next.value;
  }
}

/** Thrown when `shouldCancel` says stop. The caller paged away; nothing is wrong. */
export class EstimateCancelled extends Error {
  constructor() {
    super('the upgrade estimate was cancelled');
  }
}

/**
 * The same answer without holding the page: hands the thread back whenever `budgetMs` has been
 * spent, Genshin Optimizer's `uiYieldBudgetMs = 12` pattern (`artifact-outcome.ts`).
 */
export async function slotBeatProbabilityAsync(
  input: SlotBeatInput,
  cache: BeatCache = newBeatCache(),
  options: { shouldCancel?: () => boolean; budgetMs?: number } = {},
): Promise<SlotBeat> {
  const budget = options.budgetMs ?? 12;
  const steps = slotBeatSteps(input, cache);
  let started = performance.now();
  for (;;) {
    const next = steps.next();
    if (next.done) return next.value;
    if (performance.now() - started >= budget) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      if (options.shouldCancel?.()) throw new EstimateCancelled();
      started = performance.now();
    }
  }
}

/** How far `P(beat)` moves when each substat weight is nudged by ±1. DESIGN §10. */
export interface WeightSensitivity {
  low: number;
  high: number;
}

/**
 * Re-ask the slot's question with every weight nudged up and down by one, and report the range.
 *
 * The weights are a community table the owner's export disagrees with
 * (`RESEARCH_substat_draw_weights.md`), so a number derived from them should say how firm it is.
 * Twenty re-weightings over a shared cache: the enumeration is paid once.
 */
export function weightSensitivity(
  input: SlotBeatInput,
  cache: BeatCache,
): WeightSensitivity {
  let low = Infinity;
  let high = -Infinity;
  for (const quantity of Object.keys(input.substatWeights)) {
    for (const delta of [-1, 1]) {
      const weight = input.substatWeights[quantity] + delta;
      if (weight <= 0) continue;
      const nudged = { ...input, substatWeights: { ...input.substatWeights, [quantity]: weight } };
      const { pBeat } = slotBeatProbability(nudged, cache);
      low = Math.min(low, pBeat);
      high = Math.max(high, pBeat);
    }
  }
  return { low, high };
}

/** `weightSensitivity` without holding the page; each re-weighting yields as the estimate does. */
export async function weightSensitivityAsync(
  input: SlotBeatInput,
  cache: BeatCache,
  options: { shouldCancel?: () => boolean; budgetMs?: number } = {},
): Promise<WeightSensitivity> {
  let low = Infinity;
  let high = -Infinity;
  for (const quantity of Object.keys(input.substatWeights)) {
    for (const delta of [-1, 1]) {
      const weight = input.substatWeights[quantity] + delta;
      if (weight <= 0) continue;
      const nudged = { ...input, substatWeights: { ...input.substatWeights, [quantity]: weight } };
      const { pBeat } = await slotBeatProbabilityAsync(nudged, cache, options);
      low = Math.min(low, pBeat);
      high = Math.max(high, pBeat);
    }
  }
  return { low, high };
}
