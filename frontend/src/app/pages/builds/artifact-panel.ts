import { Component, computed, effect, inject, input, signal } from '@angular/core';

import { apiErrorMessage } from '../../api/api-error';
import { CardPicker, type CardFilter, type CardOption } from '../../shared/card-picker/card-picker';
import { formatStat } from '../../shared/stat-label';
import { rollValuePercent, substatReadings } from '../../shared/substat-bars/substat-bars';
import {
  ArtifactsService,
  type ArtifactOptions,
  type ArtifactRead,
  type ArtifactSlotKey,
} from '../artifacts/artifacts.service';

/** One of the build's five slots, with what fills it and what could. */
export interface PanelSlot {
  key: ArtifactSlotKey;
  display: string;
  equipped: ArtifactRead | null;
  candidates: ArtifactRead[];
}

/**
 * The five artifact slots on a build.
 *
 * **The picker offers only pieces the API would accept.** A.1 refuses a slot that is already
 * filled, naming the holder rather than swapping — so a picker listing equipped pieces would
 * let a user choose one and be told their own choice is invalid. Each slot therefore offers
 * the *unequipped* pieces of that slot, fetched with the server's own filters.
 *
 * Its own component rather than more of `builds.ts`: the build editor is already a form with
 * eight fields, and five slots each with a picker and two actions is a second thing happening
 * in the same file.
 */
@Component({
  selector: 'build-artifact-panel',
  imports: [CardPicker],
  templateUrl: './artifact-panel.html',
  styleUrl: './artifact-panel.scss',
})
export class ArtifactPanel {
  /** Null while a new build is being composed — nothing can be equipped to a build yet. */
  readonly buildId = input<string | null>(null);

  // **A piece equipped to another build is not offered here.** The API would take it — A.1
  // refuses a filled *target* slot, not a piece with an owner — but moving one silently
  // strips it from the other build, and the user would find that out from a damage number.
  // Taking it off there first is the visible version of the same move.

  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly slots = signal<PanelSlot[]>([]);

  protected readonly hasBuild = computed(() => this.buildId() !== null);

  private readonly service = inject(ArtifactsService);
  private options: ArtifactOptions | null = null;

  constructor() {
    // Reloads whenever the build changes, including from null when one is first saved.
    effect(() => {
      const id = this.buildId();
      void this.load(id);
    });
  }

  protected async equip(artifactId: string): Promise<void> {
    const id = this.buildId();
    // An empty selection is the "Empty" option, which means "leave this alone" rather than
    // "equip nothing" — there is no piece to send.
    if (!id || !artifactId) return;
    await this.act(() => this.service.equip(artifactId, id));
  }

  protected async unequip(slot: PanelSlot): Promise<void> {
    const piece = slot.equipped;
    if (!piece) return;
    await this.act(() => this.service.equip(piece.id, null));
  }

  /** `CRIT DMG 62.2%` — through the published vocabulary, never a table of our own. */
  protected describe(piece: ArtifactRead): string {
    const stat = this.options?.stats.find((s) => s.key === piece.main_stat_type);
    if (!stat) return String(piece.main_stat_type);
    return `${stat.display} ${formatStat(piece.main_stat_value, stat.percentage)}`;
  }

  /**
   * One candidate as a card.
   *
   * **This was a native `<select>` holding 360 single-line options.** The audit's third finding:
   * no search, no sort, no roll value, no substats, no art — *"none of the information the
   * Inventory page shows for the same pieces, and no way to find the good one in three
   * hundred"*. It was also the only native control in a dialog whose character and weapon
   * fields are card pickers, so the most important control in it was the least designed one.
   *
   * Everything below is already computed elsewhere and was simply not reaching this control:
   * `substatReadings` and `rollValuePercent` are the inventory's own helpers, reused rather
   * than reimplemented so the two surfaces cannot disagree about what a piece is worth.
   */
  private toOption(piece: ArtifactRead): CardOption {
    const readings = substatReadings(
      piece.substats as never, piece.substat_analysis as never,
      (stat, value) => this.substatLabel(stat, value),
    );
    const rolled = readings
      .map((sub) => rollValuePercent(sub))
      .filter((value): value is number => value !== null);
    // The piece's total roll value, which is what sorting "the good one" out of three hundred
    // actually means. Absent rather than zero when nothing could be established — a `0%` on a
    // piece whose rolls could not be decomposed would read as a bad piece rather than an
    // unknown one.
    const total = rolled.length
      ? `RV ${rolled.reduce((sum, value) => sum + value, 0)}%`
      : null;
    return {
      value: piece.id,
      label: piece.set_name || 'No set',
      detail: [`+${piece.level}`, this.describe(piece), total]
        .filter(Boolean).join(' · '),
      // The substats, which the `<select>` could not show at all — an `<option>` is one line of
      // text. This is the information the choice is actually made on.
      tooltip: readings.map((sub) => sub.label).join('\n') || undefined,
      tags: {
        set: piece.set_name || 'No set',
        main: String(piece.main_stat_type),
      },
    };
  }

