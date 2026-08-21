import { Component, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

export type LockedSlotMap = Partial<Record<1 | 2 | 3 | 4 | 5 | 6, string>>;

const SLOTS = [1, 2, 3, 4, 5, 6] as const;

@Component({
  selector: 'optimizer-locked-slots',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './optimizer-locked-slots.html',
  styleUrl: './optimizer-locked-slots.scss',
})
export class OptimizerLockedSlots {
  lockedSlots = input<LockedSlotMap>({});
  lockedSlotsChange = output<LockedSlotMap>();

  protected expanded = signal(false);
  protected readonly slots = SLOTS;

  protected toggle() {
    this.expanded.update((v) => !v);
  }

  protected getValue(slot: number): string {
    return (this.lockedSlots() as Record<number, string>)[slot] ?? '';
  }

  protected setValue(slot: number, value: string) {
    const trimmed = value.trim();
    const next = { ...this.lockedSlots() } as Record<number, string>;
    if (trimmed) {
      next[slot] = trimmed;
    } else {
      delete next[slot];
    }
    this.lockedSlotsChange.emit(next as LockedSlotMap);
  }

  protected clear(slot: number) {
    this.setValue(slot, '');
  }
}
