import { NgClass } from '@angular/common';
import { Component, input } from '@angular/core';

import { totalRolls } from '../disc-rolls';
import { formatStatLabel, formatStatValue } from '../stat-meta';
import type { DiscRead } from '../../pages/builds/builds.service';

export interface Substat {
  stat: string;
  value: number;
  rolls?: number;
}

const SLOT_LABEL: Record<number, string> = {
  1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI',
};

@Component({
  selector: 'mist-disc-card',
  standalone: true,
  imports: [NgClass],
  templateUrl: './disc-card.html',
  styleUrl: './disc-card.scss',
})
export class DiscCard {
  disc = input.required<DiscRead>();
  /** Set name lookup keyed by disc_set_id. */
  setNames = input<Record<string, string>>({});
  /** Set icon lookup keyed by disc_set_id. */
  setIcons = input<Record<string, string | null>>({});
  /** Tooltip text keyed by disc_set_id (2pc/4pc bonus descriptions). */
  setTooltips = input<Record<string, string>>({});
  /** Build name lookup keyed by build_id (for equipped indicator). */
  buildNames = input<Record<string, string>>({});
  /** Whether this card is currently selected (picker mode). */
  selected = input(false);

  protected iconUrl(): string | null {
    return this.setIcons()[this.disc().disc_set_id] ?? null;
  }

  protected setName(): string {
    return this.setNames()[this.disc().disc_set_id] ?? '—';
  }

  protected setTooltip(): string {
    return this.setTooltips()[this.disc().disc_set_id] ?? '';
  }

  protected slotLabel(): string {
    return SLOT_LABEL[this.disc().slot] ?? String(this.disc().slot);
  }

  protected mainLabel(): string {
    return formatStatLabel(this.disc().main_stat_type as string);
  }

  protected mainValue(): string {
    return formatStatValue(this.disc().main_stat_type as string, this.disc().main_stat_value);
  }

  protected substats(): Substat[] {
    const raw = this.disc().substats;
    if (!raw) return [];
    return raw as unknown as Substat[];
  }

  protected subLabel(s: Substat): string {
    return formatStatLabel(s.stat);
  }

  protected subValue(s: Substat): string {
    return formatStatValue(s.stat, s.value);
  }

  protected rollDots(s: Substat): number[] {
    return Array.from({ length: totalRolls(s.rolls) });
  }

  protected equippedBuildName(): string | null {
    const bid = this.disc().build_id;
    if (!bid) return null;
    return this.buildNames()[bid] ?? 'Equipped';
  }
}
