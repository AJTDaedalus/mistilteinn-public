import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CatalogueIcon } from '../../shared/icon/icon';
import { WeaponMark } from '../../shared/weapon-mark/weapon-mark';

import { catalogueList } from './catalogue-list';
import { CatalogueService, type WeaponSummary } from './catalogue.service';
import { allPages } from '../../api/all-pages';

/**
 * The seeded weapon catalogue — 260 entries.
 *
 * `base_atk` is shown as the number the importer stored, which is a **curve base**, not the
 * weapon's level-90 ATK (`backend/CLAUDE.md`: "Weapon `base_atk` and substat carry their
 * `GROW_CURVE_*` name"). The template says so rather than printing a bare figure a reader
 * would take for a stat — a number labelled wrong is worse than a number omitted.
 */
/**
 * The weapon classes, as a fallback.
 *
 * `GET /weapon-classes` publishes these **with their marks**, and the mark's basename is an
 * allowlist server-side rather than a string built from the class name. This list is what the
 * chips show if that call fails: the filter still works, without art.
 *
 * The crossbow class is in neither, and the server decides that rather than this page —
 * `app/services/weapon_symbols.py` explains why a class with no mark gets no chip.
 */
const WEAPON_TYPES: readonly { value: string; display: string; icon: string | null }[] = [
  ['WEAPON_SWORD_ONE_HAND', 'Sword'],
  ['WEAPON_CLAYMORE', 'Claymore'],
  ['WEAPON_POLE', 'Polearm'],
  ['WEAPON_BOW', 'Bow'],
  ['WEAPON_CATALYST', 'Catalyst'],
].map(([value, display]) => ({ value, display, icon: null }));

@Component({
  selector: 'page-weapons',
  imports: [FormsModule, CatalogueIcon, WeaponMark],
  templateUrl: './weapons.html',
  styleUrl: './catalogue.scss',
})
export class WeaponsPage implements OnInit {
  protected search = '';

  /** Server-side filters the endpoint already took and this page never offered. */
  protected readonly weaponType = signal<WeaponSummary['weapon_type'] | null>(null);
  protected readonly rarity = signal<WeaponSummary['rarity'] | null>(null);
  protected readonly types = signal(WEAPON_TYPES);

  protected pickType(value: WeaponSummary['weapon_type']): void {
    this.weaponType.set(this.weaponType() === value ? null : value);
    void this.load();
  }

  protected pickRarity(value: WeaponSummary['rarity']): void {
    this.rarity.set(this.rarity() === value ? null : value);
    void this.load();
  }

  /** `[1..stars]`, so the card can draw one ★ per rarity point. */
  protected starList(stars: number): number[] {
    return Array.from({ length: Math.max(0, stars) }, (_, i) => i + 1);
  }
  // 260 weapons against a cap of 200, so this is one of the two pages that was showing a
  // short list beside the full total.
  protected readonly list = catalogueList<WeaponSummary>((name) =>
    allPages((offset, limit) => this.catalogue.listWeapons({
      name,
      weapon_type: this.weaponType() ?? undefined,
      rarity: this.rarity() ?? undefined,
      offset,
      limit,
    })),
  );

  private readonly catalogue = inject(CatalogueService);

  ngOnInit(): void {
    void this.load();
    // Never fatal: the chips read as words already, so a failure costs the art and nothing
    // else. Failing the page over a decoration would be the worse trade.
    void this.catalogue.listWeaponClasses()
      .then((classes) => this.types.set(classes))
      .catch(() => undefined);
  }

  protected load(): Promise<void> {
    return this.list.run(this.search, 'weapon catalogue');
  }
}
