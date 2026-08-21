import { Component, computed, input, model, output } from '@angular/core';

import type { DiscRead } from '../../pages/builds/builds.service';
import { DiscCard } from './disc-card';
import { DiscFiltersPanel, type DiscFilterState, defaultFilters } from './disc-filters';
import { type DiscSetSummary, discSetIconUrl } from '../icon-url';

export type DiscListMode = 'browse' | 'pick';

@Component({
  selector: 'fairy-disc-list',
  standalone: true,
  imports: [DiscCard, DiscFiltersPanel],
  templateUrl: './disc-list.html',
  styleUrl: './disc-list.scss',
})
export class DiscList {
  discs = input<DiscRead[]>([]);
  discSets = input<DiscSetSummary[]>([]);
  /** Highlighted card in pick mode. */
  selectedDiscId = input<string | undefined>(undefined);
  mode = input<DiscListMode>('browse');
  /**
   * When non-zero, only discs in this slot are shown and the slot filter UI
   * is hidden (picker mode). When 0, the user can pick the slot via filters.
   */
  slotConstraint = input<number>(0);
  /** Build-name lookup keyed by build_id — passed through to disc-card. */
  buildNames = input<Record<string, string>>({});

  /** Two-way bindable filter state — parent can drive URL-synced filters. */
  filters = model<DiscFilterState>(defaultFilters());

  discSelected = output<string>();

  protected setNames = computed<Record<string, string>>(() => {
    const m: Record<string, string> = {};
    for (const s of this.discSets()) m[s.id] = s.name;
    return m;
  });

  protected setIcons = computed<Record<string, string | null>>(() => {
    const m: Record<string, string | null> = {};
    for (const s of this.discSets()) m[s.id] = discSetIconUrl(s.icon_path);
    return m;
  });

  protected setTooltips = computed<Record<string, string>>(() => {
    const m: Record<string, string> = {};
    for (const s of this.discSets()) {
      const parts: string[] = [];
      if (s.two_piece_text) parts.push(`2pc: ${s.two_piece_text}`);
      if (s.four_piece_text) parts.push(`4pc: ${s.four_piece_text}`);
      if (parts.length) m[s.id] = parts.join('\n\n');
    }
    return m;
  });

  protected filtered = computed<DiscRead[]>(() => {
    const f = this.filters();
    let items = this.discs();

    const constraint = this.slotConstraint();
    if (constraint !== 0) {
      items = items.filter((d) => Number(slotValue(d)) === constraint);
    } else if (f.slot) {
      items = items.filter((d) => Number(slotValue(d)) === f.slot);
    }

    if (f.mainStats.length > 0) {
      items = items.filter((d) => f.mainStats.includes(d.main_stat_type as string));
    }

    if (f.substats.length > 0) {
      items = items.filter((d) => {
        const subs = (d.substats ?? []) as { stat: string }[];
        return f.substats.every((req) => subs.some((s) => s.stat === req));
      });
    }

    if (f.sets.length > 0) {
      items = items.filter((d) => f.sets.includes(d.disc_set_id));
    }

    if (f.rarities.length > 0) {
      items = items.filter((d) => f.rarities.includes(d.rarity as string));
    }

    if (f.minLevel > 0) {
      items = items.filter((d) => d.level >= f.minLevel);
    }

    if (f.equipped === 'unequipped') {
      items = items.filter((d) => !d.build_id);
    } else if (f.equipped === 'any-equipped') {
      items = items.filter((d) => !!d.build_id);
    }

    return sortDiscs(items, f.sort, f.substats);
  });

  protected onFiltersChange(f: DiscFilterState): void {
    this.filters.set(f);
  }

  protected onSelect(discId: string): void {
    if (this.mode() === 'pick') {
      this.discSelected.emit(discId);
    }
  }
}

function slotValue(d: DiscRead): number {
  return (d.slot as unknown as { value?: number })?.value ?? (d.slot as unknown as number);
}

function sortDiscs(items: DiscRead[], sort: DiscFilterState['sort'], selectedSubstats: string[]): DiscRead[] {
  const copy = [...items];
  if (sort === 'level') {
    copy.sort((a, b) => b.level - a.level);
  } else if (sort === 'rolls') {
    copy.sort((a, b) => totalRolls(b) - totalRolls(a));
  } else if (sort === 'relevant-substats') {
    copy.sort((a, b) => relevantRolls(b, selectedSubstats) - relevantRolls(a, selectedSubstats));
  } else if (sort === 'slot') {
    copy.sort((a, b) => Number(slotValue(a)) - Number(slotValue(b)));
  }
  // 'recent' keeps server order (insertion order)
  return copy;
}

function totalRolls(d: DiscRead): number {
  const subs = (d.substats ?? []) as { rolls?: number }[];
  return subs.reduce((acc, s) => acc + (s.rolls ?? 1), 0);
}

function relevantRolls(d: DiscRead, selected: string[]): number {
  if (!selected.length) return totalRolls(d);
  const subs = (d.substats ?? []) as { stat: string; rolls?: number }[];
  return subs
    .filter((s) => selected.includes(s.stat))
    .reduce((acc, s) => acc + (s.rolls ?? 1), 0);
}
