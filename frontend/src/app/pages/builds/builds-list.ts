import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { BuildPriorityList } from './build-priority-list';
import { AgentSummary, BuildRead, BuildsService } from './builds.service';
import { agentIconUrl, elementIconUrl, specialtyIconUrl } from '../../shared/icon-url';
import { BuildFilters, BuildFilterState, defaultBuildFilters } from './build-filters';

@Component({
  selector: 'page-builds-list',
  imports: [RouterLink, BuildPriorityList, BuildFilters],
  templateUrl: './builds-list.html',
  styleUrl: './builds-list.scss',
})
export class BuildsListPage implements OnInit {
  private svc = inject(BuildsService);

  protected builds = signal<BuildRead[]>([]);
  protected agents = signal<AgentSummary[]>([]);
  protected loading = signal(true);
  protected error = signal<string | null>(null);
  protected priorityOpen = signal(false);
  protected filterState = signal<BuildFilterState>(defaultBuildFilters());

  protected agentName = computed(() => {
    const map = new Map<string, string>();
    for (const a of this.agents()) map.set(a.id, a.name);
    return (id: string | null | undefined): string =>
      (id && map.get(id)) ?? '—';
  });

  protected agentIcon = computed(() => {
    const map = new Map<string, string | null>();
    for (const a of this.agents()) map.set(a.id, agentIconUrl(a.icon_path));
    return (id: string | null | undefined): string | null =>
      (id && map.get(id)) ?? null;
  });

  protected agentElement = computed(() => {
    const map = new Map<string, string>();
    for (const a of this.agents()) map.set(a.id, a.element);
    return (id: string | null | undefined): string =>
      (id && map.get(id)) ?? '';
  });

  protected agentRarity = computed(() => {
    const map = new Map<string, string>();
    for (const a of this.agents()) map.set(a.id, a.rarity);
    return (id: string | null | undefined): string =>
      (id && map.get(id)) ?? '';
  });

  // Exposed for template use (icon path → static asset URL).
  protected elementIconUrl = elementIconUrl;
  protected specialtyIconUrl = specialtyIconUrl;

  protected filteredBuilds = computed(() => {
    const f = this.filterState();
    const nameOf = this.agentName();
    const elementOf = this.agentElement();
    return this.builds().filter(b => {
      if (f.text && !nameOf(b.agent_id).toLowerCase().includes(f.text.toLowerCase())) return false;
      if (f.elements.length > 0 && !f.elements.includes(elementOf(b.agent_id))) return false;
      if (f.specialties.length > 0 && !f.specialties.includes(b.agent_specialty)) return false;
      return true;
    });
  });

  async ngOnInit() {
    try {
      const [builds, agents] = await Promise.all([
        this.svc.list(),
        this.svc.listAgents(),
      ]);
      this.builds.set(builds);
      this.agents.set(agents);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }

  protected onPrioritySaved(updated: BuildRead[]) {
    this.builds.set(updated);
  }

  protected async deleteBuild(event: Event, id: string) {
    event.preventDefault();
    event.stopPropagation();
    if (!confirm('Delete this build?')) return;
    try {
      await this.svc.remove(id);
      this.builds.update((bs) => bs.filter((b) => b.id !== id));
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }
}
