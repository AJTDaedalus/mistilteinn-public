/**
 * Projecting one artifact forward to the rolls it has not had yet.
 *
 * `docs/TASKS_artifact_ranking.md` A.5; `docs/DESIGN_artifact_ranking.md` §§3 and 5. This module
 * is **pure and offline**: it takes a piece's lines and the committed draw model, and returns
 * stat pools. It never evaluates a recipe, never touches the network, and has no opinion about
 * which projection is good — that is A.6's job, and keeping the two apart is why the projection
 * can be tested against hand-worked cases rather than against a simulator.
 *
 * ## The arithmetic, in Genshin's terms
 *
 * A 5-star gains a substat roll at +4/+8/+12/+16/+20, so a +0 has **five** upgrades ahead. If it
 * has three lines, **one of those five creates the fourth** and the remaining four deepen
 * whichever lines exist. With four lines already, all five deepen. That difference is most of why
 * a three-liner is a lottery ticket and a four-liner is a known quantity, and it falls out of the
 * committed schedule rather than needing a special case. The backend does that arithmetic
 * (`artifact_potential.upgrade_potential`) and sends `rollsRemaining` and `gainsASubstat`.
 *
 * ## Why `best` is a list of candidates rather than a number
 *
 * "Every remaining roll on the best line" needs to know which line is best, and *best* means
 * "raises this build's damage most" — which only the recipe evaluator can answer. Rather than
 * take a value function and pick a line by a proxy, this **enumerates** the pools: one per line
 * the rolls could be dumped into, crossed with each substat the fourth line could turn out to be.
 * The caller evaluates them and takes the maximum, which is the real damage function rather than
 * a local slope.
 *
 * That is deliberately the same reasoning `DESIGN_artifact_ranking.md` §4 used to reject finite
 * differences over the single-hit chain. Enumerating costs at most a couple of dozen evaluations
 * at ~12 µs each, and a heuristic that picked the line by substat weight would be confidently
 * wrong exactly where it matters — a piece whose CRIT Rate has already passed the cap.
 *
 * ## What it refuses
 *
 * A piece with no `potential` (the committed schedule does not cover its rarity and level) gets
 * `null`, not a projection with zero rolls. **Zero rolls is the honest answer for a maxed piece**,
 * so collapsing the two would report a broken row as *finished*.
 */

import { type StatPool } from './artifact-score';

/** The values one substat can roll at one rarity, ascending. */
export interface RollLadder {
  quantity: string;
  values: readonly number[];
}

/** The parts of the projection model every piece shares. `InventorySnapshot.draw_model`. */
export interface DrawModel {
  /** Keyed by rarity as a string, because that is how it arrives over JSON. */
  rollTiers: Readonly<Record<string, readonly RollLadder[]>>;
  /**
   * Unnormalised appearance weights, keyed by **kernel quantity** so they join `rollTiers`
   * without a second vocabulary.
   *
   * **Cited, not derived.** No primary source publishes them: the pinned game data's
   * `ReliquaryAffixExcelConfigData` has no weight field. They come from Genshin Optimizer's
   * `consts.ts`, which cites a community wiki. `docs/RESEARCH_substat_draw_weights.md` records
   * that the owner's own 2,370-piece export cannot confirm them either — a fitted table exists,
   * so the corpus cannot tell a wrong table from a selected sample.
   */
  substatWeights: Readonly<Record<string, number>>;
  /** Carried so a number derived from those weights can say so on screen. */
  weightsCaveat: string;
}

/** One piece's own half of the projection input. `KernelCandidate.potential`. */
export interface PiecePotential {
  rollsRemaining: number;
  rollsTotal: number;
  /** True when one remaining roll **creates** the fourth line rather than deepening one. */
  gainsASubstat: boolean;
  /** The kernel quantities this piece already has a line in. Distinct, in payload order. */
  substatQuantities: readonly string[];
}

