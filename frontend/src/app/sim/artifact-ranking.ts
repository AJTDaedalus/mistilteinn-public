/**
 * The five numbers the inventory shows for one artifact, against one build.
 *
 * `docs/TASKS_artifact_ranking.md` A.6. This is where A.5's projections meet the recipe
 * evaluator: the projections say what a piece could become, `scoreForSlot` says what each of
 * those is worth over the rotation, and this joins them into a row a user can sort by.
 *
 * ## The engine, and what it is not
 *
 * Owner ruling (`DECISIONS.md` §22, restated 2026-09-05): *"do what Fribbels/GO do but with
 * gcsim as the engine."* Every number here comes from `evaluateRecipe` — gcsim's own published
 * per-hit decomposition, replayed closed-form — and **gcsim itself never enters this loop**. It
 * ran once, to calibrate. Anything here that reached for a simulator would have left the design.
 *
 * ## Every number is a lower bound, and says so
 *
 * These are **single-slot swaps**: the piece goes into its slot and the other four stay put. The
 * question issue #291 actually asks — *"the best build with this artifact levelled up"* — is a
 * re-search with the piece pinned, and it can only ever be larger, because a re-search may keep
 * the same four neighbours and never does worse. So `delta` is published as *at least* this
 * much. Genshin Optimizer's own Artifact Upgrader carries the same caveat in its own UI:
 * *"as it only swaps one artifact at a time, for the best overall build across all artifacts,
 * use the main artifact optimizer."* (`docs/AUDIT_go_handson.md` §1.)
 *
 * ## Two of DESIGN §6's three refusals turned out to be Fribbels-shaped
 *
 * §6 asks for three things that must never be silent. Building it, two of them dissolved:
 *
 * - **"A piece whose rolls could not be decomposed must report no score."** Projecting *future*
 *   rolls needs the line count and the committed schedule, both exact, and never the history.
 *   `substat_rolls`' 85% / 11.5% / 3.5% exact / estimated / unknown split governs the roll bars
 *   on the card and does not reach this. What genuinely cannot be answered is a piece whose
 *   rarity and level the schedule does not cover, and that is `RankRefusal.noSchedule`.
 * - **"A wrong main stat must not be a low number that looks comparable."** True of a weights
 *   model, which cannot represent a main stat's contribution and so collapses the grade. **It is
 *   not true here**: an ATK% goblet evaluated through the real damage chain produces its real,
 *   correctly lower damage, and that number *is* comparable. So the main stat is reported as a
 *   separate fact for filtering — never folded into the score, and never used to void it.
 *
 * The third — *"a weight vector computed against an unmodelled passive must carry that caveat"* —
 * turned out to name a caveat from a **different subsystem**. `unmodelled_passives` belongs to
 * `weapon_comparison`, which runs the Chunk F single-hit chain; a recipe is calibrated by gcsim,
 * which implements the kits, so it has no unmodelled passives by construction.
 *
 * **The rule behind it is still right, and the recipe has its own two.** `meta.unstable` names
 * abilities whose instance count varied across iterations, and `meta.staleConversions` names
 * conversions no probe could resolve. Both already exist precisely because dropping them went
 * wrong once: they were returned beside the recipe rather than on it, a cached recipe came back
 * with its instability forgotten, and the page then affirmatively called the ranking sound. So
 * they travel with every row here.
 */

import { type StatPool, scoreForSlot } from './artifact-score';
import { type DrawModel, type Piece, type Projection, projectPiece } from './artifact-projection';
import { type Recipe } from './recipe';
import { evaluateRecipe } from './recipe-eval';
import { candidateStatsFrom } from './recipe-search';

/** Why a piece has no score. Never a zero standing in for one. */
export type RankRefusal =
  /** The committed upgrade schedule does not cover this rarity and level. */
  | 'noSchedule'
  /** The rarity has no roll ladders in the draw model, so nothing can be projected. */
  | 'noLadders';

