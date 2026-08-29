import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ElementChip } from '../../shared/element/element';
import { CatalogueIcon } from '../../shared/icon/icon';

import { catalogueList } from './catalogue-list';
import { CatalogueService, type CharacterSummary } from './catalogue.service';
import { allPages } from '../../api/all-pages';

/** The seven visions, in the order the game lists them. */
const ELEMENTS = [
  'Anemo', 'Cryo', 'Dendro', 'Electro', 'Geo', 'Hydro', 'Pyro',
] as const;

/**
 * The seeded character catalogue — 150 entries including all 28 Traveler variants.
 *
 * Filtering is server-side (G.6a): the endpoint's `total` is computed with the same `WHERE`
 * the page used, so the count under the list is the count of *matches*, not of the table.
 * Filtering client-side would have meant paging over an unfiltered list and reporting a
 * total that disagreed with what is on screen.
 */
@Component({
  selector: 'page-characters',
  imports: [FormsModule, CatalogueIcon, ElementChip],
  templateUrl: './characters.html',
  styleUrl: './catalogue.scss',
})
export class CharactersPage implements OnInit {
  protected search = '';

  /**
   * Filters the **server** applies. `/characters` already took `element` and `rarity`
   * (G.6a); the page never offered them, so 150 characters could only be narrowed by typing
   * a name you already knew.
   *
   * Signals, and the loader reads them — so a chip re-runs the query rather than filtering a
   * list the client happens to hold, which would disagree with the `total` beside it.
   */
  protected readonly element = signal<CharacterSummary['element'] | null>(null);
  protected readonly rarity = signal<CharacterSummary['rarity'] | null>(null);
  protected readonly elements = ELEMENTS;

  /** Set a filter and reload. Clicking the active one clears it — a chip is a toggle. */
  protected pickElement(value: CharacterSummary['element']): void {
    this.element.set(this.element() === value ? null : value);
    void this.load();
  }

  protected pickRarity(value: CharacterSummary['rarity']): void {
    this.rarity.set(this.rarity() === value ? null : value);
    void this.load();
  }

  /**
   * The half-body gacha portrait for an avatar icon, or null.
   *
   * `UI_AvatarIcon_Ayaka` -> `UI_Gacha_AvatarIcon_Ayaka`, the substitution nanoka's own paths
   * use and the one `scripts/download_icons.py` vendors by. Null rather than a guess for a
   * basename in some other shape, so `catalogue-icon` renders nothing and the small icon
   * underneath shows through.
   */
  protected portrait(icon: string | null | undefined): string | null {
    return icon?.startsWith('UI_AvatarIcon_')
      ? icon.replace('UI_AvatarIcon_', 'UI_Gacha_AvatarIcon_')
      : null;
  }

  protected readonly list = catalogueList<CharacterSummary>((name) =>
    allPages((offset, limit) => this.catalogue.listCharacters({
      name,
      element: this.element() ?? undefined,
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
    return this.list.run(this.search, 'character catalogue');
  }
}
