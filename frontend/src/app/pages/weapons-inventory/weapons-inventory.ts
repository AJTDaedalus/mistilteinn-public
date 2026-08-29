import { Component, OnInit, computed, signal } from '@angular/core';

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
@Component({
  selector: 'page-weapons-inventory',
  imports: [CatalogueIcon, WeaponMark],
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
  protected readonly shown = signal(120);

  protected readonly matching = computed(() => {
    const q = this.search().trim().toLowerCase();
    if (!q) return this.items();
    return this.items().filter((w) =>
      `${w.weapon?.name ?? ''} ${w.holder_name ?? ''}`.toLowerCase().includes(q),
    );
  });

  protected readonly visible = computed(() => this.matching().slice(0, this.shown()));
  protected readonly hasMore = computed(() => this.matching().length > this.shown());

  protected showMore(): void {
    this.shown.update((n) => n + 120);
  }

  ngOnInit(): void {
    void this.load();
  }

  protected async pick(value: '' | 'yes' | 'no'): Promise<void> {
    this.filter.set(value);
    this.shown.set(120);
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
