import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CatalogueService, type CharacterSummary } from './catalogue.service';

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
  styleUrl: './characters.scss',
})
export class CharactersPage implements OnInit {
  protected readonly characters = signal<CharacterSummary[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected search = '';

  private readonly catalogue = inject(CatalogueService);

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const page = await this.catalogue.listCharacters({
        name: this.search.trim() || undefined,
        limit: 200,
      });
      this.characters.set(page.items);
      this.total.set(page.total);
    } catch {
      // Surfaced, never swallowed: an empty list and a failed request look identical on
      // screen, and only one of them means "no matches".
      this.error.set('Could not load the character catalogue.');
      this.characters.set([]);
      this.total.set(0);
    } finally {
      this.loading.set(false);
    }
  }
}
