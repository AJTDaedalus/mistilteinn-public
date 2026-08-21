import { Component, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

export type StatFloorMap = Record<string, number>;

const STAT_FLOORS: { key: string; label: string; unit: string; max: number }[] = [
  { key: 'atk', label: 'ATK', unit: 'flat', max: 5000 },
  { key: 'atk_pct', label: 'ATK %', unit: 'bp', max: 10000 },
  { key: 'crit_rate', label: 'CRIT Rate', unit: 'bp', max: 10000 },
  { key: 'crit_dmg', label: 'CRIT DMG', unit: 'bp', max: 20000 },
  { key: 'pen_flat', label: 'PEN', unit: 'flat', max: 1000 },
  { key: 'pen_ratio', label: 'PEN Ratio', unit: 'bp', max: 10000 },
  { key: 'anomaly_proficiency', label: 'Anomaly Prof.', unit: 'flat', max: 1000 },
];

@Component({
  selector: 'optimizer-stat-floors',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './optimizer-stat-floors.html',
  styleUrl: './optimizer-stat-floors.scss',
})
export class OptimizerStatFloors {
  minStats = input<StatFloorMap>({});
  minStatsChange = output<StatFloorMap>();

  protected expanded = signal(false);
  protected readonly statFloors = STAT_FLOORS;

  protected toggle() {
    this.expanded.update((v) => !v);
  }

  protected getValue(key: string): number {
    return this.minStats()[key] ?? 0;
  }

  protected setValue(key: string, raw: string) {
    const val = Math.max(0, Number(raw) || 0);
    const next = { ...this.minStats(), [key]: val };
    if (val === 0) {
      const { [key]: _, ...rest } = next;
      this.minStatsChange.emit(rest);
    } else {
      this.minStatsChange.emit(next);
    }
  }
}
