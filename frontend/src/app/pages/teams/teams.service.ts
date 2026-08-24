import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import { MAX_PAGE_LIMIT } from '../../api/page-size';
import type { components } from '../../api/api.types';

export type TeamRead = components['schemas']['TeamRead'];

/**
 * The team's four slot fields, in party order.
 *
 * Mirrors the server's `TEAM_SLOTS`, which is itself one definition replacing four
 * hand-written lists — the fork carried ZZZ's three-agent squad into a game with four-character
 * parties and every copy had to be found. `teams.spec.ts` checks this against the committed
 * `openapi.json` rather than trusting the mirror.
 */
export const TEAM_SLOTS = ['build1_id', 'build2_id', 'build3_id', 'build4_id'] as const;
export type TeamSlot = (typeof TEAM_SLOTS)[number];

/** Reads and writes of teams — the four-slot party a rotation is authored against. */
@Injectable({ providedIn: 'root' })
export class TeamsService {
  private api = injectApi();

  async list(): Promise<TeamRead[]> {
    const { data, error } = await this.api.GET('/api/v1/teams', {
      params: { query: { limit: MAX_PAGE_LIMIT } },
    });
    if (error) throw new Error('Could not load teams');
    return data.items;
  }

  async create(body: { name: string } & Partial<Record<TeamSlot, string | null>>) {
    const { data, error } = await this.api.POST('/api/v1/teams', {
      // `build1_id` is the one required slot: a team with nobody in it is not a team.
      body: body as { name: string; build1_id: string },
    });
    if (error) throw error;
    return data;
  }

  async update(id: string, body: { name?: string } & Partial<Record<TeamSlot, string | null>>) {
    const { data, error } = await this.api.PATCH('/api/v1/teams/{team_id}', {
      params: { path: { team_id: id } },
      body,
    });
    if (error) throw error;
    return data;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/teams/{team_id}', {
      params: { path: { team_id: id } },
    });
    if (error) throw error;
  }
}
