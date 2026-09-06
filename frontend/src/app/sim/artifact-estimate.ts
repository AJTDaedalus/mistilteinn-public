/**
 * The **cheap** pass: a Gaussian estimate of what a piece could become, for every piece.
 *
 * Genshin Optimizer's shape, and `RESEARCH_genshin_optimizer_scoring.md` §1 named it as the
 * thing to copy before this chunk failed to: *"the cheap approximation ships immediately for
 * every candidate; the exact answer is computed only for what the user is looking at,
 * cancellably."* `artifact-outcome.ts` is the exact half. This is the other one.
 *
 * ## Why a Gaussian rather than the enumeration
 *
 * Enumerating one +0 five-star is ~66,000 outcomes. Over 2,370 pieces that is 150 million
 * evaluations, which is not a column. This costs about **five evaluations per piece** — one at
 * the mean and one per stat for a numerical Jacobian — so the whole inventory is under a second
 * and every row can carry the probability issue #291 asks for.
 *
 * ## The covariance is the point, and it is what a point estimate misses
 *
 * GO carries a `GaussianNode { mu, cov }` per tree node and pushes it through the objective by
 * the delta method — `f_cov = df · cov · dfᵀ`. The covariance is not decoration: **rolls
 * compete.** A roll landing on CRIT Rate is a roll not landing on CRIT DMG, so under the
 * multinomial `Cov[k_q, k_r] = −n/L²` for `q ≠ r`, and ignoring it is exactly why
 * `artifact-projection`'s point estimate is optimistic (`DESIGN_artifact_ranking.md` §8.8).
 *
 * For a random sum `S_q = Σ` of `k_q` iid rolls, with roll mean `m_q` and variance `v_q`:
 *
 *     E[S_q]        = E[k_q] · m_q                      = (n/L) · m_q
 *     Var[S_q]      = E[k_q] · v_q + Var[k_q] · m_q²    (law of total variance)
 *     Cov[S_q, S_r] = Cov[k_q, k_r] · m_q · m_r         (roll values are independent)
 *
 * ## What it is not
 *
 * **An approximation on two counts, both GO's too**: the delta-method linearisation of the
 * damage function, and the Gaussian assumption on the substat totals. A first-order delta
 * method's *mean* is `f(E[X])`, so this pass carries the same optimism the exact pass corrects —
 * which is precisely why GO draws both and labels them *Estimated* and *Exact*.
 */

import { type StatPool } from './artifact-score';
import { type DrawModel, type Piece, eligibleNewLines } from './artifact-projection';
import { lineOutcomes, meanRoll } from './artifact-distribution';

export interface OutcomeEstimate {
  /** `f(E[X])` — the objective at the expected stats. Optimistic; see the module docs. */
  mean: number;
  /** `sqrt(df · cov · dfᵀ)`, the delta-method standard deviation. */
  sd: number;
  /** Damage with the piece exactly as it stands. */
  current: number;
  /** `P(damage > current)` under the Gaussian. Issue #291's number, for every piece. */
  probabilityOfUpgrade: number;
}

/**
 * The standard normal CDF, Abramowitz & Stegun 26.2.17 (|ε| < 7.5e-8).
 *
 * Written out rather than pulled in: it is six constants, and a dependency for six constants is
 * a dependency to keep current forever.
 */
export function normalCdf(z: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const d = 0.3989422804014327 * Math.exp((-z * z) / 2);
  const p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937
    + t * (-1.821255978 + t * 1.330274429))));
  return z >= 0 ? 1 - p : p;
}

/**
 * Estimate one piece's future in a handful of evaluations.
 *
 * `null` for a piece the schedule cannot answer for, or one with nothing left — the same refusal
 * `projectPiece` makes, and for the same reason: a maxed piece has a certain future, not an
 * unknown one, and the caller should show its current value rather than a distribution.
 */
export function estimateOutcome(
  piece: Piece,
  model: DrawModel,
  evaluate: (stats: StatPool) => number,
): OutcomeEstimate | null {
  const potential = piece.potential;
  if (!potential || potential.rollsRemaining <= 0) return null;

  const ladders = new Map(
    (model.rollTiers[String(piece.rarity)] ?? []).map((row) => [row.quantity, row.values]),
  );
  const current = evaluate(piece.stats);
  const gains = potential.gainsASubstat;
  const free = gains ? Math.max(potential.rollsRemaining - 1, 0) : potential.rollsRemaining;

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

  // A mixture over which substat the fourth line turns out to be: one Gaussian per branch,
  // weighted. Summing the branch probabilities rather than the branch means is what keeps this a
  // mixture instead of an average of unlike things.
  let upgrade = 0;
  let mean = 0;
  let variance = 0;

  for (const branch of newLines) {
    const created = branch.added[0];
    const base: Record<string, number> = { ...piece.stats };
    if (created) {
      // The roll that creates the line lands at its own expected value.
      base[created] = (base[created] ?? 0) + meanRoll(ladders.get(created) ?? []);
    }
    const lines = (created ? [...potential.substatQuantities, created] : [
      ...potential.substatQuantities,
    ]).filter((q) => ladders.has(q));
    if (!lines.length) continue;

    const L = lines.length;
    const mu: Record<string, number> = { ...base };
    for (const quantity of lines) {
      mu[quantity] = (mu[quantity] ?? 0) + (free / L) * meanRoll(ladders.get(quantity) ?? []);
    }
    const atMean = evaluate(mu);

    // Numerical partials: one evaluation per line. A step of one expected roll keeps the
    // difference well inside the objective's own scale rather than probing its noise floor.
    const df: number[] = lines.map((quantity) => {
      const step = meanRoll(ladders.get(quantity) ?? []) || 1e-6;
      const bumped = { ...mu };
      bumped[quantity] = (bumped[quantity] ?? 0) + step;
      return (evaluate(bumped) - atMean) / step;
    });

    // `df · cov · dfᵀ` over the random sums. The off-diagonal terms are negative — that is the
    // competition, and dropping them would overstate the spread as well as the mean.
    let f_cov = 0;
    for (const [i, qi] of lines.entries()) {
      const mi = meanRoll(ladders.get(qi) ?? []);
      const vi = rollVariance(ladders.get(qi) ?? []);
      for (const [j, qj] of lines.entries()) {
        const mj = meanRoll(ladders.get(qj) ?? []);
        const covK = i === j ? free * (1 / L) * (1 - 1 / L) : -free / (L * L);
        const cov = i === j ? (free / L) * vi + covK * mi * mi : covK * mi * mj;
        f_cov += df[i] * df[j] * cov;
      }
    }

    const sd = Math.sqrt(Math.max(f_cov, 0));
    mean += branch.p * atMean;
    variance += branch.p * (f_cov + atMean * atMean);
    upgrade += branch.p * (sd > 0 ? 1 - normalCdf((current - atMean) / sd) : (atMean > current ? 1 : 0));
  }

  return {
    mean,
    // Mixture variance: E[σ² + μ²] − (E[μ])². The branches have different means, and treating
    // them as one Gaussian around a shared mean would understate the spread.
    sd: Math.sqrt(Math.max(variance - mean * mean, 0)),
    current,
    probabilityOfUpgrade: upgrade,
  };
}

/** Variance of one roll, over the ladder's four values, unweighted. */
function rollVariance(values: readonly number[]): number {
  if (!values.length) return 0;
  const m = meanRoll(values);
  return values.reduce((acc, v) => acc + (v - m) ** 2, 0) / values.length;
}
