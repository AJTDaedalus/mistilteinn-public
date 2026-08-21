import { Injectable, inject } from '@angular/core';

import { apiErrorMessage } from '../../api/api-error';
import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';
import { BuffContextStore, type CustomBuff } from '../../shared/buff-context.store';

export type InventoryScoreRequest = components['schemas']['InventoryScoreRequest'];
export type InventoryScoreResponse = components['schemas']['InventoryScoreResponse'];
export type DiscScoreSchema = components['schemas']['DiscScoreSchema'];
export type RankRequest = components['schemas']['RankRequest'];
export type RankContextSchema = components['schemas']['RankContextSchema'];
export type RankFilters = components['schemas']['RankFilters'];
export type OptimizationJobSummary = components['schemas']['OptimizationJobSummary'];
export type OptimizationJobRead = components['schemas']['OptimizationJobRead'];
export type TeamCalculateResponse = components['schemas']['TeamCalculateResponse'];

/** Minimum fields the caller must provide; service fills in defaults. */
export type InventoryScoreInput = Pick<InventoryScoreRequest, 'combo_id' | 'enemy_profile_id'> &
  Partial<Omit<InventoryScoreRequest, 'combo_id' | 'enemy_profile_id'>> & {
    /** hakushin_ids to pre-filter; null = score all sets. */
    allowed_set_ids?: number[] | null;
  };

/** Per-context score breakdown for one disc in the rank job result. */
export interface PerBuildBreakdown {
  build_id: string;
  avg_pct: number | null;
  max_pct: number | null;
  /**
   * "equipped" — avg_pct/max_pct are vs this context's currently-equipped
   * discs. "best" — the context has no equipped discs, so avg_pct/max_pct
   * are norm_pct instead (DESIGN_ranker_discless.md D1/D2a). Null when
   * excluded by set filter.
   */
  reference_mode?: 'equipped' | 'best' | null;
  /** Deep-link context (DESIGN §3.4) — null when this context was build_id-only. */
  team_id?: string | null;
  combo_id?: string | null;
  enemy_profile_id?: string | null;
  active_index?: number | null;
}

/** Rank result for a single disc — matches DiscRankSchema on the backend (stored as JSONB). */
export interface DiscRankSchema {
  disc_id: string;
  per_build: PerBuildBreakdown[];
  best_build_avg: number;
  best_build_avg_build_id: string;
  best_build_max: number;
  portfolio_avg: number;
}

/** Per-build row the caller provides; service fills scoring defaults. */
export interface RankContextInput {
  build_id?: string | null;
  team_id?: string | null;
  active_index?: number;
  combo_id: string;
  enemy_profile_id: string;
  weight?: number;
  allowed_set_ids?: number[] | null;
  support_slot?: number | null;
  /**
   * Buff state for *this* context (DESIGN_buff_context.md §2.5, #95). A rank
   * job carries N contexts naming N different builds, so buff state is
   * per-context rather than per-request — producers seed each one from its own
   * target build via `buffContextForBuilds`.
   *
   * Omitted fields fall back to the shared `BuffContextStore`, which is the
   * pre-#95 behavior. Both real producers supply them; the fallback only
   * covers a context whose build could not be resolved client-side.
   */
  active_conditions?: string[];
  stack_counts?: Record<string, number>;
  disabled_buffs?: string[];
  /**
   * Stage buffs for this context (#64, Task B5a). Per-context like the rest: ranking
   * the same inventory against two different Deadly-Assault stages is a normal thing
   * to want, and one run-level field could not express it.
   */
  custom_buffs?: CustomBuff[];
}

@Injectable({ providedIn: 'root' })
export class RankService {
  private api = injectApi();
  private buffContext = inject(BuffContextStore);

  /**
   * Buff state the most recent rank job sent, per `build_id`.
   *
   * Rank is the one surface whose buff state is *not* the shared store's: it derives one
   * context per build from that build's own columns (DESIGN §2.5, #95) and never calls
   * `seedFromBuilds`. So the explain view cannot read the store — it would show a total
   * the ranked run cannot reproduce, which is the exact disagreement the keystone
   * endpoint exists to rule out. This is the only place that holds both halves.
   */
  private readonly lastRunBuffState = new Map<
    string,
    {
      active_conditions: string[];
      stack_counts: Record<string, number>;
      disabled_buffs: string[];
      custom_buffs: CustomBuff[];
    }
  >();

  async scoreInventory(input: InventoryScoreInput): Promise<InventoryScoreResponse> {
    const ctx = this.buffContext.context();
    const body: InventoryScoreRequest = {
      crit_mode: 'expected',
      refinement: 1,
      is_stunned: false,
      stun_dmg_mult: 15000,
      active_conditions: ctx.active_conditions,
      stack_counts: ctx.stack_counts,
      disabled_buffs: ctx.disabled_buffs,
      custom_buffs: ctx.custom_buffs,
      include_distribution: false,
      scope: 'default',
      active_index: 0,
      ...input,
    };
    const { data, error } = await this.api.POST('/api/v1/scorer/inventory', { body });
    if (error) throw new Error(apiErrorMessage(error));
    return data as InventoryScoreResponse;
  }

