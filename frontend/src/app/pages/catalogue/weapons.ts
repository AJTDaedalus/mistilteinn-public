import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CatalogueIcon } from '../../shared/icon/icon';

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
@Component({
  selector: 'page-weapons',
  imports: [FormsModule, CatalogueIcon],
  templateUrl: './weapons.html',
  styleUrl: './catalogue.scss',
})
export class WeaponsPage implements OnInit {
  protected search = '';
  // 260 weapons against a cap of 200, so this is one of the two pages that was showing a
  // short list beside the full total.
  protected readonly list = catalogueList<WeaponSummary>((name) =>
    allPages((offset, limit) => this.catalogue.listWeapons({ name, offset, limit })),
  );

  private readonly catalogue = inject(CatalogueService);

  ngOnInit(): void {
    void this.load();
  }

  protected load(): Promise<void> {
    return this.list.run(this.search, 'weapon catalogue');
  }
}
