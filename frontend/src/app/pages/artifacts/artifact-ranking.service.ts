/**
 * Ranking a whole inventory against one build, on the optimizer's own engine.
 *
 * `docs/TASKS_artifact_ranking.md` A.7. This is the join: the inventory from
 * `OptimizeService`, the recipes from `RecipeOptimizeService`, and the per-piece arithmetic from
 * `sim/artifact-ranking.ts`. It exists as a service rather than inside the page because
 * `/optimize` is already 1,600 lines of component and a second copy of its calibration flow
 * would be a second thing to keep in step with the cache key.
 *
 * ## What it costs, and why that shape
 *
 * A calibration is ~3.2 s of gcsim **per 4-piece state**, cached client-side by
 * `recipe-cache.ts` under a key naming the gcsim pin, build, rotation, set, ER, seed and probe.
 * Scoring is then closed-form: `RESEARCH_recipe_cost.md` measures 0.048 µs per hit, so a
 * 245-hit rotation scores a 2,370-piece inventory in about 28 ms.
 *
 * **So the expensive part is paid per ranking, not per piece**, and this reuses a warm cache
 * whenever the user has already optimized that build. `DESIGN_artifact_ranking.md` §7 closed the
 * question of whether to cache the scores: it is cheaper to recompute them than to store them.
 *
 * ## Why the four numbers cost more than 28 ms and that is fine
 *
 * `current` is one evaluation. `best` and `worst` are the max and min over A.5's enumerated
 * outcomes — up to 24 per piece for a three-liner — because picking the target line by substat
 * weight is the proxy `DESIGN_artifact_ranking.md` §4 rejected. That is ~50x the single-swap
 * cost and still well inside a job with a progress bar, which is the interaction
 * `RESEARCH_recipe_cost.md` requires of anything in this area.
 */

import { Injectable, inject } from '@angular/core';

import { type StatPool, scoreForSlot } from '../../sim/artifact-score';
import { type DrawModel, type Piece, projectPiece } from '../../sim/artifact-projection';
import { type RankedArtifact, idealFor, rankArtifact } from '../../sim/artifact-ranking';
import { evaluateRecipe } from '../../sim/recipe-eval';
import { candidateStatsFrom } from '../../sim/recipe-search';
import { SLOTS, type Candidate } from '../../sim/search';
import { fourPieceSetOf, searchRecipe } from '../../sim/recipe-search';
import { type Recipe } from '../../sim/recipe';
import {
  type CalibrationProgress,
  type CalibrationTarget,
  RecipeOptimizeService,
} from '../optimize/recipe-optimize.service';
import {
  type InventorySnapshot,
  type KernelCandidate,
  OptimizeService,
} from '../optimize/optimize.service';
import { ArtifactsService } from './artifacts.service';

export interface RankingRow extends RankedArtifact {
  slot: string;
  setId: number | null;
  level: number;
  rarity: number;
  /** True when this piece is one of the five the build is wearing right now. */
  equipped: boolean;
  /**
   * Substat rolls still to come. Zero means the four projections are necessarily identical.
   *
   * On the row rather than only inside `potential` because the page filters on it, and a
   * filter reaching two levels into a nested optional is a filter that quietly matches nothing
   * the day the shape changes.
   */
  rollsRemaining: number;
}

export interface RankingResult {
  rows: RankingRow[];
  /** The build's own damage over the rotation. Every delta is measured against this. */
  baseline: number;
  /** Carried so the page can say the weights are cited rather than measured. */
  weightsCaveat: string;
  /** Pieces the server could not translate at all — never silently dropped. */
  unreadable: { artifactId: string; reason: string }[];
  /**
   * Sets that rows were refused for, most-refused first, so the page can offer the calibration
   * that would unlock the most of the inventory rather than an arbitrary one.
   *
   * Carries the catalogue **uuid** as well as the nanoka id, because `calibrateAll` resolves the
   * uuid and the search counts pieces by the id — two different numbers for two different jobs,
   * and a target given only one of them calibrates nothing.
   */
  uncalibratedSets: { setId: number; uuid: string; name: string; pieces: number }[];
  caveats: { unstable: string[]; staleConversions: string[] };
}

