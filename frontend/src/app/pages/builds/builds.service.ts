import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type BuildRead = components['schemas']['BuildRead'];
export type AgentSummary = components['schemas']['AgentSummary'];
export type WEngineSummary = components['schemas']['WEngineSummary'];
export type DiscRead = components['schemas']['DiscRead'];
export type DiscSetRead = components['schemas']['DiscSetSummary'];
export type BuildBuffsResponse = components['schemas']['BuildBuffsResponse'];
export type BuffGroup = components['schemas']['BuffGroup'];
export type BuffDescriptor = components['schemas']['BuffDescriptor'];
export type BuildConditionItem = components['schemas']['BuildConditionItem'];

export interface DiscListFilters {
  slot?: number;
  set_id?: string;
  rarity?: string;
  /** 'any' | 'unequipped' | build_id */
  equipped?: string;
  offset?: number;
  limit?: number;
}

export interface BuildCreatePayload {
  agent_id: string;
  w_engine_id?: string | null;
  w_engine_level?: number;
  w_engine_refinement?: number;
  mindscape_level?: number;
  core_skill_level?: number;
  potential_rank?: number;
  agent_level?: number;
  skill_levels?: string;
  notes?: string;
}

export interface BuildUpdatePayload {
  w_engine_id?: string | null;
  w_engine_level?: number | null;
  w_engine_refinement?: number | null;
  mindscape_level?: number | null;
  core_skill_level?: number | null;
  potential_rank?: number | null;
  agent_level?: number | null;
  skill_levels?: string | null;
  notes?: string | null;
  disabled_buffs?: string[] | null;
  active_conditions?: string[] | null;
  stack_counts?: Record<string, number> | null;
}

@Injectable({ providedIn: 'root' })
export class BuildsService {
  private api = injectApi();

  async list(): Promise<BuildRead[]> {
    const { data, error } = await this.api.GET('/api/v1/builds', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async get(id: string): Promise<BuildRead> {
    const { data, error } = await this.api.GET('/api/v1/builds/{build_id}', {
      params: { path: { build_id: id } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async create(body: BuildCreatePayload): Promise<BuildRead> {
    const { data, error } = await this.api.POST('/api/v1/builds', {
      body: {
        agent_id: body.agent_id,
        w_engine_id: body.w_engine_id ?? null,
        w_engine_level: body.w_engine_level ?? 60,
        w_engine_refinement: body.w_engine_refinement ?? 1,
        mindscape_level: body.mindscape_level ?? 0,
        core_skill_level: body.core_skill_level ?? 5,
        // Rank 5 = Potential fully unlocked, matching the server default and the
        // numbers fairy produced unconditionally before #90.
        potential_rank: body.potential_rank ?? 5,
        agent_level: body.agent_level ?? 60,
        skill_levels: body.skill_levels ?? '12,12,12,12,12',
        notes: body.notes ?? '',
      },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async update(id: string, body: BuildUpdatePayload): Promise<BuildRead> {
    const { data, error } = await this.api.PATCH(
      '/api/v1/builds/{build_id}',
      { params: { path: { build_id: id } }, body },
    );
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/builds/{build_id}', {
      params: { path: { build_id: id } },
    });
    if (error) throw new Error(JSON.stringify(error));
  }

  // ---- Reference data needed by the editor ------------------------------

  async listAgents(): Promise<AgentSummary[]> {
    const { data, error } = await this.api.GET('/api/v1/agents', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async listWEngines(): Promise<WEngineSummary[]> {
    const { data, error } = await this.api.GET('/api/v1/w-engines', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async listDiscSets(): Promise<DiscSetRead[]> {
    const { data, error } = await this.api.GET('/api/v1/disc-sets', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  /** Fetch discs with optional server-side filtering.
   *
   * Auto-paginates until all results are collected. Uses a page size of 3000
   * (the in-game per-account cap) so a typical inventory fits in one round-trip;
   * additional pages are fetched if the inventory exceeds that. */
  async listDiscs(filters: DiscListFilters = {}): Promise<DiscRead[]> {
    const pageSize = filters.limit ?? 3000;
    const all: DiscRead[] = [];
    let offset = filters.offset ?? 0;
    for (;;) {
      const { data, error } = await this.api.GET('/api/v1/discs', {
        params: {
          query: {
            limit: pageSize,
            offset,
            slot: filters.slot,
            set_id: filters.set_id,
            rarity: filters.rarity,
            equipped: filters.equipped,
          },
        },
      });
      if (error) throw new Error(JSON.stringify(error));
      all.push(...data.items);
      if (data.items.length < pageSize) break;
      offset += pageSize;
    }
    return all;
  }

  /** Discs available for this build's slot pickers (unequipped + this build's). */
  async listDiscsForBuild(buildId: string | null): Promise<DiscRead[]> {
    return this.listDiscs({ equipped: buildId ?? 'unequipped' });
  }

  async listUnequippedDiscs(): Promise<DiscRead[]> {
    return this.listDiscs({ equipped: 'unequipped' });
  }

  async listBuffs(buildId: string): Promise<BuildBuffsResponse> {
    const { data, error } = await this.api.GET(
      '/api/v1/builds/{build_id}/buffs',
      { params: { path: { build_id: buildId } } },
    );
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async listConditions(buildId: string): Promise<BuildConditionItem[]> {
    const { data, error } = await this.api.GET(
      '/api/v1/builds/{build_id}/conditions',
      { params: { path: { build_id: buildId } } },
    );
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async equipDisc(
    buildId: string, slot: number, discId: string | null,
  ): Promise<void> {
    const { error } = await this.api.PUT(
      '/api/v1/builds/{build_id}/discs/{slot}',
      {
        params: { path: { build_id: buildId, slot } },
        body: { disc_id: discId },
      },
    );
    if (error) throw new Error(JSON.stringify(error));
  }

  async setPriorityOrder(orderedBuildIds: string[]): Promise<BuildRead[]> {
    const { data, error } = await this.api.PUT('/api/v1/builds/priority', {
      body: { ordered_build_ids: orderedBuildIds },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  /** PATCH /api/v1/builds/{id}/equip-discs — atomically replace all 6 disc slots. */
  async equipAll(buildId: string, discs: Record<number, string>): Promise<BuildRead> {
    const { data, error } = await this.api.PATCH(
      '/api/v1/builds/{build_id}/equip-discs',
      {
        params: { path: { build_id: buildId } },
        body: { discs } as { discs: Record<string, string> },
      },
    );
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }
}
