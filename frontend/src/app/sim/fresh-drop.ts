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

/** Every ordered draw of four distinct positions from `n`, computed once per `n`. */
const ORDERS = new Map<number, Int8Array[]>();
function ordersOf(n: number): Int8Array[] {
  let found = ORDERS.get(n);
  if (!found) {
    found = [];
    for (let a = 0; a < n; a += 1) {
      for (let b = 0; b < n; b += 1) {
        if (b === a) continue;
        for (let c = 0; c < n; c += 1) {
          if (c === a || c === b) continue;
          for (let d = 0; d < n; d += 1) {
            if (d === a || d === b || d === c) continue;
            found.push(Int8Array.of(a, b, c, d));
          }
        }
      }
    }
    ORDERS.set(n, found);
  }
  return found;
}

/**
 * Every (main stat, four substats) a fresh drop for one slot can be, with its probability.
 *
 * The weighted draw **without replacement** — each draw's denominator is what is left of the
 * pool — summed over every order of a set, which is what GO's `substatProb` and this repo's
 * `lineOutcomes` compute. Written out flat here rather than calling `lineOutcomes`, because
 * the weight-sensitivity pass asks this twenty times per slot: the orders depend only on the
 * pool's size and are built once; a re-weighting is then `5,040 × 4` multiplications per main
 * stat. A spec pins the two against each other.
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
    // Sorted, so a set's key is the same whichever order its members were drawn in.
    const keys = Object.keys(substatWeights).filter((quantity) => quantity !== main).sort();
    if (keys.length < LINES) continue;
    const weights = keys.map((quantity) => substatWeights[quantity]);
    const poolTotal = weights.reduce((a, b) => a + b, 0);
    const bySet = new Map<number, number>();
    for (const order of ordersOf(keys.length)) {
      let p = 1;
      let left = poolTotal;
      let mask = 0;
      for (let i = 0; i < LINES; i += 1) {
        const w = weights[order[i]];
        p *= w / left;
        left -= w;
        mask |= 1 << order[i];
      }
      bySet.set(mask, (bySet.get(mask) ?? 0) + p);
    }
    for (const [mask, p] of bySet) {
      const subs = keys.filter((_, index) => mask & (1 << index));
      cells.push({ main, subs, p: pMain * p });
    }
  }
  return cells;
}
