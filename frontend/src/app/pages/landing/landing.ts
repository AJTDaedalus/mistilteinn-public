import { Component } from '@angular/core';

/**
 * The signed-in front page.
 *
 * **It fetched four catalogue totals to print one sentence**, and that sentence is gone with
 * the card that held it — so the page now makes no request at all. `CatalogueService`,
 * `OnInit` and the `counts` signal went with it.
 */
@Component({
  selector: 'page-landing',
  templateUrl: './landing.html',
  styleUrl: './landing.scss',
})
export class LandingPage {}
