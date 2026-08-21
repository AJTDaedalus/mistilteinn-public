import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type ComboRead = components['schemas']['ComboRead'];
export type AttackRead = components['schemas']['AttackRead'];
export type TeamCalculateRequest = components['schemas']['TeamCalculateRequest'];
export type TeamCalculateResponse = components['schemas']['TeamCalculateResponse'];

export interface ComboStep {
  /** Either move_name or attack_id should be set; move_name expands to
   *  every hit sharing that name on the build's agent at calc time.
   *  Marker steps (step_type='stun_trigger'|'stun_end') have no move_name/attack_id. */
  label: string;
  agent_id?: string;
  step_type?: string;
  move_name?: string;
  attack_id?: string;
  /** For variant moves: selects which game-state context to use. */
  variant_label?: string;
  /** For sequential moves: false (full chain, default) or true (single-press). */
  single_tap?: boolean;
  /** Optional: explicit cycle position override for single-tap sequential. */
  cycle_position?: number;
}

export interface ComboCreatePayload {
  name: string;
  team_id: string;
  sequence: ComboStep[];
  description?: string;
}

export interface ComboUpdatePayload {
  name?: string | null;
  sequence?: ComboStep[] | null;
  description?: string | null;
}

function toApiStep(s: ComboStep) {
  return { ...s, single_tap: s.single_tap ?? false };
}

@Injectable({ providedIn: 'root' })
export class CombosService {
  private api = injectApi();

  async get(id: string): Promise<ComboRead> {
    const { data, error } = await this.api.GET('/api/v1/combos/{combo_id}', {
      params: { path: { combo_id: id } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async listForBuild(buildId: string): Promise<ComboRead[]> {
    const { data, error } = await this.api.GET('/api/v1/combos', {
      params: { query: { build_id: buildId, limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async listForTeam(teamId: string): Promise<ComboRead[]> {
    const { data, error } = await this.api.GET('/api/v1/combos', {
      params: { query: { team_id: teamId, limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async evaluateTeam(
    teamId: string,
    body: TeamCalculateRequest,
  ): Promise<TeamCalculateResponse> {
    const { data, error } = await this.api.POST(
      '/api/v1/teams/{team_id}/calculate',
      { params: { path: { team_id: teamId } }, body },
    );
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async create(payload: ComboCreatePayload): Promise<ComboRead> {
    const { data, error } = await this.api.POST('/api/v1/combos', {
      body: {
        name: payload.name,
        team_id: payload.team_id,
        sequence: payload.sequence.map(toApiStep),
        description: payload.description ?? '',
      },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async update(id: string, patch: ComboUpdatePayload): Promise<ComboRead> {
    const { data, error } = await this.api.PATCH(
      '/api/v1/combos/{combo_id}',
      {
        params: { path: { combo_id: id } },
        body: { ...patch, sequence: patch.sequence?.map(toApiStep) ?? null },
      },
    );
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/combos/{combo_id}', {
      params: { path: { combo_id: id } },
    });
    if (error) throw new Error(JSON.stringify(error));
  }

  /** Fetches the agent's full payload and pulls out the attacks list. */
  async getAgentAttacks(agentId: string): Promise<AttackRead[]> {
    const { data, error } = await this.api.GET(
      '/api/v1/agents/{agent_id}',
      { params: { path: { agent_id: agentId } } },
    );
    if (error) throw new Error(JSON.stringify(error));
    return data.attacks ?? [];
  }
}
