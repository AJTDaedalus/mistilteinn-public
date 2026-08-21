import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type TeamRead = components['schemas']['TeamRead'];
export type TeamUpdate = components['schemas']['TeamUpdate'];

export interface TeamCreatePayload {
  name?: string;
  build1_id: string;
  build2_id?: string | null;
  build3_id?: string | null;
}

@Injectable({ providedIn: 'root' })
export class TeamsService {
  private api = injectApi();

  async list(): Promise<TeamRead[]> {
    const { data, error } = await this.api.GET('/api/v1/teams', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  async get(id: string): Promise<TeamRead> {
    const { data, error } = await this.api.GET('/api/v1/teams/{team_id}', {
      params: { path: { team_id: id } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async create(body: TeamCreatePayload): Promise<TeamRead> {
    const { data, error } = await this.api.POST('/api/v1/teams', {
      body: {
        name: body.name ?? '',
        build1_id: body.build1_id,
        build2_id: body.build2_id ?? null,
        build3_id: body.build3_id ?? null,
      },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async update(id: string, body: TeamUpdate): Promise<TeamRead> {
    const { data, error } = await this.api.PATCH('/api/v1/teams/{team_id}', {
      params: { path: { team_id: id } },
      body,
    });
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/teams/{team_id}', {
      params: { path: { team_id: id } },
    });
    if (error) throw new Error(JSON.stringify(error));
  }
}
