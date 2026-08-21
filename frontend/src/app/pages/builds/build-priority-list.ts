import {
  Component,
  OnChanges,
  SimpleChanges,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';

import { AgentSummary, BuildRead, BuildsService } from './builds.service';
import { agentIconUrl } from '../../shared/icon-url';

@Component({
  selector: 'build-priority-list',
  imports: [],
  templateUrl: './build-priority-list.html',
  styleUrl: './build-priority-list.scss',
})
export class BuildPriorityList implements OnChanges {
  private svc = inject(BuildsService);

  builds = input<BuildRead[]>([]);
  agents = input<AgentSummary[]>([]);
  prioritySaved = output<BuildRead[]>();
  closed = output<void>();

  protected ranked = signal<BuildRead[]>([]);
  protected unranked = signal<BuildRead[]>([]);
  protected saving = signal(false);
  protected error = signal<string | null>(null);
  protected dirty = signal(false);

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

  ngOnChanges(changes: SimpleChanges) {
    if (changes['builds']) this.syncFromBuilds();
  }

  private syncFromBuilds() {
    const all = this.builds();
    const r = all
      .filter((b) => b.optimizer_priority != null)
      .sort((a, b) => (a.optimizer_priority ?? 0) - (b.optimizer_priority ?? 0));
    const u = all.filter((b) => b.optimizer_priority == null);
    this.ranked.set(r);
    this.unranked.set(u);
    this.dirty.set(false);
  }

  protected moveUp(index: number) {
    if (index === 0) return;
    this.ranked.update((list) => {
      const arr = [...list];
      [arr[index - 1], arr[index]] = [arr[index], arr[index - 1]];
      return arr;
    });
    this.dirty.set(true);
  }

  protected moveDown(index: number) {
    if (index >= this.ranked().length - 1) return;
    this.ranked.update((list) => {
      const arr = [...list];
      [arr[index], arr[index + 1]] = [arr[index + 1], arr[index]];
      return arr;
    });
    this.dirty.set(true);
  }

  protected promote(build: BuildRead) {
    this.unranked.update((u) => u.filter((b) => b.id !== build.id));
    this.ranked.update((r) => [...r, build]);
    this.dirty.set(true);
  }

  protected demote(build: BuildRead) {
    this.ranked.update((r) => r.filter((b) => b.id !== build.id));
    this.unranked.update((u) => [...u, build]);
    this.dirty.set(true);
  }

  protected async save() {
    this.saving.set(true);
    this.error.set(null);
    try {
      const ids = this.ranked().map((b) => b.id);
      const result = await this.svc.setPriorityOrder(ids);
      this.dirty.set(false);
      this.prioritySaved.emit(result);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.saving.set(false);
    }
  }
}
