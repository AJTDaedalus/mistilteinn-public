import { Component, computed, effect, inject, signal, viewChild, OnDestroy } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';

import { BuildsService, type BuildRead, type AgentSummary } from '../builds/builds.service';
import { teamBuildsTargetFirst, teamMemberSlots } from '../../shared/team-member-slots';
import { BuffContextStore } from '../../shared/buff-context.store';
import { CombosService, type ComboRead } from '../builds/combos.service';
import { CalculateService, type EnemyProfileRead } from '../calculate/calculate.service';
import { DiscsService } from '../builds/discs.service';
import { defaultEnemyId, ENEMY_TABS, filterEnemiesByTab, type EnemyTab } from '../../shared/enemy-tabs';
import { DiscSetsService, type DiscSetSummary } from './disc-sets.service';
import { TeamsService, type TeamRead } from '../teams/teams.service';
import { OptimizerDiagnostics } from './optimizer-diagnostics';
import { OptimizerResultsGrid } from './optimizer-results-grid';
import {
  OptimizerSetFilter,
  emptySetFilterState,
  type SetFilterState,
} from './optimizer-set-filter';
import { OptimizerStatFloors, type StatFloorMap } from './optimizer-stat-floors';
import { OptimizerLockedSlots, type LockedSlotMap } from './optimizer-locked-slots';
import {
  OptimizerInventoryFilter,
  emptyInventoryFilterState,
  type InventoryFilterState,
} from './optimizer-inventory-filter';
import { filterInventory } from './filter-inventory';
import {
  type OptimizationJobSummary,
  type OptimizerDiscBuildSchema,
  OptimizerService,
} from './optimizer.service';
import { OptimizerJobDetail } from './optimizer-job-detail';
import { OptimizerJobsList } from './optimizer-jobs-list';
import { StageBuffsPanelComponent } from '../../shared/stage-buffs/stage-buffs-panel';
import { Toast } from '../../shared/toast/toast';

