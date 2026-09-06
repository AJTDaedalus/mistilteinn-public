/**
 * A piece's whole future, as a distribution over damage.
 *
 * `docs/TASKS_artifact_ranking.md` A.14. Joins A.13's exact probability model to the recipe
 * evaluator: every way the remaining rolls can land, each with its probability, each scored by
 * the real damage function.
 *
 * ## Exact enumeration, no Monte Carlo
 *
 * Genshin Optimizer's method is a delta method at the coarse tree levels and **exact
 * enumeration at the leaves** (`RESEARCH_genshin_optimizer_scoring.md`). This is the leaf half
 * done all the way up, which is affordable here for a reason GO's own audit doubted of gcsim:
 * the objective is not a simulation. `sim/recipe.ts` is a transcription of gcsim's published
 * per-hit decomposition, replayed closed-form at ~0.048 µs per hit, so a few thousand outcomes
 * is a few hundred milliseconds.
 *
 * A 5-star with four lines and five upgrades enumerates ~8,400 outcomes; a three-liner, which
 * also sums over which substat the fourth turns out to be, tens of thousands — a real +0 flower
 * measured **66,816**. **One piece at a time**, on the panel.
 *
 * ## It yields, because it once did not
 *
 * `outcomeDistributionAsync` yields the thread and takes a `shouldCancel`, after GO's
 * `expandRollsLevelAsync` — `uiYieldBudgetMs = 12`, a cancel callback, calls serialised — which
 * `RESEARCH_genshin_optimizer_scoring.md` named as *"the pattern worth copying"* before this
 * module shipped without it. The synchronous version froze the page for about a second on a +0
 * five-star, which is the defect `BACKLOG_frontend.md` §12 records and #175 already fixed once
 * for the single-hit search.
 *
 * **It yields between branches, not inside them, and that is a real limit.** A branch is one
 * candidate identity for the fourth substat, so a **three-liner** splits into as many chunks as
 * its pool has members, while a **four-line piece has exactly one branch and never yields
 * inside it**. GO chunks one level deeper, inside the roll expansion itself.
 *
 * Measured on the owner's inventory: main-thread lag **max 223 ms, median 5–12 ms** across two
 * runs, against ~1,000 ms for the synchronous version. Below the threshold that reads as a
 * freeze, above the 16 ms that reads as nothing. Written down rather than rounded to "chunked",
 * because the next person to enlarge the model will hit the four-line case first.
 *
 * `outcomeDistribution` stays for tests and for callers already off the main thread; **the page
 * uses the async one**.
 *
 * ## What "the mean" is, and the plan's acceptance criterion was wrong
 *
 * `DESIGN_artifact_ranking.md` §5 says the *average* becomes this distribution's mean, so "the
 * two cannot disagree". **That holds at the level of stats and not at the level of damage.**
 *
 * The expected stat total is linear in the rolls, so A.5's `average` pool is exactly the
 * distribution's mean pool — `meanStats` below, and a test pins it. Damage is *not* linear in
 * stats: crit rate and crit damage multiply. So `E[damage]` is not `damage(E[stats])`, and the
 * gap is the curvature of the damage function — Jensen, not a bug.
 *
 * Both numbers are therefore reported. `atAverage` is A.5's figure, `mean` is the distribution's,
 * and `curvature` is the difference expressed against `atAverage`. Asserting they were equal
 * would have meant either tuning one until it matched or picking a tolerance loose enough to
 * hide the disagreement, and both are worse than saying which is which.
 */

import { type StatPool } from './artifact-score';
import { type DrawModel, type Piece, eligibleNewLines } from './artifact-projection';
import { lineOutcomes, meanRoll, rollSplits, rollTotals } from './artifact-distribution';

/** One bin of the damage histogram. */
export interface OutcomeBin {
  /** Damage at the low edge of the bin. */
  from: number;
  /** Damage at the high edge. */
  to: number;
  p: number;
}

export interface OutcomeDistribution {
  /** Bins over damage, ascending, probabilities summing to 1. */
  bins: OutcomeBin[];
  /** `E[damage]` — the distribution's own mean. */
  mean: number;
  /** `damage(E[stats])` — A.5's `average`, which is a different number. See the module docs. */
  atAverage: number;
  /** `(mean - atAverage) / atAverage`. The damage function's curvature, not an error. */
  curvature: number;
  /** Damage with the piece exactly as it stands. The reference the shading is measured from. */
  current: number;
  /** `P(damage > current)` — the number issue #291 names. */
  probabilityOfUpgrade: number;
  /** How many distinct outcomes were enumerated, so the panel can say it enumerated them. */
  outcomes: number;
}

/** How many bins the histogram is drawn with. Enough to show multi-modality, few enough to read. */
const BINS = 60;

