/**
 * Ranking weapon candidates by simulated DPS — and saying which pairs are not separated.
 *
 * W.5, `docs/DESIGN_weapon_passives.md` §4. **The separability is not a garnish on the
 * ranking; it is the reason the ranking is allowed to be published.**
 *
 * gcsim is a Monte Carlo simulator, so every candidate's DPS is an estimate with a standard
 * error. Measured against the committed browser build, a 100-iteration 90-second rotation
 * gives mean ~707 and sd ~87 — a standard error near **1.2 %**. Two weapons three percent
 * apart are therefore *indistinguishable at that iteration count*, and presenting them as
 * first and second is a confident answer to a question the run did not resolve.
 *
 * This repo has legislated the same point twice already, from both directions: `isExact` on
 * the optimizer says whether a top-10 is really the top 10, and `sim_retrieval` refuses to
 * return a run without the measured error for its neighbourhood. This is that rule applied to
 * a ranking.
 */

/** One candidate's simulated result. `sd` is the per-iteration spread, not the standard error. */
export interface RankedCandidate {
  weaponId: string;
  name: string;
  dpsMean: number;
  dpsSd: number;
  iterations: number;
}

export interface RankedRow extends RankedCandidate {
  rank: number;
  /** Standard error of this candidate's mean: `sd / sqrt(iterations)`. */
  standardError: number;
  /**
   * Candidates this one is **not** separated from, by `weaponId`.
   *
   * Non-empty means the ranking does not distinguish them and a caller must not present the
   * order between them as a result. It is a symmetric relation, and deliberately **not**
   * transitive-closed: A may be inseparable from B and B from C while A and C are cleanly
   * apart, and collapsing that into one group would discard a real distinction.
   */
  notSeparatedFrom: string[];
}

export interface Ranking {
  rows: RankedRow[];
  /** True when every adjacent pair is separated — the ranking is fully ordered. */
  fullyOrdered: boolean;
  /**
   * The iteration count behind every row, or **null when they differ**.
   *
   * Null rather than the first row's, which is what this reported at first. Mixed counts are
   * not hypothetical — a cached run and a fresh one are exactly how they arise — and a single
   * number stamped on a ranking assembled from several is one number describing several
   * things. Each row carries its own `iterations` regardless, and `areSeparated` already uses
   * the per-candidate standard error, so the comparison itself is sound either way. It is
   * only the summary that could lie.
   */
  iterations: number | null;
}

/**
 * Are two candidates' means far enough apart to be told apart?
 *
 * A two-sample comparison on the standard errors: separated when the gap exceeds
 * `z` combined standard errors. `z = 2` is ~95 % and is the default; it is a **parameter
 * rather than a constant** because the honest threshold depends on how many pairs are being
 * compared at once, and pretending otherwise would bury a choice in a magic number.
 *
 * **Zero iterations or zero spread does not mean infinite confidence.** A candidate with
 * `sd = 0` is either deterministic or unmeasured, and this cannot tell those apart, so a
 * zero-width interval separates only when the means genuinely differ.
 */
export function areSeparated(a: RankedCandidate, b: RankedCandidate, z = 2): boolean {
  const seA = standardError(a);
  const seB = standardError(b);
  const combined = Math.sqrt(seA * seA + seB * seB);
  const gap = Math.abs(a.dpsMean - b.dpsMean);
  if (combined === 0) return gap > 0;
  return gap > z * combined;
}

/** `sd / sqrt(iterations)`. Zero iterations would be a division by zero, so it reports 0. */
export function standardError(c: RankedCandidate): number {
  if (!Number.isFinite(c.dpsSd) || c.iterations < 1) return 0;
  return c.dpsSd / Math.sqrt(c.iterations);
}

/**
 * Rank candidates by mean DPS, carrying which pairs the run could not separate.
 *
 * Ties in the mean are broken by name so the order is **fully determined** — an unstable sort
 * would make two runs of the same data disagree about a ranking neither of them resolved,
 * which looks like the simulation being noisy rather than the sort being arbitrary.
 */
export function rank(candidates: readonly RankedCandidate[], z = 2): Ranking {
  const sorted = [...candidates].sort(
    (a, b) => b.dpsMean - a.dpsMean || a.name.localeCompare(b.name),
  );
  const rows: RankedRow[] = sorted.map((c, i) => ({
    ...c,
    rank: i + 1,
    standardError: standardError(c),
    notSeparatedFrom: sorted
      .filter((other) => other.weaponId !== c.weaponId && !areSeparated(c, other, z))
      .map((other) => other.weaponId),
  }));
  const fullyOrdered = rows.every((row, i) =>
    i === 0 || areSeparated(rows[i - 1], row, z),
  );
  const counts = new Set(candidates.map((c) => c.iterations));
  return { rows, fullyOrdered, iterations: counts.size === 1 ? [...counts][0] : null };
}
