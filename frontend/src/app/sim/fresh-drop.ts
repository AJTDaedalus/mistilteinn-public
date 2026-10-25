/**
 * What a freshly dropped domain 5-star can be, before anyone has levelled it.
 *
 * `docs/TASKS_upgrade_estimator.md` Task 4; `docs/DESIGN_upgrade_estimator.md` §3. **Pure and
 * offline**: no recipe, no evaluator. It answers "with what probability does a new drop for this
 * slot have this main stat and these four substats", and `upgrade-estimate.ts` turns that into a
 * probability of beating what the build wears.
 *
 * ## The generation, per `docs/RESEARCH_artifact_drop_model.md` §§2–4
 *
 * A main stat by the slot's table; three substats (80%) or four (20%), each drawn by weight
 * **without replacement**, excluding the main stat; one roll on each; then five upgrades. A
 * three-liner's first upgrade **adds** the fourth line — drawn by the same weighted rule — and
 * every other upgrade picks one of the four lines uniformly.
 *
 * ## The simplification that halves the state
 *
 * Because the fourth line of a three-liner is drawn by the same rule as the first three, **the
 * set of four substats has the same distribution whichever way the piece started**. The line
 * count changes only the roll budget:
 *
 * - **four-line**: each line gets `1 + Multinomial(5, ¼)` rolls, nine in all;
 * - **three-line**: each line — the added one included — gets `1 + Multinomial(4, ¼)`, eight.
 *
 * So the prior is a mixture over (main stat, unordered four-substat set), with two roll budgets
 * per cell. That is what `freshDropCells` and `rollBudgets` return.
 */

import { lineOutcomes } from './artifact-distribution';

/** Genshin gives an artifact four substats at most, and a fresh drop always ends with four. */
export const LINES = 4;

/** Upgrades a 5-star gets between +0 and +20. `artifact_roll_schedule.json`. */
export const UPGRADES = 5;

/** One (main stat, four substats) a fresh drop can turn out to be. */
export interface FreshDropCell {
  main: string;
  /** The four substats, sorted, so two draw orders of one set land in one cell. */
  subs: readonly string[];
  /** `P(main) · P(these four | main)` — exact, summing to 1 over a slot's cells. */
  p: number;
}

/** How many upgrade rolls land on the four lines beyond each line's own first roll. */
export interface RollBudget {
  /** Upgrades spread uniformly over the four lines: 5 for a four-liner, 4 for a three-liner. */
  upgrades: number;
  p: number;
}

/**
 * The two roll budgets, weighted by how often a domain piece starts with four lines.
 *
 * A three-liner spends one of its five upgrades creating the fourth line, and that line's first
 * roll is the one it is created with — so every line ends with one roll plus a uniform share of
 * the remaining four.
 */
export function rollBudgets(fourLineShare: number): RollBudget[] {
  if (!(fourLineShare > 0 && fourLineShare < 1)) {
    throw new RangeError(
      `a four-line share of ${fourLineShare} is not a share; a domain piece starts with three `
      + 'or four lines and both happen',
    );
  }
  return [
    { upgrades: UPGRADES - 1, p: 1 - fourLineShare },
    { upgrades: UPGRADES, p: fourLineShare },
  ];
}

/**
 * Every (main stat, four substats) a fresh drop for one slot can be, with its probability.
 *
 * Draw orders are enumerated by `lineOutcomes` — the port of Genshin Optimizer's `substatProb`
 * that the artifact ranker already uses — and collapsed to unordered sets. At most `10·9·8·7 =
 * 5,040` orders and `C(10, 4) = 210` sets per main stat, so this is exact and cheap.
 *
 * **Refuses a main-stat table that does not sum to 1.** A slot whose table quietly lost a row
 * would hand that row's probability to nobody, and every estimate would come out wrong by that
 * share with nothing on screen to say so.
 */
export function freshDropCells(
  mainStatProbabilities: Readonly<Record<string, number>>,
  substatWeights: Readonly<Record<string, number>>,
): FreshDropCell[] {
  const total = Object.values(mainStatProbabilities).reduce((a, b) => a + b, 0);
  if (Math.abs(total - 1) > 1e-9) {
    throw new RangeError(`main-stat probabilities sum to ${total}, not 1`);
  }
  const cells: FreshDropCell[] = [];
  for (const [main, pMain] of Object.entries(mainStatProbabilities)) {
    if (pMain <= 0) continue;
    // The main stat is out of the pool when it is a substat type: no piece has CRIT DMG twice.
    const pool = Object.fromEntries(
      Object.entries(substatWeights).filter(([quantity]) => quantity !== main),
    );
    const bySet = new Map<string, { subs: string[]; p: number }>();
    for (const outcome of lineOutcomes(pool, LINES)) {
      const subs = [...outcome.added].sort();
      const key = subs.join('|');
      const found = bySet.get(key);
      if (found) found.p += outcome.p;
      else bySet.set(key, { subs, p: outcome.p });
    }
    for (const { subs, p } of bySet.values()) cells.push({ main, subs, p: pMain * p });
  }
  return cells;
}
