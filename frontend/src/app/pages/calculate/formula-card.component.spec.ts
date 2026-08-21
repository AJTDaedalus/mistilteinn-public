import { describe, it, expect } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { FormulaCardComponent } from './formula-card.component';
import type { EquationTerm } from './equation-terms';
import type { components } from '../../api/api.types';

type ComboStepResult = components['schemas']['ComboStepResultSchema'];
type StepAttribution = components['schemas']['StepAttributionSchema'];
type ZoneFormulaSchema = components['schemas']['ZoneFormulaSchema'];

function makeTerm(overrides: Partial<EquationTerm> & { key: EquationTerm['key'] }): EquationTerm {
  return {
    label: overrides.key,
    displayValue: '',
    rawValue: 0,
    zones: [],
    clickable: true,
    formulaKey: null,
    ...overrides,
  };
}

function makeStep(overrides: Partial<ComboStepResult> = {}): ComboStepResult {
  return {
    label: 'Basic 1', attack_id: 'a', attack_name: 'Basic', scope: 'basic',
    element: 'ice', multiplier: 10000, total: 5000,
    damage_no_crit: 4000, damage_crit: 8000, damage_expected: 5000,
    base_dmg: 2000, boost_mult: 10000, crit_mult: 18400,
    def_mult: 3834, res_mult: 10000, vulnerability_mult: 10000,
    stun_mult: 10000, effective_atk: 2450, is_anomaly: false,
    anomaly_proficiency_mult: 0, anomaly_level_mult: 0, anomaly_dmg_bonus_mult: 10000,
    level_factor: 794, effective_enemy_def: 1275, stun_base_mult: 0,
    attribution: null,
    zone_formulas: null,
    ...overrides,
  };
}

function makeAttr(
  overrides: Partial<StepAttribution> = {},
): StepAttribution {
  const z = () => ({ contributions: [], total: 0 });
  return {
    atk_components: z(), atk_pct_components: z(), crit_rate: z(), crit_dmg: z(),
    boost_bonuses: z(), pen_ratio: z(), pen_flat: z(), res_reduction: z(),
    res_ignore: z(), def_ignore: z(), vulnerability: z(), stun_bonuses: z(),
    ...overrides,
  };
}

function zf(overrides: Partial<ZoneFormulaSchema>): ZoneFormulaSchema {
  return { template: '', terms: {}, result_bp: 0, pre_clamp_bp: null, ...overrides };
}

async function render(term: EquationTerm, step: ComboStepResult) {
  @Component({
    standalone: true,
    imports: [FormulaCardComponent],
    template: `<app-formula-card [term]="term" [step]="step" />`,
  })
  class Host {
    term = term;
    step = step;
  }
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture.nativeElement as HTMLElement;
}

describe('FormulaCardComponent — data-driven from zone_formulas', () => {
  it('renders nothing when the chip has no formulaKey and is not anomaly_crit', async () => {
    const el = await render(makeTerm({ key: 'atk', formulaKey: null }), makeStep());
    expect(el.querySelector('.formula-card')).toBeNull();
  });

  it('renders nothing when formulaKey is set but step.zone_formulas has no matching entry', async () => {
    const el = await render(
      makeTerm({ key: 'def', formulaKey: 'def' }),
      makeStep({ zone_formulas: null }),
    );
    expect(el.querySelector('.formula-card')).toBeNull();
  });

  it('renders the DEF formula from zone_formulas', async () => {
    const step = makeStep({
      def_mult: 3834,
      zone_formulas: {
        def: zf({
          template: 'def_area',
          terms: {
            level_factor_bp: 794,
            effective_enemy_def: 1275,
            pen_ratio_bp: 0,
            pen_flat: 0,
            def_ignore_bp: 0,
          },
          result_bp: 3834,
        }),
      },
    });
    const el = await render(makeTerm({ key: 'def', formulaKey: 'def' }), step);
    const text = el.textContent ?? '';
    expect(text).toContain('794');
    expect(text).toContain('1,275');
    expect(text).toContain('×0.38');
  });

  it('renders the Stun formula from zone_formulas', async () => {
    const step = makeStep({
      stun_mult: 19500,
      zone_formulas: {
        stun: zf({
          template: 'stun_area',
          terms: { stun_base_mult_bp: 15000, stun_area_override_bp: 0 },
          result_bp: 19500,
        }),
      },
    });
    const el = await render(makeTerm({ key: 'stun', formulaKey: 'stun' }), step);
    const text = el.textContent ?? '';
    expect(text).toContain('×1.50');
    expect(text).toContain('×1.95');
  });

  it('renders the Crit formula from zone_formulas with a cap note when clamped', async () => {
    const step = makeStep({
      crit_mult: 39020,
      zone_formulas: {
        crit: zf({
          template: 'crit_rate_times_dmg',
          terms: { crit_rate_bp: 10060, crit_dmg_bp: 29020 },
          result_bp: 39020,
          pre_clamp_bp: 39218,
        }),
      },
    });
    const el = await render(makeTerm({ key: 'crit', formulaKey: 'crit' }), step);
    const text = el.textContent ?? '';
    expect(text).toContain('100%'); // clamped crit rate, not 100.6%
    expect(text).toContain('290.2%');
    expect(text).toContain('×3.90');
    expect(text).toContain('capped from');
  });

  it('renders the Base formula from zone_formulas', async () => {
    const step = makeStep({
      zone_formulas: {
        base: zf({
          template: 'base_mv_scaling',
          terms: { multiplier_bp: 3120, scaling_stat: 1000 },
          result_bp: 312,
        }),
      },
    });
    const el = await render(makeTerm({ key: 'base', formulaKey: 'base' }), step);
    const text = el.textContent ?? '';
    expect(text).toContain('31.2%');
    expect(text).toContain('312');
  });
});

describe('FormulaCardComponent — anomaly_crit fallback (no backend zone_formula)', () => {
  it('renders a hand-computed crit block for anomaly_crit regardless of zone_formulas', async () => {
    const attr = makeAttr({
      crit_rate: { contributions: [], total: 5000 },
      crit_dmg: { contributions: [], total: 12000 },
    });
    const step = makeStep({ crit_mult: 16000, attribution: attr, zone_formulas: null });
    const el = await render(makeTerm({ key: 'anomaly_crit', formulaKey: null }), step);
    const text = el.textContent ?? '';
    expect(text).toContain('50%');
    expect(text).toContain('120%');
    expect(text).toContain('×1.60');
  });

  it('clamps displayed crit rate to 100% when stat exceeds cap', async () => {
    const attr = makeAttr({
      crit_rate: { contributions: [], total: 10060 },
      crit_dmg: { contributions: [], total: 29020 },
    });
    const step = makeStep({ crit_mult: 39020, attribution: attr, zone_formulas: null });
    const el = await render(makeTerm({ key: 'anomaly_crit', formulaKey: null }), step);
    const text = el.textContent ?? '';
    expect(text).toContain('100%');
    expect(text).toContain('290.2%');
    expect(text).toContain('×3.90');
  });
});
