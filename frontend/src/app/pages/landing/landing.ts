import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { CatalogueService } from '../catalogue/catalogue.service';

@Component({
  selector: 'page-landing',
  imports: [RouterLink],
  templateUrl: './landing.html',
  styleUrl: './landing.scss',
})
export class LandingPage implements OnInit {
  /**
   * The catalogue's size, read rather than written down.
   *
   * It said "150 characters" until the practice mannequins were hidden and the real answer
   * became 136 — a number on the front page that had quietly become wrong, and that nothing
   * would ever have failed on. Every count here is one request with `limit=1`, so the page
   * pays for four totals and no rows.
   *
   * Null while loading and after a failure, and the sentence is written to read without the
   * numbers: a landing page must not turn a catalogue hiccup into an error message.
   */
  protected readonly counts = signal<Record<string, number> | null>(null);

  private readonly catalogue = inject(CatalogueService);

  async ngOnInit(): Promise<void> {
    try {
      const [characters, weapons, sets, enemies] = await Promise.all([
        this.catalogue.listCharacters({ limit: 1 }),
        this.catalogue.listWeapons({ limit: 1 }),
        this.catalogue.listArtifactSets({ limit: 1 }),
        this.catalogue.listEnemies({ limit: 1 }),
      ]);
      this.counts.set({
        characters: characters?.total ?? 0,
        weapons: weapons?.total ?? 0,
        sets: sets?.total ?? 0,
        enemies: enemies?.total ?? 0,
      });
    } catch {
      // Deliberately silent. The copy reads fine without the numbers, and a logged-out
      // visitor hitting an authed catalogue endpoint is not something to shout about here.
      this.counts.set(null);
    }
  }
}
