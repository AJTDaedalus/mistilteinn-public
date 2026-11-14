import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { FORMULA_LABEL, FORMULA_SCORE_LABEL } from '../../sim/formula-calibration';

/** `Kit buffs from Bennett: verified …` → `Bennett`: the givers an estimate applied. */
const KIT_GIVER = /^Kit buffs from (.+?): /;

/**
 * The members whose kit sheet an estimate applied, read from its own assumptions
 * (`formula-recipe.ts:kitAssumptions` writes one `Kit buffs from <name>: …` line per giver).
 */
export function kitGivers(assumptions: readonly string[]): string[] {
  return assumptions.flatMap((line) => {
    const found = KIT_GIVER.exec(line);
    return found ? [found[1]] : [];
  });
}

/**
 * "Formula estimate — no simulation", said the same way on every surface that shows one.
 *
 * `DESIGN_team_math_fallback.md` §2.5: a formula result is labelled as an estimate, **in a style
 * distinct from gcsim results** — a dashed amber frame where a gcsim result has none — and its
 * number is never called DPS. One component so Optimize, Rank, Upgrade and a reopened saved run
 * cannot drift into four phrasings.
 *
 * **It says what the estimate applied.** Given the estimate's assumptions it names the members
 * whose kit buffs are in the number; the sentence that stood here said "no kit buffs are
 * modelled" over results that carried Bennett's and Kazuha's — found driving it.
 */
@Component({
  selector: 'formula-label',
  template: `
    <p class="formula-label" role="note">
      <span class="formula-label__tag">{{ label }}</span>
      @if (detail()) {
        <span class="formula-label__detail">{{ scoreLabel }}: closed-form damage, no timeline,
          not comparable across teams. {{ kitsSentence() }}</span>
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
  /** The estimate's own assumptions, from which the kits it applied are named. */
  readonly assumptions = input<readonly string[]>([]);

  protected readonly label = FORMULA_LABEL;
  protected readonly scoreLabel = FORMULA_SCORE_LABEL;

  protected readonly kitsSentence = computed(() => {
    const givers = kitGivers(this.assumptions());
    if (!givers.length) return 'No kit buffs or weapon passives are modelled.';
    return `Kit buffs applied from ${givers.join(', ')} (listed in the assumptions); `
      + 'weapon passives are not modelled.';
  });
}
