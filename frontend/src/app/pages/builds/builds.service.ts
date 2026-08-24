import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';
import type { CharacterSummary, WeaponSummary } from '../catalogue/catalogue.service';
import { allPages } from '../../api/all-pages';

export type BuildRead = components['schemas']['BuildRead'];
export type BuildOptions = components['schemas']['BuildOptions'];
export type { CharacterSummary, WeaponSummary };

/** Everything the form sends. Levels are numbers the server bounds; it is not asked twice. */
export interface BuildFields {
  character_level: number;
  ascension_phase: number;
  weapon_level: number;
  refinement: number;
  constellation_level: number;
  talent_levels: Record<string, number>;
  notes: string;
}

/**
 * Reads and writes of saved builds — T.1/T.2's endpoints.
 *
 * `weapon_type` is the source's internal spelling (`WEAPON_SWORD_ONE_HAND`), so it is what
 * the weapon filter takes; `weapon_type_display` is what a person reads. Both come from the
 * server, because deriving the second from the first here would be a copy of
 * `WeaponType.display`.
 */
@Injectable({ providedIn: 'root' })
export class BuildsService {
  private api = injectApi();

  /** The talent keys a build may carry, and the level cap the validator enforces. */
  async options(): Promise<BuildOptions> {
    const { data, error } = await this.api.GET('/api/v1/builds/options');
    if (error) throw new Error('Could not load the build form');
    return data;
  }

  /** Every build, gathered a page at a time — see `allPages` on why not one request. */
  async list(): Promise<BuildRead[]> {
    const page = await allPages<BuildRead>(async (offset, limit) => {
      const { data, error } = await this.api.GET('/api/v1/builds', {
        params: { query: { offset, limit } },
      });
      if (error) throw new Error('Could not load builds');
      return data;
    });
    return page.items;
  }

  async create(body: BuildFields & { character_id: string; weapon_id: string | null }) {
    const { data, error } = await this.api.POST('/api/v1/builds', { body });
    if (error) throw error;
    return data;
  }

  /**
   * `character_id` is deliberately absent from the patch type.
   *
   * `BuildUpdate` has no such field and now **refuses** one rather than dropping it silently
   * (T.1) — sending it used to return 200 having changed nothing. Changing a build's
   * character makes it a different build.
   */
  async update(id: string, body: Partial<BuildFields> & { weapon_id?: string | null }) {
    const { data, error } = await this.api.PATCH('/api/v1/builds/{build_id}', {
      params: { path: { build_id: id } },
      body,
    });
    if (error) throw error;
    return data;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/builds/{build_id}', {
      params: { path: { build_id: id } },
    });
    if (error) throw error;
  }
}
