import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type CharacterSummary = components['schemas']['CharacterSummary'];
export type CharacterRead = components['schemas']['CharacterRead'];
export type WeaponSummary = components['schemas']['WeaponSummary'];
export type ArtifactSetRead = components['schemas']['ArtifactSetRead'];
export type EnemyProfileRead = components['schemas']['EnemyProfileRead'];
export type ReactionRead = components['schemas']['ReactionRead'];
export type ElementRead = components['schemas']['ElementRead'];
export type WeaponClassRead = components['schemas']['WeaponClassRead'];

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
    // `rarity` and `weapon_type` were taken by the endpoint from the start and missing here,
    // so a page could not offer a filter the server already implemented.
    rarity?: CharacterSummary['rarity'];
    weapon_type?: CharacterSummary['weapon_type'];
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

  /**
   * Weapons, optionally filtered to one class.
   *
   * `weapon_type` takes the source's internal spelling (`WEAPON_SWORD_ONE_HAND`), which is
   * what `CharacterSummary.weapon_type` carries — so a caller passes a character's own value
   * through rather than translating it. The filtering is the **server's**: T.1 refuses a
   * weapon whose class does not match the character's, and a client-side filter would be a
   * second copy of that rule, free to drift toward offering something the API then refuses.
   */
  async listWeapons(
    params: {
      name?: string;
      weapon_type?: WeaponSummary['weapon_type'];
      rarity?: WeaponSummary['rarity'];
      offset?: number;
      limit?: number;
    } = {},
  ) {
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

  /**
   * Every elemental reaction a team filter can offer.
   *
   * Read rather than restated: the table is committed and cited in
   * `docs/RESEARCH_elemental_reactions.md`, and a client-side copy would be the second
   * definition that drifts.
   */
  async listReactions() {
    const { data, error } = await this.api.GET('/api/v1/reactions');
    if (error) throw new Error('Could not load reactions');
    return data;
  }

  /**
   * The seven visions and their emblems.
   *
   * Read rather than restated, for the same reason as the reaction table and one more: the
   * emblem's basename is an **allowlist** server-side, not `f"{element}.webp"`, precisely so
   * an eighth vision does not put a broken mark on screen. Building it here would undo that.
   */
  async listElements() {
    const { data, error } = await this.api.GET('/api/v1/elements');
    if (error) throw new Error('Could not load elements');
    return data;
  }

  /**
   * The weapon classes that have a mark.
   *
   * Read rather than restated, like the visions: this replaced a five-entry list written out
   * here *and* would otherwise need the mark's basename built client-side. The crossbow class
   * is absent by the server's decision, which the page does not need to know about.
   */
  async listWeaponClasses() {
    const { data, error } = await this.api.GET('/api/v1/weapon-classes');
    if (error) throw new Error('Could not load weapon classes');
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
