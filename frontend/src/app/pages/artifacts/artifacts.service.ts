import { Injectable } from '@angular/core';

import { allPages } from '../../api/all-pages';
import { injectApi } from '../../api/api.client';
import type { components, paths } from '../../api/api.types';

export type ArtifactRead = components['schemas']['ArtifactRead'];
export type ArtifactOptions = components['schemas']['ArtifactOptions'];
export type GoodImportResponse = components['schemas']['GoodImportResponse'];
export type ImportMode = components['schemas']['GoodImportRequest']['mode'];

/**
 * The five slot keys, taken from the endpoint's own query type.
 *
 * `ArtifactRead.slot` is typed `string` because the schema says so, but the *filter* is an
 * enum — so this is where the five are actually named in the contract, and taking them from
 * here means a page cannot pass a slot the endpoint would reject.
 */
export type ArtifactSlotKey = NonNullable<
  NonNullable<paths['/api/v1/artifacts']['get']['parameters']['query']>['slot']
>;

/**
 * Reads and writes of the caller's artifacts.
 *
 * `slot` and `main_stat_type` carry the source's internal spellings and the stored values are
 * units-dependent, so nothing here renders a piece — `options()` supplies the vocabulary and
 * the page looks pieces up in it. A page translating those itself would be a second copy of
 * `StatType.display` and `is_percentage`.
 */
@Injectable({ providedIn: 'root' })
export class ArtifactsService {
  private api = injectApi();

  /** Stat and slot labels, and which values are fractions. One request, not one per row. */
  async options(): Promise<ArtifactOptions> {
    const { data, error } = await this.api.GET('/api/v1/artifacts/options');
    if (error) throw new Error('Could not load the artifact vocabulary');
    return data;
  }

  async list(
    filters: {
      slot?: ArtifactSlotKey;
      set_id?: string;
      equipped?: boolean;
      build_id?: string;
      /**
       * Specific pieces. **An empty array asks for none of them, not for all of them** —
       * which is what the server means by it too, so a caller with nothing to fetch should
       * skip the call rather than pass `[]` and hope.
       */
      ids?: string[];
    } = {},
  ) {
    return allPages<ArtifactRead>(async (offset, limit) => {
      const { data, error } = await this.api.GET('/api/v1/artifacts', {
        params: { query: { ...filters, offset, limit } },
      });
      if (error) throw new Error('Could not load artifacts');
      return data;
    });
  }

  /**
   * Import a GOOD export.
   *
   * `mode` is a **required parameter with no default here either**. The API refuses to
   * assume, because `replace` and `append` are different intentions and GOOD carries no
   * stable per-artifact id to merge on — so defaulting it in the client would be this layer
   * quietly deciding whether to delete someone's inventory.
   */
  async importGood(
    mode: ImportMode,
    payload: unknown,
    rebuildBuilds = false,
  ): Promise<GoodImportResponse> {
    const { data, error } = await this.api.POST('/api/v1/artifacts/import/good', {
      body: {
        mode,
        payload: payload as Record<string, never>,
        // Off unless asked. The export can reconstitute a build per equipped character, but
        // that writes rows outside the inventory the caller came here for.
        rebuild_builds: rebuildBuilds,
      },
    });
    if (error) throw error;
    return data;
  }

  /** One piece, by id. Used to learn who currently holds it before moving it. */
  async get(id: string): Promise<ArtifactRead> {
    const { data, error } = await this.api.GET('/api/v1/artifacts/{artifact_id}', {
      params: { path: { artifact_id: id } },
    });
    if (error) throw error;
    return data;
  }

  /**
   * Attach a piece to a build, or take it off with `null`.
   *
   * A filled slot is **refused, naming the holder** (A.1) rather than swapped — so the
   * caller's picker must offer only pieces that fit, and this is where its refusals come
   * back when it does not.
   */
  async equip(id: string, buildId: string | null): Promise<ArtifactRead> {
    const { data, error } = await this.api.PATCH('/api/v1/artifacts/{artifact_id}', {
      params: { path: { artifact_id: id } },
      body: { build_id: buildId },
    });
    if (error) throw error;
    return data;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/artifacts/{artifact_id}', {
      params: { path: { artifact_id: id } },
    });
    if (error) throw error;
  }

}
