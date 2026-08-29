import { ChangeDetectionStrategy, Component, booleanAttribute, computed, input } from '@angular/core';

import { CatalogueIcon } from '../icon/icon';

/** The seven visions, lowercased. Anything else — including `"None"` — is unknown. */
const KNOWN = new Set([
  'anemo',
  'cryo',
  'dendro',
  'electro',
  'geo',
  'hydro',
  'pyro',
]);

/**
 * A character's vision, as a coloured chip.
 *
 * **Colour is added to the word, never substituted for it.** A chip that were colour alone
 * would be unreadable to a colourblind reader and unsearchable to anyone using find-in-page,
 * and the palette already carries `--accent-border-width` for exactly this reason (issue
 * #57). The hue is a second channel on a label that still says "Electro".
 *
 * Unknown input renders in `--element-none` rather than being dropped. Two catalogue rows
 * carry the literal `"None"` — the Traveler before a vision is chosen — and a build's
 * character can legitimately have no element; showing "No vision" in a muted chip keeps the
 * row the same shape as its neighbours.
 */
@Component({
  selector: 'element-chip',
  imports: [CatalogueIcon],
  template: `
    <span class="chip" [style.--element]="colour()" [attr.title]="compact() ? label() : null">
      @if (icon()) {
        <catalogue-icon [icon]="icon()" [alt]="''" [size]="size()" />
      }
      @if (compact() && icon()) {
        <span class="sr-only">{{ label() }}</span>
      } @else {
        <span>{{ label() }}</span>
      }
    </span>
  `,
  styles: `
    :host { display: inline-flex; }

    .chip {
      display: inline-flex;
      align-items: center;
      gap: var(--space-1);
      padding: 0 var(--space-2);
      border-radius: var(--radius-pill);
      border: 1px solid color-mix(in srgb, var(--element) 55%, transparent);
      background: color-mix(in srgb, var(--element) 14%, transparent);
      color: var(--element);
      font-size: var(--text-xs);
      font-weight: 600;
      letter-spacing: 0.04em;
      line-height: 1.7;
      white-space: nowrap;
    }

    /* The emblems arrive already in their element's colour, so they need no tinting — and
       must not be given any: a Pyro flame recoloured to sit with the chip's border would
       stop being the mark players recognise. */
    catalogue-icon { margin-left: -0.1em; }

    /* compact with no emblem falls back to the word, so this never hides the only label. */
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
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ElementChip {
  /** The element name as the catalogue spells it — `Electro`, or null. */
  readonly element = input<string | null | undefined>(null);
  /** What to show when there is no vision. Overridable: "No vision" reads oddly on a hit. */
  readonly fallback = input('No vision');
  /**
   * The emblem's basename, from the API's `element_icon`. Null keeps the chip as a word.
   *
   * An input rather than derived from `element()`: building `f"{element}.webp"` here would
   * be a second copy of the mapping, and would request art nobody vendored the moment a
   * patch adds a vision. `app/services/element_symbols.py` is the one place that decides.
   */
  readonly icon = input<string | null | undefined>(null);
  /**
   * Emblem only, with the word kept for assistive tech and as a tooltip.
   *
   * **Falls back to the word when there is no emblem**, so this can never leave a chip with
   * no visible label at all — which is the failure the whole "colour is a second channel"
   * argument above exists to prevent, arrived at from the other direction.
   */
  readonly compact = input(false, { transform: booleanAttribute });
  readonly size = input(16);

  private readonly key = computed(() => (this.element() ?? '').trim().toLowerCase());

  protected readonly known = computed(() => KNOWN.has(this.key()));

  protected readonly label = computed(() =>
    this.known() ? (this.element() as string) : this.fallback(),
  );

  protected readonly colour = computed(() =>
    this.known() ? `var(--element-${this.key()})` : 'var(--element-none)',
  );
}
