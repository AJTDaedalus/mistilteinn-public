import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';
import type { AvailableHit } from '../explain/explain.service';

export type SearchContext = components['schemas']['SearchContextRead'];
export type InventorySnapshot = components['schemas']['InventorySnapshot'];
export type KernelCandidate = components['schemas']['KernelCandidate'];
export type UnreadableArtifact = components['schemas']['UnreadableArtifact'];
export type { AvailableHit };

/**
 * The two halves the browser kernel needs, and nothing else.
 *
 * Neither is computed here. `search.ts` reads quantities like `flat_atk`; the API speaks
 * `FIGHT_PROP_*`; and the mapping between them decides what every stat means. O.1 and O.2
 * exist so that translation happens once, on the server, rather than twice.
 */
/** What the set filter needs to draw one set: its name, its art, and what its 4-piece does. */
export interface ArtifactSetChoice {
  id: string;
  name: string;
  icon: string | null | undefined;
  fourPieceText: string | null;
  /** Whether gcsim implements it at the pin. A set it does not cannot be calibrated. */
  simulable: boolean;
}

@Injectable({ providedIn: 'root' })
export class OptimizeService {
  private api = injectApi();

  /**
   * The per-build, per-hit half: base, set bonuses, target, hit.
   *
   * Takes the same body as `/explain` because it is the same description of the same hit —
   * two request shapes for one description is how they drift apart.
   */
  async context(
    buildId: string,
    hit: { talent: AvailableHit['talent']; label: string; index: number },
    channel: string,
    scope: string,
    enemyLevel: number,
  ): Promise<SearchContext> {
    const { data, error } = await this.api.POST('/api/v1/builds/{build_id}/search-context', {
      params: { path: { build_id: buildId } },
      body: {
        hit: { channel, scope, talent: hit, scaling_stat: 'atk', flat_damage: 0 },
        enemy: { level: enemyLevel, resistances: {}, default_resistance: 0.1 },
        compare_to_equipped: false,
      },
    });
    if (error) throw error;
    return data;
  }

  /**
   * The whole inventory at one instant, kernel-ready.
   *
   * Not paged: a search needs one instant, and four paged round-trips have no such instant —
   * a concurrent import shifts every offset under the reader. The endpoint is ETag'd for
   * exactly this reason (OQ-S3).
   */
  async inventory(): Promise<InventorySnapshot> {
    const { data, error } = await this.api.GET('/api/v1/artifacts/inventory');
    if (error) throw new Error('Could not load your artifacts');
    return data;
  }

  /**
   * Every tier of every set the caller owns a piece of, in kernel terms.
   *
   * **Its own endpoint, not `search-context`.** That one returns these too but requires a
   * *hit*, and the rotation objective has none — it scores a whole gcsim run rather than one
   * Cutting DMG. Passing a hit purely to reach the bonuses would couple the two paths.
   *
   * A conditional tier arrives with **empty** `stats`: nine of the sixty 2-piece affixes have
   * no static props, six of them ability-scoped DMG bonuses a flat stat pool cannot express.
   * They are not omitted, so a caller can see that a bonus exists and is not being scored.
   */
  async setBonuses(): Promise<components['schemas']['KernelSetBonus'][]> {
    const { data, error } = await this.api.GET('/api/v1/artifacts/set-bonuses');
    if (error) throw new Error('Could not load artifact set bonuses');
    return data;
  }

  /**
   * The set catalogue, keyed by the id an artifact carries.
   *
   * **Two ids, and the difference is load-bearing.** An inventory snapshot's `set_id` is the
   * *nanoka* id (15003); `POST /builds/{id}/calibrate` resolves `artifact_set_id` with
   * `get_by_id`, which wants the catalogue **uuid**. Passing the nanoka id through 404s on
   * every 4-piece calibration — which is what the page did until this map carried both.
   *
   * The name is here for the same round trip, because the inventory publishes no name and a
   * filter built from `set_id` alone would offer the user "set 15003".
   *
   * One request: there are 65 sets and the page cap is 200.
   */
  async artifactSets(): Promise<Map<number, ArtifactSetChoice>> {
    const { data, error } = await this.api.GET('/api/v1/artifact-sets', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error('Could not load artifact sets');
    return new Map(data.items.map((set) => [set.nanoka_id, {
      id: set.id,
      name: set.name,
      icon: set.icon,
      // The 4-piece bonus in the set's own words. It is what anyone is choosing between, and
      // the card is too small to print it — so it is the card's tooltip.
      fourPieceText: set.affixes?.find((a) => a.pieces_required === 4)?.description ?? null,
      // `?? true`: **absent is unknown, not known-bad.** `optimize.ts` guards with `!== false`
      // for exactly that reason, and defaulting to `false` here defeated it before that guard
      // ever ran — an older backend, or a cached response predating the field, would make
      // every set unsimulable and empty the picker.
      simulable: set.simulable ?? true,
    }]));
  }
}