  async rank(
    contextInputs: RankContextInput[],
    scope: 'default' | 'all' = 'default',
    filters?: RankFilters | null,
  ): Promise<OptimizationJobSummary> {
    // Per-context buff state (DESIGN §2.5, #95): each context carries the buff
    // state seeded from its own build, so a job spanning unrelated builds no
    // longer stamps one shared value onto all of them. `context()` is read
    // inside the map, per context, so contexts falling back to the store still
    // get their own copies rather than aliasing one snapshot's arrays.
    const contexts: RankContextSchema[] = contextInputs.map((c) => {
      const ctx = this.buffContext.context();
      return {
        build_id: c.build_id ?? null,
        team_id: c.team_id ?? null,
        combo_id: c.combo_id,
        enemy_profile_id: c.enemy_profile_id,
        weight: c.weight ?? 1,
        active_index: c.active_index ?? 0,
        allowed_set_ids: c.allowed_set_ids ?? null,
        support_slot: c.support_slot ?? null,
        crit_mode: 'expected',
        refinement: 1,
        is_stunned: false,
        stun_dmg_mult: 15000,
        active_conditions: c.active_conditions ?? ctx.active_conditions,
        stack_counts: c.stack_counts ?? ctx.stack_counts,
        disabled_buffs: c.disabled_buffs ?? ctx.disabled_buffs,
        custom_buffs: c.custom_buffs ?? ctx.custom_buffs,
        include_distribution: false,
      };
    });
    // Remember what each context actually ran with, so the keystone explain view can
    // reproduce it (see `evaluateDiscs`). Rank derives its buff state per context from
    // build rows and never seeds the shared store, so the store is the wrong source
    // there — and since the server now *replaces* the build columns with whatever the
    // request carries, reading the store would make the breakdown apply buffs the ranked
    // run had switched off.
    this.lastRunBuffState.clear();
    for (const ctx of contexts) {
      if (ctx.build_id) {
        this.lastRunBuffState.set(ctx.build_id, {
          active_conditions: [...(ctx.active_conditions ?? [])],
          stack_counts: { ...(ctx.stack_counts ?? {}) },
          disabled_buffs: [...(ctx.disabled_buffs ?? [])],
          custom_buffs: (ctx.custom_buffs ?? []).map((b) => ({ ...b })),
        });
      }
    }

    const body: RankRequest = { contexts, scope, filters: filters ?? null };
    const { data, error } = await this.api.POST('/api/v1/scorer/rank', { body });
    if (error) throw new Error(apiErrorMessage(error));
    return data as OptimizationJobSummary;
  }

  /**
   * Keystone deep-link (DESIGN §3.4) — swap ``discIds`` onto the team member
   * at ``activeIndex`` and run the full-attribution calculator, comparing
   * against the equipped set so the caller gets a gain readout for free.
   */
  async evaluateDiscs(
    teamId: string,
    params: {
      comboId: string;
      enemyProfileId: string;
      activeIndex: number;
      discIds: string[];
      /**
       * The context's build, when the caller is explaining a *ranked* candidate. Selects
       * the buff state that run used; omitted (the optimizer's grid, whose page does seed
       * the store) falls back to the shared store.
       */
      buildId?: string;
    },
  ): Promise<TeamCalculateResponse> {
    // This is the explain view for an optimizer/rank candidate, so every field the run
    // used has to come with it or the explanation disagrees with the number it explains.
    // `custom_buffs` landed in Task B5a; `disabled_buffs` was added to the request in the
    // same pass, because without it a stage buff the run had switched off was applied
    // here — the candidate's damage could not be reproduced by the run that found it.
    //
    // For a ranked candidate that means the *ranked context's* state, not the store's:
    // rank never seeds the store. See `lastRunBuffState`.
    const ctx =
      (params.buildId ? this.lastRunBuffState.get(params.buildId) : undefined) ??
      this.buffContext.context();
    const { data, error } = await this.api.POST('/api/v1/teams/{team_id}/evaluate-discs', {
      params: { path: { team_id: teamId } },
      body: {
        combo_id: params.comboId,
        enemy_profile_id: params.enemyProfileId,
        active_index: params.activeIndex,
        disc_ids: params.discIds,
        compare_to: 'equipped',
        active_conditions: ctx.active_conditions,
        stack_counts: ctx.stack_counts,
        custom_buffs: ctx.custom_buffs,
        disabled_buffs: ctx.disabled_buffs,
        refinement: 1,
        crit_mode: 'expected',
        is_stunned: false,
        stun_dmg_mult: 15000,
      },
    });
    if (error) throw new Error(apiErrorMessage(error));
    return data as TeamCalculateResponse;
  }

  async listRankJobs(): Promise<OptimizationJobSummary[]> {
    const { data, error } = await this.api.GET('/api/v1/optimizer/jobs', {
      params: { query: { job_type: 'rank' } },
    });
    if (error) throw new Error(apiErrorMessage(error));
    return data;
  }

  async cancelJob(jobId: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/optimizer/jobs/{job_id}', {
      params: { path: { job_id: jobId } },
    });
    if (error) throw new Error(apiErrorMessage(error));
  }

  async getRankJob(jobId: string): Promise<OptimizationJobRead> {
    const { data, error } = await this.api.GET('/api/v1/optimizer/jobs/{job_id}', {
      params: { path: { job_id: jobId } },
    });
    if (error) throw new Error(apiErrorMessage(error));
    return data as OptimizationJobRead;
  }

  async pollUntilDone(
    jobId: string,
    onProgress?: (job: OptimizationJobRead) => void,
    intervalMs = 1000,
  ): Promise<OptimizationJobRead> {
    const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
    for (;;) {
      const job = await this.getRankJob(jobId);
      onProgress?.(job);
      if (TERMINAL.has(job.status)) return job;
      await new Promise<void>((resolve) => setTimeout(resolve, intervalMs));
    }
  }
}