export interface RankedArtifact {
  id: string;
  /** The piece's main stat, as a kernel quantity. Reported, never folded into the score. */
  mainStatQuantity: string | null;
  /** Damage over the rotation with this piece in its slot, exactly as it stands today. */
  current: number;
  /** Expected damage once the remaining rolls land — mid tier, spread evenly. */
  average: number;
  /** The best the remaining rolls could do, maximised over where they could land. */
  best: number;
  /** The mirror. Worth showing because a wide band is itself information about a +0. */
  worst: number;
  /**
   * `current` minus the damage of the build as it stands. **Positive means an upgrade today.**
   *
   * `AUDIT_fribbels_handson.md` names the signed delta as the one column that turns a sortable
   * list into a decidable one: a score says how good a piece is, a delta says whether to keep it.
   */
  delta: number;
  /** `average` minus the same baseline — whether levelling this piece is worth the resin. */
  averageDelta: number;
  /**
   * How good this piece's **substats** are, against the best they could have been, 0–1.
   *
   * **The main stat is held identical in both ends and cancels.** It was in both when this
   * shipped, and driving the page is what showed the consequence: an ATK% sands contributes
   * 46.6% before a single substat, so `(main + rolled) / (main + ideal)` lands near 0.8 for
   * anything decent and **every piece in the owner's inventory graded `WTF+`**. A grade that
   * cannot separate a good piece from a mediocre one is not a grade.
   *
   * Cancelling it also makes the number mean what the page already says beside it — *"what
   * this artifact rolled, against the best it could"*, which is the roll-value line's own
   * wording. Whether the main stat is the right one is a separate fact, reported separately,
   * exactly as `DESIGN_artifact_ranking.md` §6 asks.
   */
  fraction: number;
  grade: string;
  /** Non-null when no number could honestly be produced. The caller shows nothing, not a zero. */
  refusal: RankRefusal | null;
  /**
   * Caveats carried from the recipe these numbers came out of.
   *
   * A clean-looking number derived from a caveated one is a lie, and this repo has shipped that
   * exact lie once — see the module docstring.
   */
  caveats: {
    /** Abilities whose instance count varied across iterations. Empty means the run was stable. */
    unstable: readonly string[];
    /** Conversions baked into the recipe that a candidate's stats would have moved. */
    staleConversions: readonly string[];
  };
}

/**
 * Fribbels' letter tiers, verbatim from `scoreFormatting.ts` at the pin
 * (`RESEARCH_fribbels_hsr.md` §4.7). 5% steps.
 *
 * Copied rather than invented because a grade scale is a shared vocabulary — a user who knows
 * what an "S+" means from one tool should not have to relearn it here. What differs is what the
 * percentage is *of*: theirs is a weighted score against an ideal relic, ours is damage over a
 * real rotation against an ideal piece with the same main stat.
 */
const RATING_TIERS: readonly (readonly [number, string])[] = [
  [0, 'F'], [0.05, 'F+'], [0.1, 'D'], [0.15, 'D+'], [0.2, 'C'], [0.25, 'C+'],
  [0.3, 'B'], [0.35, 'B+'], [0.4, 'A'], [0.45, 'A+'], [0.5, 'S'], [0.55, 'S+'],
  [0.6, 'SS'], [0.65, 'SS+'], [0.7, 'SSS'], [0.75, 'SSS+'], [0.8, 'WTF'], [0.85, 'WTF+'],
  [0.9, 'AEON'],
];

/** Genshin gives an artifact four substats at most. */
const MAX_SUBSTATS = 4;

export function grade(fraction: number): string {
  let out = RATING_TIERS[0][1];
  for (const [floor, rating] of RATING_TIERS) if (fraction >= floor) out = rating;
  return out;
}

/**
 * The damage of the best piece that could exist in this slot, with this main stat.
 *
 * **The denominator of the grade.** Normalising against the inventory instead would make an "S"
 * mean "good for what you happen to own", which is a different claim that changes as you farm —
 * and it would grade a bare account's best junk piece as perfect.
 *
 * The ideal is built the way the game would: the same main stat, four substat lines, every roll
 * at the top tier, and the lines chosen to **maximise damage** rather than by substat weight. The
 * choice is enumerated — `C(9,4)` is 126 pools at ~12 µs — because picking by weight is exactly
 * the proxy `DESIGN_artifact_ranking.md` §4 rejected, and it would misprice a build whose CRIT
 * Rate is already at the cap.
 *
 * Memoise per `(slot, mainStat, rarity)` across an inventory sweep; it does not vary per piece.
 */
