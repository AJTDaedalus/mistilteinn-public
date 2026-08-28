import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

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
  imports: [],
  template: `
    <span class="chip" [style.--element]="colour()">{{ label() }}</span>
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
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ElementChip {
  /** The element name as the catalogue spells it — `Electro`, or null. */
  readonly element = input<string | null | undefined>(null);
  /** What to show when there is no vision. Overridable: "No vision" reads oddly on a hit. */
  readonly fallback = input('No vision');

  private readonly key = computed(() => (this.element() ?? '').trim().toLowerCase());

  protected readonly known = computed(() => KNOWN.has(this.key()));

  protected readonly label = computed(() =>
    this.known() ? (this.element() as string) : this.fallback(),
  );

  protected readonly colour = computed(() =>
    this.known() ? `var(--element-${this.key()})` : 'var(--element-none)',
  );
}