export interface Piece {
  rarity: number;
  /** The piece's summed pool — main stat and substats together, as the kernel reads it. */
  stats: StatPool;
  /** The main stat's kernel quantity, or `null` when it is not a substat-eligible stat. */
  mainStatQuantity: string | null;
  potential: PiecePotential | null;
}

/** One enumerated outcome: the pool this piece would have, and what got it there. */
export interface ProjectedOutcome {
  stats: StatPool;
  /** The line every free roll was spent on. */
  target: string;
  /** The substat the fourth line turned out to be, or `null` when the piece already had four. */
  newLine: string | null;
}

export interface Projection {
  /** The piece exactly as it stands. Not a projection at all, and the baseline for the rest. */
  current: StatPool;
  /**
   * Expected value of the remaining rolls: mid-tier, spread evenly across the lines.
   *
   * Fribbels' rule (`futureScore.ts`, `RESEARCH_fribbels_hsr.md` §4.5), and it is a
   * **deterministic point estimate, not a distribution**. `DESIGN_artifact_ranking.md` §5 is
   * explicit that this is superseded by the distribution's mean once A.14 lands, at which point
   * the two cannot disagree because there is only one of them.
   */
  average: StatPool;
  /** Every way the rolls could land at top tier. The caller evaluates and takes the maximum. */
  bestCandidates: readonly ProjectedOutcome[];
  /** The mirror, at bottom tier. The caller takes the minimum. */
  worstCandidates: readonly ProjectedOutcome[];
}

/** Genshin gives an artifact four substats at most. */
const MAX_SUBSTATS = 4;

function laddersFor(model: DrawModel, rarity: number): Map<string, readonly number[]> {
  const rows = model.rollTiers[String(rarity)];
  return new Map((rows ?? []).map((row) => [row.quantity, row.values]));
}

/**
 * The mid-tier value of one roll of `quantity`.
 *
 * The **unweighted mean of the ladder**, not its median and not its top value. Genshin
 * Optimizer's `subMuVar` takes an unweighted mean and variance over exactly these four tiers
 * (`RESEARCH_genshin_optimizer_scoring.md` §2), because the tiers are uniform — 70/80/90/100% of
 * the maximum. Fribbels calls the same thing `.mid`.
 */
