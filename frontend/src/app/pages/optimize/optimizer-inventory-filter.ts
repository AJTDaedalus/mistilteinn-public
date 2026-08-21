import { Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

export interface InventoryFilterState {
  minRarity: 'S' | 'A' | 'B';
  minLevel: number;
  mainStatBySlot: Partial<Record<4 | 5 | 6, string[]>>;
}

export const SLOT_MAINS: Record<4 | 5 | 6, { key: string; label: string }[]> = {
  4: [
    { key: 'hp_pct', label: 'HP%' },
    { key: 'atk_pct', label: 'ATK%' },
    { key: 'def_pct', label: 'DEF%' },
    { key: 'crit_rate', label: 'CRIT Rate' },
    { key: 'crit_dmg', label: 'CRIT DMG' },
    { key: 'anomaly_proficiency', label: 'Anomaly Prof.' },
  ],
  5: [
    { key: 'hp_pct', label: 'HP%' },
    { key: 'atk_pct', label: 'ATK%' },
    { key: 'def_pct', label: 'DEF%' },
    { key: 'pen_ratio', label: 'PEN Ratio' },
    { key: 'physical_dmg', label: 'Physical DMG%' },
    { key: 'fire_dmg', label: 'Fire DMG%' },
    { key: 'ice_dmg', label: 'Ice DMG%' },
    { key: 'electric_dmg', label: 'Electric DMG%' },
    { key: 'ether_dmg', label: 'Ether DMG%' },
  ],
  6: [
    { key: 'hp_pct', label: 'HP%' },
    { key: 'atk_pct', label: 'ATK%' },
    { key: 'def_pct', label: 'DEF%' },
    { key: 'anomaly_mastery', label: 'Anomaly Mastery' },
    { key: 'impact_pct', label: 'Impact%' },
    { key: 'energy_regen', label: 'Energy Regen' },
  ],
};

const RARITIES: ('S' | 'A' | 'B')[] = ['S', 'A', 'B'];
const MAIN_STAT_SLOTS = [4, 5, 6] as const;

export function emptyInventoryFilterState(): InventoryFilterState {
  return { minRarity: 'S', minLevel: 15, mainStatBySlot: {} };
}

@Component({
  selector: 'optimizer-inventory-filter',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './optimizer-inventory-filter.html',
  styleUrl: './optimizer-inventory-filter.scss',
})
export class OptimizerInventoryFilter {
  state = input<InventoryFilterState>(emptyInventoryFilterState());
  stateChange = output<InventoryFilterState>();

  protected readonly rarities = RARITIES;
  protected readonly mainStatSlots = MAIN_STAT_SLOTS;
  protected readonly slotMains = SLOT_MAINS;

  protected setRarity(r: 'S' | 'A' | 'B') {
    this.stateChange.emit({ ...this.state(), minRarity: r });
  }

  protected setLevel(raw: string) {
    const val = Math.max(0, Math.min(15, Number(raw) || 0));
    this.stateChange.emit({ ...this.state(), minLevel: val });
  }

  protected isMainSelected(slot: 4 | 5 | 6, key: string): boolean {
    return (this.state().mainStatBySlot[slot] ?? []).includes(key);
  }

  protected toggleMain(slot: 4 | 5 | 6, key: string) {
    const current = this.state().mainStatBySlot[slot] ?? [];
    const next = current.includes(key)
      ? current.filter((k) => k !== key)
      : [...current, key];
    const bySlot = { ...this.state().mainStatBySlot, [slot]: next };
    // Drop empty arrays (empty = any allowed)
    if (next.length === 0) {
      delete bySlot[slot];
    }
    this.stateChange.emit({ ...this.state(), mainStatBySlot: bySlot });
  }

  protected slotMainsCount(slot: 4 | 5 | 6): number {
    return (this.state().mainStatBySlot[slot] ?? []).length;
  }
}
