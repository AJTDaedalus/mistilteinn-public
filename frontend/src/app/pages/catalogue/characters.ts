import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { catalogueList } from './catalogue-list';
import { CatalogueService, type CharacterSummary } from './catalogue.service';
import { allPages } from '../../api/all-pages';

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
  imports: [FormsModule],
  templateUrl: './characters.html',
  styleUrl: './catalogue.scss',
})
export class CharactersPage implements OnInit {
  protected search = '';
  protected readonly list = catalogueList<CharacterSummary>((name) =>
    allPages((offset, limit) => this.catalogue.listCharacters({ name, offset, limit })),
  );

  private readonly catalogue = inject(CatalogueService);

  ngOnInit(): void {
    void this.load();
  }

  protected load(): Promise<void> {
    return this.list.run(this.search, 'character catalogue');
  }
}
