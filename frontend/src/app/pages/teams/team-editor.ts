import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Location } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { TeamsService, TeamRead } from './teams.service';
import { BuildsService, BuildRead, AgentSummary } from '../builds/builds.service';
import { agentIconUrl } from '../../shared/icon-url';
import { TeamMemberFilters, MemberFilterState, defaultMemberFilters } from './team-member-filters';
import { ComboBuilder, ComboMemberRef } from '../builds/combo-builder';

@Component({
  selector: 'page-team-editor',
  imports: [RouterLink, FormsModule, TeamMemberFilters, ComboBuilder],
  templateUrl: './team-editor.html',
  styleUrl: './team-editor.scss',
})
export class TeamEditorPage implements OnInit {
  private teamsSvc = inject(TeamsService);
  private buildsSvc = inject(BuildsService);
  private route = inject(ActivatedRoute);
  private location = inject(Location);

  protected teamId = signal<string | null>(null);
  protected teamName = signal('');
  protected selectedBuilds = signal<BuildRead[]>([]);

  protected builds = signal<BuildRead[]>([]);
  protected agents = signal<AgentSummary[]>([]);
  protected loading = signal(true);
  protected saving = signal(false);
  protected error = signal<string | null>(null);
  protected filters = signal<MemberFilterState>(defaultMemberFilters());

  protected isCreate = computed(() => this.teamId() === null);
  protected readonly defaultFilters = defaultMemberFilters;

  protected agentForBuild = computed(() => {
    const map = new Map<string, AgentSummary>();
    for (const a of this.agents()) map.set(a.id, a);
    return (build: BuildRead): AgentSummary | null =>
      map.get(build.agent_id) ?? null;
  });

  protected portrait = computed(() => {
    const resolve = this.agentForBuild();
    return (build: BuildRead): { name: string; iconUrl: string | null } => {
      const agent = resolve(build);
      return { name: agent?.name ?? '?', iconUrl: agentIconUrl(agent?.icon_path) };
    };
  });

  protected selectedIds = computed(() => new Set(this.selectedBuilds().map(b => b.id)));

  protected filteredBuilds = computed(() => {
    const f = this.filters();
    const resolve = this.agentForBuild();
    if (!f.name && !f.elements.length && !f.specialties.length && !f.rarities.length) {
      return this.builds();
    }
    const nameLower = f.name.toLowerCase();
    return this.builds().filter(build => {
      const agent = resolve(build);
      if (f.name && !agent?.name.toLowerCase().includes(nameLower)) return false;
      if (f.elements.length && (!agent || !f.elements.includes(agent.element))) return false;
      if (f.specialties.length && !f.specialties.includes(build.agent_specialty)) return false;
      if (f.rarities.length && (!agent || !f.rarities.includes(agent.rarity))) return false;
      return true;
    });
  });

  protected canSave = computed(() =>
    this.teamName().trim().length > 0 &&
    this.selectedBuilds().length >= 1 &&
    this.selectedBuilds().length <= 3
  );

  /** Show the Rotation section once the team is saved and has ≥1 member. */
  protected showRotation = computed(() =>
    this.teamId() !== null && this.selectedBuilds().length >= 1
  );

  /** Team members (slot order) for the combo builder's owner picker. */
  protected comboMembers = computed<ComboMemberRef[]>(() => {
    const resolve = this.agentForBuild();
    return this.selectedBuilds().map(b => ({
      buildId: b.id,
      agentId: b.agent_id,
      agentName: resolve(b)?.name ?? '?',
    }));
  });

  async ngOnInit() {
    const id = this.route.snapshot.paramMap.get('id');
    try {
      const [builds, agents] = await Promise.all([
        this.buildsSvc.list(),
        this.buildsSvc.listAgents(),
      ]);
      this.builds.set(builds);
      this.agents.set(agents);

      if (id && id !== 'new') {
        const team = await this.teamsSvc.get(id);
        this.teamId.set(team.id);
        this.teamName.set(team.name);
        const slotIds = [team.build1_id, team.build2_id ?? null, team.build3_id ?? null]
          .filter((bid): bid is string => bid != null);
        const buildMap = new Map(builds.map(b => [b.id, b]));
        this.selectedBuilds.set(slotIds.map(bid => buildMap.get(bid)).filter((b): b is BuildRead => b != null));
      }
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }

  protected toggleBuild(build: BuildRead) {
    const current = this.selectedBuilds();
    const idx = current.findIndex(b => b.id === build.id);
    if (idx !== -1) {
      this.selectedBuilds.set(current.filter((_, i) => i !== idx));
    } else if (current.length < 3) {
      this.selectedBuilds.set([...current, build]);
    }
  }

  protected removeMember(index: number) {
    this.selectedBuilds.update(bs => bs.filter((_, i) => i !== index));
  }

  protected async save() {
    if (!this.canSave()) return;
    this.saving.set(true);
    this.error.set(null);
    const members = this.selectedBuilds();
    const payload = {
      name: this.teamName().trim(),
      build1_id: members[0].id,
      build2_id: members[1]?.id ?? null,
      build3_id: members[2]?.id ?? null,
    };
    try {
      const id = this.teamId();
      let saved: TeamRead;
      if (id) {
        saved = await this.teamsSvc.update(id, payload);
      } else {
        saved = await this.teamsSvc.create(payload);
        this.teamId.set(saved.id);
        this.location.replaceState(`/teams/${saved.id}`);
      }
      this.teamName.set(saved.name);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.saving.set(false);
    }
  }
}