function midRoll(values: readonly number[]): number {
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

function add(pool: Record<string, number>, quantity: string, amount: number): void {
  pool[quantity] = (pool[quantity] ?? 0) + amount;
}

/**
 * Which substats a fourth line could turn out to be.
 *
 * The pool is every weighted substat **minus the main stat and minus the lines already present**
 * — the exclusion rule the game applies and the one GO's `substatProb` applies. Getting this
 * wrong is not a rounding error: it would let a projection create a second CRIT DMG line, or
 * create one on a stat the main stat has already taken.
 */
export function eligibleNewLines(piece: Piece, model: DrawModel): string[] {
  const taken = new Set<string>(piece.potential?.substatQuantities ?? []);
  if (piece.mainStatQuantity) taken.add(piece.mainStatQuantity);
  return Object.keys(model.substatWeights).filter((q) => !taken.has(q));
}

/**
 * The four projections of one piece.
 *
 * `null` when the piece carries no `potential` — see the module docstring on why that is not the
 * same as a piece with nothing left.
 */
export function projectPiece(piece: Piece, model: DrawModel): Projection | null {
  const potential = piece.potential;
  if (!potential) return null;

  const ladders = laddersFor(model, piece.rarity);
  const current: StatPool = { ...piece.stats };
  const remaining = potential.rollsRemaining;

  // A piece with nothing left projects to itself, four times over. Stated rather than left to
  // fall out of the loops below: a maxed piece is the common case on an equipped build, and
  // "best equals current" is the correct answer rather than an edge case to guard.
  if (remaining <= 0) {
    const only: ProjectedOutcome[] = [{ stats: current, target: '', newLine: null }];
    return { current, average: current, bestCandidates: only, worstCandidates: only };
  }

  const newLinePool = potential.gainsASubstat ? eligibleNewLines(piece, model) : [];

  return {
    current,
    average: averagePool(piece, model, ladders, newLinePool),
    bestCandidates: enumerate(piece, ladders, newLinePool, (values) => values[values.length - 1]),
    worstCandidates: enumerate(piece, ladders, newLinePool, (values) => values[0]),
  };
}

/**
 * Expected value: every remaining roll at mid tier, spread evenly over the lines it could hit.
 *
 * Spread **evenly**, not by weight, and that is not an oversight. Which line an *upgrade*
 * enhances is uniform over the four — `rollCountProb` in GO's `markov-tree/mathUtil.ts` is a
 * plain multinomial with p = 1/4 — and the weights govern only which substats a piece is created
 * with. Conflating the two is the mistake `RESEARCH_genshin_optimizer_scoring.md` §2 records GO
 * as correctly avoiding, and it would systematically overstate CRIT DMG.
 *
 * The fourth line, when there is one to come, is charged the **weighted** average contribution
 * across the substats that could still appear — because *that* draw is weighted.
 */
function averagePool(
  piece: Piece,
  model: DrawModel,
  ladders: Map<string, readonly number[]>,
  newLinePool: readonly string[],
): StatPool {
  const potential = piece.potential!;
  const pool: Record<string, number> = { ...piece.stats };
  const lines = potential.substatQuantities;

  // One roll creates the fourth line, so it is not free to land anywhere.
  const free = potential.gainsASubstat ? potential.rollsRemaining - 1 : potential.rollsRemaining;

  if (potential.gainsASubstat && newLinePool.length) {
    const totalWeight = newLinePool.reduce((sum, q) => sum + (model.substatWeights[q] ?? 0), 0);
    for (const quantity of newLinePool) {
      const values = ladders.get(quantity);
      if (!values?.length || !totalWeight) continue;
      const share = (model.substatWeights[quantity] ?? 0) / totalWeight;
      // The created line receives its own roll, and then its share of the free ones — it is one
      // of the four an upgrade can choose from once it exists.
      add(pool, quantity, share * midRoll(values) * (1 + free / MAX_SUBSTATS));
    }
  }

  const perLine = free / (potential.gainsASubstat ? MAX_SUBSTATS : Math.max(lines.length, 1));
  for (const quantity of lines) {
    const values = ladders.get(quantity);
    if (!values?.length) continue;
    add(pool, quantity, perLine * midRoll(values));
  }
  return pool;
}

/**
 * Every way the free rolls could be spent, at one tier.
 *
 * Enumerated as `(fourth line) × (line the free rolls land on)`. A three-liner with a six-stat
 * pool yields 6 × 4 = 24 outcomes; a four-liner yields 4. The caller evaluates them all, which
 * is cheap next to the honesty of not guessing which line is worth most.
 */
function enumerate(
  piece: Piece,
  ladders: Map<string, readonly number[]>,
  newLinePool: readonly string[],
  tier: (values: readonly number[]) => number,
): ProjectedOutcome[] {
  const potential = piece.potential!;
  const lines = potential.substatQuantities;
  const gains = potential.gainsASubstat && newLinePool.length > 0;
  const free = gains ? potential.rollsRemaining - 1 : potential.rollsRemaining;
  const out: ProjectedOutcome[] = [];

  for (const newLine of gains ? newLinePool : [null]) {
    const base: Record<string, number> = { ...piece.stats };
    if (newLine) {
      const values = ladders.get(newLine);
      if (!values?.length) continue;
      add(base, newLine, tier(values));
    }
    const targets = newLine ? [...lines, newLine] : lines;
    for (const target of targets) {
      const values = ladders.get(target);
      if (!values?.length) continue;
      const stats = { ...base };
      add(stats, target, free * tier(values));
      out.push({ stats, target, newLine });
    }
  }
  return out;
}
