import { Component, OnInit, computed, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';
import { CatalogueIcon } from '../../shared/icon/icon';
import { WeaponMark } from '../../shared/weapon-mark/weapon-mark';

export type OwnedWeapon = components['schemas']['OwnedWeaponRead'];

/**
 * The weapons you own, as opposed to the 260 the catalogue describes.
 *
 * **Nothing showed these until now.** A GOOD export lists every weapon on the account — 320 on
 * the owner's — and the importer read the 68 that named a holder purely to set
 * `builds.weapon_id`, discarding the rest. `ParsedWeapon`'s own docstring said so: *"Unheld
 * weapons are parsed and simply unused."*
 *
 * **Equipped first is the server's ordering, not a sort control here.** It is what the owner
 * asked for, and it answers "what am I actually using" without the user having to ask. The
 * filter narrows; it does not reorder.
 */
/** The render cap, and the sizes offered.
 *
 * **The same list `/artifacts` offers**, because this page had the defect that page's
 * page-size control was added to fix and did not get the fix: the only way past piece 120 was
 * a SHOW MORE button at the bottom of a 6,662px page. Two pages, one problem, one solved.
 */
const INITIAL_ROWS = 120;
const PAGE_SIZES = [120, 300, 600, Infinity] as const;

@Component({
  selector: 'page-weapons-inventory',
  imports: [CatalogueIcon, RouterLink, WeaponMark],
  templateUrl: './weapons-inventory.html',
  styleUrl: './weapons-inventory.scss',
})
export class WeaponsInventoryPage implements OnInit {
  private readonly api = injectApi();

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly items = signal<OwnedWeapon[]>([]);
  protected readonly total = signal(0);
  protected readonly filter = signal<'' | 'yes' | 'no'>('');
  protected readonly search = signal('');

  /**
   * Rendered rows, after the name filter and the render cap.
   *
   * Capped for the same reason `/artifacts` is: 320 is survivable and a 2,000-weapon account
   * is not, and a cap that only appears once someone hits the wall is a cap nobody tested.
   */
  protected readonly shown = signal(INITIAL_ROWS);

  protected readonly matching = computed(() => {
    const q = this.search().trim().toLowerCase();
    if (!q) return this.items();
    return this.items().filter((w) =>
      `${w.weapon?.name ?? ''} ${w.holder_name ?? ''}`.toLowerCase().includes(q),
    );
  });

  protected readonly visible = computed(() => this.matching().slice(0, this.shown()));
  protected readonly hasMore = computed(() => this.matching().length > this.shown());

  protected readonly pageSizes = PAGE_SIZES;

  /** Label for a size chip: the number, or "All" with the count it means. */
  protected sizeLabel(size: number): string {
    return Number.isFinite(size) ? String(size) : `All ${this.matching().length}`;
  }

  protected setPageSize(size: number): void {
    this.shown.set(Number.isFinite(size) ? size : this.matching().length);
  }

  /** Which chip reads as pressed. `Infinity` matches once everything is on screen. */
  protected isPageSize(size: number): boolean {
    return Number.isFinite(size)
      ? this.shown() === size
      : !this.hasMore() && this.matching().length > 0;
  }

  protected showMore(): void {
    this.shown.update((n) => n + INITIAL_ROWS);
  }

  ngOnInit(): void {
    void this.load();
  }

  protected async pick(value: '' | 'yes' | 'no'): Promise<void> {
    this.filter.set(value);
    this.shown.set(INITIAL_ROWS);
    await this.load();
  }

  /** Server-side, so `total` is counted with the same filter the list used. */
  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const equipped = this.filter() === '' ? undefined : this.filter() === 'yes';
      const { data, error } = await this.api.GET('/api/v1/weapons/owned', {
        params: { query: { equipped, limit: 200 } },
      });
      if (error) throw new Error('Could not load your weapons');
      this.items.set(data.items);
      this.total.set(data.total);
    } catch {
      this.error.set('Could not load your weapons.');
      this.items.set([]);
    } finally {
      this.loading.set(false);
    }
  }
}
