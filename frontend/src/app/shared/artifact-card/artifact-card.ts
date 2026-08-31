import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { CatalogueIcon } from '../icon/icon';
import { SubstatBars, type SubstatReading } from '../substat-bars/substat-bars';

/**
 * One artifact, small: its set art, its level, its main stat, and its four lines with roll
 * bars.
 *
 * `BACKLOG_optimize.md` §16. A result row used to read `Flower · Plume · Sands · Goblet ·
 * Circlet` beside a number — ten identical lines, saying nothing about *which* pieces won.
 * The difference between rank 1 and rank 4 is the thing a ranked list is for, and five names
 * that never change cannot show it.
 */
export interface ArtifactCardModel {
  id: string;
  /** The set's icon basename, or null. `catalogue-icon` renders nothing for a null. */
  icon: string | null;
  setName: string;
  slot: string;
  level: number;
  /** Already formatted — `ATK +46.6%`. Formatting stat values is the caller's job. */
  mainStat: string;
  substats: SubstatReading[];
}

@Component({
  selector: 'artifact-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CatalogueIcon, SubstatBars],
  template: `
    <header class="piece__head">
      <catalogue-icon [icon]="piece().icon" [alt]="''" [size]="compact() ? 28 : 40" />
      <div class="piece__ident">
        <span class="piece__slot">{{ piece().slot }}</span>
        <span class="piece__set">{{ piece().setName }}</span>
      </div>
      <span class="piece__level mono">+{{ piece().level }}</span>
    </header>

    <p class="piece__main mono">{{ piece().mainStat }}</p>

    <ul class="piece__subs">
      @for (sub of piece().substats; track $index) {
        <li>
          <substat-bars [sub]="sub" [showRollValue]="!compact()" />
        </li>
      }
    </ul>
  `,
  styleUrl: './artifact-card.scss',
  host: { '[class.piece--compact]': 'compact()' },
})
export class ArtifactCard {
  readonly piece = input.required<ArtifactCardModel>();
  /** The row-level size: no roll-value column, smaller art. */
  readonly compact = input(false);
}
