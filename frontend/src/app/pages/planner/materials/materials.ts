import { Component, type OnInit, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CatalogueIcon } from '../../../shared/icon/icon';
import {
  PlannerService,
  type MaterialStockRead,
  type MaterialStockUpdate,
} from '../planner.service';

/**
 * A typed entry as a count, or `null` when it is not one.
 *
 * An unparseable or negative entry reverts to untouched rather than being sent. The server
 * refuses both by name; this stops a typo becoming a request in the first place.
 */
function parse(raw: unknown): number | null {
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : null;
}

/** One row, and the number the user has typed into it if they have typed one. */
interface StockRow {
  readonly item: MaterialStockRead;
  /** `null` while untouched. An empty input is not a zero — see `dirty`. */
  readonly edited: number | null;
}

/**
 * The materials you own, editable.
 *
 * `docs/DESIGN_planner_materials.md` §5. The planner subtracts your stock from every bill it
 * prints, and until this existed the only writer of that stock was a GOOD export — so a
 * scanner that miscounted was a bill you could not correct.
 *
 * ## An import replaces everything here, and the page says so
 *
 * Owner ruling, 2026-09-19. `/roster` answers the same question the other way: a character you
 * un-own stays un-owned across a rescan, because `source: manual` says so. Materials diverge
 * because *"do I own Ayaka"* is durable and *"how many Teachings do I hold"* is a reading that
 * goes stale within a day — and a sticky override goes stale **invisibly**, printing a number
 * the user's own export disagrees with for as long as they never look. The failure mode we
 * chose is the one they can see, and the standing line below is what makes it visible.
 *
 * ## Sorted owned-first, not by rarity
 *
 * Rarity 0 is *unranked*, not worst: it is where the local specialties live — Sakura Bloom,
 * Philanemo Mushroom, Valberry. A rarity sort buries sixty real ascension materials under the
 * gem tiers. The server sorts; this page does not re-sort, so the order is decided once.
 */
@Component({
  selector: 'planner-materials',
  standalone: true,
  imports: [FormsModule, CatalogueIcon],
  templateUrl: './materials.html',
  styleUrl: './materials.scss',
})
export class PlannerMaterials implements OnInit {
  private readonly planner = inject(PlannerService);

  /**
   * The materials the plan on the other tab needs, or empty when there is no plan.
   *
   * The plan response already names every one of them, so the filter this feeds costs a
   * `Set` and nothing else — OQ-M3, answered 2026-09-20. It is the fastest route from *this
   * bill looks wrong* to the rows that are wrong, and unlike the search it does not need the
   * user to remember what a material is called.
   */
  readonly planMaterialIds = input<readonly number[]>([]);

  protected readonly rows = signal<StockRow[]>([]);
  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly saved = signal(false);

  /**
   * The mora balance, and the number typed into its box if one has been.
   *
   * **Its own state, beside the list rather than in it.** Mora is the one planner quantity no
   * GOOD export carries — so it is the one an import does not replace, it has no icon and no
   * rarity, and a row in the list would be counted by `ownedCount` and by every "your import
   * missed this". `docs/DESIGN_planner_materials.md` §8 OQ-M1.
   */
  protected readonly mora = signal<number | null>(null);
  protected readonly moraEdited = signal<number | null | undefined>(undefined);

  protected readonly search = signal('');
  /**
   * Default **off**. The case this page was asked for is *the import missed something*, so the
   * material being hunted for is the one with no row — hiding it would hide the whole point.
   */
  protected readonly ownedOnly = signal(false);

  /** Narrow to the materials the current plan needs. Off until a plan exists to narrow to. */
  protected readonly planOnly = signal(false);

  /** Whether there is a plan to filter by at all. The chip is hidden when there is not. */
  protected readonly hasPlan = computed(() => this.planMaterialIds().length > 0);

  /** What the mora box shows: the typed value, or the stored one. */
  protected readonly moraValue = computed(() => {
    const edited = this.moraEdited();
    return edited === undefined ? this.mora() : edited;
  });

  /** True once the box holds something other than what the server last told us. */
  protected readonly moraDirty = computed(
    () => this.moraEdited() !== undefined && this.moraEdited() !== this.mora(),
  );

  /** Rows whose typed value differs from what the server last told us. */
  protected readonly dirty = computed(() =>
    this.rows().filter((row) => row.edited !== null && row.edited !== row.item.count),
  );