/** One slot's before-and-after in a deep dive's winning build. */
export interface MovedPiece {
  slot: string;
  fromId: string | null;
  toId: string;
  changed: boolean;
}

/** What "the best build with this artifact levelled up" came out to. */
export interface DeepDive {
  /** The build's damage as it stands today — what the percentage is *of*. */
  before: number;
  /** The best build that contains this piece, at the piece's projected max-level stats. */
  after: number;
  /** `(after - before) / before`. Issue #291's "% gain". */
  gain: number;
  /**
   * The best build that does **not** contain it, over the same inventory and budget.
   *
   * OQ-A10 names this the other defensible reading of "% gain", and the two diverge exactly
   * when the current build is not optimal — which, for a piece someone is asking about, is most
   * of the time. Both are reported and labelled rather than one being chosen silently.
   */
  bestWithout: number;
  /** Which slots the winning build changed, so a four-slot answer reads as one. */
  moved: MovedPiece[];
  /** The pinned piece's projected stats, so the panel can say what it assumed. */
  projectedFrom: 'average' | 'current';
  /**
   * How many candidates per slot the search actually considered.
   *
   * **Reported because the answer is a best-of-this-pool, not a proof.** `searchRecipe` is
   * exhaustive over what it is given and says `isExact: true` — which is true of the *pool* and
   * would be a lie about the inventory if the pool were silently trimmed. See `trimForDive`.
   */
  searchedPerSlot: number;
  /** The inventory it was trimmed from, so the panel can say what fraction that was. */
  inventorySize: number;
}

/** What `rank` needs to know before it can start. */
export interface RankingRequest {
  buildId: string;
  rotationId: string;
  onProgress?: (progress: CalibrationProgress) => void;
  waitForEnergy?: boolean;
  /**
   * Extra 4-piece sets to calibrate, as catalogue **uuids** paired with their nanoka ids.
   *
   * OQ-A8's "calibrate the other set on demand". Each costs ~3.2 s of gcsim, so this is opt-in
   * and driven by the user asking about a specific set rather than by calibrating all 65.
   */
  extraSets?: readonly { uuid: string; setId: number; name: string }[];
}

@Injectable({ providedIn: 'root' })
export class ArtifactRankingService {
  /**
   * The calibration targets for a build: the baseline, its own 4-piece, and anything asked for.
   *
   * **The build's own set is not optional.** `/optimize` says the same of the baseline — *"it is
   * not optional and never was"* — and this is the second half of that: a build wearing a
   * 4-piece has to have that state calibrated before its own damage can be measured, and
   * without it the whole ranking refuses. Driving the page is how that was learned.
   *
   * A set with no catalogue entry is skipped rather than guessed at: `calibrateAll` resolves the
   * **uuid**, and a target built from the nanoka id alone calibrates nothing.
   */
  private async targetsFor(
    wornFourPiece: number | null,
    extras: readonly { uuid: string; setId: number; name: string }[],
  ): Promise<CalibrationTarget[]> {
    const targets: CalibrationTarget[] = [
      { artifactSetIds: [], setIds: [], label: 'the baseline (no 4-piece bonus)' },
    ];
    const wanted = new Map<number, { uuid: string; setId: number; name: string }>();
    if (wornFourPiece !== null) {
      const catalogue = await this.optimize.artifactSets();
      const entry = catalogue.get(wornFourPiece);
      if (entry) {
        wanted.set(wornFourPiece, {
          uuid: entry.id, setId: wornFourPiece, name: entry.name,
        });
      }
    }
    for (const set of extras) if (!wanted.has(set.setId)) wanted.set(set.setId, set);
    for (const set of wanted.values()) {
      targets.push({ artifactSetIds: [set.uuid], setIds: [set.setId], label: set.name });
    }
    return targets;
  }

