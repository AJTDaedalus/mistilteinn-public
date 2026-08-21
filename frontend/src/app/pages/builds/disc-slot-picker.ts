import { Component, computed, input, output, signal } from '@angular/core';

import type { DiscRead, DiscSetRead } from './builds.service';
import { DiscCard } from '../../shared/disc-list/disc-card';
import { DiscList } from '../../shared/disc-list/disc-list';
import { defaultFilters, type DiscFilterState } from '../../shared/disc-list/disc-filters';
import { discSetIconUrl } from '../../shared/icon-url';

const SLOT_LABEL: Record<number, string> = {
  1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI',
};

@Component({
  selector: 'disc-slot-picker',
  standalone: true,
  imports: [DiscCard, DiscList],
  templateUrl: './disc-slot-picker.html',
  styleUrl: './disc-slot-picker.scss',
})
export class DiscSlotPicker {
  slot = input.required<number>();
  /** Build ID — used for equip calls in the parent; not used internally. */
  buildId = input<string>('');
  /** All discs available for this build (unequipped + already on this build). */
  discs = input<DiscRead[]>([]);
  discSets = input<DiscSetRead[]>([]);
  /** Currently equipped disc in this slot. */
  currentDisc = input<DiscRead | null>(null);
  /** Build-name lookup for the equipped indicator on disc cards. */
  buildNames = input<Record<string, string>>({});

  equip = output<string | null>();

  protected open = signal(false);

  /** Filter state lives here so choices persist across close/reopen of the dialog. */
  protected pickerFilters = signal<DiscFilterState>({
    ...defaultFilters(),
    rarities: ['S', 'A', 'B'],
    minLevel: 0,
  });

  protected slotLabel = computed(() => SLOT_LABEL[this.slot()] ?? String(this.slot()));

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

  protected openPicker(): void {
    this.open.set(true);
  }

  protected closePicker(): void {
    this.open.set(false);
  }

  protected onSelect(discId: string): void {
    this.equip.emit(discId);
    this.open.set(false);
  }

  protected onUnequip(): void {
    this.equip.emit(null);
    this.open.set(false);
  }
}
