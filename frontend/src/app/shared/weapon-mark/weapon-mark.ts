import { ChangeDetectionStrategy, Component, booleanAttribute, input } from '@angular/core';

import { CatalogueIcon } from '../icon/icon';

/**
 * A weapon class as Genshin's own mark — the sword, bow, polearm, claymore or catalyst glyph.
 *
 * **The name is kept, not replaced.** The glyph is the fast channel and the word is the one
 * that survives a screen reader, a find-in-page, and a reader who has not memorised five
 * monochrome silhouettes. Same argument `ElementChip` makes about colour, and the same reason
 * `ng lint` caught a control with no accessible name on #131: a symbol alone is a label only
 * for the person who already knows it.
 *
 * `compact` shows the glyph with the word as a tooltip and as screen-reader-only text — for a
 * card where the class is a second-order fact and the space is the picture's. The default
 * shows both, which is what a list row wants.
 *
 * A class with no mark renders the word alone rather than a gap. The crossbow class has none
 * at nanoka 7.0.51: it is two unreleased Traveler variants with no talents seeded, so there is
 * nothing to derive — see `app/services/weapon_symbols.py`.
 */
@Component({
  selector: 'weapon-mark',
  imports: [CatalogueIcon],
  template: `
    <span class="mark" [attr.title]="compact() ? label() : null">
      @if (icon()) {
        <catalogue-icon [icon]="icon()" [alt]="''" [size]="size()" />
      }
      @if (compact()) {
        <span class="sr-only">{{ label() }}</span>
      } @else {
        <span class="label">{{ label() }}</span>
      }
    </span>
  `,
  styles: `
    :host { display: inline-flex; min-width: 0; }

    .mark {
      display: inline-flex;
      align-items: center;
      gap: var(--space-1);
      min-width: 0;
      color: var(--ink-dim);
      font-size: var(--text-xs);
      letter-spacing: 0.04em;
    }

    /* The marks are white-on-transparent line art, which reads as a highlight rather than a
       label at full strength. Dimmed to sit with the text it accompanies, and brightened with
       its card on hover. */
    catalogue-icon {
      opacity: 0.72;
      transition: opacity var(--t-fast) var(--ease);
    }

    :host(:hover) catalogue-icon,
    :host-context(.card:hover) catalogue-icon { opacity: 1; }

    /* Defined here rather than as a global utility: this is the first use, and a
       visually-hidden class is the kind of thing that gets three near-identical definitions
       once it lives in one stylesheet and is copied into another. Promote it when a second
       component needs it. */
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
      border: 0;
    }

    .label {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WeaponMark {
  /** The mark's basename, from the API's `weapon_type_icon`. Null renders the word alone. */
  readonly icon = input<string | null | undefined>(null);
  /** The readable class name, from the API's `weapon_type_display` — `Sword`, `Polearm`. */
  readonly label = input('');
  /** Glyph only, with the word for assistive tech and as a tooltip. */
  readonly compact = input(false, { transform: booleanAttribute });
  readonly size = input(16);
}
