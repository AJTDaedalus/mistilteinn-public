import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { catalogueList } from './catalogue-list';
import { CatalogueService, type WeaponSummary } from './catalogue.service';
import { MAX_PAGE_LIMIT } from '../../api/page-size';

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
  imports: [FormsModule],
  templateUrl: './weapons.html',
  styleUrl: './catalogue.scss',
})
export class WeaponsPage implements OnInit {
  protected search = '';
  protected readonly list = catalogueList<WeaponSummary>((name) =>
    this.catalogue.listWeapons({ name, limit: MAX_PAGE_LIMIT }),
  );

  private readonly catalogue = inject(CatalogueService);

  ngOnInit(): void {
    void this.load();
  }

  protected load(): Promise<void> {
    return this.list.run(this.search, 'weapon catalogue');
  }
}
