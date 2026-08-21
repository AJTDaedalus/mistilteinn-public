import { Component, computed, input, model, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { STAT_META } from '../stat-meta';
import { type DiscSetSummary } from '../icon-url';
import { SetPicker } from '../set-picker/set-picker';

export type EquippedFilter = 'all' | 'unequipped' | 'any-equipped';
export type SortField = 'level' | 'rolls' | 'relevant-substats' | 'slot' | 'recent';

export interface DiscFilterState {
  slot: number;
  mainStats: string[];
  substats: string[];
  sets: string[];
  rarities: string[];
  minLevel: number;
  equipped: EquippedFilter;
  sort: SortField;
}

export function defaultFilters(): DiscFilterState {
  return {
    slot: 0,
    mainStats: [],
    substats: [],
    sets: [],
    rarities: ['S'],
    minLevel: 15,
    equipped: 'all',
    sort: 'level',
  };
}

// Slots 1–3 have fixed main stats (HP/ATK/DEF flat) — excluded from selector.
export const MAIN_STAT_BY_SLOT: Record<number, string[]> = {
  4: ['atk_pct', 'crit_rate', 'crit_dmg', 'anomaly_proficiency', 'hp_pct', 'def_pct'],
  5: ['atk_pct', 'hp_pct', 'pen_ratio', 'def_pct', 'ice_dmg', 'ether_dmg', 'electric_dmg', 'physical_dmg', 'fire_dmg'],
  6: ['atk_pct', 'anomaly_mastery', 'energy_regen', 'hp_pct', 'impact_pct', 'def_pct'],
};

const ALL_MAIN_STATS = [...new Set(Object.values(MAIN_STAT_BY_SLOT).flat())];

const SUBSTAT_OPTIONS: string[] = [
  'hp_pct', 'atk_pct', 'def_pct', 'hp', 'atk', 'def',
  'crit_rate', 'crit_dmg', 'pen_flat', 'anomaly_proficiency',
];

const RARITY_OPTIONS = ['S', 'A', 'B'] as const;

const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: 'level',              label: 'Level ↓' },
  { value: 'rolls',              label: 'Total rolls ↓' },
  { value: 'relevant-substats', label: 'Relevant rolls ↓' },
  { value: 'slot',              label: 'Slot ↑' },
  { value: 'recent',            label: 'Recently added' },
];

const EQUIPPED_OPTIONS: { value: EquippedFilter; label: string }[] = [
  { value: 'all',          label: 'All' },
  { value: 'unequipped',   label: 'Free' },
  { value: 'any-equipped', label: 'Equipped' },
];

const SLOT_OPTIONS = [0, 1, 2, 3, 4, 5, 6] as const;

@Component({
  selector: 'mist-disc-filters',
  standalone: true,
  imports: [FormsModule, SetPicker],
  templateUrl: './disc-filters.html',
  styleUrl: './disc-filters.scss',
})
export class DiscFiltersPanel {
  discSets = input<DiscSetSummary[]>([]);
  /**
   * When non-zero, the slot is externally fixed (picker mode).
   * Hides the slot selector and restricts main stat options to that slot.
   */
  slotConstraint = input<number>(0);

  filters = model<DiscFilterState>(defaultFilters());
  filtersChange = output<DiscFilterState>();

  protected readonly substatOptions = SUBSTAT_OPTIONS.map((k) => ({
    key: k, label: STAT_META[k]?.label ?? k,
  }));

  protected readonly rarityOptions = RARITY_OPTIONS;
  protected readonly sortOptions = SORT_OPTIONS;
  protected readonly equippedOptions = EQUIPPED_OPTIONS;
  protected readonly slotOptions = SLOT_OPTIONS;

  /** Main stat chips filtered to the effective slot. Empty for slots 1–3 (fixed main). */
  protected mainStatOptions = computed(() => {
    const effective = this.slotConstraint() || this.filters().slot;
    if (effective > 0 && effective <= 3) return [];
    const keys = effective ? (MAIN_STAT_BY_SLOT[effective] ?? ALL_MAIN_STATS) : ALL_MAIN_STATS;
    return keys.map((k) => ({ key: k, label: STAT_META[k]?.label ?? k }));
  });

  protected isMainStatSelected(key: string): boolean {
    return this.filters().mainStats.includes(key);
  }

  protected isSubstatSelected(key: string): boolean {
    return this.filters().substats.includes(key);
  }

  protected isRaritySelected(r: string): boolean {
    return this.filters().rarities.includes(r);
  }

  protected toggleMainStat(key: string): void {
    this.updateFilters((f) => ({ ...f, mainStats: toggle(f.mainStats, key) }));
  }

  protected toggleSubstat(key: string): void {
    this.updateFilters((f) => ({ ...f, substats: toggle(f.substats, key) }));
  }

  protected onSetChange(ids: string[]): void {
    this.updateFilters((f) => ({ ...f, sets: ids }));
  }

  protected toggleRarity(r: string): void {
    this.updateFilters((f) => ({ ...f, rarities: toggle(f.rarities, r) }));
  }

  protected setSlot(slot: number): void {
    this.updateFilters((f) => {
      if (slot > 0 && slot <= 3) return { ...f, slot, mainStats: [] };
      const validKeys = slot ? (MAIN_STAT_BY_SLOT[slot] ?? ALL_MAIN_STATS) : ALL_MAIN_STATS;
      const mainStats = f.mainStats.filter((k) => validKeys.includes(k));
      return { ...f, slot, mainStats };
    });
  }

  protected setMinLevel(value: number): void {
    this.updateFilters((f) => ({ ...f, minLevel: value }));
  }

  protected setEquipped(value: EquippedFilter): void {
    this.updateFilters((f) => ({ ...f, equipped: value }));
  }

  protected setSort(value: SortField): void {
    this.updateFilters((f) => ({ ...f, sort: value }));
  }

  protected reset(): void {
    const next = defaultFilters();
    this.filters.set(next);
    this.filtersChange.emit(next);
  }

  protected get currentMinLevel(): number {
    return this.filters().minLevel;
  }

  private updateFilters(fn: (f: DiscFilterState) => DiscFilterState): void {
    const next = fn(this.filters());
    this.filters.set(next);
    this.filtersChange.emit(next);
  }
}

function toggle(arr: string[], key: string): string[] {
  return arr.includes(key) ? arr.filter((x) => x !== key) : [...arr, key];
}