  /**
   * Put a name and a uuid on each refused set, so the page can offer the calibration.
   *
   * A set with no catalogue entry is **dropped rather than offered**: without its uuid nothing
   * could calibrate it, and a button that cannot work is worse than an absent one.
   */
  private async nameSets(
    counts: readonly (readonly [number, number])[],
  ): Promise<{ setId: number; uuid: string; name: string; pieces: number }[]> {
    if (!counts.length) return [];
    const catalogue = await this.optimize.artifactSets();
    return counts
      .map(([setId, pieces]) => {
        const entry = catalogue.get(setId);
        return entry ? { setId, uuid: entry.id, name: entry.name, pieces } : null;
      })
      .filter((row): row is { setId: number; uuid: string; name: string; pieces: number } =>
        row !== null)
      .sort((a, b) => b.pieces - a.pieces);
  }

  private readonly optimize = inject(OptimizeService);
  private readonly artifacts = inject(ArtifactsService);
  private readonly recipes = inject(RecipeOptimizeService);

  /**
   * Score every owned piece against one build, in its own slot.
   *
   * ## Three 4-piece states, not one
   *
   * A.9, and it is bigger than "handle cross-set pieces". Swapping a piece changes **which
   * recipe applies**, not just the stats fed to one, and there are three states in play:
   *
   * - **the build's current 4-piece**, if it has one. This is the honest baseline. The first
   *   draft calibrated only the no-4-piece state, so a build wearing 4-piece Emblem was scored
   *   under a recipe missing its own bonus — and not uniformly, because a set bonus interacts
   *   with the stats rather than adding to them.
   * - **no 4-piece**, which is what a set-breaking swap actually produces.
   * - **a different 4-piece** the candidate would complete. Calibrated on demand when the
   *   caller asks (`extraSets`); refused with `needsCalibration` when it has not been.
   *
   * `scoreForSlot`'s `recipeAfterSwap` parameter was written for exactly this and had no caller
   * until now.
   */
  async rank(request: RankingRequest): Promise<RankingResult> {
    const snapshot = await this.optimize.inventory();
    const raw = snapshot.draw_model;
    if (!raw) {
      throw new Error(
        'the server sent no draw model, so nothing can be projected. Ranking is unavailable '
        + 'rather than approximate: a projection without roll ladders would be a confident '
        + 'number about nothing.',
      );
    }

    const worn = await this.artifacts.list({ build_id: request.buildId });
    const byId = new Map(snapshot.artifacts.map((c) => [c.id, c]));
    const wornBySlot = new Map(worn.items.map((piece) => [piece.slot, piece.id] as const));

    // **What the build wears has to be calibrated before anything can be scored**, and it is
    // not an "extra" set — it is the state the baseline is measured in. Driving the page found
    // this: the refusal below fired on a Nahida build wearing 4-piece Blizzard Strayer, which
    // is what a real build looks like. Calibrating only the no-4-piece baseline made the
    // feature unusable for most of them.
    const wornFourPiece = fourPieceSetOf(setCountsOf(wornBySlot, byId));
    const calibration = await this.recipes.calibrateAll(
      request.buildId,
      request.rotationId,
      snapshot.version,
      // **The baseline is a target, not the absence of one.** Passing `[]` here calibrated
      // nothing at all and `noFourPiece` came back null — which the refusal below caught, but
      // only after a real run in a browser. `/optimize`'s own comment says why: "it is not
      // optional and never was: every combination that reaches no 4-piece is scored against
      // it, so a search without it can rank nothing."
      await this.targetsFor(wornFourPiece, request.extraSets ?? []),
      request.onProgress ?? (() => undefined),
      undefined,
      request.waitForEnergy ?? false,
    );
    const noFourPiece = calibration.noFourPiece;
    if (!noFourPiece) {
      throw new Error(
        'the baseline recipe did not calibrate, so there is nothing to score against. This is '
        + 'a refusal rather than a fallback: a ranking computed off a recipe that is not this '
        + "build's would sort the inventory confidently and wrongly.",
      );
    }
    const model = drawModelFrom(raw);

    const wornIds = new Set(worn.items.map((piece) => piece.id));

    // The five slots the build is wearing, as the evaluator reads them. A slot with nothing in
    // it contributes an empty pool rather than being absent: the kernel takes five.
    const equipped: StatPool[] = SLOTS.map((slot) => {
      const id = wornBySlot.get(slot);
      const candidate = id ? byId.get(id) : undefined;
      return candidate ? candidate.stats : {};
    });
    const wornSetCounts = setCountsOf(wornBySlot, byId);
    // `undefined` from the map means the build's own 4-piece did not calibrate — a gcsim
    // failure rather than an omission, now that `targetsFor` always asks for it. Falling back
    // to `noFourPiece` would understate the build by its own set bonus, so it refuses.
    const recipe = wornFourPiece === null
      ? noFourPiece
      : calibration.byFourPieceSet.get(wornFourPiece);
    if (!recipe) {
      throw new Error(
        `the build wears a 4-piece set (${wornFourPiece}) that was not calibrated, so its own `
        + 'damage cannot be measured. Ranking against a recipe missing the build\'s own set '
        + 'bonus would understate every piece, and not uniformly.',
      );
    }

    const baseline = evaluateRecipe(recipe, candidateStatsFrom(equipped));

    const emptyBySlot = SLOTS.map((_slot, index) => {
      const bare = [...equipped];
      bare[index] = {};
      return evaluateRecipe(recipe, candidateStatsFrom(bare));
    });

    /**
     * Damage with only the piece's main stat in its slot — the grade's zero point.
     *
     * Keyed the same way the ideal is, and computed alongside it, because the two are the ends
     * of one scale and computing them in different places is how they would drift apart.
     */
    const mainOnlies = new Map<string, number>();

    // The grade's denominator does not vary per piece — only per slot, main stat and rarity —
    // so it is computed once per distinct triple rather than 2,370 times.
    const ideals = new Map<string, number>();

    const uncalibrated = new Map<number, number>();
    const rows: RankingRow[] = [];
    for (const candidate of snapshot.artifacts) {
      const slot = SLOTS.indexOf(candidate.slot as (typeof SLOTS)[number]);
      if (slot < 0) continue;

      // Which 4-piece state the build would be in with this piece equipped.
      const swappedCounts = { ...wornSetCounts };
      const outgoing = worn.items.find((piece) => piece.slot === candidate.slot);
      const outgoingSet = outgoing ? byId.get(outgoing.id)?.set_id : undefined;
      if (outgoingSet != null) swappedCounts[outgoingSet] = (swappedCounts[outgoingSet] ?? 1) - 1;
      if (candidate.set_id != null) {
        swappedCounts[candidate.set_id] = (swappedCounts[candidate.set_id] ?? 0) + 1;
      }
      const swappedFourPiece = fourPieceSetOf(swappedCounts);
      let afterSwap: Recipe | null | undefined;
      let needsSet: number | null = null;
      if (swappedFourPiece === wornFourPiece) {
        afterSwap = undefined;
      } else if (swappedFourPiece === null) {
        afterSwap = noFourPiece;
      } else {
        afterSwap = calibration.byFourPieceSet.get(swappedFourPiece) ?? null;
        if (afterSwap === null) {
          needsSet = swappedFourPiece;
          uncalibrated.set(swappedFourPiece, (uncalibrated.get(swappedFourPiece) ?? 0) + 1);
        }
      }
      const piece = pieceOf(candidate);
      const key = `${slot}:${candidate.main_stat}:${candidate.rarity}`;
      const mainStatValue = mainStatValueOf(candidate, piece.mainStatQuantity);
      let ideal = ideals.get(key);
      if (ideal === undefined) {
        ideal = idealFor(recipe, equipped, slot, {
          rarity: candidate.rarity,
          mainStatQuantity: piece.mainStatQuantity,
          mainStatValue,
          rollsTotal: candidate.potential?.rolls_total ?? 0,
        }, model);
        ideals.set(key, ideal);
        const bare = [...equipped];
        bare[slot] = piece.mainStatQuantity
          ? { [piece.mainStatQuantity]: mainStatValue }
          : {};
        mainOnlies.set(key, evaluateRecipe(recipe, candidateStatsFrom(bare)));
      }
      rows.push({
        ...rankArtifact(recipe, equipped, slot, { ...piece, id: candidate.id }, model, {
          baseline,
          ideal,
          emptySlot: emptyBySlot[slot],
          mainOnly: mainOnlies.get(key) ?? emptyBySlot[slot],
          afterSwap,
          needsSet,
        }),
        slot: candidate.slot,
        setId: candidate.set_id ?? null,
        level: candidate.level,
        rarity: candidate.rarity,
        equipped: wornIds.has(candidate.id),
        rollsRemaining: candidate.potential?.rolls_remaining ?? 0,
      });
    }

    return {
      rows,
      baseline,
      weightsCaveat: model.weightsCaveat,
      unreadable: snapshot.unreadable.map((row) => ({
        artifactId: row.artifact_id, reason: row.reason,
      })),
      uncalibratedSets: await this.nameSets([...uncalibrated]),
      caveats: {
        unstable: recipe.meta?.unstable ?? [],
        staleConversions: (recipe.meta?.staleConversions ?? []).map((c) => c.term),
      },
    };
  }