@Component({
  selector: 'app-optimize-page',
  standalone: true,
  imports: [
    RouterLink,
    FormsModule,
    OptimizerDiagnostics,
    OptimizerResultsGrid,
    OptimizerSetFilter,
    OptimizerStatFloors,
    OptimizerLockedSlots,
    OptimizerInventoryFilter,
    OptimizerJobDetail,
    OptimizerJobsList,
    StageBuffsPanelComponent,
    Toast,
  ],
  templateUrl: './optimize-page.html',
  styleUrl: './optimize-page.scss',
})
export class OptimizePage implements OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private buildsService = inject(BuildsService);
  private combosService = inject(CombosService);
  private calcService = inject(CalculateService);
  private discsService = inject(DiscsService);
  private discSetsService = inject(DiscSetsService);
  private teamsService = inject(TeamsService);
  protected optimizerService = inject(OptimizerService);
  private buffContext = inject(BuffContextStore);

  protected builds = signal<BuildRead[]>([]);
  protected agents = signal<AgentSummary[]>([]);
  protected teams = signal<TeamRead[]>([]);
  protected selectedTeamId = signal<string | null>(null);
  protected selectedActiveIndex = signal<number>(0);
  protected combos = signal<ComboRead[]>([]);
  protected selectedComboId = signal<string | null>(null);
  protected enemies = signal<EnemyProfileRead[]>([]);
  protected enemyTab = signal<EnemyTab>('bosses');
  protected readonly enemyTabs = ENEMY_TABS;
  protected filteredEnemies = computed(() => filterEnemiesByTab(this.enemies(), this.enemyTab()));
  protected selectedEnemyId = signal<string | null>(null);
  protected discSets = signal<DiscSetSummary[]>([]);

  protected setFilterState = signal<SetFilterState>(emptySetFilterState());
  protected inventoryFilterState = signal<InventoryFilterState>(emptyInventoryFilterState());
  protected minStats = signal<StatFloorMap>({});
  protected lockedSlots = signal<LockedSlotMap>({});
  protected topN = signal(25);
  protected inventoryScope = signal<'this_build' | 'priority'>('this_build');

  protected selectedTeam = computed(() =>
    this.teams().find((t) => t.id === this.selectedTeamId()) ?? null
  );

  /** Build ID of the member being optimised (slot at active_index). */
  protected selectedBuildId = computed(() => {
    const team = this.selectedTeam();
    if (!team) return null;
    const ids = [team.build1_id, team.build2_id ?? null, team.build3_id ?? null];
    return ids[this.selectedActiveIndex()] ?? null;
  });

  protected selectedBuild = computed(
    () => this.builds().find((b) => b.id === this.selectedBuildId()) ?? null
  );

  /**
   * The team's builds with the one being optimised first — the order
   * {@link BuffContextStore.seedFromBuilds} wants, since it reads
   * `active_conditions`/`stack_counts` off the head and merges
   * `disabled_buffs` across the rest.
   */
  private seedableTeamBuilds = computed<BuildRead[]>(() => {
    const team = this.selectedTeam();
    if (!team) return [];
    return teamBuildsTargetFirst(team, this.selectedActiveIndex(), this.builds());
  });

  protected higherPriorityBuilds = computed(() => {
    const build = this.selectedBuild();
    if (!build) return [];
    const myPriority = build.optimizer_priority ?? null;
    return this.builds().filter((b) => {
      if (b.id === build.id) return false;
      const bp = b.optimizer_priority ?? null;
      if (bp === null) return false;
      if (myPriority === null) return true;
      return bp < myPriority;
    });
  });

  protected toast = viewChild(Toast);

  protected isRunning = signal(false);
  protected results = signal<OptimizerDiscBuildSchema[]>([]);
  protected diagnostics = signal<{
    evaluated: number;
    pruned_sets: number;
    pruned_stats: number;
  } | null>(null);
  protected currentBuildDamage = signal<number | null>(null);
  protected errorMessage = signal<string | null>(null);
  protected slotWarnings = signal<string[]>([]);
  protected equippedBuildIdx = signal<number | null>(null);
  protected jobs = signal<OptimizationJobSummary[]>([]);

  private _routeQueryParams = toSignal(this.route.queryParams, {
    initialValue: {} as Record<string, string>,
  });
  protected selectedJobId = computed(
    () => (this._routeQueryParams() as Record<string, string>)['job'] ?? null,
  );

  private _pollTimer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    void this.init();

    // Seed the shared buff context from the team being optimised
    // (DESIGN_buff_context.md §2.2 — the client owns defaulting). The
    // optimizer used to inherit active_conditions and disabled_buffs off the
    // build row server-side; §2.1 removed that fallback, so without this the
    // page would submit the store's empty initial context.
    effect(() => {
      this.buffContext.seedFromBuilds(this.seedableTeamBuilds());
    });
  }

  private async init() {
    let builds: BuildRead[],
      agents: AgentSummary[],
      enemies: EnemyProfileRead[],
      sets: DiscSetSummary[],
      jobs: OptimizationJobSummary[],
      teams: TeamRead[];
    try {
      [builds, agents, enemies, sets, jobs, teams] = await Promise.all([
        this.buildsService.list(),
        this.buildsService.listAgents(),
        this.calcService.listEnemies(),
        this.discSetsService.listSets(),
        this.optimizerService
          .listJobs({ jobType: 'optimize' })
          .catch(() => [] as OptimizationJobSummary[]),
        this.teamsService.list(),
      ]);
    } catch (e) {
      this.errorMessage.set(`Failed to load: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    this.builds.set(builds);
    this.agents.set(agents);
    this.enemies.set(enemies);
    this.discSets.set(sets);
    this.jobs.set(jobs);
    this.teams.set(teams);

    this.selectedEnemyId.set(defaultEnemyId(enemies, this.enemyTab()));

    const queryTeamId = this.route.snapshot.queryParamMap.get('teamId');
    if (queryTeamId && teams.some((t) => t.id === queryTeamId)) {
      await this.onTeamSelected(queryTeamId);
    }

    this.startPolling();
  }

  private async onTeamSelected(teamId: string) {
    void this.router.navigate([], {
      queryParams: { teamId },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
    this.selectedTeamId.set(teamId);
    this.selectedActiveIndex.set(0);
    this.combos.set([]);
    this.selectedComboId.set(null);
    this.results.set([]);
    this.diagnostics.set(null);
    this.currentBuildDamage.set(null);

    try {
      const combos = await this.combosService.listForTeam(teamId);
      this.combos.set(combos);
      this.selectedComboId.set(combos[0]?.id ?? null);
    } catch (e) {
      this.errorMessage.set(e instanceof Error ? e.message : String(e));
    }
  }

  protected onTeamChange(id: string) {
    if (id) void this.onTeamSelected(id);
    else {
      this.selectedTeamId.set(null);
      this.combos.set([]);
      this.selectedComboId.set(null);
    }
  }

  protected onEnemyTabChange(tab: EnemyTab) {
    this.enemyTab.set(tab);
    const current = this.selectedEnemyId();
    const stillVisible = this.filteredEnemies().some((e) => e.id === current);
    if (!stillVisible) this.selectedEnemyId.set(defaultEnemyId(this.enemies(), tab));
  }

  /** Resolves a member build id to its agent's display name. */
  private agentNameForBuild = computed(() => {
    const nameByAgent = new Map(this.agents().map((a) => [a.id, a.name]));
    const agentByBuild = new Map(this.builds().map((b) => [b.id, b.agent_id]));
    return (buildId: string): string | null => {
      const agentId = agentByBuild.get(buildId);
      return (agentId && nameByAgent.get(agentId)) ?? null;
    };
  });

  /** Slots present in the selected team (for active_index picker), by agent name. */
  protected teamMemberIndices = computed(() => {
    const team = this.selectedTeam();
    if (!team) return [];
    return teamMemberSlots(team, this.agentNameForBuild());
  });

  /** Why Run is unavailable, or null when it's ready. Surfaced next to the button. */
  protected runDisabledReason = computed<string | null>(() => {
    if (!this.selectedTeamId()) return 'Select a team';
    if (!this.selectedComboId()) return 'Select a combo';
    if (!this.selectedEnemyId()) return 'Select an enemy';
    if (this.setFilterState().frames.length === 0) return 'Pick a 4-piece and 2-piece set';
    return null;
  });

  protected async run() {
    if (this.isRunning()) return;

    // The button stays clickable when prerequisites are unmet so we can tell
    // the user what's missing instead of looking like a dead no-op.
    const missing = this.runDisabledReason();
    if (missing) {
      this.toast()?.show(`Can't run yet — ${missing.toLowerCase()}.`);
      return;
    }

    this.isRunning.set(true);
    this.errorMessage.set(null);
    this.slotWarnings.set([]);

    try {
      const allDiscs = await this.discsService.list();
      const { discIds, warnings } = filterInventory(allDiscs, this.inventoryFilterState());
      this.slotWarnings.set(warnings);

      const lockedSlots = this.lockedSlots();
      const lockedSlotsStr: Record<string, string> = {};
      for (const [slot, discId] of Object.entries(lockedSlots)) {
        if (discId) lockedSlotsStr[slot] = discId;
      }

      const job = await this.optimizerService.submit({
        combo_ids: [this.selectedComboId()!],
        enemy_profile_id: this.selectedEnemyId()!,
        team_id: this.selectedTeamId() ?? undefined,
        active_index: this.selectedActiveIndex(),
        disc_ids: discIds.length > 0 ? discIds : null,
        allowed_frames: this.setFilterState().frames,
        min_stats: this.minStats(),
        locked_slots: lockedSlotsStr,
        top_n: this.topN(),
        inventory_scope: this.inventoryScope(),
      });

      this.jobs.update((prev) => [job, ...prev]);
      this.startPolling();
    } catch (e) {
      this.errorMessage.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.isRunning.set(false);
    }
  }

  protected async onEquipFromJob(event: { discIds: string[]; buildId: string }) {
    await this.onEquip(event.discIds, event.buildId);
  }

  protected async onEquip(discIds: string[], targetBuildId?: string) {
    const buildId = targetBuildId ?? this.selectedBuildId();
    if (!buildId) return;

    const idx = this.results().findIndex((r) => r.disc_ids.join() === discIds.join());
    this.equippedBuildIdx.set(idx);
    this.currentBuildDamage.set(null);

    const discsMap: Record<number, string> = {};
    discIds.forEach((id, i) => {
      discsMap[i + 1] = id;
    });

    this.toast()?.show('Equipped.', {
      label: 'Undo',
      callback: () => void this.undoEquip(buildId, discsMap),
    });

    try {
      const updated = await this.buildsService.equipAll(buildId, discsMap);
      this.builds.update((bs) => bs.map((b) => (b.id === updated.id ? updated : b)));
    } catch (e) {
      this.errorMessage.set(e instanceof Error ? e.message : String(e));
      this.equippedBuildIdx.set(null);
      this.toast()?.dismiss();
      this.toast()?.show(`Equip failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  private async undoEquip(buildId: string, discsMap: Record<number, string>) {
    try {
      await this.buildsService.equipAll(buildId, discsMap);
      this.equippedBuildIdx.set(null);
      this.toast()?.show('Undo successful.');
    } catch (e) {
      this.toast()?.show(`Undo failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  private startPolling() {
    if (this._pollTimer !== null) return;
    this._pollTimer = setInterval(() => void this.poll(), 2000);
  }

  private async poll() {
    try {
      const updated = await this.optimizerService.listJobs({ jobType: 'optimize' });
      this.jobs.set(updated);
      const TERMINAL = ['succeeded', 'failed', 'cancelled'];
      if (updated.length > 0 && updated.every((j) => TERMINAL.includes(j.status))) {
        this.stopPolling();
      }
    } catch {
      /* ignore transient errors */
    }
  }

  private stopPolling() {
    if (this._pollTimer !== null) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  }

  ngOnDestroy() {
    this.stopPolling();
  }

  protected onViewJob(id: string) {
    void this.router.navigate([], { queryParams: { job: id }, queryParamsHandling: 'merge' });
  }

  protected onBack() {
    void this.router.navigate([], { queryParams: { job: null }, queryParamsHandling: 'merge' });
  }

  protected async onDeleteJob(id: string) {
    try {
      await this.optimizerService.deleteJob(id);
      this.jobs.update((prev) => prev.filter((j) => j.id !== id));
    } catch (e) {
      this.errorMessage.set(e instanceof Error ? e.message : String(e));
    }
  }
}
