import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type CharacterSummary = components['schemas']['CharacterSummary'];
export type CharacterRead = components['schemas']['CharacterRead'];
export type WeaponSummary = components['schemas']['WeaponSummary'];
export type ArtifactSetRead = components['schemas']['ArtifactSetRead'];
export type EnemyProfileRead = components['schemas']['EnemyProfileRead'];

/**
 * Reads of the seeded catalogue — G.6a's endpoints.
 *
 * Every type here comes from `api.types`, which `npm run codegen` generates from the
 * committed `openapi.json`. Nothing in this file describes the API by hand: a hand-written
 * shape is a second definition of the contract, and the one that drifts is whichever the
 * tests exercise less. `test_openapi_contract_is_current.py` keeps the spec honest on the
 * backend side, so this side inherits that guarantee rather than restating it.
 */
@Injectable({ providedIn: 'root' })
export class CatalogueService {
  private api = injectApi();

  async listCharacters(params: {
    name?: string;
    element?: CharacterSummary['element'];
    offset?: number;
    limit?: number;
  } = {}) {
    const { data, error } = await this.api.GET('/api/v1/characters', {
      params: { query: params },
    });
    if (error) throw new Error('Could not load characters');
    return data;
  }

  /**
   * One character, by its source key.
   *
   * The key is a **string**: 28 of the 150 characters are Traveler variants spelled
   * `10000005-2`. Typing this as a number would 404 — or worse, silently truncate — on
   * every one of them.
   */
  async getCharacter(nanokaId: string) {
    const { data, error } = await this.api.GET('/api/v1/characters/{nanoka_id}', {
      params: { path: { nanoka_id: nanokaId } },
    });
    if (error) throw new Error(`No character ${nanokaId}`);
    return data;
  }

  async listWeapons(params: { name?: string; offset?: number; limit?: number } = {}) {
    const { data, error } = await this.api.GET('/api/v1/weapons', {
      params: { query: params },
    });
    if (error) throw new Error('Could not load weapons');
    return data;
  }

  async listArtifactSets(params: { name?: string; offset?: number; limit?: number } = {}) {
    const { data, error } = await this.api.GET('/api/v1/artifact-sets', {
      params: { query: params },
    });
    if (error) throw new Error('Could not load artifact sets');
    return data;
  }

  async listEnemies(params: { name?: string; offset?: number; limit?: number } = {}) {
    const { data, error } = await this.api.GET('/api/v1/enemies', {
      params: { query: params },
    });
    if (error) throw new Error('Could not load enemies');
    return data;
  }
}