  /**
   * **The best build containing this piece, at its projected max level.** Issue #291's headline.
   *
   * This is the half a single-slot swap cannot answer. *"Assume that you can move other
   * artifacts"* is a re-optimization with the piece nailed down, not a substitution — and the
   * two are five orders of magnitude apart per piece, which is why the column triages and this
   * settles (`DESIGN_artifact_ranking.md` §8.1).
   *
   * **Neither Fribbels nor Genshin Optimizer offers it.** All five of Fribbels' per-relic
   * columns are single-piece scores against a weights vector, and GO's Artifact Upgrader says so
   * in its own UI: *"as it only swaps one artifact at a time, for the best overall build across
   * all artifacts, use the main artifact optimizer."* Both ship the two tools and no bridge
   * between them. This is the bridge.
   *
   * ## What it costs
   *
   * A pinned search, measured in `RESEARCH_pinned_search_cost.md`: the same
   * `COMBINATION_BUDGET_SECONDS = 5` walk the optimizer already runs, reaching ~47 candidates
   * per remaining slot against a free search's ~28. **Pinning does not make it faster, it makes
   * it deeper for the same money** — so this is not a slower optimizer, it is the same job asked
   * a narrower question. One piece at a time, deliberately: 2,370 of them would be three hours.
   */
  async deepDive(request: RankingRequest & { artifactId: string }): Promise<DeepDive> {
    const snapshot = await this.optimize.inventory();
    const raw = snapshot.draw_model;
    if (!raw) throw new Error('the server sent no draw model, so nothing can be projected');
    const model = drawModelFrom(raw);

    const target = snapshot.artifacts.find((c) => c.id === request.artifactId);
    if (!target) {
      throw new Error(`artifact ${request.artifactId} is not in the inventory snapshot`);
    }

    const worn = await this.artifacts.list({ build_id: request.buildId });
    const byId = new Map(snapshot.artifacts.map((c) => [c.id, c]));
    const wornBySlot = new Map(
      worn.items.map((piece) => [piece.slot, piece.id] as const),
    );
    const wornFour = fourPieceSetOf(setCountsOf(wornBySlot, byId));

    const calibration = await this.recipes.calibrateAll(
      request.buildId,
      request.rotationId,
      snapshot.version,
      await this.targetsFor(wornFour, request.extraSets ?? []),
      request.onProgress ?? (() => undefined),
      undefined,
      request.waitForEnergy ?? false,
    );
    const noFourPiece = calibration.noFourPiece;
    if (!noFourPiece) throw new Error('the baseline recipe did not calibrate');
    const equipped: StatPool[] = SLOTS.map((slot) => {
      const id = wornBySlot.get(slot);
      const candidate = id ? byId.get(id) : undefined;
      return candidate ? candidate.stats : {};
    });

    // The build's own 4-piece state decides which recipe describes it today — A.9's first
    // state, and the number every percentage below is *of*.
    const current = wornFour === null
      ? noFourPiece
      : calibration.byFourPieceSet.get(wornFour) ?? noFourPiece;
    const before = evaluateRecipe(current, candidateStatsFrom(equipped));

    // **Pinned at the piece's projected max-level stats**, because #291 asks about the artifact
    // "at max level". `average` rather than `best`: the expected outcome is the honest thing to
    // plan a resin spend around, and the ceiling is already on the card.
    const piece = pieceOf(target);
    const projection = projectPiece(piece, model);
    const projected = projection?.average ?? target.stats;

    // **Pieces in a slot the kernel does not search are dropped, not coerced.** The five slot
    // names are a closed set; a payload carrying a sixth is a piece this walk cannot place, and
    // casting it in would put it in whichever bucket the string happened to match.
    const searchable = new Set<string>(SLOTS);
    const all: Candidate[] = snapshot.artifacts
      .filter((c) => searchable.has(c.slot))
      .map((c) => ({
        id: c.id,
        slot: c.slot as (typeof SLOTS)[number],
        setId: c.set_id ?? 0,
        stats: c.stats,
      }));
    const candidates = trimForDive(all, target.id, current, equipped);
    const recipes = {
      noFourPiece,
      byFourPieceSet: calibration.byFourPieceSet,
      byPair: calibration.byPair,
    };

    const withPiece = searchRecipe(candidates, {
      recipes,
      topN: 1,
      pinned: {
        id: target.id,
        slot: target.slot as (typeof SLOTS)[number],
        setId: target.set_id ?? 0,
        stats: projected,
      },
    });
    // OQ-A10's other reading. Same inventory minus this piece, same budget.
    const without = searchRecipe(
      candidates.filter((c) => c.id !== target.id),
      { recipes, topN: 1 },
    );

    const winner = withPiece.builds[0];
    if (!winner) {
      throw new Error(
        'the pinned search found no build. That is a refusal rather than a zero: it means no '
        + '4-piece state containing this piece was calibrated, and a percentage computed from '
        + 'nothing would look like a real answer.',
      );
    }

    const moved: MovedPiece[] = SLOTS.map((slot, index) => {
      const toId = winner.artifactIds[index];
      const fromId = wornBySlot.get(slot) ?? null;
      return { slot, fromId, toId, changed: fromId !== toId };
    });

    return {
      before,
      after: winner.damage,
      gain: before > 0 ? (winner.damage - before) / before : 0,
      bestWithout: without.builds[0]?.damage ?? before,
      moved,
      projectedFrom: projection ? 'average' : 'current',
      searchedPerSlot: DIVE_PER_SLOT,
      inventorySize: all.length,
    };
  }
}

