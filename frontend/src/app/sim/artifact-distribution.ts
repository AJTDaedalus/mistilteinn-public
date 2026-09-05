/**
 * The probability model behind "what will this artifact become".
 *
 * `docs/TASKS_artifact_ranking.md` A.13; the audit it follows is
 * `docs/RESEARCH_genshin_optimizer_scoring.md` §2, read off Genshin Optimizer's shipped source.
 * **Pure and offline**: no recipe, no evaluator, no network. It answers "with what probability
 * does this piece end up with these stats", and A.14 turns that into a distribution over damage.
 *
 * ## Two mechanisms, and GO does not mix them up
 *
 * - **Which substats a piece *has*** is a weighted draw **without replacement**, excluding the
 *   main stat and any line already present. The weights are `substatWeights` — cited, not
 *   derived, and `docs/RESEARCH_substat_draw_weights.md` records that the owner's own export
 *   cannot confirm them because a fitted table exists that reproduces it exactly.
 * - **Which existing line an upgrade enhances** is **uniform over the four**, independent per
 *   roll: `rollCountProb` is a plain multinomial with p = 1/4.
 *
 * Conflating them would systematically overstate CRIT DMG, which is the whole reason
 * `artifact-projection.ts` spreads its average evenly rather than by weight.
 *
 * ## Why the tier sum is enumerated rather than sampled
 *
 * A roll takes one of four values — 70/80/90/100 % of the stat's maximum, uniform. The *sum* of
 * `n` such rolls has only `3n + 1` distinct totals, and their probabilities are the quadrinomial
 * coefficients: the coefficient of xᵏ in (1 + x + x² + x³)ⁿ, OEIS A008287. So 4ⁿ orderings
 * collapse into 3n + 1 exact numbers — six rolls is 4⁶ = 4,096 orderings and 19 totals.
 *
 * **No Monte Carlo anywhere**, which matters beyond speed: `CROSSVAL_gcsim.md` takes a
 * deliberate divergence from gcsim precisely so that crit is *computed* rather than rolled and
 * the evaluator stays deterministic. Sampling here would put the noise back.
 */

/**
 * The coefficient of xᵏ in (1 + x + x² + x³)ⁿ.
 *
 * Built by repeated convolution rather than by a closed form: the closed form is an alternating
 * sum of binomials that loses precision exactly where the distribution is interesting, and this
 * is O(n²) on numbers this small.
 */
export function quadrinomialRow(rolls: number): number[] {
  let row = [1];
  for (let i = 0; i < rolls; i += 1) {
    const next = new Array<number>(row.length + 3).fill(0);
    for (let k = 0; k < row.length; k += 1) {
      for (let d = 0; d < 4; d += 1) next[k + d] += row[k];
    }
    row = next;
  }
  return row;
}

/** One possible total for a run of rolls, as a multiple of the stat's maximum roll. */
export interface TierSum {
  /** Sum of the rolls, in tenths of a max roll: `7 * rolls` to `10 * rolls`. */
  tenths: number;
  /** The share of that total, as a multiple of the max roll. `tenths / 10`. */
  multiple: number;
  p: number;
}

/**
 * Every total `rolls` rolls of one substat can reach, with its exact probability.
 *
 * Zero rolls is one certain outcome of zero, stated rather than left to the loop: a piece with
 * nothing left is the common case on an equipped build, and "no outcomes" would make the whole
 * distribution vanish rather than collapse onto a point.
 */
export function tierSums(rolls: number): TierSum[] {
  if (rolls <= 0) return [{ tenths: 0, multiple: 0, p: 1 }];
  const row = quadrinomialRow(rolls);
  const total = 4 ** rolls;
  return row.map((coefficient, index) => {
    const tenths = 7 * rolls + index;
    return { tenths, multiple: tenths / 10, p: coefficient / total };
  });
}

/** How `n` upgrade rolls split across `lines` substats, and how likely each split is. */
export interface RollSplit {
  /** One count per line, summing to `n`. */
  counts: number[];
  p: number;
}

/**
 * Every way `n` rolls land across `lines` substats, uniformly and independently.
 *
 * A plain multinomial with p = 1/`lines`. `C(n + lines - 1, lines - 1)` splits — 5 rolls over 4
 * lines is 56 — so enumerating is cheap and exact where sampling would be neither.
 */
