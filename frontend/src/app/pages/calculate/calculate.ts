import {
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';

import { DecimalPipe, UpperCasePipe, KeyValuePipe } from '@angular/common';
import { Combobox, ComboboxOption } from '../../shared/combobox/combobox';
import {
  BuildRead,
  CalculateService,
  ComboRead,
  EnemyProfileRead,
  SimulationResponse,
  TeamRead,
} from './calculate.service';
import type { components } from '../../api/api.types';
import { StepDetailComponent } from './step-detail.component';
import { BuffRosterPanelComponent } from './buff-roster-panel.component';
import { StageBuffsPanelComponent } from '../../shared/stage-buffs/stage-buffs-panel';
import { ENEMY_TABS, filterEnemiesByTab, type EnemyTab } from '../../shared/enemy-tabs';
import { BuffContextStore } from '../../shared/buff-context.store';
import { customBuffId } from '../../shared/custom-buff-id';

@Component({
  selector: 'page-calculate',
  imports: [
    Combobox,
    StepDetailComponent,
    BuffRosterPanelComponent,
    StageBuffsPanelComponent,
    DecimalPipe,
    UpperCasePipe,
    KeyValuePipe,
  ],
  templateUrl: './calculate.html',
  styleUrl: './calculate.scss',
})
export class CalculatePage {
  private svc = inject(CalculateService);
  private buffContext = inject(BuffContextStore);

  // ---- form state
  protected teams = signal<TeamRead[]>([]);
  protected builds = signal<BuildRead[]>([]);
  protected combos = signal<ComboRead[]>([]);
  protected enemies = signal<EnemyProfileRead[]>([]);
  protected agents = signal<components['schemas']['AgentSummary'][]>([]);

  protected teamId = signal<string>('');
  protected comboId = signal<string>('');
  protected enemyId = signal<string>('');

  // ---- async result
  protected simulationResult = signal<SimulationResponse | null>(null);
  protected loading = signal(false);
  protected error = signal<string | null>(null);

  protected expandedSimEvent = signal<number | null>(null);

  protected toggleSimEvent(i: number) {
    this.expandedSimEvent.update((cur) => (cur === i ? null : i));
  }

  protected maxSimTime = computed(() => {
    const res = this.simulationResult();
    if (!res || res.events.length === 0) return 0;
    return Math.max(...res.events.map((e) => e.t));
  });

  protected activeAuraBlocks = computed(() => {
    const res = this.simulationResult();
    if (!res) return [];
    const blocks: { element: string; start: number; end: number }[] = [];
    let currentAura: { element: string; start: number } | null = null;
    const events = [...res.events].sort((a, b) => a.t - b.t);
    for (const e of events) {
      if (e.kind === 'anomaly') {
        if (currentAura) {
          blocks.push({ element: currentAura.element, start: currentAura.start, end: e.t });
        }
        currentAura = { element: e.element || '', start: e.t };
      } else if (e.kind === 'disorder' || e.kind === 'expire') {
        if (currentAura && currentAura.element === e.element) {
          blocks.push({ element: currentAura.element, start: currentAura.start, end: e.t });
          currentAura = null;
        }
      }
    }
    if (currentAura) {
      blocks.push({ element: currentAura.element, start: currentAura.start, end: this.maxSimTime() });
    }
    return blocks;
  });

  protected stunBlocks = computed(() => {
    const res = this.simulationResult();
    if (!res) return [];
    const blocks: { start: number; end: number }[] = [];
    let stunStart: number | null = null;
    const events = [...res.events].sort((a, b) => a.t - b.t);
    for (const e of events) {
      if (e.kind === 'stun_trigger') {
        stunStart = e.t;
      } else if (e.kind === 'stun_end') {
        if (stunStart !== null) {
          blocks.push({ start: stunStart, end: e.t });
          stunStart = null;
        }
      }
    }
    if (stunStart !== null) {
      blocks.push({ start: stunStart, end: this.maxSimTime() });
    }
    return blocks;
  });

  protected timelineEvents = computed(() => {
    const res = this.simulationResult();
    if (!res) return [];
    return res.events.map((e) => ({
      ...e,
      pct: this.maxSimTime() > 0 ? (e.t / this.maxSimTime()) * 100 : 0,
    }));
  });

  /** The selected team's member build ids in slot order. */
  protected memberBuildIds = computed<string[]>(() => {
    const team = this.teams().find((t) => t.id === this.teamId());
    if (!team) return [];
    return [team.build1_id, team.build2_id ?? null, team.build3_id ?? null].filter(
      (id): id is string => !!id,
    );
  });

  /**
   * Resolves a simulation owner key (build id, or a legacy ``dps``/``support1``/
   * ``support2`` role) to that member's agent display name. Simulation events
   * are keyed by build id once a team combo is run.
   */
  protected agentRoleToName = computed(() => {
    const agentById = new Map(this.agents().map((a) => [a.id, a.name]));
    const nameForBuild = (buildId: string): string => {
      const build = this.builds().find((b) => b.id === buildId);
      return (build && agentById.get(build.agent_id)) ?? buildId;
    };
    const members = this.memberBuildIds();
    return (key: string | null | undefined): string => {
      if (!key) return '—';
      const owner = this.resolveOwner(key, members);
      return owner ? nameForBuild(owner) : key;
    };
  });

  /**
   * Maps a stored step owner to a real member build id. Team combos persist the
   * owning member's build id in ``agent_id``; older combos may still carry the
   * legacy ``dps``/``support1``/``support2`` roles. Mirrors the combo builder's
   * owner resolution so playback matches authoring.
   */
  private resolveOwner(key: string, members: string[]): string {
    if (!key || key === 'dps') return members[0] ?? '';
    if (key === 'support1') return members[1] ?? members[0] ?? '';
    if (key === 'support2') return members[2] ?? members[0] ?? '';
    if (members.includes(key)) return key;
    return members[0] ?? key;
  }

  /**
   * One active-buff roster panel per team member (DESIGN_explainability.md
   * §2.3), keyed by the same build-id keys `sim.buff_roster` uses.
   */
  protected buffRosterPanels = computed(() => {
    const res = this.simulationResult();
    if (!res) return [];
    const nameForBuild = this.agentRoleToName();
    return this.memberBuildIds().map((buildId) => ({
      buildId,
      agentLabel: nameForBuild(buildId),
      roster: res.buff_roster?.[buildId] ?? [],
    }));
  });

  // ---- collapse state for the three heavy result sections -----------------
  protected buffsOpen = signal(false);

  /**
   * Stage-buff editor (#64). Collapsed by default but opened automatically when the
   * run already carries stage buffs — a buff silently applied behind a collapsed
   * header is exactly the "why is my number different?" the panel exists to answer.
   */
  protected stageBuffsOpen = signal(this.buffContext.customBuffs().length > 0);

  /**
   * How many stage buffs this run will actually apply — switched-off ones excluded.
   *
   * Counting the list length instead reported "3 active" for three buffs the user had
   * just unticked, contradicting the panel's own summary one click away.
   */
  protected stageBuffCount = computed(() => {
    const disabled = new Set(this.buffContext.disabledBuffs());
    return this.buffContext.customBuffs().filter((b) => !disabled.has(customBuffId(b.label))).length;
  });
  protected attributionOpen = signal(false);
  protected timelineOpen = signal(false);

  /** Summary: "N resolved across M agents" shown while buff rosters are collapsed. */
  protected buffsSummary = computed(() => {
    const panels = this.buffRosterPanels();
    const total = panels.reduce((sum, p) => sum + p.roster.length, 0);
    const agents = panels.length;
    return `${total} resolved across ${agents} agent${agents !== 1 ? 's' : ''}`;
  });

  /** Summary: top contributor name + pct, e.g. "Miyabi 62.4% · +2 more". */
  protected attributionSummary = computed(() => {
    const res = this.simulationResult();
    if (!res) return '';
    const total = res.totals['total'] ?? 0;
    if (total === 0) return '';
    const entries = Object.entries(res.per_agent_attribution ?? {})
      .map(([key, val]) => ({ name: this.agentRoleToName()(key), pct: (val / total) * 100 }))
      .sort((a, b) => b.pct - a.pct);
    if (entries.length === 0) return '';
    const top = entries[0];
    const rest = entries.length - 1;
    return `${top.name} ${top.pct.toFixed(1)}%${rest > 0 ? ` · +${rest} more` : ''}`;
  });

  /** Summary: "K events over Ts". */
  protected timelineSummary = computed(() => {
    const events = this.timelineEvents();
    const maxT = this.maxSimTime();
    return `${events.length} events over ${maxT.toFixed(1)}s`;
  });

  protected canEvaluate = computed(
    () => !!this.teamId() && !!this.comboId() && !!this.enemyId() && !this.loading(),
  );

  constructor() {
    void this.loadTeams();
    void this.loadBuilds();
    void this.loadEnemies();
    void this.loadAgents();

    effect(() => {
      const id = this.teamId();
      if (!id) {
        this.combos.set([]);
        return;
      }
      void this.loadCombos(id);
    });

    // Seed the shared buff context from the selected team's builds
    // (DESIGN_buff_context.md §2.2 — the client owns defaulting). The server
    // no longer falls back to build.active_conditions / disabled_buffs, so
    // without this a user who never opened the Builds defaults editor would
    // simulate with an empty context and silently lose all of it.
    effect(() => {
      const byId = new Map(this.builds().map((b) => [b.id, b]));
      const members = this.memberBuildIds().map((id) => byId.get(id));
      if (members.length > 0 && members.every((b): b is BuildRead => !!b)) {
        this.buffContext.seedFromBuilds(members);
      }
    });
  }

  protected teamOptions = computed<ComboboxOption[]>(() =>
    this.teams().map((t) => ({
      value: t.id,
      label: t.name || t.id,
    })),
  );

  protected comboOptions = computed<ComboboxOption[]>(() =>
    this.combos().map((c) => ({
      value: c.id,
      label: c.name,
      detail: `${c.sequence?.length ?? 0} steps`,
    })),
  );

  protected enemyTab = signal<EnemyTab>('bosses');
  protected readonly enemyTabs = ENEMY_TABS;

  protected enemyNameOptions = computed<ComboboxOption[]>(() => {
    const seen = new Set<string>();
    const out: ComboboxOption[] = [];
    for (const e of filterEnemiesByTab(this.enemies(), this.enemyTab())) {
      if (seen.has(e.name)) continue;
      seen.add(e.name);
      out.push({ value: e.name, label: e.name });
    }
    return out;
  });

  protected enemyName = signal<string>('');

  protected enemyVariantOptions = computed<ComboboxOption[]>(() => {
    const name = this.enemyName();
    if (!name) return [];
    return this.enemies()
      .filter((e) => e.name === name)
      .map((e) => ({
        value: e.id,
        label: `Lv ${e.level}`,
        detail: `rarity ${e.rarity}`,
      }));
  });

  protected onTeamPick(value: string | null) {
    this.teamId.set(value ?? '');
    this.comboId.set('');
    this.simulationResult.set(null);
  }

  protected onComboPick(value: string | null) {
    this.comboId.set(value ?? '');
    this.simulationResult.set(null);
  }

  protected onEnemyTabChange(tab: EnemyTab) {
    this.enemyTab.set(tab);
    const stillVisible = this.enemyNameOptions().some((o) => o.value === this.enemyName());
    if (!stillVisible) {
      this.enemyName.set('');
      this.enemyId.set('');
      this.simulationResult.set(null);
    }
  }

  protected onEnemyNamePick(value: string | null) {
    this.enemyName.set(value ?? '');
    const variants = this.enemyVariantOptions();
    this.enemyId.set(variants[0]?.value ?? '');
    this.simulationResult.set(null);
  }

  protected onEnemyVariantPick(value: string | null) {
    this.enemyId.set(value ?? '');
    this.simulationResult.set(null);
  }

  protected async evaluate() {
    if (!this.canEvaluate()) return;
    this.loading.set(true);
    this.error.set(null);
    try {
      const combo = this.combos().find((c) => c.id === this.comboId());
      const members = this.memberBuildIds();
      if (!combo) throw new Error('Rotation not found');
      if (members.length === 0) throw new Error('Team has no members');

      // Each member contributes a build snapshot, keyed by its own build id —
      // the same key team combo steps store in ``agent_id``.
      const teamBuilds: Record<string, string> = {};
      for (const buildId of members) teamBuilds[buildId] = buildId;

      const steps = (combo.sequence || []).map((raw) => {
        const s = raw as components['schemas']['ComboStepInput'];
        let moveName = s.move_name || '';
        if (s.step_type === 'stun_trigger') moveName = 'stun_trigger';
        else if (s.step_type === 'stun_end') moveName = 'stun_end';
        return {
          agent_id: this.resolveOwner(s.agent_id || '', members),
          move_name: moveName,
          conditions: [],
          variant_label: s.variant_label || null,
          single_tap: s.single_tap !== undefined ? s.single_tap : null,
          cycle_position: s.cycle_position !== undefined ? s.cycle_position : null,
        };
      });

      const res = await this.svc.simulate(teamBuilds, steps, this.enemyId());
      this.simulationResult.set(res);
      this.expandedSimEvent.set(null);
      // Collapse all heavy sections so each run starts compact.
      this.buffsOpen.set(false);
      this.attributionOpen.set(false);
      this.timelineOpen.set(false);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }

  // ---- loaders
  private async loadTeams() {
    try {
      this.teams.set(await this.svc.listTeams());
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }

  private async loadBuilds() {
    try {
      this.builds.set(await this.svc.listBuilds());
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }

  private async loadCombos(teamId: string) {
    try {
      this.combos.set(await this.svc.listTeamCombos(teamId));
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }

  private async loadEnemies() {
    try {
      this.enemies.set(await this.svc.listEnemies());
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }

  private async loadAgents() {
    try {
      this.agents.set(await this.svc.listAgents());
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }
}