/**
 * Candidates per slot the deep dive searches.
 *
 * **Measured, not chosen**, and the first attempt at this had no cap at all.
 * `RESEARCH_pinned_search_cost.md`: the uncapped pinned search over the owner's real
 * 2,369-piece inventory **did not finish in 300 seconds**. After the Pareto filter the space is
 * 130 × 103 × 135 × 149 × 147, and pinning one slot still leaves ~3e8 combinations — further
 * than branch-and-bound prunes.
 *
 * Both searches run over the same pool, and the **free** one is the expensive half:
 *
 * | per slot | free | pinned |
 * |---:|---:|---:|
 * | 20 | 0.93 s | 0.11 s |
 * | **24** | **3.31 s** | **0.21 s** |
 * | 28 | 5.40 s | 0.33 s |
 * | 40 | 28.4 s | 1.29 s |
 *
 * 24 keeps the pair at ~3.5 s. They share a pool deliberately: `bestWithout` is only comparable
 * to `after` if both were chosen from the same candidates.
 *
 * **This makes the dive a best-of-this-pool rather than a proof**, which is why `DeepDive`
 * reports the number to the page. `searchRecipe` is still exhaustive over what it is handed and
 * still says `isExact: true` — that claim is about the pool, and trimming silently would turn it
 * into a claim about the inventory that is not true.
 */
