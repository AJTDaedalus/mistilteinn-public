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

/** One substat, with whatever could be established about the rolls behind it. */
export interface ArtifactSubstat {
  label: string;
  /**
   * Rolls behind this line, or **null** when the decompositions disagree on how many.
   *
   * 95% of a real inventory has a count. The rest draws no bars rather than a plausible
   * number of them.
   */
  rolls: number | null;
  /**
   * One entry per roll, `0` (worst tier) to `3` (best) — null unless exactly one
   * decomposition fits, so a bar is never coloured by a guess.
   *
   * When `rolls` is known but this is not, the card draws that many *undifferentiated*
   * bars: the count is established, the individual qualities are not.
   */
  tiers: number[] | null;
  /** The line as a multiple of one best-case roll. `3.2` reads as "3.2 max rolls". */
  rollValue: number | null;
  /** True when the count is the likeliest reading rather than the only one. */
  estimated: boolean;
}

/** One piece, with everything the row needs already resolved. */
export interface ArtifactRow {
  id: string;
  setName: string;
  setIcon: string | null;
  slot: string;
  stars: number;
  level: number;
  mainStat: string;
  substats: ArtifactSubstat[];
  equipped: boolean;
  /** Sort keys, kept beside the display strings so a comparator never re-parses one. */
  setId: string;
  mainStatKey: string;
  slotKey: string;
  /** The piece's total roll value, or null when its rolls could not be decomposed.
   *  Null sorts last rather than as zero — "unknown" is not "worst". */
  rollValue: number | null;
}

/** How many cards are rendered before "show more", and how many each press adds. */
const INITIAL_ROWS = 120;
const MORE_ROWS = 120;

export type SortKey = 'rollValue' | 'level' | 'set' | 'slot' | 'stars';

/**
 * A piece's total roll value, or null when any substat could not be decomposed.
 *
 * **Null rather than a partial sum.** 3.5% of the owner's real export cannot be decomposed,
 * and adding up the three substats that could be would rank a piece by less than it has —
 * quietly, and always downward. Sorting puts null last, because "unknown" is not "worst".
 */
export function totalRollValue(
  analysis: readonly { roll_value?: number | null }[] | null | undefined,
): number | null {
  if (!analysis?.length) return null;
  let total = 0;
  for (const sub of analysis) {
    if (typeof sub.roll_value !== 'number') return null;
    total += sub.roll_value;
  }
  return total;
}

