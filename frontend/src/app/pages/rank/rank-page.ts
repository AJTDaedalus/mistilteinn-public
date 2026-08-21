import {
  Component,
  computed,
  inject,
  OnDestroy,
  signal,
  viewChild,
} from '@angular/core';

import { BuildsService, type BuildRead } from '../builds/builds.service';
import type { DiscRead } from '../builds/discs.service';
import { DiscSetsService, type DiscSetSummary } from '../optimize/disc-sets.service';
import { discSetIconUrl } from '../../shared/icon-url';
import { PriorityBuildsPanel } from './priority-builds-panel';
import { RankContextBar, type RankContextSelection } from './rank-context-bar';
import { defaultRankFilters, RankFilters, type RankFilterState } from './rank-filters';
import { RankJobsList } from './rank-jobs-list';
import { RankTable } from './rank-table';
import {
  RankService,
  type DiscScoreSchema,
  type DiscRankSchema,
  type OptimizationJobSummary,
  type RankContextInput,
  type RankFilters as RankFiltersPayload,
} from './rank.service';

const TERMINAL = ['succeeded', 'failed', 'cancelled'];

@Component({
  selector: 'page-rank',
  standalone: true,
  imports: [PriorityBuildsPanel, RankContextBar, RankFilters, RankJobsList, RankTable],
  templateUrl: './rank-page.html',
  styleUrl: './rank-page.scss',
})
export class RankPage implements OnDestroy {
  private rankService = inject(RankService);
  private buildsService = inject(BuildsService);
  private discSetsService = inject(DiscSetsService);

  protected scores = signal<DiscScoreSchema[]>([]);
  protected rankResults = signal<DiscRankSchema[] | null>(null);
  protected discMap = signal<Record<string, DiscRead>>({});
  protected setNames = signal<Record<string, string>>({});
  protected setIcons = signal<Record<string, string | null>>({});
  protected buildNames = signal<Record<string, string>>({});
  protected filters = signal<RankFilterState>(defaultRankFilters());
  protected loading = signal(false);
  protected initError = signal<string | null>(null);
  protected scoreError = signal<string | null>(null);
  protected jobProgress = signal<number | null>(null);
  protected jobs = signal<OptimizationJobSummary[]>([]);

  protected priorityPanelVisible = signal(false);

  protected totalDiscCount = signal<number>(0);

  protected activeContexts = signal<RankContextInput[]>([]);

  protected discSets = signal<DiscSetSummary[]>([]);

  protected supportBuildIds = computed<Set<string>>(() => {
    const ids = new Set<string>();
    for (const ctx of this.activeContexts()) {
      if (ctx.support_slot != null && ctx.build_id) ids.add(ctx.build_id);
    }
    return ids;
  });

  protected get hasResults(): boolean {
    const r = this.rankResults();
    return r !== null && r.length > 0;
  }

  /** Pending contexts — set on selection change, run on button click. */
  protected singleCtx: RankContextInput | null = null;
  private priorityContexts: RankContextInput[] | null = null;

