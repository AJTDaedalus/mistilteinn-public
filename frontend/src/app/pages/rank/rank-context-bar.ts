import {
  Component,
  computed,
  inject,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { BuildsService, type BuildRead, type AgentSummary } from '../builds/builds.service';
import { CombosService, type ComboRead } from '../builds/combos.service';
import { TeamsService, type TeamRead } from '../teams/teams.service';
import { CalculateService, type EnemyProfileRead } from '../calculate/calculate.service';
import { DiscSetsService, type DiscSetSummary } from '../optimize/disc-sets.service';
import { teamBuildsTargetFirst, teamMemberSlots } from '../../shared/team-member-slots';
import {
  buffContextForBuilds,
  type BuffContextDefaults,
} from '../../shared/buff-context.store';
import { MAIN_STAT_BY_SLOT } from '../../shared/disc-list/disc-filters';
import { STAT_META } from '../../shared/stat-meta';
import { discSetIconUrl } from '../../shared/icon-url';
import { defaultEnemyId, ENEMY_TABS, filterEnemiesByTab, type EnemyTab } from '../../shared/enemy-tabs';

const ALL_MAIN_STATS = [...new Set(Object.values(MAIN_STAT_BY_SLOT).flat())];
const RARITY_OPTIONS = ['S', 'A', 'B'] as const;

export interface RankContextSelection {
  teamId: string;
  activeIndex: number;
  comboId: string;
  enemyProfileId: string;
  /** hakushin_ids to pre-filter; null = score all sets. */
  allowedSetIds: number[] | null;
  /** Display-filter: main stat keys; empty = all. */
  mainStats: string[];
  /** Display-filter: rarities; empty = all. */
  rarities: string[];
  /**
   * Buff state for this context, seeded from the selected team member (and
   * its supports, for `disabled_buffs`) — DESIGN_buff_context.md §2.5, #95.
   * Null when the team's build rows aren't loaded yet; the caller then falls
   * back to the shared `BuffContextStore`.
   */
  buffContext: BuffContextDefaults | null;
}

@Component({
  selector: 'rank-context-bar',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './rank-context-bar.html',
  styleUrl: './rank-context-bar.scss',
})
export class RankContextBar {
  private teamsService = inject(TeamsService);
  private buildsService = inject(BuildsService);
  private combosService = inject(CombosService);
  private calcService = inject(CalculateService);
  private discSetsService = inject(DiscSetsService);

  selectionChange = output<RankContextSelection>();

  protected teams = signal<TeamRead[]>([]);
  protected builds = signal<BuildRead[]>([]);
  protected agents = signal<AgentSummary[]>([]);
  protected combos = signal<ComboRead[]>([]);
  protected enemies = signal<EnemyProfileRead[]>([]);
  protected enemyTab = signal<EnemyTab>('bosses');
  protected readonly enemyTabs = ENEMY_TABS;
  protected filteredEnemies = computed(() => filterEnemiesByTab(this.enemies(), this.enemyTab()));
  protected allSets = signal<DiscSetSummary[]>([]);
  protected selectedSetIds = signal<number[]>([]);
  protected selectedTeamId = signal<string | null>(null);
  protected selectedActiveIndex = signal<number>(0);
  protected selectedComboId = signal<string | null>(null);
  protected selectedEnemyId = signal<string | null>(null);
  protected errorMessage = signal<string | null>(null);

  protected readonly rarityOptions = RARITY_OPTIONS;
  protected readonly mainStatOptions = ALL_MAIN_STATS.map((k) => ({
    key: k,
    label: STAT_META[k]?.label ?? k,
  }));
  protected iconUrl = discSetIconUrl;

  protected mainStats = signal<string[]>([]);
  protected rarities = signal<string[]>(['S']);

  protected selectedTeam = computed(() =>
    this.teams().find((t) => t.id === this.selectedTeamId()) ?? null,
  );

  /** Resolves a member build id to its agent's display name. */
  private agentNameForBuild = computed(() => {
    const nameByAgent = new Map(this.agents().map((a) => [a.id, a.name]));
    const agentByBuild = new Map(this.builds().map((b) => [b.id, b.agent_id]));
    return (buildId: string): string | null => {
      const agentId = agentByBuild.get(buildId);
      return (agentId && nameByAgent.get(agentId)) ?? null;
    };
  });

  protected teamMemberIndices = computed(() => {
    const team = this.selectedTeam();
    if (!team) return [];
    return teamMemberSlots(team, this.agentNameForBuild());
  });

  /**
   * This context's buff state, seeded from the selected member's own build
   * columns (DESIGN §2.5, #95) — rank no longer broadcasts one shared store
   * value across contexts. Null while the build rows are still loading.
   */
  private selectedBuffContext = computed<BuffContextDefaults | null>(() => {
    const team = this.selectedTeam();
    if (!team) return null;
    const seedable = teamBuildsTargetFirst(team, this.selectedActiveIndex(), this.builds());
    return seedable.length > 0 ? buffContextForBuilds(seedable) : null;
  });

  protected isMainStatSelected(key: string): boolean { return this.mainStats().includes(key); }
  protected isRaritySelected(r: string): boolean { return this.rarities().includes(r); }

  protected toggleMainStat(key: string): void {
    const ms = this.mainStats();
    this.mainStats.set(ms.includes(key) ? ms.filter((x) => x !== key) : [...ms, key]);
    this.tryEmit();
  }

  protected toggleRarity(r: string): void {
    const rs = this.rarities();
    this.rarities.set(rs.includes(r as string) ? rs.filter((x) => x !== r) : [...rs, r]);
    this.tryEmit();
  }

  constructor() {
    void this.init();
  }

  private async init() {
    try {
      const [teams, builds, agents, enemies, sets] = await Promise.all([
        this.teamsService.list(),
        this.buildsService.list(),
        this.buildsService.listAgents(),
        this.calcService.listEnemies(),
        this.discSetsService.listSets(),
      ]);
      this.teams.set(teams);
      this.builds.set(builds);
      this.agents.set(agents);
      this.enemies.set(enemies);
      this.allSets.set(sets);
      const defaultId = defaultEnemyId(enemies, this.enemyTab());
      if (defaultId) {
        this.selectedEnemyId.set(defaultId);
        this.tryEmit();
      }
    } catch (e) {
      this.errorMessage.set(e instanceof Error ? e.message : String(e));
    }
  }

  protected async onTeamChange(teamId: string) {
    if (!teamId) {
      this.selectedTeamId.set(null);
      this.combos.set([]);
      this.selectedComboId.set(null);
      this.selectedActiveIndex.set(0);
      this.selectedSetIds.set([]);
      return;
    }
    this.selectedTeamId.set(teamId);
    this.selectedActiveIndex.set(0);
    this.combos.set([]);
    this.selectedComboId.set(null);
    this.selectedSetIds.set([]);
    try {
      const combos = await this.combosService.listForTeam(teamId);
      this.combos.set(combos);
      this.selectedComboId.set(combos[0]?.id ?? null);
      this.tryEmit();
    } catch (e) {
      this.errorMessage.set(e instanceof Error ? e.message : String(e));
    }
  }

  protected onMemberChange(index: number) {
    this.selectedActiveIndex.set(index);
    this.tryEmit();
  }

  protected onComboChange(comboId: string) {
    this.selectedComboId.set(comboId || null);
    this.tryEmit();
  }

  protected onEnemyChange(enemyId: string) {
    this.selectedEnemyId.set(enemyId || null);
    this.tryEmit();
  }

  protected onEnemyTabChange(tab: EnemyTab) {
    this.enemyTab.set(tab);
    const current = this.selectedEnemyId();
    const stillVisible = this.filteredEnemies().some((e) => e.id === current);
    if (!stillVisible) {
      this.selectedEnemyId.set(defaultEnemyId(this.enemies(), tab));
      this.tryEmit();
    }
  }

  protected toggleSet(hakushinId: number) {
    const ids = this.selectedSetIds();
    const next = ids.includes(hakushinId)
      ? ids.filter((id) => id !== hakushinId)
      : [...ids, hakushinId];
    this.selectedSetIds.set(next);
    this.tryEmit();
  }

  protected clearSets() {
    this.selectedSetIds.set([]);
    this.tryEmit();
  }

  private tryEmit() {
    const teamId = this.selectedTeamId();
    const comboId = this.selectedComboId();
    const enemyProfileId = this.selectedEnemyId();
    if (teamId && comboId && enemyProfileId) {
      const ids = this.selectedSetIds();
      this.selectionChange.emit({
        teamId,
        activeIndex: this.selectedActiveIndex(),
        comboId,
        enemyProfileId,
        allowedSetIds: ids.length > 0 ? ids : null,
        mainStats: this.mainStats(),
        rarities: this.rarities(),
        buffContext: this.selectedBuffContext(),
      });
    }
  }

  protected isSetSelected(hakushinId: number): boolean {
    return this.selectedSetIds().includes(hakushinId);
  }
}