  private substatLabel(stat: string, value: unknown): string {
    const found = this.options?.stats.find((s) => s.key === stat);
    if (!found) return `${stat} ${value}`;
    return `${found.display} ${formatStat(Number(value ?? 0), found.percentage)}`;
  }

  /**
   * The slot's candidates as cards, **best first**.
   *
   * The audit's complaint was not only that the `<select>` was plain — it was that there was
   * *"no way to find the good one in three hundred"*. Offering 2,200 flowers in database order
   * has the same problem in a prettier control, and the first screen was entirely `+0` pieces.
   *
   * Level first, then roll value: a `+20` is a piece someone invested in, and a lucky `+0`
   * ranking above it would be the sort actively misleading. Within a level, roll value is the
   * only quality signal this data carries.
   */
  protected options_for(slot: PanelSlot): CardOption[] {
    return [...slot.candidates]
      .sort((a, b) => (b.level - a.level) || (this.rollTotal(b) - this.rollTotal(a)))
      .map((piece) => this.toOption(piece));
  }

  /** A piece's total roll value as a percentage, or 0 when nothing could be established. */
  private rollTotal(piece: ArtifactRead): number {
    return substatReadings(
      piece.substats as never, piece.substat_analysis as never, () => '',
    ).reduce((sum, sub) => sum + (rollValuePercent(sub) ?? 0), 0);
  }

  /**
   * Set and main stat, the two axes a player narrows a slot by.
   *
   * Drawn from the candidates on screen rather than the catalogue, for the reason the builds
   * page gives: a chip whose only possible outcome is an empty list is a control that cannot
   * work.
   */
  protected filtersFor(slot: PanelSlot): CardFilter[] {
    const sets = new Set<string>();
    const mains = new Map<string, string>();
    for (const piece of slot.candidates) {
      sets.add(piece.set_name || 'No set');
      mains.set(String(piece.main_stat_type), this.mainStatName(piece.main_stat_type));
    }
    const filters: CardFilter[] = [];
    if (sets.size > 1) {
      filters.push({
        group: 'set',
        label: 'Set',
        options: [...sets].sort().map((name) => ({ value: name, label: name })),
      });
    }
    if (mains.size > 1) {
      filters.push({
        group: 'main',
        label: 'Main stat',
        options: [...mains].sort((a, b) => a[1].localeCompare(b[1]))
          .map(([value, label]) => ({ value, label })),
      });
    }
    return filters;
  }

  private mainStatName(key: string): string {
    return this.options?.stats.find((s) => s.key === key)?.display ?? String(key);
  }

  private async act(action: () => Promise<unknown>): Promise<void> {
    this.error.set(null);
    try {
      await action();
      await this.load(this.buildId());
    } catch (err) {
      // Verbatim: A.1's refusal names the piece already in the slot, which is more use than
      // anything this panel could invent.
      this.error.set(apiErrorMessage(err));
    }
  }

  private async load(buildId: string | null): Promise<void> {
    if (buildId === null) {
      this.slots.set([]);
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    try {
      this.options ??= await this.service.options();
      // Two requests, not six. `build_id` has to be the server's — fetching every equipped
      // piece to find five scales with the whole inventory. Splitting the *spare* pieces by
      // slot does not: the five slot-filtered requests would carry exactly the same rows
      // between them, so doing it here costs nothing and saves four round trips.
      const [equipped, free] = await Promise.all([
        this.service.list({ build_id: buildId }),
        this.service.list({ equipped: false }),
      ]);
      const held = new Map(equipped.items.map((piece) => [piece.slot, piece]));
      this.slots.set(
        this.options.slots.map((slot) => ({
          key: slot.key as ArtifactSlotKey,
          display: slot.display,
          equipped: held.get(slot.key) ?? null,
          candidates: free.items.filter((piece) => piece.slot === slot.key),
        })),
      );
    } catch {
      // Surfaced rather than left as five empty slots, which would read as "you own nothing
      // that fits" — a different and much more discouraging statement.
      this.error.set('Could not load this build’s artifacts.');
      this.slots.set([]);
    } finally {
      this.loading.set(false);
    }
  }
}
