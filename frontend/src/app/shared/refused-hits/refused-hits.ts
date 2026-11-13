import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import type { components } from '../../api/api.types';

export type RefusedHit = components['schemas']['RefusedHitRead'];

/**
 * The damage rows a hit picker cannot offer, with why — beside the picker, never in its choices.
 *
 * Owner, 2026-11-13: rows the parser refuses must not **vanish**. Venti's Windsunder Arrow
 * missing from his list reads as a broken picker; listed here, greyed, with the parser's own
 * sentence, it reads as what it is — a hit the closed-form chain has no term for.
 *
 * The picker also carries each one as a **disabled** option, which a keyboard and a screen
 * reader skip; this list is where the reason is visible, because a disabled `<option>` shows
 * no tooltip in most browsers. Shared by Optimize and Explain so the two say it the same way.
 */
@Component({
  selector: 'refused-hits',
  template: `
    @if (refused().length) {
      <div class="refused" role="note" aria-label="Hits that cannot be scored">
        <span class="refused__head">Not scored</span>
        <ul>
          @for (row of refused(); track row.talent + row.label) {
            <li>
              <span class="refused__label">{{ row.label }}</span>
              <span class="refused__reason">— {{ row.reason }}</span>
            </li>
          }
        </ul>
      </div>
    }
  `,
  styles: `
    :host { display: block; }
    .refused {
      margin-top: var(--space-1);
      font-size: var(--text-xs);
      color: var(--ink-faint);
    }
    .refused__head {
      font-family: var(--font-display);
      letter-spacing: 0.06em;
      color: var(--ink-dim);
    }
    ul { margin: 0; padding: 0; list-style: none; }
    li { margin-top: var(--space-1); }
    .refused__reason { margin-left: 0.35em; }
    .refused__label {
      color: var(--ink-dim);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RefusedHits {
  readonly refused = input<readonly RefusedHit[]>([]);
}