const DIVE_PER_SLOT = 24;

/**
 * The best `DIVE_PER_SLOT` pieces per slot for this build, plus the pinned one whatever it is.
 *
 * Ranked by what each piece is worth **in this build**, which is the same single-slot swap the
 * column already computes — 12 µs a piece, so trimming the whole inventory costs about 28 ms
 * against a search that would otherwise not terminate.
 *
 * **The pinned piece is kept unconditionally.** It is very often not in the top 40 — that is
 * usually the whole reason someone is asking about it — and dropping it here would produce a
 * search that silently answered a different question, which is the same failure the pin's own
 * placement after the Pareto filter exists to avoid.
 */
function trimForDive(
  candidates: readonly Candidate[],
  pinnedId: string,
  recipe: Recipe,
  equipped: readonly StatPool[],
): Candidate[] {
  const bySlot = new Map<string, Candidate[]>();
  for (const candidate of candidates) {
    const bucket = bySlot.get(candidate.slot) ?? [];
    bucket.push(candidate);
    bySlot.set(candidate.slot, bucket);
  }

  const out: Candidate[] = [];
  for (const [slot, bucket] of bySlot) {
    const index = SLOTS.indexOf(slot as (typeof SLOTS)[number]);
    if (index < 0) continue;
    const scored = scoreForSlot(
      recipe,
      equipped,
      bucket.map((c) => ({ id: c.id, stats: c.stats })),
      index,
    );
    const rank = new Map(scored.map((row) => [row.id, row.score.damage]));
    const kept = [...bucket]
      .sort((a, b) => (rank.get(b.id) ?? 0) - (rank.get(a.id) ?? 0))
      .slice(0, DIVE_PER_SLOT);
    if (!kept.some((c) => c.id === pinnedId)) {
      const pinned = bucket.find((c) => c.id === pinnedId);
      if (pinned) kept.push(pinned);
    }
    out.push(...kept);
  }
  return out;
}