/**
 * Every way this piece's remaining rolls can land, scored.
 *
 * `evaluate` takes a stat pool for the piece and returns the build's damage with it equipped —
 * the caller owns that, because it owns the recipe and the other four slots.
 *
 * Returns `null` for a piece with no `potential`, the same refusal `projectPiece` makes: a
 * distribution over one certain outcome is a fact about a maxed piece, but "no schedule" is not
 * an outcome at all.
 */
export function outcomeDistribution(
  piece: Piece,
  model: DrawModel,
  evaluate: (stats: StatPool) => number,
): OutcomeDistribution | null {
  const potential = piece.potential;
  if (!potential) return null;

  const ladders = new Map(
    (model.rollTiers[String(piece.rarity)] ?? []).map((row) => [row.quantity, row.values]),
  );
  const valuesFor = (quantity: string): readonly number[] => ladders.get(quantity) ?? [];

  const current = evaluate(piece.stats);
  const lines = potential.substatQuantities;
  const gains = potential.gainsASubstat;
  const free = gains ? Math.max(potential.rollsRemaining - 1, 0) : potential.rollsRemaining;

  // Which substat the fourth line turns out to be. One certain "no new line" outcome when the
  // piece already has four — stated rather than special-cased, so the loop below is one shape.
  const newLines = gains
    ? lineOutcomes(
        Object.fromEntries(
          eligibleNewLines(piece, model)
            .filter((q) => ladders.has(q))
            .map((q) => [q, model.substatWeights[q] ?? 0]),
        ),
        1,
      )
    : [{ added: [] as string[], p: 1 }];

  const damages: number[] = [];
  const weights: number[] = [];
  // The expected stat pool, accumulated alongside. Linear in the rolls, so this is exactly
  // A.5's `average` — which is what makes it a check rather than a second opinion.
  const meanStats: Record<string, number> = { ...piece.stats };

  for (const newLine of newLines) {
    const created = newLine.added[0];
    const base: Record<string, number> = { ...piece.stats };
    // The roll that creates the line is itself a roll, so it carries a tier like any other.
    const targets = created ? [...lines, created] : [...lines];
    const rollable = targets.filter((q) => ladders.has(q));
    if (!rollable.length) continue;

    for (const split of rollSplits(free, rollable.length)) {
      // The created line's own roll is folded in as one extra roll on that line.
      const counts = rollable.map((quantity, index) =>
        split.counts[index] + (quantity === created ? 1 : 0));
      // **The committed roll values, not a ratio of their maximum.** GO's model assumes the
      // four tiers are 70/80/90/100 % of the max; measured against the real 5-star ladders that
      // holds to about one part in a thousand, and enumerating the actual values costs nothing.
      const perLine = counts.map((n, i) => rollTotals(valuesFor(rollable[i]), n));

      // Cartesian product over each line's possible totals.
      const walk = (index: number, stats: Record<string, number>, p: number): void => {
        if (index === rollable.length) {
          damages.push(evaluate(stats));
          weights.push(p);
          return;
        }
        const quantity = rollable[index];
        for (const total of perLine[index]) {
          const next = { ...stats };
          next[quantity] = (next[quantity] ?? 0) + total.value;
          walk(index + 1, next, p * total.p);
        }
      };
      walk(0, base, newLine.p * split.p);

      // Expected contribution per line: the ladder's own unweighted mean, which is exactly
      // what `artifact-projection`'s `midRoll` uses. Using 0.85 x max instead — GO's assumed
      // tier spacing — put the two out by 1 % and broke the identity below.
      for (const [index, quantity] of rollable.entries()) {
        meanStats[quantity] = (meanStats[quantity] ?? 0)
          + newLine.p * split.p * counts[index] * meanRoll(valuesFor(quantity));
      }
    }
  }

  if (!damages.length) return null;

  const total = weights.reduce((a, b) => a + b, 0);
  const mean = damages.reduce((acc, d, i) => acc + d * weights[i], 0) / total;
  const atAverage = evaluate(meanStats);
  const upgrade = damages.reduce(
    (acc, d, i) => acc + (d > current ? weights[i] : 0), 0,
  ) / total;

  return {
    bins: histogram(damages, weights, total),
    mean,
    atAverage,
    curvature: atAverage > 0 ? (mean - atAverage) / atAverage : 0,
    current,
    probabilityOfUpgrade: upgrade,
    outcomes: damages.length,
  };
}

/** Equal-width bins over the observed range. A degenerate range collapses to one bin. */
function histogram(
  damages: readonly number[],
  weights: readonly number[],
  total: number,
): OutcomeBin[] {
  const low = Math.min(...damages);
  const high = Math.max(...damages);
  if (!(high > low)) return [{ from: low, to: high, p: 1 }];

  const width = (high - low) / BINS;
  const bins: OutcomeBin[] = Array.from({ length: BINS }, (_, i) => ({
    from: low + i * width,
    to: low + (i + 1) * width,
    p: 0,
  }));
  for (const [i, damage] of damages.entries()) {
    const index = Math.min(Math.floor((damage - low) / width), BINS - 1);
    bins[index].p += weights[i] / total;
  }
  return bins;
}


