import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type RotationRead = components['schemas']['RotationRead'];
export type RotationStep = components['schemas']['RotationStep'];
export type RotationOptions = components['schemas']['RotationOptions'];
export type TeamRoster = components['schemas']['TeamRoster'];
export type RosterCharacter = components['schemas']['RosterCharacter'];

/** The action a step may name — the ten the backend publishes, not a list restated here. */
export type RotationAction = RotationStep['action'];

/**
 * Reads and writes of user-authored rotations — R.4's endpoints.
 *
 * Every type is generated from the committed `openapi.json`, so nothing here describes the
 * API by hand. That matters more than usual for `RotationAction`: a hand-written union would
 * be a second copy of gcsim's action vocabulary, and the copy that drifted would be the one
 * offering something the backend then refused.
 */
@Injectable({ providedIn: 'root' })
export class RotationsService {
  private api = injectApi();

  /** Everything the editor may offer: the actions, and the caller's teams with rosters. */
  async options(): Promise<RotationOptions> {
    const { data, error } = await this.api.GET('/api/v1/rotations/options');
    if (error) throw new Error('Could not load rotation options');
    return data;
  }

  async list(teamId?: string) {
    const { data, error } = await this.api.GET('/api/v1/rotations', {
      params: { query: teamId ? { team_id: teamId } : {} },
    });
    if (error) throw new Error('Could not load rotations');
    return data;
  }

  async get(id: string): Promise<RotationRead> {
    const { data, error } = await this.api.GET('/api/v1/rotations/{rotation_id}', {
      params: { path: { rotation_id: id } },
    });
    if (error) throw new Error(`No rotation ${id}`);
    return data;
  }

  /**
   * `description` is sent explicitly because the generated request type requires it.
   *
   * openapi-typescript treats a schema field carrying a `default` as required on the way in
   * — the server would happily fill it, but the contract as published does not say so. Left
   * to each caller, that is a field three call sites remember and the fourth forgets.
   */
  async create(body: {
    name: string;
    team_id: string;
    steps: RotationStep[];
    description?: string;
  }) {
    const { data, error } = await this.api.POST('/api/v1/rotations', {
      body: { ...body, description: body.description ?? '' },
    });
    if (error) throw error;
    return data;
  }

  /**
   * Steps are sent whole, never per index.
   *
   * The API replaces them wholesale for the reason R.4 records: "change step 3" and "insert
   * before step 3" are the same edit from here and different ones to a per-index API.
   */
  async update(id: string, body: { name?: string; steps?: RotationStep[] }) {
    const { data, error } = await this.api.PATCH('/api/v1/rotations/{rotation_id}', {
      params: { path: { rotation_id: id } },
      body,
    });
    if (error) throw error;
    return data;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/rotations/{rotation_id}', {
      params: { path: { rotation_id: id } },
    });
    if (error) throw error;
  }

  /** The gcsim config this rotation becomes — so a user can see what they authored. */
  async compile(id: string): Promise<string> {
    const { data, error } = await this.api.POST('/api/v1/rotations/{rotation_id}/compile', {
      params: { path: { rotation_id: id } },
    });
    if (error) throw error;
    return (data as { config: string }).config;
  }
}
