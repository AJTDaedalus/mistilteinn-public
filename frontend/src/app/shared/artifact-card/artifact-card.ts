import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { CatalogueIcon } from '../icon/icon';
import { SubstatBars, type SubstatReading } from '../substat-bars/substat-bars';

/**
 * One artifact, small: its art, its level, its main stat, and — on demand — its four lines
 * with roll bars.
 *
 * `BACKLOG_optimize.md` §16. A result row used to read `Flower · Plume · Sands · Goblet ·
 * Circlet` — five names that never change beside a number, which cannot show the difference
 * between rank 1 and rank 4 that a ranked list exists to show.
 *
 * **The art replaces both names** (owner, 2026-08-31): *"we could replace both the slot name
 * and the set name with just the icon, making it a little bigger."* That only became possible
 * once the per-slot icons were seeded — until then every slot drew the set's flower, so the
 * icon identified the set but not the piece, and the slot name was carrying that alone.
 * The names live on as the `title`, so nothing is lost to a reader who wants them.
 */
export interface ArtifactCardModel {
  id: string;
  /** The icon for this piece's own slot, falling back to the set's. */
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
    <div class="piece__head" [attr.title]="piece().slot + ' · ' + piece().setName">
      <catalogue-icon
        [icon]="piece().icon"
        [alt]="piece().slot + ', ' + piece().setName"
        [size]="compact() ? 34 : 44"
      />
      <div class="piece__figures">
        <span class="piece__main mono">{{ piece().mainStat }}</span>
        <!-- **The set name, in compact form too.** Compact dropped it to a tooltip, and on the
             optimize results that made ten ranked rows visually identical: the same five main
             stats on every line, the only difference a 34px icon. The set is the thing that
             actually differs between candidates, so it is the thing a ranked list has to show.
             The full card keeps showing substats below and has no need of it in this row. -->
        @if (compact()) {
          <span class="piece__set">{{ piece().setName }}</span>
        } @else {
          <span class="piece__level mono">+{{ piece().level }}</span>
        }
      </div>
    </div>

    @if (!compact()) {
      <ul class="piece__subs">
        @for (sub of piece().substats; track $index) {
          <li><substat-bars [sub]="sub" /></li>
        }
      </ul>
    }
  `,
  styleUrl: './artifact-card.scss',
  host: { '[class.piece--compact]': 'compact()' },
})
export class ArtifactCard {
  readonly piece = input.required<ArtifactCardModel>();
  /**
   * The row-level size: art, main stat and level only.
   *
   * **The substats are hidden here, not merely smaller** (owner): *"we could hide the stats
   * until you hit details, just show the set icons and main stats until hitting details."*
   * Five cards each carrying four bar-rows is most of a screen per result row, and the row's
   * job is to be scannable — the detail pane is where a piece is read.
   */
  readonly compact = input(false);
}