  private priorityPanel = viewChild(PriorityBuildsPanel);
  private _pollTimer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    void this.init();
  }

  private async init() {
    try {
      const [discs, sets, builds, agents, jobs] = await Promise.all([
        this.buildsService.listDiscs(),
        this.discSetsService.listSets(),
        this.buildsService.list(),
        this.buildsService.listAgents(),
        this.rankService.listRankJobs(),
      ]);

      const dm: Record<string, DiscRead> = {};
      for (const d of discs) dm[d.id] = d;
      this.discMap.set(dm);
      this.totalDiscCount.set(discs.length);

      this.discSets.set(sets);

      const sn: Record<string, string> = {};
      const si: Record<string, string | null> = {};
      for (const s of sets) {
        sn[String(s.id)] = s.name;
        si[String(s.id)] = discSetIconUrl(s.icon_path);
      }
      this.setNames.set(sn);
      this.setIcons.set(si);

      const agentNameMap = new Map((agents as { id: string; name: string }[]).map(a => [a.id, a.name]));
      const bn: Record<string, string> = {};
      for (const b of builds as BuildRead[]) bn[b.id] = agentNameMap.get(b.agent_id) ?? b.id;
      this.buildNames.set(bn);

      this.jobs.set(jobs);
      if (jobs.some((j) => !TERMINAL.includes(j.status))) {
        this.startPolling();
      }
    } catch (e) {
      this.initError.set(e instanceof Error ? e.message : String(e));
    }
  }

  private startPolling() {
    if (this._pollTimer !== null) return;
    this._pollTimer = setInterval(() => void this.poll(), 2000);
  }

  private async poll() {
    try {
      const updated = await this.rankService.listRankJobs();
      this.jobs.set(updated);
      if (updated.length === 0 || updated.every((j) => TERMINAL.includes(j.status))) {
        this.stopPolling();
      }
    } catch { /* ignore transient errors */ }
  }

  private stopPolling() {
    if (this._pollTimer !== null) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  }

  ngOnDestroy() { this.stopPolling(); }

  protected onSelectionChange(sel: RankContextSelection) {
    this.singleCtx = {
      team_id: sel.teamId,
      active_index: sel.activeIndex,
      combo_id: sel.comboId,
      enemy_profile_id: sel.enemyProfileId,
      weight: 1,
      allowed_set_ids: sel.allowedSetIds,
      // Per-context buff state (DESIGN §2.5, #95). Spread only when the bar
      // could resolve it, so an unresolved selection keeps the store fallback
      // rather than sending an empty context that would read as "all buffs on,
      // nothing disabled".
      ...(sel.buffContext ?? {}),
    };
    this.filters.update((f) => ({ ...f, mainStats: sel.mainStats, rarities: sel.rarities }));
  }

  protected onPriorityContextsChange(contexts: RankContextInput[] | null) {
    this.priorityContexts = contexts ?? null;
  }

  protected onPriorityFiltersChange(pf: { mainStats: string[]; rarities: string[] }) {
    this.filters.update((f) => ({ ...f, mainStats: pf.mainStats, rarities: pf.rarities }));
  }

  protected async scoreSingle() {
    if (!this.singleCtx) return;
    await this.runRankJob([this.singleCtx]);
  }

  protected async scorePriority() {
    if (!this.priorityContexts) return;
    await this.runRankJob(this.priorityContexts);
  }

  protected onFiltersChange(f: RankFilterState) {
    this.filters.update((prev) => ({
      ...prev,
      slot: f.slot,
      levelValue: f.levelValue,
      levelMode: f.levelMode,
      sets: f.sets,
    }));
  }

  protected togglePriorityPanel() {
    this.priorityPanelVisible.update((v) => !v);
  }

  private extractRankResults(result: unknown): DiscRankSchema[] {
    if (Array.isArray(result)) return result as DiscRankSchema[];
    const wrapped = result as { discs?: DiscRankSchema[] } | null;
    return wrapped?.discs ?? [];
  }

  protected async onViewJob(id: string) {
    try {
      const job = await this.rankService.getRankJob(id);
      const results = this.extractRankResults(job.result);
      this.rankResults.set(results);
      this.scores.set(this.stubScores(results));
      const request = job.request as { contexts?: RankContextInput[] };
      if (request?.contexts?.length) {
        this.activeContexts.set(request.contexts);
        void this.priorityPanel()?.loadContexts(request.contexts);
        this.priorityPanelVisible.set(true);
      }
    } catch (e) {
      this.scoreError.set(e instanceof Error ? e.message : String(e));
    }
  }

  protected async onCancelJob(id: string) {
    try {
      await this.rankService.cancelJob(id);
      const updated = await this.rankService.listRankJobs();
      this.jobs.set(updated);
    } catch (e) {
      this.scoreError.set(e instanceof Error ? e.message : String(e));
    }
  }

  private filtersToBackend(state: RankFilterState): RankFiltersPayload | null {
    const f = state;
    const hasAny =
      f.slot !== 0 ||
      f.levelValue !== null ||
      f.sets.length > 0 ||
      f.rarities.length > 0 ||
      f.mainStats.length > 0;
    if (!hasAny) return null;
    return {
      slot: f.slot !== 0 ? f.slot : null,
      set_ids: f.sets.map(Number),
      rarities: f.rarities,
      main_stats: f.mainStats,
      level_value: f.levelValue,
      level_mode: f.levelMode,
    };
  }

  private async runRankJob(contexts: RankContextInput[]) {
    this.scoreError.set(null);
    this.loading.set(true);
    this.jobProgress.set(0);
    this.scores.set([]);
    this.rankResults.set(null);
    this.activeContexts.set(contexts);
    try {
      const filters = this.filtersToBackend(this.filters());
      const summary = await this.rankService.rank(contexts, 'default', filters);
      this.jobs.update((prev) =>
        prev.some((j) => j.id === summary.id) ? prev : [summary, ...prev],
      );
      this.startPolling();
      const job = await this.rankService.pollUntilDone(summary.id, (j) => {
        const total = j.assignments_total;
        if (total > 0) {
          this.jobProgress.set(Math.round((j.assignments_done / total) * 100));
        }
      });
      if (job.status !== 'succeeded') {
        throw new Error(`Rank job ${job.status}`);
      }
      const results = this.extractRankResults(job.result);
      this.rankResults.set(results);
      this.scores.set(this.stubScores(results));
    } catch (e) {
      this.scoreError.set(e instanceof Error ? e.message : String(e));
      this.rankResults.set(null);
      this.scores.set([]);
    } finally {
      this.loading.set(false);
      this.jobProgress.set(null);
    }
  }

  /** Build stub DiscScoreSchema rows so rank-table can iterate disc IDs. */
  private stubScores(results: DiscRankSchema[]): DiscScoreSchema[] {
    return results.map((r) => ({
      disc_id: r.disc_id,
      rolls_used: 0,
      remaining_rolls: 0,
      current_damage: 0,
      baseline_damage: 0,
      max_improvement: 0,
      mean_improvement: 0,
      stddev_improvement: 0,
      p10: 0,
      p50: 0,
      p90: 0,
      distribution: null,
    })) as DiscScoreSchema[];
  }
}
