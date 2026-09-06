import { DecimalPipe } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CatalogueIcon } from '../../shared/icon/icon';

import { catalogueList } from './catalogue-list';
import { CatalogueService, type EnemyProfileRead } from './catalogue.service';
import { allPages } from '../../api/all-pages';

/** The eight damage channels, in the order the resistance columns are read. */
const CHANNELS = [
  ['physical', 'physical_res'],
  ['anemo', 'anemo_res'],
  ['cryo', 'cryo_res'],
  ['dendro', 'dendro_res'],
  ['electro', 'electro_res'],
  ['geo', 'geo_res'],
  ['hydro', 'hydro_res'],
  ['pyro', 'pyro_res'],
] as const;

/** One profile with its resistances already shaped for the template. */
type EnemyRow = EnemyProfileRead & {
  resistances: { channel: string; percent: number; notable: boolean }[];
};

/**
 * The seeded enemy profiles — 360 entries.
 *
 * **Resistances are what this page is for**, because they are the only part of a profile the
 * damage chain reads. `base_hp`/`base_atk`/`base_def` are deliberately *not* shown as stats:
 * they are **curve bases**, not level-90 values (`backend/CLAUDE.md` — a Hilichurl's
 * `base_hp` is `13.584`), and nothing in this repo applies the curve yet. Printing `13.584`
 * next to the word "HP" would be a number that means something else, which is the failure
 * this project has spent every chunk avoiding.
 */
@Component({
  selector: 'page-enemies',
  imports: [FormsModule, DecimalPipe, CatalogueIcon],
  templateUrl: './enemies.html',
  styleUrl: './catalogue.scss',
})
export class EnemiesPage implements OnInit {
  protected search = '';
  // Reshaped **once per load**, not once per change-detection pass. Calling a method from
  // the template would rebuild 360 x 8 objects every cycle and hand `@for` a fresh array
  // identity each time, so nothing could be reused. The work is the same either way; how
  // often it happens is not.
  // 360 enemies against a cap of 200 — the worse of the two short lists.
  protected readonly list = catalogueList<EnemyRow>(async (name) => {
    const page = await allPages((offset, limit) =>
      this.catalogue.listEnemies({ name, offset, limit }),
    );
    return {
      ...page,
      items: page.items.map((enemy) => ({ ...enemy, resistances: resistancesOf(enemy) })),
    };
  });

  private readonly catalogue = inject(CatalogueService);

  ngOnInit(): void {
    void this.load();
  }

  protected load(): Promise<void> {
    return this.list.run(this.search, 'enemy catalogue');
  }
}

/**
 * Resistances as `(channel, percent)`, so the template does not repeat eight fields.
 *
 * All eight are always returned. A channel the row leaves null becomes `0` rather than
 * vanishing from the list: an absent entry would read as "this enemy has no cryo resistance"
 * when what it means is "we do not know", and `Enemy` in the damage chain refuses a partial
 * profile for exactly that reason.
 */
export function resistancesOf(
  enemy: EnemyProfileRead,
): { channel: string; percent: number; notable: boolean }[] {
  const rows = CHANNELS.map(([channel, field]) => ({
    channel,
    percent: (enemy[field] ?? 0) * 100,
  }));
  const baseline = modal(rows.map((row) => row.percent));
  return rows.map((row) => ({ ...row, notable: row.percent !== baseline }));
}

/**
 * The most common value in a list; the first one on a tie.
 *
 * **This is what makes an enemy card readable.** Nearly every profile is eight channels at
 * one shared number and one or two that differ — `physical 70%` on the Aeonblight Drake,
 * `hydro 70%` on the Narwhal — and all nine were drawn in the same size, weight and colour.
 * On a 13,000px page of near-identical cards, the one value worth reading was hidden among
 * eight that were not.
 *
 * Taken from the enemy's own values rather than assuming 10% is the baseline: 10% is merely
 * the *usual* baseline, and an enemy whose floor is something else would otherwise have all
 * nine channels flagged, which is the same as flagging none.
 *
 * When every channel agrees, the mode is that value and nothing is notable — correct, because
 * nothing about that enemy's resistances distinguishes it.
 */
function modal(values: number[]): number | undefined {
  const counts = new Map<number, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  let best: number | undefined;
  let bestCount = 0;
  for (const [value, count] of counts) {
    if (count > bestCount) {
      best = value;
      bestCount = count;
    }
  }
  return best;
}
