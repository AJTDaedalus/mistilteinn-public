import {
  Component,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';

import { TeamsService } from '../teams/teams.service';
import { OptimizerResultsGrid } from './optimizer-results-grid';
import {
  type DiscOptimizeResponse,
  type OptimizationJobRead,
  type OptimizerDiscBuildSchema,
  OptimizerService,
} from './optimizer.service';

@Component({
  selector: 'optimizer-job-detail',
  standalone: true,
  imports: [OptimizerResultsGrid],
  templateUrl: './optimizer-job-detail.html',
  styleUrl: './optimizer-job-detail.scss',
})
export class OptimizerJobDetail {
  private service = inject(OptimizerService);
  private teamsService = inject(TeamsService);

  jobId = input.required<string>();
  back = output<void>();
  equip = output<{ discIds: string[]; buildId: string }>();

  protected job = signal<OptimizationJobRead | null>(null);
  protected loading = signal(false);
  protected error = signal<string | null>(null);
  protected resolvedBuildId = signal<string | null>(null);

  constructor() {
    effect(() => {
      const id = this.jobId();
      void this.load(id);
    });
  }

  private async load(id: string) {
    this.loading.set(true);
    this.error.set(null);
    this.resolvedBuildId.set(null);
    try {
      const job = await this.service.getJob(id);
      this.job.set(job);
      await this.resolveBuildId();
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }

  /** DiscOptimizeRequest shape stored on the job -- see optimizer.py schema. */
  private get requestContext(): {
    team_id?: string | null;
    active_index?: number;
    combo_id?: string;
    combo_ids?: string[];
    enemy_profile_id?: string;
  } {
    return (this.job()?.request ?? {}) as {
      team_id?: string | null;
      active_index?: number;
      combo_id?: string;
      combo_ids?: string[];
      enemy_profile_id?: string;
    };
  }

  /**
   * Keystone deep-link context (DESIGN §3.1-3.2, F3) threaded from the
   * job's stored request down to the results grid. `teamId` is null for
   * jobs that predate team-context submission or weren't run against a
   * team -- the grid disables its breakdown button in that case.
   */
  protected get deepLinkTeamId(): string | null {
    return this.requestContext.team_id ?? null;
  }

  protected get deepLinkComboId(): string | null {
    const req = this.requestContext;
    return req.combo_ids?.[0] ?? req.combo_id ?? null;
  }

  protected get deepLinkEnemyProfileId(): string | null {
    return this.requestContext.enemy_profile_id ?? null;
  }

  protected get deepLinkActiveIndex(): number {
    return this.requestContext.active_index ?? 0;
  }

  /** Resolves the equip target via team_id + active_index (a combo carries
   * no build_id since B0 -- combos are team-owned, not build-owned). Absent
   * for legacy jobs with no team_id, matching deepLinkTeamId's null case. */
  private async resolveBuildId() {
    const teamId = this.deepLinkTeamId;
    if (!teamId) return;
    try {
      const team = await this.teamsService.get(teamId);
      const builds = [team.build1_id, team.build2_id, team.build3_id];
      this.resolvedBuildId.set(builds[this.deepLinkActiveIndex] ?? null);
    } catch {
      // Non-fatal: equip button will remain disabled
    }
  }

  private get optimizeResult(): DiscOptimizeResponse | null {
    const r = this.job()?.result;
    if (!r || Array.isArray(r)) return null;
    return r as unknown as DiscOptimizeResponse;
  }

  protected get builds(): OptimizerDiscBuildSchema[] {
    return this.optimizeResult?.builds ?? [];
  }

  protected get currentBuildDamage(): number | null {
    return this.optimizeResult?.current_build_damage ?? null;
  }

  protected get autoPrefilterK(): number | null {
    return this.optimizeResult?.auto_prefilter_k ?? null;
  }

  /** Human-readable, honest search-space label (Task B5 / F3). Absent on
   * jobs stored before that field existed -- the auto-prefilter notice
   * below still covers that case. */
  protected get searchSummary(): string | null {
    return this.optimizeResult?.search_summary ?? null;
  }

  protected onBack() {
    this.back.emit();
  }

  protected onEquip(discIds: string[]) {
    const buildId = this.resolvedBuildId();
    if (!buildId) return;
    this.equip.emit({ discIds, buildId });
  }
}
