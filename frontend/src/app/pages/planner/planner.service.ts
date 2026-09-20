import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type PlannerOptions = components['schemas']['PlannerOptions'];
export type PlanRead = components['schemas']['PlanRead'];
export type PlanRequest = components['schemas']['PlanRequest'];
export type SectionRead = components['schemas']['SectionRead'];
export type MaterialLineRead = components['schemas']['MaterialLineRead'];
export type HistogramBinRead = components['schemas']['HistogramBinRead'];
export type CraftingBonusRead = components['schemas']['CraftingBonusRead'];
export type TalentOption = components['schemas']['TalentOption'];
export type BuildOption = components['schemas']['BuildOption'];
export type MaterialStockRead = components['schemas']['MaterialStockRead'];
export type MaterialStockList = components['schemas']['MaterialStockList'];
export type MaterialStockUpdate = components['schemas']['MaterialStockUpdate'];

/**
 * The leveling planner's two calls.
 *
 * Every type comes from `api.types`, generated from the committed `openapi.json` — nothing
 * here describes the API by hand, for the reason `catalogue.service.ts` gives.
 */
@Injectable({ providedIn: 'root' })
export class PlannerService {
  private api = injectApi();

  async options(characterId?: string): Promise<PlannerOptions> {
    const { data, error } = await this.api.GET('/api/v1/planner/options', {
      params: { query: characterId ? { character_id: characterId } : {} },
    });
    if (error) throw error;
    return data;
  }

  async plan(body: PlanRequest): Promise<PlanRead> {
    const { data, error } = await this.api.POST('/api/v1/planner/plan', { body });
    if (error) throw error;
    return data;
  }

  /** Every material, with this account's count — zero where it holds none. */
  async materials(): Promise<MaterialStockList> {
    const { data, error } = await this.api.GET('/api/v1/planner/materials', {});
    if (error) throw error;
    return data;
  }

  /**
   * Correct some counts. **Only the rows named here change.**
   *
   * A later GOOD import replaces every one of them, deliberately —
   * `docs/DESIGN_planner_materials.md` §2 — which is why both callers of this say so on
   * screen rather than leaving the user to discover it after a rescan.
   */
  async saveMaterials(counts: MaterialStockUpdate[]): Promise<MaterialStockRead[]> {
    const { data, error } = await this.api.PATCH('/api/v1/planner/materials', {
      body: { counts },
    });
    if (error) throw error;
    return data;
  }
}
