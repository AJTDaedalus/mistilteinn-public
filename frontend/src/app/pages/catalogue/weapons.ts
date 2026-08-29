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
/** The six weapon classes, with the label a person reads. The key is the source's own
 *  spelling, passed to the endpoint verbatim. */
const WEAPON_TYPES = [
  ['WEAPON_SWORD_ONE_HAND', 'Sword'],
  ['WEAPON_CLAYMORE', 'Claymore'],
  ['WEAPON_POLE', 'Polearm'],
  ['WEAPON_BOW', 'Bow'],
  ['WEAPON_CATALYST', 'Catalyst'],
] as const;

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
  protected readonly types = WEAPON_TYPES;

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
  }

  protected load(): Promise<void> {
    return this.list.run(this.search, 'weapon catalogue');
  }
}
