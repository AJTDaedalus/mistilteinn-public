import { Injectable, inject } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';
import { BuffContextStore } from '../../shared/buff-context.store';

export type BuildRead = components['schemas']['BuildRead'];
export type ComboRead = components['schemas']['ComboRead'];
export type EnemyProfileRead = components['schemas']['EnemyProfileRead'];
export type TeamRead = components['schemas']['TeamRead'];
export type SimulationResponse = components['schemas']['SimulationResponse'];

@Injectable({ providedIn: 'root' })
export class CalculateService {
  private api = injectApi();
  private buffContext = inject(BuffContextStore);

  async listBuilds(): Promise<BuildRead[]> {
    const { data, error } = await this.api.GET('/api/v1/builds', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async listTeams(): Promise<TeamRead[]> {
    const { data, error } = await this.api.GET('/api/v1/teams', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async listTeamCombos(teamId: string): Promise<ComboRead[]> {
    const { data, error } = await this.api.GET('/api/v1/combos', {
      params: { query: { team_id: teamId, limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async listEnemies(): Promise<EnemyProfileRead[]> {
    const { data, error } = await this.api.GET('/api/v1/enemies', {
      params: { query: { limit: 1000 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async listAgents(): Promise<components['schemas']['AgentSummary'][]> {
    const { data, error } = await this.api.GET('/api/v1/agents', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async simulate(
    teamBuilds: Record<string, string>,
    steps: {
      agent_id: string;
      move_name: string;
      conditions: string[];
      variant_label?: string | null;
      single_tap?: boolean | null;
      cycle_position?: number | null;
    }[],
    enemyProfileId: string,
  ): Promise<SimulationResponse> {
    const { data, error } = await this.api.POST('/api/v1/simulate', {
      body: {
        team_builds: teamBuilds,
        steps: steps,
        enemy_profile_id: enemyProfileId,
        buff_context: this.buffContext.context(),
      },
    });
    if (error) throw new Error(JSON.stringify(error));
    // openapi-fetch widens the ``field_timeline`` tuple ([number, string])
    // to (number | string)[] on the response object, so the inferred ``data``
    // type is structurally distinct from the named SimulationResponse schema.
    // The runtime payload matches the schema; assert it back.
    return data as SimulationResponse;
  }
}
