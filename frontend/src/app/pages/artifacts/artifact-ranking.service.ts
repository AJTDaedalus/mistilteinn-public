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

import { type StatPool } from '../../sim/artifact-score';
import { type DrawModel, type Piece } from '../../sim/artifact-projection';
import { type RankedArtifact, idealFor, rankArtifact } from '../../sim/artifact-ranking';
import { evaluateRecipe } from '../../sim/recipe-eval';
import { candidateStatsFrom } from '../../sim/recipe-search';
import { SLOTS } from '../../sim/search';
import {
  type CalibrationProgress,
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
  caveats: { unstable: string[]; staleConversions: string[] };
}

/** What `rank` needs to know before it can start. */
export interface RankingRequest {
  buildId: string;
  rotationId: string;
  onProgress?: (progress: CalibrationProgress) => void;
  waitForEnergy?: boolean;
}

@Injectable({ providedIn: 'root' })
export class ArtifactRankingService {
  private readonly optimize = inject(OptimizeService);
  private readonly artifacts = inject(ArtifactsService);
  private readonly recipes = inject(RecipeOptimizeService);

  /**
   * Score every owned piece against one build, in its own slot.
   *
   * **Only the no-four-piece recipe is calibrated here.** A candidate that would complete a
   * different set is a different *recipe*, not different stats, and A.9 is where that gets its
   * own calibration on demand. Scoring a cross-set piece under this recipe would credit a bonus
   * the swapped build would not have — the failure `artifact-score.ts` documents and
   * `scoreForSlot`'s `recipeAfterSwap` exists to discharge.
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

    const calibration = await this.recipes.calibrateAll(
      request.buildId,
      request.rotationId,
      snapshot.version,
      // **The baseline is a target, not the absence of one.** Passing `[]` here calibrated
      // nothing at all and `noFourPiece` came back null — which the refusal below caught, but
      // only after a real run in a browser. `/optimize`'s own comment says why: "it is not
      // optional and never was: every combination that reaches no 4-piece is scored against
      // it, so a search without it can rank nothing."
      [{ artifactSetIds: [], setIds: [], label: 'the baseline (no 4-piece bonus)' }],
      request.onProgress ?? (() => undefined),
      undefined,
      request.waitForEnergy ?? false,
    );
    const recipe = calibration.noFourPiece;
    if (!recipe) {
      throw new Error(
        'the baseline recipe did not calibrate, so there is nothing to score against. This is '
        + 'a refusal rather than a fallback: a ranking computed off a recipe that is not this '
        + "build's would sort the inventory confidently and wrongly.",
      );
    }
    const model = drawModelFrom(raw);

    const worn = await this.artifacts.list({ build_id: request.buildId });
    const wornIds = new Set(worn.items.map((piece) => piece.id));
    const byId = new Map(snapshot.artifacts.map((c) => [c.id, c]));

    // The five slots the build is wearing, as the evaluator reads them. A slot with nothing in
    // it contributes an empty pool rather than being absent: the kernel takes five.
    const equipped: StatPool[] = SLOTS.map((slot) => {
      const found = worn.items.find((piece) => piece.slot === slot);
      const candidate = found ? byId.get(found.id) : undefined;
      return candidate ? candidate.stats : {};
    });
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

    const rows: RankingRow[] = [];
    for (const candidate of snapshot.artifacts) {
      const slot = SLOTS.indexOf(candidate.slot as (typeof SLOTS)[number]);
      if (slot < 0) continue;
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
      caveats: {
        unstable: recipe.meta?.unstable ?? [],
        staleConversions: (recipe.meta?.staleConversions ?? []).map((c) => c.term),
      },
    };
  }
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
