import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import { allPages } from '../../api/all-pages';
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

  /** Every team, gathered a page at a time — see `allPages` on why not one request. */
  async list(): Promise<TeamRead[]> {
    const page = await allPages<TeamRead>(async (offset, limit) => {
      const { data, error } = await this.api.GET('/api/v1/teams', {
        params: { query: { offset, limit } },
      });
      if (error) throw new Error('Could not load teams');
      return data;
    });
    return page.items;
  }

  /**
   * `build1_id` is required, matching `TeamCreate`.
   *
   * Typed rather than cast. It was `body as never` first, and the cast hid that the page
   * would happily send a null first slot — the picker let a user fill slot 2 alone, and the
   * server refused it with a schema error about a field the page never showed them.
   */
  async create(
    body: { name: string; notes?: string; build1_id: string }
      & Partial<Record<TeamSlot, string | null>>,
  ) {
    // `notes` has a server default; sending it explicitly keeps the typed body honest about
    // what the endpoint accepts rather than relying on a cast to paper over the difference.
    const { data, error } = await this.api.POST('/api/v1/teams', {
      body: { notes: '', ...body },
    });
    if (error) throw error;
    return data;
  }

  async update(
    id: string,
    body: { name?: string; notes?: string } & Partial<Record<TeamSlot, string | null>>,
  ) {
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
