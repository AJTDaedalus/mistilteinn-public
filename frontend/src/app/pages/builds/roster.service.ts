import { Injectable } from '@angular/core';
import { injectApi } from '../../api/api.client';

/**
 * One catalogue character, and what this account has said about them.
 *
 * `owned` is **tri-state, and that is the point**. `null` means nobody has said — a character
 * the user has never imported or touched — which is not the same as `false`, the user saying
 * they do not have them. Collapsing the two would make a fresh account read as *"you own none
 * of the 150 characters"*, and would let the next import quietly resurrect a character somebody
 * deliberately un-owned. `DESIGN_character_roster.md` §2.1.
 */
export interface RosterEntry {
  character_id: string;
  name: string;
  icon: string | null;
  element: string | null;
  weapon_type: string | null;
  rarity: string | null;
  owned: boolean | null;
  /** `"import"`, `"manual"`, or null when nobody has said. */
  source: string | null;
}

export interface RosterRead {
  entries: RosterEntry[];
  owned_count: number;
}

/**
 * The account's character roster.
 *
 * Separate from `BuildsService` because they answer different questions, which is the whole
 * reason this exists: a build says *what gear this character has* and is only ever made for a
 * character holding some, while the roster says *does this account have this character*. They
 * were one thing until 2026-09-03, and twelve characters the owner owns were invisible because
 * of it — 22 furnishing sets, 440 Primogems the teapot tracker could not see.
 */
@Injectable({ providedIn: 'root' })
export class RosterService {
  private api = injectApi();

  async list(): Promise<RosterRead> {
    const { data, error } = await this.api.GET('/api/v1/roster');
    if (error) throw new Error('Could not load the roster');
    return data as RosterRead;
  }

  /** Record the user's own answer. The server always stores it as `manual`. */
  async setOwned(characterId: string, owned: boolean): Promise<RosterEntry> {
    const { data, error } = await this.api.PATCH('/api/v1/roster/{character_id}', {
      params: { path: { character_id: characterId } },
      body: { owned },
    });
    if (error) throw new Error('Could not save that');
    return data as RosterEntry;
  }
}
