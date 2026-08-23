import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * The Mitya emblem — his ornament, as geometry.
 *
 * The reference (`references/mitya_ornament.png`) is an orbital device: three ellipses
 * crossing at a shared centre, a large amber cabochon where they meet, two azure gems on
 * opposing nodes and pale beads on the rest, all in brass linework.
 *
 * **Drawn, not traced.** A traced outline of a game asset would carry that asset's licence
 * and its rendering artefacts into the app, and would not scale to a favicon. Three ellipses
 * at 60° increments reproduce the structure exactly, because the structure *is* three
 * ellipses — which is also why it survives being shrunk to 16px, where a trace would silt up.
 *
 * The owner's ruling was that Mitya himself stays out of the design and his ornament becomes
 * the mark, the way fairy's "eye" is fairy's. This is that mark.
 */
@Component({
  selector: 'app-emblem',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      [attr.width]="size()"
      [attr.height]="size()"
      viewBox="0 0 64 64"
      role="img"
      [attr.aria-label]="label()"
      class="emblem"
    >
      <g fill="none" stroke="var(--brass)" stroke-width="2.1" stroke-linecap="round">
        <!-- Three orbits at 60° increments. Flat and wide, as the reference's are, so the
             crossings sit out near the nodes instead of piling up behind the centre gem. -->
        <ellipse cx="32" cy="32" rx="25" ry="10" />
        <ellipse cx="32" cy="32" rx="25" ry="10" transform="rotate(60 32 32)" />
        <ellipse cx="32" cy="32" rx="25" ry="10" transform="rotate(120 32 32)" />
      </g>

      <!-- Nodes sit on the **orbit tips** — the six major-axis endpoints at radius 25 — not
           at eyeballed positions. The first draft floated them, and rendering it showed beads
           scattered near an atom rather than one device. Geometry derived from the orbits
           cannot drift from them. -->
      <circle class="emblem__bead" cx="57" cy="32" r="3.2" />
      <circle class="emblem__bead" cx="19.5" cy="53.7" r="3.2" />
      <circle class="emblem__bead" cx="7" cy="32" r="3.2" />
      <circle class="emblem__bead" cx="44.5" cy="10.3" r="3.2" />
      <!-- Two azure gems on opposing tips. Diagonal rather than horizontal: the reference's
           are offset, and a symmetric pair reads as a diagram instead of an ornament. -->
      <circle class="emblem__gem" cx="44.5" cy="53.7" r="3.8" />
      <circle class="emblem__gem" cx="19.5" cy="10.3" r="3.8" />

      <!-- The centre cabochon, the one warm focal point. -->
      <circle class="emblem__core" cx="32" cy="32" r="7.5" />
      <circle class="emblem__core-light" cx="29.6" cy="29.6" r="2.4" />
    </svg>
  `,
  styleUrl: './emblem.scss',
})
export class Emblem {
  /** Rendered size in px. Square by construction — the mark has no landscape form. */
  readonly size = input(40);
  /** Overridden where the emblem sits beside a wordmark that already says the name. */
  readonly label = input('Mistilteinn');
}