export function idealFor(
  recipe: Recipe,
  equipped: readonly StatPool[],
  slot: number,
  piece: Pick<Piece, 'rarity' | 'mainStatQuantity'> & { mainStatValue: number; rollsTotal: number },
  model: DrawModel,
): number {
  const ladders = new Map(
    (model.rollTiers[String(piece.rarity)] ?? []).map((row) => [row.quantity, row.values]),
  );
  const eligible = [...ladders.keys()].filter((q) => q !== piece.mainStatQuantity);

  const base: Record<string, number> = {};
  if (piece.mainStatQuantity) base[piece.mainStatQuantity] = piece.mainStatValue;

  const pools: { id: string; stats: StatPool }[] = [];
  // Every way to choose four lines out of the eligible pool. The rolls then split evenly, which
  // is the best a real piece can do: an artifact cannot put five rolls into one line and still
  // have four lines.
  const choose = (start: number, picked: string[]): void => {
    if (picked.length === MAX_SUBSTATS) {
      const stats: Record<string, number> = { ...base };
      // **The four lines come with the artifact, and every upgrade is free on top.** A 5-star
      // is created with its substats — each carrying one roll — and then gains a roll at
      // +4/+8/+12/+16/+20, so one line can reach six rolls, not five. The first draft spent
      // upgrades creating the lines and graded a real maxed piece at 117% of "ideal", which is
      // how the arithmetic got caught.
      const free = piece.rollsTotal;
      for (const quantity of picked) {
        stats[quantity] = (stats[quantity] ?? 0) + top(ladders, quantity);
      }
      for (const target of picked) {
        const withTarget = { ...stats };
        withTarget[target] += free * top(ladders, target);
        pools.push({ id: `${picked.join('+')}>${target}`, stats: withTarget });
      }
      return;
    }
    for (let i = start; i < eligible.length; i += 1) choose(i + 1, [...picked, eligible[i]]);
  };
  choose(0, []);

  if (!pools.length) return Number.NaN;
  const scored = scoreForSlot(recipe, equipped, pools, slot);
  return Math.max(...scored.map((row) => row.score.damage));
}

function top(ladders: Map<string, readonly number[]>, quantity: string): number {
  const values = ladders.get(quantity);
  return values?.length ? values[values.length - 1] : 0;
}

/**
 * Score one piece, five ways, against one build.
 *
 * `ideal` and `baseline` are passed in rather than recomputed: neither varies per piece, and
 * recomputing them inside a 2,370-iteration sweep would dominate the cost of the sweep.
 */
export function rankArtifact(
  recipe: Recipe,
  equipped: readonly StatPool[],
  slot: number,
  piece: Piece & { id: string },
  model: DrawModel,
  context: {
    /** The build's own damage as it stands. Every delta is measured against it. */
    baseline: number;
    /** The best piece that could exist in this slot with this main stat. `idealFor`. */
    ideal: number;
    /** Damage with the slot empty. Not the grade's zero point — see `mainOnly`. */
    emptySlot: number;
    /**
     * Damage with **only this main stat** in the slot, no substats.
     *
     * The grade's zero point, so the main stat cancels out of `fraction`. Using `emptySlot`
     * here instead put the main stat in both ends of the ratio and graded every piece in a real
     * 2,370-artifact inventory `WTF+`.
     */
    mainOnly: number;
  },
): RankedArtifact {
  const shell = {
    id: piece.id,
    mainStatQuantity: piece.mainStatQuantity,
    caveats: {
      unstable: recipe.meta?.unstable ?? [],
      staleConversions: (recipe.meta?.staleConversions ?? []).map((c) => c.term),
    },
  };
  const nothing = {
    ...shell,
    current: Number.NaN, average: Number.NaN, best: Number.NaN, worst: Number.NaN,
    delta: Number.NaN, averageDelta: Number.NaN, fraction: Number.NaN, grade: '',
  };

  if (!piece.potential) return { ...nothing, refusal: 'noSchedule' };
  if (!(model.rollTiers[String(piece.rarity)] ?? []).length) {
    return { ...nothing, refusal: 'noLadders' };
  }

  const projection = projectPiece(piece, model) as Projection;
  const at = (stats: StatPool): number => {
    const swapped = [...equipped];
    swapped[slot] = stats;
    return evaluateRecipe(recipe, candidateStatsFrom(swapped));
  };

  const current = at(projection.current);
  const average = at(projection.average);
  // The maximum over enumerated outcomes, against the real damage function — not the outcome a
  // substat-weight heuristic would have guessed at.
  const best = Math.max(...projection.bestCandidates.map((c) => at(c.stats)));
  const worst = Math.min(...projection.worstCandidates.map((c) => at(c.stats)));

  // Zero when the ideal's substats are worth nothing over the bare main stat, which would
  // otherwise divide by ~0 and produce an AEON for a piece contributing nothing.
  const span = context.ideal - context.mainOnly;
  const fraction = span > 0
    ? Math.min(Math.max((current - context.mainOnly) / span, 0), 1)
    : 0;

  return {
    ...shell,
    current,
    average,
    best,
    worst,
    delta: current - context.baseline,
    averageDelta: average - context.baseline,
    fraction,
    grade: grade(fraction),
    refusal: null,
  };
}