  /**
   * Every row the search and the toggle allow — **all of them, however many that is.**
   *
   * Owner, 2026-09-20: *"scroll the 514"*. An earlier version capped this at 80 and said how
   * many it was holding back, because rendering every row made the page **25,349 pixels
   * tall** against a real inventory. The height was the real complaint and the cap was the
   * wrong fix: the table scrolls in its own box now, so the page stays a page and the whole
   * list is reachable by dragging rather than by guessing a search term.
   *
   * 514 rows is affordable in the DOM, and `catalogue-icon` already carries `loading="lazy"`,
   * so the art arrives as you scroll rather than as 514 requests at once.
   */
  protected readonly visible = computed(() => {
    const term = this.search().trim().toLowerCase();
    const ownedOnly = this.ownedOnly();
    // **Empty when the filter is off**, rather than "every id" — a `Set` built per keystroke
    // over 514 rows is waste, and `planOnly` already gates it.
    const inPlan =
      this.planOnly() && this.hasPlan() ? new Set(this.planMaterialIds()) : null;
    return this.rows().filter((row) => {
      if (inPlan && !inPlan.has(row.item.material_id)) return false;
      if (ownedOnly && !this.value(row)) return false;
      if (!term) return true;
      return row.item.name.toLowerCase().includes(term);
    });
  });

  protected readonly ownedCount = computed(
    () => this.rows().filter((row) => this.value(row) > 0).length,
  );

  async ngOnInit(): Promise<void> {
    await this.load();
  }

  /** What a row currently shows: the typed number, or the stored one. */
  protected value(row: StockRow): number {
    return row.edited ?? row.item.count;
  }

  protected isDirty(row: StockRow): boolean {
    return row.edited !== null && row.edited !== row.item.count;
  }

  protected setCount(materialId: number, raw: unknown): void {
    // **An empty box is not a zero.** `Number('')` is 0, so a user who selects the field and
    // deletes it to start typing would, for that instant, be telling the page they hold none
    // — and if they then clicked away, saving it. Emptiness means untouched.
    const next = raw === '' || raw === null || raw === undefined ? null : parse(raw);
    this.rows.update((rows) =>
      rows.map((row) =>
        row.item.material_id === materialId ? { ...row, edited: next } : row,
      ),
    );
    this.saved.set(false);
  }

  /**
   * An emptied mora box means **unsay it**, not zero.
   *
   * This is the one place emptiness is not "untouched": a material you hold none of is
   * absent from the export anyway, but a mora balance you have never given is a state the
   * planner reports differently from zero — it refuses to compute a shortfall at all.
   */
  protected setMora(raw: unknown): void {
    if (raw === '' || raw === null || raw === undefined) {
      this.moraEdited.set(null);
    } else {
      const parsed = Number(raw);
      if (Number.isFinite(parsed) && parsed >= 0) this.moraEdited.set(Math.floor(parsed));
    }
    this.saved.set(false);
  }

  /** Anything at all to write — a count, a balance, or both. */
  protected readonly hasChanges = computed(() => this.dirty().length > 0 || this.moraDirty());

  /** How many unsaved changes the button offers to write. Mora counts as one of them. */
  protected readonly changeCount = computed(
    () => this.dirty().length + (this.moraDirty() ? 1 : 0),
  );

  protected async save(): Promise<void> {
    if (!this.hasChanges() || this.saving()) return;

    this.saving.set(true);
    this.error.set(null);
    try {
      // Mora first and separately: `saveMaterials` never sends the key, because omitting it
      // and sending `null` mean different things to the route — leave it alone, and unsay it.
      if (this.moraDirty()) await this.saveMoraOnly();
      if (this.dirty().length) await this.saveCounts();
      // **Only when nothing reported a failure.** Both writers catch and set `error`, so a
      // blanket "Saved." here would sit next to the sentence saying it was not.
      if (!this.error()) this.saved.set(true);
    } finally {
      this.saving.set(false);
    }
  }

  private async saveCounts(): Promise<void> {
    const updates: MaterialStockUpdate[] = this.dirty().map((row) => ({
      material_id: row.item.material_id,
      count: row.edited as number,
    }));
    try {
      const written = (await this.planner.saveMaterials(updates)).items;
      // **Reconciled from the response, not from what we sent.** The server is what the
      // planner will read; echoing our own numbers back into the table would show a save
      // that had not happened if it ever wrote something different.
      const byId = new Map(written.map((item) => [item.material_id, item]));
      this.rows.update((rows) =>
        rows.map((row) => {
          const fresh = byId.get(row.item.material_id);
          return fresh ? { item: fresh, edited: null } : row;
        }),
      );
    } catch {
      this.error.set('Those counts could not be saved.');
    }
  }

  private async saveMoraOnly(): Promise<void> {
    try {
      const written = await this.planner.saveMora(this.moraEdited() ?? null);
      this.mora.set(written.mora ?? null);
      this.moraEdited.set(undefined);
    } catch {
      this.error.set('That mora balance could not be saved.');
    }
  }

  protected revert(): void {
    this.rows.update((rows) => rows.map((row) => ({ ...row, edited: null })));
    this.moraEdited.set(undefined);
    this.saved.set(false);
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    try {
      const body = await this.planner.materials();
      this.rows.set(body.items.map((item) => ({ item, edited: null })));
      this.mora.set(body.mora ?? null);
      this.error.set(null);
    } catch {
      this.error.set('Your materials could not be loaded.');
    } finally {
      this.loading.set(false);
    }
  }
}
