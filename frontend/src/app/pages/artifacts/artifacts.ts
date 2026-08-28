import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { apiErrorMessage } from '../../api/api-error';
import { CatalogueIcon } from '../../shared/icon/icon';
import { CatalogueService } from '../catalogue/catalogue.service';
import {
  ArtifactsService,
  type ArtifactOptions,
  type ArtifactRead,
  type ArtifactSlotKey,
  type GoodImportResponse,
  type ImportMode,
} from './artifacts.service';

/** One piece, with everything the row needs already resolved. */
export interface ArtifactRow {
  id: string;
  setName: string;
  setIcon: string | null;
  slot: string;
  stars: number;
  level: number;
  mainStat: string;
  substats: string[];
  equipped: boolean;
  /**
   * How much upgrading is left, with the parts behind it — or null when the schedule could
   * not answer for this piece.
   *
   * Null is not zero. Zero is the honest answer for a maxed piece; null means the row is at a
   * level its rarity cannot reach, and showing "0 rolls left" for that would hide a broken
   * piece behind a plausible number.
   */
  potential: { headline: string; detail: string } | null;
}

/**
 * `0.466` → `46.6%`, `4780` → `4,780`. The flag decides; the page does not guess.
 *
 * Non-numeric input is rendered rather than thrown on. `substats` is a JSONB column with no
 * schema behind it, so a row written by an older importer or by hand can hold anything — and
 * `.toFixed` on that is a `TypeError` inside a computed, which takes out **the entire
 * inventory** rather than one substat. Showing the raw value keeps the bad row visible and
 * the other 799 readable.
 */
export function formatStat(value: unknown, percentage: boolean): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return String(value);
  return percentage
    ? `${(value * 100).toFixed(1)}%`
    : value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

/**
 * The artifact inventory, and the GOOD import that fills it.
 *
 * **The import result is rendered in full.** The endpoint rejects individual artifacts rather
 * than failing the file — someone with 800 pieces and two odd ones wants the 798 — so a page
 * showing only "imported 798" has thrown away the only record of the two. Every rejection is
 * listed with its reason.
 *
 * **`mode` is chosen, never defaulted.** `replace` and `append` are different intentions and
 * GOOD carries no stable per-artifact id to merge on, so a default would be this page
 * deciding whether to delete someone's inventory.
 *
 * Rows are drawn from the vocabulary at `/artifacts/options`: `slot` and `main_stat_type`
 * carry the source's internal spellings, and the stored values are units-dependent — `4780`
 * is flat HP and `0.466` is 46.6%. A page translating those itself would be a second copy of
 * `StatType.display` and `is_percentage`.
 */