/** How long the async walk may hold the thread before handing it back. GO's `uiYieldBudgetMs`. */
const YIELD_MS = 12;

/**
 * `outcomeDistribution`, chunked so the page stays responsive.
 *
 * Identical arithmetic — it delegates, one branch of the enumeration at a time — so there is no
 * second implementation of the model to drift. What it adds is a yield between branches and a
 * cancellation check, which is the whole difference between a feature and a freeze.
 *
 * Resolves `null` if cancelled, the same as for a piece that cannot be answered: the caller
 * shows nothing either way, and a partial distribution is not a distribution.
 */
export async function outcomeDistributionAsync(
  piece: Piece,
  model: DrawModel,
  evaluate: (stats: StatPool) => number,
  options: {
    shouldCancel?: () => boolean;
    onProgress?: (done: number, total: number) => void;
  } = {},
): Promise<OutcomeDistribution | null> {
  const potential = piece.potential;
  if (!potential) return null;

  // Split on the fourth line's identity — the outermost loop, and the one that makes a
  // three-liner expensive. A four-liner has exactly one branch and yields once, which costs
  // nothing and keeps one code path.
  const branches = potential.gainsASubstat
    ? eligibleNewLines(piece, model).filter(
        (q) => (model.rollTiers[String(piece.rarity)] ?? []).some((r) => r.quantity === q),
      )
    : [null];
  if (!branches.length) return outcomeDistribution(piece, model, evaluate);

  const parts: { found: OutcomeDistribution; weight: number }[] = [];
  let clock = Date.now();

  for (const [index, line] of branches.entries()) {
    if (options.shouldCancel?.()) return null;

    // One branch at a time, by narrowing the model's pool to the single line under
    // consideration. `lineOutcomes` then returns that line with probability 1, so the weight has
    // to be reapplied here — from the *full* pool, or the mixture would not sum to one.
    const narrowed: DrawModel = line === null ? model : {
      ...model,
      substatWeights: { [line]: model.substatWeights[line] ?? 1 },
    };
    const found = outcomeDistribution(piece, narrowed, evaluate);
    if (found) parts.push({ found, weight: weightOf(piece, model, line) });

    options.onProgress?.(index + 1, branches.length);
    if (Date.now() - clock > YIELD_MS) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      clock = Date.now();
    }
  }

  if (!parts.length) return null;
  return combine(parts);
}

/** One candidate fourth line's share of the draw, from the **full** eligible pool. */
function weightOf(piece: Piece, model: DrawModel, line: string | null): number {
  if (line === null) return 1;
  const pool = eligibleNewLines(piece, model).filter(
    (q) => (model.rollTiers[String(piece.rarity)] ?? []).some((r) => r.quantity === q),
  );
  const total = pool.reduce((sum, q) => sum + (model.substatWeights[q] ?? 0), 0);
  return total > 0 ? (model.substatWeights[line] ?? 0) / total : 1 / Math.max(pool.length, 1);
}

/** Fold per-branch distributions into one, re-binned over their combined range. */
function combine(parts: readonly { found: OutcomeDistribution; weight: number }[]): OutcomeDistribution {
  const total = parts.reduce((sum, part) => sum + part.weight, 0) || 1;
  const low = Math.min(...parts.map((p) => p.found.bins[0].from));
  const high = Math.max(...parts.map((p) => p.found.bins[p.found.bins.length - 1].to));
  const width = (high - low) / BINS || 1;

  const bins: OutcomeBin[] = Array.from({ length: BINS }, (_, i) => ({
    from: low + i * width, to: low + (i + 1) * width, p: 0,
  }));
  for (const { found, weight } of parts) {
    for (const bin of found.bins) {
      const mid = (bin.from + bin.to) / 2;
      const index = Math.min(Math.max(Math.floor((mid - low) / width), 0), BINS - 1);
      bins[index].p += (bin.p * weight) / total;
    }
  }

  const share = (pick: (d: OutcomeDistribution) => number) =>
    parts.reduce((sum, part) => sum + (part.weight / total) * pick(part.found), 0);
  const mean = share((d) => d.mean);
  const atAverage = share((d) => d.atAverage);

  return {
    bins,
    mean,
    atAverage,
    curvature: atAverage > 0 ? (mean - atAverage) / atAverage : 0,
    current: parts[0].found.current,
    probabilityOfUpgrade: share((d) => d.probabilityOfUpgrade),
    outcomes: parts.reduce((sum, part) => sum + part.found.outcomes, 0),
  };
}
