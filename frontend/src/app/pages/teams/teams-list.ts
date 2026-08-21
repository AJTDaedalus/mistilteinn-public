import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { TeamsService, TeamRead } from './teams.service';
import { BuildsService, BuildRead, AgentSummary } from '../builds/builds.service';
import { agentIconUrl } from '../../shared/icon-url';

@Component({
  selector: 'page-teams-list',
  imports: [RouterLink],
  templateUrl: './teams-list.html',
  styleUrl: './teams-list.scss',
})
export class TeamsListPage implements OnInit {
  private teamsSvc = inject(TeamsService);
  private buildsSvc = inject(BuildsService);

  protected teams = signal<TeamRead[]>([]);
  protected builds = signal<BuildRead[]>([]);
  protected agents = signal<AgentSummary[]>([]);
  protected loading = signal(true);
  protected error = signal<string | null>(null);

  protected agentForBuild = computed(() => {
    const buildMap = new Map<string, string>();
    for (const b of this.builds()) buildMap.set(b.id, b.agent_id);
    const agentMap = new Map<string, AgentSummary>();
    for (const a of this.agents()) agentMap.set(a.id, a);
    return (buildId: string | null | undefined): AgentSummary | null => {
      if (!buildId) return null;
      const agentId = buildMap.get(buildId);
      return agentId ? (agentMap.get(agentId) ?? null) : null;
    };
  });

  protected memberPortraits = computed(() => {
    const resolve = this.agentForBuild();
    return (team: TeamRead): { name: string; iconUrl: string | null }[] => {
      return [team.build1_id, team.build2_id ?? null, team.build3_id ?? null]
        .filter((id): id is string => id != null)
        .map(id => {
          const agent = resolve(id);
          return {
            name: agent?.name ?? '?',
            iconUrl: agentIconUrl(agent?.icon_path),
          };
        });
    };
  });

  async ngOnInit() {
    try {
      const [teams, builds, agents] = await Promise.all([
        this.teamsSvc.list(),
        this.buildsSvc.list(),
        this.buildsSvc.listAgents(),
      ]);
      this.teams.set(teams);
      this.builds.set(builds);
      this.agents.set(agents);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }

  protected async deleteTeam(event: Event, id: string) {
    event.preventDefault();
    event.stopPropagation();
    if (!confirm('Delete this team?')) return;
    try {
      await this.teamsSvc.remove(id);
      this.teams.update(ts => ts.filter(t => t.id !== id));
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }
}
