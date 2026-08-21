import { Injectable } from '@angular/core';

import { injectApi } from '../api/api.client';
import { apiErrorMessage } from '../api/api-error';
import type { components } from '../api/api.types';
import type { CustomBuff } from './buff-context.store';

export type BuffPresetRead = components['schemas']['BuffPresetRead'];

/**
 * CRUD for saved stage-buff presets (#64, DESIGN_buff_context.md §2.4).
 *
 * A preset is storage only. Applying one **copies** its buffs into the run's
 * `BuffContext` (`BuffContextStore.setCustomBuffs`) — the calc never resolves a preset
 * id, so editing a preset cannot retroactively change a result already computed with it.
 * The UI has to make that copy semantic visible, or users will expect the other thing.
 */
@Injectable({ providedIn: 'root' })
export class BuffPresetsService {
  private api = injectApi();

  async list(): Promise<BuffPresetRead[]> {
    const { data, error } = await this.api.GET('/api/v1/buff-presets', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error(apiErrorMessage(error));
    return data.items;
  }

  async create(name: string, buffs: readonly CustomBuff[]): Promise<BuffPresetRead> {
    const { data, error } = await this.api.POST('/api/v1/buff-presets', {
      body: { name, buffs: buffs.map((b) => ({ ...b })) },
    });
    if (error) throw new Error(apiErrorMessage(error));
    return data;
  }

  async update(
    id: string,
    patch: { name?: string; buffs?: readonly CustomBuff[] },
  ): Promise<BuffPresetRead> {
    const body: { name?: string; buffs?: CustomBuff[] } = {};
    if (patch.name !== undefined) body.name = patch.name;
    if (patch.buffs !== undefined) body.buffs = patch.buffs.map((b) => ({ ...b }));
    const { data, error } = await this.api.PATCH('/api/v1/buff-presets/{preset_id}', {
      params: { path: { preset_id: id } },
      body,
    });
    if (error) throw new Error(apiErrorMessage(error));
    return data;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/buff-presets/{preset_id}', {
      params: { path: { preset_id: id } },
    });
    if (error) throw new Error(apiErrorMessage(error));
  }

  /** Stat keys a stage buff may target — served so the picker cannot drift (Task B2). */
  async statOptions(): Promise<string[]> {
    const { data, error } = await this.api.GET('/api/v1/damage/custom-buff-stats', {});
    if (error) throw new Error(apiErrorMessage(error));
    return data;
  }
}
