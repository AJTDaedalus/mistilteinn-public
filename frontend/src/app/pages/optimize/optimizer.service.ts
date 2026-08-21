import { Injectable, inject } from '@angular/core';

import { apiErrorMessage } from '../../api/api-error';
import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';
import { BuffContextStore } from '../../shared/buff-context.store';

export type DiscOptimizeRequest = components['schemas']['DiscOptimizeRequest'];
export type OptimizationJobSummary = components['schemas']['OptimizationJobSummary'];
export type OptimizationJobRead = components['schemas']['OptimizationJobRead'];
export type SetFrameSchema = components['schemas']['SetFrameSchema'];

/** One substat entry on a disc. */
export interface SubstatRollSummary {
  stat_type: string;
  value: number;
  rolls: number;
}

/** Disc metadata projected onto each result build. */
export interface OptimizerDiscSummary {
  disc_id: string;
  slot: number;
  set_id: number;
  set_name: string;
  main_stat_type: string;
  main_stat_value: number;
  rarity: string;
  substats?: SubstatRollSummary[];
  score?: number | null;
  icon_path?: string;
}

/** One candidate build produced by the optimizer. */
export interface OptimizerDiscBuildSchema {
  total_damage: number;
  disc_ids: string[];
  set_counts: Record<string, number>;
  per_combo_damage?: Record<string, number>;
  discs?: OptimizerDiscSummary[];
  total_stats?: Record<string, unknown>;
}

/**
 * Structured search-space diagnostics (Task B5). Not derivable from
 * api.types.ts -- DiscOptimizeResponse is never a route response_model
 * (it rides inside OptimizationJobRead.result, typed only as `dict` on the
 * backend), so this is hand-declared like the rest of this file.
 */
export interface SearchTransparencySchema {
  total_space: number;
  evaluated: number;
  pruned_sets: number;
  pruned_stats: number;
  prefiltered: number;
  auto_prefilter_k?: number | null;
  is_exact: boolean;
}

/** Top-N optimizer results plus search diagnostics. */
export interface DiscOptimizeResponse {
  combo_id: string;
  combo_name: string;
  agent_name: string;
  enemy_name: string;
  current_build_damage?: number | null;
  builds: OptimizerDiscBuildSchema[];
  evaluated: number;
  pruned_sets: number;
  pruned_stats: number;
  prefiltered?: number;
  auto_prefilter_k?: number | null;
  search_transparency?: SearchTransparencySchema;
  search_summary?: string;
}

/** Frontend-only filter state that maps 1:1 to the backend request constraints. */
export interface OptimizerFilterState {
  lockedSlots: Record<number, string>;
  requiredSets: Record<number, number>;
  allowedFrames: SetFrameSchema[] | null;
  minStats: Record<string, number>;
  topN: number;
}

export function defaultFilterState(): OptimizerFilterState {
  return {
    lockedSlots: {},
    requiredSets: {},
    allowedFrames: [{ counts: { 0: 6 } }],
    minStats: {},
    topN: 25,
  };
}

/** Subset that callers must supply; service fills backend defaults. */
export type OptimizeInput = Pick<DiscOptimizeRequest, 'enemy_profile_id'> &
  ({ combo_id: string; combo_ids?: never } | { combo_ids: string[]; combo_id?: never }) &
  Partial<Omit<DiscOptimizeRequest, 'combo_id' | 'combo_ids' | 'enemy_profile_id'>>;

@Injectable({ providedIn: 'root' })
export class OptimizerService {
  private api = injectApi();
  private buffContext = inject(BuffContextStore);

  async submit(input: OptimizeInput): Promise<OptimizationJobSummary> {
    const ctx = this.buffContext.context();
    const body: DiscOptimizeRequest = {
      aggregation: 'max',
      active_index: 0,
      top_n: 25,
      refinement: 1,
      crit_mode: 'expected',
      is_stunned: false,
      stun_dmg_mult: 15000,
      inventory_scope: 'this_build',
      // Only consumed when rotation_energy_cost is set; mirror the backend default.
      rotation_duration_s: 0,
      ...input,
      // After the spread, with an explicit fallback: `OptimizeInput` is a
      // `Partial<...>` of the request, so a caller that passes these keys as
      // `undefined` would otherwise blank the store's context rather than
      // leave it alone.
      active_conditions: input.active_conditions ?? ctx.active_conditions,
      stack_counts: input.stack_counts ?? ctx.stack_counts,
      disabled_buffs: input.disabled_buffs ?? ctx.disabled_buffs,
      // Stage buffs (#64, Task B5a). You optimize *for* a stage, so the discs a
      // Deadly-Assault buff favours have to be able to win the run.
      custom_buffs: input.custom_buffs ?? ctx.custom_buffs,
    };
    const { data, error } = await this.api.POST('/api/v1/optimizer/discs', { body });
    if (error) throw new Error(apiErrorMessage(error));
    return data;
  }

  async listJobs(opts?: { status?: string; jobType?: string }): Promise<OptimizationJobSummary[]> {
    const query: Record<string, string> = {};
    if (opts?.status) query['status'] = opts.status;
    if (opts?.jobType) query['job_type'] = opts.jobType;
    const { data, error } = await this.api.GET('/api/v1/optimizer/jobs', {
      params: { query },
    });
    if (error) throw new Error(apiErrorMessage(error));
    return data;
  }

  async getJob(id: string): Promise<OptimizationJobRead> {
    const { data, error } = await this.api.GET('/api/v1/optimizer/jobs/{job_id}', {
      params: { path: { job_id: id } },
    });
    if (error) throw new Error(apiErrorMessage(error));
    return data;
  }

  async deleteJob(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/optimizer/jobs/{job_id}', {
      params: { path: { job_id: id } },
    });
    if (error) throw new Error(apiErrorMessage(error));
  }
}
