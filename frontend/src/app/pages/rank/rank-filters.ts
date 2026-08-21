import {
  Component,
  input,
  output,
  signal,
} from '@angular/core';

import { type DiscSetSummary } from '../../shared/icon-url';
import { SetPicker } from '../../shared/set-picker/set-picker';

export type LevelMode = 'min' | 'max' | 'exact';

export interface RankFilterState {
  slot: number;
  levelValue: number | null;
  levelMode: LevelMode;
  mainStats: string[];
  sets: string[];
  rarities: string[];
}

export function defaultRankFilters(): RankFilterState {
  return { slot: 0, levelValue: null, levelMode: 'min', mainStats: [], sets: [], rarities: [] };
}

const SLOT_OPTIONS = [0, 1, 2, 3, 4, 5, 6] as const;
const LEVEL_VALUES = Array.from({ length: 16 }, (_, i) => i);
const LEVEL_MODES: LevelMode[] = ['min', 'max', 'exact'];

@Component({
  selector: 'rank-filters',
  standalone: true,
  imports: [SetPicker],
  templateUrl: './rank-filters.html',
  styleUrl: './rank-filters.scss',
})
export class RankFilters {
  discSets = input<DiscSetSummary[]>([]);

  filtersChange = output<RankFilterState>();

  protected readonly slotOptions = SLOT_OPTIONS;
  protected readonly levelValues = LEVEL_VALUES;
  protected readonly levelModes  = LEVEL_MODES;

  protected slot       = signal<number>(0);
  protected levelValue = signal<number | null>(null);
  protected levelMode  = signal<LevelMode>('min');
  protected sets       = signal<string[]>([]);

  protected setSlot(s: number): void {
    this.slot.set(s);
    this.emit();
  }

  protected onLevelValueChange(event: Event): void {
    const raw = (event.target as HTMLSelectElement).value;
    this.levelValue.set(raw === '' ? null : Number(raw));
    this.emit();
  }

  protected setLevelMode(mode: LevelMode): void {
    this.levelMode.set(mode);
    this.emit();
  }

  protected onSetChange(ids: string[]): void {
    this.sets.set(ids);
    this.emit();
  }

  protected reset(): void {
    this.slot.set(0);
    this.levelValue.set(null);
    this.levelMode.set('min');
    this.sets.set([]);
    this.emit();
  }

  private emit(): void {
    this.filtersChange.emit({
      slot: this.slot(),
      levelValue: this.levelValue(),
      levelMode: this.levelMode(),
      mainStats: [],
      sets: this.sets(),
      rarities: [],
    });
  }
}
