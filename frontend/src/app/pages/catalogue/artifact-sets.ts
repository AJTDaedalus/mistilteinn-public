import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { catalogueList } from './catalogue-list';
import { CatalogueService, type ArtifactSetRead } from './catalogue.service';
import { allPages } from '../../api/all-pages';

/**
 * The seeded artifact sets — 65 entries, each with its affix rows.
 *
 * `piece_thresholds` is shown rather than assumed to be `[2, 4]`: the one-piece "Prayers"
 * circlets exist and a page that hard-coded 2pc/4pc would be quietly wrong about five sets.
 * The affix descriptions are the catalogue's own text, printed verbatim — the same rule the
 * D.4 explanation follows, and for the same reason.
 */
@Component({
  selector: 'page-artifact-sets',
  imports: [FormsModule],
  templateUrl: './artifact-sets.html',
  styleUrl: './catalogue.scss',
})
export class ArtifactSetsPage implements OnInit {
  protected search = '';
  protected readonly list = catalogueList<ArtifactSetRead>((name) =>
    allPages((offset, limit) => this.catalogue.listArtifactSets({ name, offset, limit })),
  );

  private readonly catalogue = inject(CatalogueService);

  ngOnInit(): void {
    void this.load();
  }

  protected load(): Promise<void> {
    return this.list.run(this.search, 'artifact set catalogue');
  }
}