export function rollSplits(n: number, lines: number): RollSplit[] {
  if (lines <= 0) return [];
  const out: RollSplit[] = [];
  const counts = new Array<number>(lines).fill(0);
  const walk = (index: number, left: number): void => {
    if (index === lines - 1) {
      counts[index] = left;
      out.push({ counts: [...counts], p: multinomial(counts) / lines ** n });
      return;
    }
    for (let take = 0; take <= left; take += 1) {
      counts[index] = take;
      walk(index + 1, left - take);
    }
  };
  walk(0, n);
  return out;
}

/** `n! / (c1! c2! …)`, computed by ratio so it does not overflow before it divides. */
function multinomial(counts: readonly number[]): number {
  const n = counts.reduce((sum, c) => sum + c, 0);
  let result = 1;
  let remaining = n;
  for (const count of counts) {
    // C(remaining, count), built multiplicatively so intermediate values stay small.
    for (let i = 0; i < count; i += 1) result = (result * (remaining - i)) / (i + 1);
    remaining -= count;
  }
  return result;
}

/** One possible identity for the lines a piece ends up with. */
export interface LineOutcome {
  /** The substats added, in draw order. Empty when the piece already had four. */
  added: string[];
  p: number;
}

/**
 * Which substats a piece gains, drawn **without replacement** and weighted.
 *
 * Recursing over draw orders and renormalising the denominator after each draw — exactly what
 * GO's `substatProb` does, and deliberately **not** an independent-weights approximation, which
 * would overstate the chance of two heavy stats appearing together.
 *
 * `pool` is what could still appear: the caller has already removed the main stat and every line
 * the piece has. Drawing more lines than the pool holds yields nothing, which is honest — there
 * is no such artifact.
 */
export function lineOutcomes(
  pool: Readonly<Record<string, number>>,
  draws: number,
): LineOutcome[] {
  if (draws <= 0) return [{ added: [], p: 1 }];
  const keys = Object.keys(pool);
  if (draws > keys.length) return [];

  const out: LineOutcome[] = [];
  const walk = (chosen: string[], remaining: Set<string>, p: number): void => {
    if (chosen.length === draws) {
      out.push({ added: [...chosen], p });
      return;
    }
    let total = 0;
    for (const key of remaining) total += pool[key];
    if (total <= 0) return;
    for (const key of [...remaining]) {
      remaining.delete(key);
      walk([...chosen, key], remaining, p * (pool[key] / total));
      remaining.add(key);
    }
  };
  walk([], new Set(keys), 1);
  return out;
}


/** One possible total for a run of rolls of one substat, in the stat's own units. */
export interface RollTotal {
  /** The summed value, exact — built from the committed ladder, not from a ratio of its max. */
  value: number;
  p: number;
}

/**
 * Every total `rolls` rolls of one substat can reach, using the **committed roll values**.
 *
 * `tierSums` expresses the structure — 4ⁿ orderings collapsing to 3n+1 totals via the
 * quadrinomial coefficients — under GO's assumption that the four tiers are exactly 70/80/90/100
 * % of the maximum. Measured against the committed 5-star ladders that assumption holds to about
 * one part in a thousand (`crit_rate` is 0.6992, not 0.7), **and this does not rely on it**: it
 * enumerates count-vectors over the actual four values.
 *
 * `C(rolls + 3, 3)` of them — 84 at the six-roll ceiling — so exactness costs nothing. A test
 * pins the two against each other on an exactly-spaced ladder, which is what keeps `tierSums`
 * honest as a description of this.
 */
export function rollTotals(values: readonly number[], rolls: number): RollTotal[] {
  if (rolls <= 0) return [{ value: 0, p: 1 }];
  if (!values.length) return [{ value: 0, p: 1 }];

  const out: RollTotal[] = [];
  const counts = new Array<number>(values.length).fill(0);
  const denominator = values.length ** rolls;
  const walk = (index: number, left: number): void => {
    if (index === values.length - 1) {
      counts[index] = left;
      const value = counts.reduce((acc, c, i) => acc + c * values[i], 0);
      out.push({ value, p: multinomial(counts) / denominator });
      return;
    }
    for (let take = 0; take <= left; take += 1) {
      counts[index] = take;
      walk(index + 1, left - take);
    }
  };
  walk(0, rolls);
  return out;
}

/** The mean value of one roll of a substat — the ladder unweighted, which is what GO takes. */
export function meanRoll(values: readonly number[]): number {
  if (!values.length) return 0;
  return values.reduce((a, b) => a + b, 0) / values.length;
}
