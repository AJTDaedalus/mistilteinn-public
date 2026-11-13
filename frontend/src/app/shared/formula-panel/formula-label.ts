import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { FORMULA_LABEL, FORMULA_SCORE_LABEL } from '../../sim/formula-calibration';

/**
 * "Formula estimate — no simulation", said the same way on every surface that shows one.
 *
 * `DESIGN_team_math_fallback.md` §2.5: a formula result is labelled as an estimate, **in a style
 * distinct from gcsim results** — a dashed amber frame where a gcsim result has none — and its
 * number is never called DPS. One component so Optimize, Rank, Upgrade and a reopened saved run
 * cannot drift into four phrasings.
 */
@Component({
  selector: 'formula-label',
  template: `
    <p class="formula-label" role="note">
      <span class="formula-label__tag">{{ label }}</span>
      @if (detail()) {
        <span class="formula-label__detail">{{ scoreLabel }}: closed-form damage, no timeline,
          not comparable across teams. No kit buffs or weapon passives are modelled.</span>
      }
    </p>
  `,
  styles: `
    :host { display: block; }
    .formula-label {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: var(--space-1) var(--space-3);
      margin: 0;
      padding: var(--space-2) var(--space-3);
      border: 1px dashed var(--amber);
      border-radius: var(--radius-1);
      font-size: var(--text-sm);
    }
    .formula-label__tag {
      font-family: var(--font-display);
      letter-spacing: 0.06em;
      color: var(--amber);
    }
    .formula-label__detail { color: var(--ink-dim); font-size: var(--text-xs); }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FormulaLabel {
  /** Whether to add the sentence saying what the number is. Off for a compact tag. */
  readonly detail = input(true);

  protected readonly label = FORMULA_LABEL;
  protected readonly scoreLabel = FORMULA_SCORE_LABEL;
}