/**
 * How many pieces of each set a build is wearing.
 *
 * One definition, used by both `rank` and `deepDive`. It was written twice first, and the two
 * copies are exactly the sort that drift into disagreeing about what a build is wearing.
 */
function setCountsOf(
  wornBySlot: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, KernelCandidate>,
): Record<number, number> {
  const counts: Record<number, number> = {};
  for (const slot of SLOTS) {
    const setId = byId.get(wornBySlot.get(slot) ?? '')?.set_id;
    if (setId != null) counts[setId] = (counts[setId] ?? 0) + 1;
  }
  return counts;
}

/**
 * The wire shape into the module's shape.
 *
 * **A cast would not have done.** The payload is snake_case and `DrawModel` is camelCase, and
 * TypeScript rejected the cast rather than letting `rollTiers` arrive `undefined` — at which
 * point every ladder lookup would have missed and every piece would have projected to itself,
 * silently, with a full set of plausible numbers.
 */
function drawModelFrom(raw: NonNullable<InventorySnapshot['draw_model']>): DrawModel {
  return {
    rollTiers: Object.fromEntries(
      Object.entries(raw.roll_tiers).map(([rarity, ladders]) => [
        rarity,
        ladders.map((ladder) => ({ quantity: ladder.quantity, values: ladder.values })),
      ]),
    ),
    substatWeights: raw.substat_weights,
    weightsCaveat: raw.weights_caveat,
  };
}

/**
 * The main stat's own contribution, recovered from the summed pool.
 *
 * The payload sums the main stat and substats into one map, so the main stat's value has to be
 * backed out — its pool entry **minus** whatever the substat lines of the same quantity carry.
 * In practice a piece never has a substat of its own main stat, so this is the pool entry; the
 * subtraction is here because relying on "in practice" is how a quiet double-count starts.
 */
function mainStatValueOf(candidate: KernelCandidate, quantity: string | null): number {
  if (!quantity) return 0;
  const lines = candidate.potential?.substat_quantities ?? [];
  return lines.includes(quantity) ? 0 : (candidate.stats[quantity] ?? 0);
}

function pieceOf(candidate: KernelCandidate): Piece {
  const lines = candidate.potential?.substat_quantities ?? [];
  // The main stat as a kernel quantity: whichever pooled entry is not a substat line. The raw
  // `main_stat` is a `FIGHT_PROP_*` key and the projection speaks quantities; translating it
  // here would be a second copy of `_quantity_for_prop`, which is the one thing the payload
  // design exists to prevent.
  const mainStatQuantity = Object.keys(candidate.stats).find((q) => !lines.includes(q)) ?? null;
  return {
    rarity: candidate.rarity,
    stats: candidate.stats,
    mainStatQuantity,
    potential: candidate.potential
      ? {
          rollsRemaining: candidate.potential.rolls_remaining,
          rollsTotal: candidate.potential.rolls_total,
          gainsASubstat: candidate.potential.gains_a_substat,
          substatQuantities: lines,
        }
      : null,
  };
}