/** Orderings, each descending in the direction a player cares about. */
export function comparator(key: SortKey): (a: ArtifactRow, b: ArtifactRow) => number {
  switch (key) {
    case 'level':
      return (a, b) => b.level - a.level || a.setName.localeCompare(b.setName);
    case 'set':
      return (a, b) => a.setName.localeCompare(b.setName) || a.slotKey.localeCompare(b.slotKey);
    case 'slot':
      return (a, b) => a.slotKey.localeCompare(b.slotKey) || b.level - a.level;
    case 'stars':
      return (a, b) => b.stars - a.stars || b.level - a.level;
    case 'rollValue':
    default:
      // Undecomposed pieces sink to the bottom whichever way the list is read, rather than
      // sorting as zero and looking like the worst artifacts the user owns.
      return (a, b) => {
        if (a.rollValue === null && b.rollValue === null) return b.level - a.level;
        if (a.rollValue === null) return 1;
        if (b.rollValue === null) return -1;
        return b.rollValue - a.rollValue;
      };
  }
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
 * **`mode` defaults to `replace`** (owner ruling, 2026-08-28). It was deliberately empty
 * before, on the reasoning that a default would be this page deciding whether to delete
 * someone's inventory. In practice a re-scan *is* the inventory — GOOD carries no stable
 * per-artifact id, so `append` on a second scan of the same account duplicates every piece,
 * which is the outcome the empty default was steering people into. `replace` is what the
 * common case wants, `append` stays one click away, and N.3 already re-equips what it can
 * and names what it could not.
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
  /** `replace` by default — see the class docstring. */
  protected mode: ImportMode | '' = 'replace';
  protected payloadText = '';
  /**
   * Also rebuild builds from the export's `characters`, `weapons` and each artifact's
   * `location`.
   *
   * **On by default, and safe to be.** It never overwrites a build that already exists, so
   * the worst case for a returning user is a report saying nothing changed — while for a
   * first import it removes the whole manual setup the inventory otherwise leads into.
   */
  protected rebuildBuilds = true;
  /** The name of a file chosen through the picker, shown so a paste and a file cannot be
   *  confused for one another. */
  protected readonly fileName = signal<string | null>(null);

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
      substats: (piece.substats as { stat?: string; value?: unknown }[]).map(
        (sub, index) => {
          const found = piece.substat_analysis?.[index];
          return {
            label: describe(sub?.stat ?? 'unknown', sub?.value, stats),
            rolls: found?.rolls ?? null,
            tiers: found?.roll_tiers ?? null,
            rollValue: found?.roll_value ?? null,
            estimated: found?.estimated ?? false,
          };
        },
      ),
      equipped: piece.build_id !== null,
      setId: piece.artifact_set_id ?? '',
      mainStatKey: piece.main_stat_type,
      slotKey: piece.slot,
      rollValue: totalRollValue(piece.substat_analysis),
    }));
  });

  // ── narrowing and ordering ────────────────────────────────────────────────
  //
  // All client-side, over an array the page already holds in full. The API's own `set_id`
  // filter exists, but re-fetching on every dropdown change would trade one cheap array pass
  // for a round trip, and the slot filter already goes to the server for `total`.

  protected readonly setFilter = signal('');
  protected readonly mainStatFilter = signal('');
  protected readonly equippedFilter = signal<'' | 'yes' | 'no'>('');
  protected readonly sortBy = signal<SortKey>('rollValue');

  /**
   * How many cards are actually put in the DOM.
   *
   * **This is the fix for the audit's largest finding.** The page rendered all 2,370 pieces at
   * once — roughly 30,000 nodes, and a full-page screenshot of 313 megapixels. It renders,
   * which is why it survived; it should not have to.
   *
   * A cap with an explicit "show more" rather than a virtual scroller: `@angular/cdk` is a
   * dependency this app does not otherwise carry, and the anonymous-volume dance in
   * `frontend/CLAUDE.md` makes adding one a heavier change than the problem needs. The count
   * line always says how many of how many, so a capped view can never be mistaken for the
   * whole inventory.
   */
  protected readonly shown = signal(INITIAL_ROWS);

  protected readonly setOptions = computed(() => {
    const names = new Map<string, string>();
    for (const row of this.rows()) {
      if (row.setId) names.set(row.setId, row.setName);
    }
    return [...names].map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  });

  protected readonly mainStatOptions = computed(() => {
    const stats = new Map(
      (this.options()?.stats ?? []).map((s) => [s.key, s.display ?? s.key]),
    );
    const keys = new Set(this.rows().map((r) => r.mainStatKey));
    return [...keys].map((key) => ({ key, display: stats.get(key) ?? key }))
      .sort((a, b) => a.display.localeCompare(b.display));
  });

  /** Every row that passes the filters, in sort order — before the render cap. */
  protected readonly matching = computed<ArtifactRow[]>(() => {
    const set = this.setFilter();
    const main = this.mainStatFilter();
    const equipped = this.equippedFilter();
    const kept = this.rows().filter((row) =>
      (!set || row.setId === set)
      && (!main || row.mainStatKey === main)
      && (!equipped || (equipped === 'yes') === row.equipped),
    );
    return [...kept].sort(comparator(this.sortBy()));
  });

  /** What the template draws. */
  protected readonly visible = computed(() => this.matching().slice(0, this.shown()));

  protected readonly hasMore = computed(() => this.matching().length > this.shown());

  protected showMore(): void {
    this.shown.update((n) => n + MORE_ROWS);
  }

  /** Any narrowing at all resets the cap: page 3 of the old filter is not page 1 of the new. */
  protected narrow(apply: () => void): void {
    apply();
    this.shown.set(INITIAL_ROWS);
  }

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

  /** `[1..stars]`, so the template can draw one ★ per rarity point. */
  protected starList(stars: number): number[] {
    return Array.from({ length: Math.max(0, stars) }, (_, i) => i + 1);
  }

  /**
   * The bars to draw for one substat: the tier of each roll, or `-1` per roll when only the
   * count is known.
   *
   * `-1` renders undifferentiated rather than as tier 0 — the worst tier and "we do not know
   * which tier" are different claims, and colouring the second as the first would tell the
   * reader a line is bad on no evidence.
   */
  protected rollBars(sub: ArtifactSubstat): number[] {
    if (sub.tiers) return sub.tiers;
    if (!sub.rolls) return [];
    return Array.from({ length: Math.min(sub.rolls, 6) }, () => -1);
  }

  /** What the bars are claiming, for the `title`. Unlabelled grey bars mean nothing. */
  protected barsTitle(sub: ArtifactSubstat): string | null {
    if (!sub.rolls) return null;
    const rolls = `${sub.rolls} roll${sub.rolls === 1 ? '' : 's'}`;
    // **Estimated first.** Checking `tiers` first returned the confident wording for a
    // guessed count, so the one case that most needs the caveat was the one that lost it.
    if (sub.estimated) return `${rolls} — the likeliest reading, not the only one`;
    if (sub.tiers) return `${rolls}, shaded by how high each rolled`;
    return `${rolls}; which of them rolled high cannot be told apart`;
  }

  /** `3.2` → `320`, for the roll-value column. */
  protected rollValuePercent(sub: ArtifactSubstat): number | null {
    return sub.rollValue === null ? null : Math.round(sub.rollValue * 100);
  }

  /**
   * The piece's roll value as **what it got out of what those rolls could have been**.
   *
   * A bare `789%` is a number with no scale — it means nothing without knowing the piece had
   * nine rolls to spend. Against the maximum those nine could have produced (`900%`) it says
   * the thing a reader actually wants: how well this artifact rolled.
   *
   * Null unless every substat contributed both a value and a count, because a total silently
   * short one line reads as a worse artifact rather than as an incomplete sum.
   */
  protected totalRollValue(row: ArtifactRow): { got: number; max: number | null } | null {
    if (!row.substats.length) return null;
    let sum = 0;
    let rolls = 0;
    let counted = true;
    for (const sub of row.substats) {
      // The numerator needs no roll count — `roll_value` is value over the best single roll.
      // Only the denominator does, so a line without a count costs the *scale*, not the
      // number. Returning null for the whole thing took the headline off 11% of pieces that
      // had shown one, which is the opposite of the point.
      if (sub.rollValue === null) return null;
      sum += sub.rollValue;
      if (sub.rolls === null) counted = false;
      else rolls += sub.rolls;
    }
    return { got: Math.round(sum * 100), max: counted ? rolls * 100 : null };
  }

  protected canImport(): boolean {
    return this.mode !== '' && this.payloadText.trim().length > 0 && !this.importing();
  }

  /**
   * Read a chosen `.json` into the same buffer a paste fills.
   *
   * One path through the importer, not two: the file becomes text and everything downstream
   * — the `JSON.parse` that distinguishes a bad file from a server error, the rejection
   * list, the re-equip report — is unchanged. A separate upload endpoint would be a second
   * implementation of a flow that already reports carefully.
   *
   * A 2,370-artifact export is a couple of megabytes, which `text()` handles without a
   * streaming reader.
   */
  protected async chooseFile(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    this.actionError.set(null);
    this.importResult.set(null);
    try {
      this.payloadText = await file.text();
      this.fileName.set(file.name);
    } catch {
      // A file the browser cannot read — removed mid-pick, or a permissions failure. Said
      // plainly rather than left as an empty box the Import button silently refuses.
      this.fileName.set(null);
      this.actionError.set(`Could not read ${file.name}.`);
    } finally {
      // Cleared so re-picking the *same* file fires `change` again. Without this, a user who
      // edits their export and re-selects it sees nothing happen.
      input.value = '';
    }
  }

  /** Drop a loaded file, so the box is visibly empty rather than holding a stale export. */
  protected clearPayload(): void {
    this.payloadText = '';
    this.fileName.set(null);
    this.importResult.set(null);
    this.actionError.set(null);
  }

  /**
   * True while a `replace` would delete pieces that already exist.
   *
   * The default is `replace` by owner ruling, which is right for a re-scan — but paste-then-
   * Import would then permanently delete an inventory in one click, and a scanner that died
   * half way through 2,370 pieces writes a *valid* GOOD file holding a fraction of them.
   * The default stays; the irreversible one-click path does not.
   */
  protected readonly confirmingReplace = signal(false);

  protected needsConfirmation(): boolean {
    return this.mode === 'replace' && this.total() > 0;
  }

  protected cancelReplace(): void {
    this.confirmingReplace.set(false);
  }

  protected async runImport(): Promise<void> {
    if (!this.canImport()) return;
    if (this.needsConfirmation() && !this.confirmingReplace()) {
      this.confirmingReplace.set(true);
      return;
    }
    this.confirmingReplace.set(false);
    this.actionError.set(null);
    this.importResult.set(null);
    this.importing.set(true);
    try {
      const parsed: unknown = JSON.parse(this.payloadText);
      this.importResult.set(
        await this.service.importGood(
          this.mode as ImportMode, parsed, this.rebuildBuilds,
        ),
      );
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


