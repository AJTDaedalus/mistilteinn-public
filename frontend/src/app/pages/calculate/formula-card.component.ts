import { Component, computed, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import type { EquationTerm } from './equation-terms';
import type { components } from '../../api/api.types';
import { fmtMultBp, fmtPctBp } from './format-helpers';
import { renderZoneFormula, type FormulaRow } from './zone-formula-render';

type ComboStepResult = components['schemas']['ComboStepResultSchema'];
type StepAttribution = components['schemas']['StepAttributionSchema'];

@Component({
  selector: 'app-formula-card',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './formula-card.component.html',
  styleUrls: ['./formula-card.component.scss'],
})
export class FormulaCardComponent {
  term = input.required<EquationTerm>();
  step = input.required<ComboStepResult>();

  /** Data-driven formula row from `step.zone_formulas[term.formulaKey]` (DESIGN §2.1/2.2). */
  readonly formulaRow = computed<FormulaRow | null>(() => {
    const key = this.term().formulaKey;
    if (!key) return null;
    const zf = this.step().zone_formulas?.[key];
    if (!zf) return null;
    return renderZoneFormula(zf);
  });

  /**
   * Anomaly-crit exception: attribution.py only builds a "crit" zone_formula
   * on the non-anomaly path, so this data-driven-elsewhere card falls back
   * to a hand-computed block matching the same math as the chip's displayed
   * crit_mult.
   */
  readonly anomalyCritLines = computed(() => {
    if (this.term().key !== 'anomaly_crit') return null;
    const s = this.step();
    const attr = s.attribution as StepAttribution | null;
    const critRate = attr?.crit_rate?.total ?? 0;
    const critDmg = attr?.crit_dmg?.total ?? 0;
    // Crit rate is clamped to 100% (10000 bp) in the damage formula.
    const effectiveCritRate = Math.min(critRate, 10000);
    return {
      ratePct: fmtPctBp(effectiveCritRate, false),
      dmgPct: fmtPctBp(critDmg, false),
      totalMult: fmtMultBp(s.crit_mult),
    };
  });

  readonly showCard = computed(() => this.formulaRow() !== null || this.anomalyCritLines() !== null);
}