@Component({
  selector: 'page-artifacts',
  imports: [FormsModule, CatalogueIcon],
  templateUrl: './artifacts.html',
  styleUrl: './artifacts.scss',
})
export class ArtifactsPage implements OnInit {
  protected readonly loading = signal(true);
  /** Non-null means the page failed to load. Never rendered as "you have no artifacts". */
  protected readonly error = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);

  protected readonly options = signal<ArtifactOptions | null>(null);
  protected readonly artifacts = signal<ArtifactRead[]>([]);
  protected readonly total = signal(0);
  protected readonly truncated = signal(false);

  protected slotFilter = '';
  /** Non-null after an import, so the result stays on screen to be read. */
  protected readonly importResult = signal<GoodImportResponse | null>(null);
  protected readonly importing = signal(false);
  /** Deliberately empty: the user picks. See the class docstring. */
  protected mode: ImportMode | '' = '';
  protected payloadText = '';

  protected readonly slots = computed(() => this.options()?.slots ?? []);

  /**
   * Set id → art, joined here rather than added to `ArtifactRead`.
   *
   * `/artifact-sets` already publishes the basename and there are 65 of them, so this is one
   * extra request against a list the app can hold entirely. Widening the artifact schema
   * would put the same value on every one of a user's several hundred pieces.
   *
   * Empty until it loads, and a miss yields null — which `CatalogueIcon` renders as nothing.
   * Art arriving late must never hold up the inventory.
   */
  protected readonly setIcons = signal<Map<string, string | null>>(new Map());

  protected readonly rows = computed<ArtifactRow[]>(() => {
    const opts = this.options();
    if (!opts) return [];
    const stats = new Map(opts.stats.map((s) => [s.key, s]));
    const slots = new Map(opts.slots.map((s) => [s.key, s.display]));
    const stars = new Map(opts.rarities.map((r) => [r.key, r.stars]));
    const setArt = this.setIcons();
    return this.artifacts().map((piece) => ({
      id: piece.id,
      setName: piece.set_name ?? 'No set',
      setIcon: setArt.get(piece.artifact_set_id ?? '') ?? null,
      slot: slots.get(piece.slot) ?? piece.slot,
      stars: stars.get(piece.rarity) ?? 0,
      level: piece.level,
      mainStat: describe(piece.main_stat_type, piece.main_stat_value, stats),
      substats: (piece.substats as { stat?: string; value?: unknown }[]).map((sub) =>
        describe(sub?.stat ?? 'unknown', sub?.value, stats),
      ),
      equipped: piece.build_id !== null,
      potential: describePotential(piece.potential),
    }));
  });

  private readonly service = inject(ArtifactsService);
  private readonly catalogue = inject(CatalogueService);

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [options, page] = await Promise.all([
        this.service.options(),
        this.service.list(this.filters()),
      ]);
      this.options.set(options);
      this.artifacts.set(page.items);
      this.total.set(page.total);
      this.truncated.set(page.truncated);
      // Deliberately not awaited and deliberately not in the `Promise.all` above: art is
      // decoration, and an inventory that will not render until the set catalogue arrives
      // is an inventory held hostage by a picture.
      void this.loadSetArt();
    } catch {
      // Surfaced, not swallowed: an empty inventory and a failed request look identical, and
      // only one of them means the account has nothing in it.
      this.error.set('Could not load your artifacts.');
      this.artifacts.set([]);
      this.total.set(0);
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Fill {@link setIcons}. Failure is silent — the pieces render without art.
   *
   * Once per session. `load()` re-runs on every slot filter and every page change, and the
   * 65 artifact sets do not change between them; without this guard, filtering to Circlets
   * refetched the whole set catalogue to rebuild an identical map.
   */
  private async loadSetArt(): Promise<void> {
    if (this.setIcons().size > 0) return;
    try {
      const page = await this.catalogue.listArtifactSets({ limit: 200 });
      this.setIcons.set(new Map(page.items.map((set) => [set.id, set.icon ?? null])));
    } catch {
      // No `error` signal: this failing means the cards have no pictures, which is not a
      // state worth telling somebody about while their inventory is on screen.
    }
  }

  protected canImport(): boolean {
    return this.mode !== '' && this.payloadText.trim().length > 0 && !this.importing();
  }

  protected async runImport(): Promise<void> {
    if (!this.canImport()) return;
    this.actionError.set(null);
    this.importResult.set(null);
    this.importing.set(true);
    try {
      const parsed: unknown = JSON.parse(this.payloadText);
      this.importResult.set(await this.service.importGood(this.mode as ImportMode, parsed));
      await this.load();
    } catch (err) {
      // A `SyntaxError` from `JSON.parse` is the user's file, not the server's fault — said
      // as such rather than as an API error, which would send them looking in the wrong place.
      this.actionError.set(
        err instanceof SyntaxError
          ? 'That file is not valid JSON. A GOOD export is a .json file.'
          : apiErrorMessage(err),
      );
    } finally {
      this.importing.set(false);
    }
  }

  protected async remove(row: ArtifactRow): Promise<void> {
    this.actionError.set(null);
    try {
      await this.service.remove(row.id);
      await this.load();
    } catch (err) {
      this.actionError.set(apiErrorMessage(err));
    }
  }

  protected async filterBySlot(slot: string): Promise<void> {
    this.slotFilter = slot;
    await this.load();
  }

  /** Server-side, so `total` is computed with the same `WHERE` the list used. */
  private filters(): { slot?: ArtifactSlotKey } {
    return this.slotFilter ? { slot: this.slotFilter as ArtifactSlotKey } : {};
  }
}

function describe(
  key: string,
  value: unknown,
  stats: Map<string, { display: string; percentage: boolean }>,
): string {
  const stat = stats.get(key);
  // Falls back to the raw key rather than hiding the stat: a piece carrying something the
  // vocabulary does not know is worth seeing, not worth silently dropping from the row.
  if (!stat) return `${key} ${value}`;
  return `${stat.display} ${formatStat(value, stat.percentage)}`;
}


/**
 * Upgrade potential as a headline and the working behind it.
 *
 * Both, because **a score is a claim**: "3 rolls left" alone is something a reader takes on
 * trust, and "of a possible 5 · +9 of +20" is something they can check. This repo's rule that
 * a number must explain itself applies to a two-digit figure as much as to a damage total.
 */
export function describePotential(
  potential: ArtifactRead['potential'],
): { headline: string; detail: string } | null {
  if (!potential) return null;
  const rolls = potential.rolls_remaining;
  return {
    headline: rolls === 0 ? 'Fully upgraded' : `${rolls} roll${rolls === 1 ? '' : 's'} left`,
    detail: `of ${potential.rolls_total} · +${potential.level} of +${potential.max_level}`,
  };
}
