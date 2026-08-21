import { describe, it, expect } from 'vitest';
import { renderZoneFormula } from './zone-formula-render';
import type { components } from '../../api/api.types';

type ZoneFormulaSchema = components['schemas']['ZoneFormulaSchema'];

function zf(overrides: Partial<ZoneFormulaSchema>): ZoneFormulaSchema {
  return { template: '', terms: {}, result_bp: 0, pre_clamp_bp: null, ...overrides };
}

describe('renderZoneFormula — base_mv_scaling', () => {
  it('renders MV × scaling stat = raw base damage', () => {
    const row = renderZoneFormula(
      zf({
        template: 'base_mv_scaling',
        terms: { multiplier_bp: 3120, scaling_stat: 1000 },
        result_bp: 312,
      }),
    );
    expect(row.substituted).toContain('31.2%');
    expect(row.substituted).toContain('1,000');
    expect(row.result).toBe('312');
  });
});

describe('renderZoneFormula — boost_sum_dmg_pct', () => {
  it('renders 1 + sum as a multiplier', () => {
    const row = renderZoneFormula(
      zf({ template: 'boost_sum_dmg_pct', terms: { sum_dmg_pct_bp: 13500 }, result_bp: 23500 }),
    );
    expect(row.substituted).toContain('+135%');
    expect(row.result).toBe('×2.35');
  });
});

describe('renderZoneFormula — crit_rate_times_dmg', () => {
  it('renders rate × dmg with no cap note when uncapped', () => {
    const row = renderZoneFormula(
      zf({
        template: 'crit_rate_times_dmg',
        terms: { crit_rate_bp: 7500, crit_dmg_bp: 20000 },
        result_bp: 25000,
      }),
    );
    expect(row.substituted).toContain('75%');
    expect(row.substituted).toContain('200%');
    expect(row.result).toBe('×2.50');
    expect(row.capNote).toBeUndefined();
  });

  it('shows a cap note when crit rate was clamped to 100%', () => {
    const row = renderZoneFormula(
      zf({
        template: 'crit_rate_times_dmg',
        terms: { crit_rate_bp: 10060, crit_dmg_bp: 29020 },
        result_bp: 39020,
        pre_clamp_bp: 39218,
      }),
    );
    expect(row.result).toBe('×3.90');
    expect(row.capNote).toContain('×3.92');
  });
});

describe('renderZoneFormula — def_area', () => {
  it('renders LF / (LF + Eff. DEF)', () => {
    const row = renderZoneFormula(
      zf({
        template: 'def_area',
        terms: {
          level_factor_bp: 794,
          effective_enemy_def: 1275,
          pen_ratio_bp: 0,
          pen_flat: 0,
          def_ignore_bp: 0,
        },
        result_bp: 3838,
      }),
    );
    expect(row.substituted).toContain('794');
    expect(row.substituted).toContain('1,275');
    expect(row.result).toBe('×0.38');
  });
});

describe('renderZoneFormula — res_area', () => {
  it('renders 1 − enemy RES + reduction + ignore', () => {
    const row = renderZoneFormula(
      zf({
        template: 'res_area',
        terms: { enemy_res_bp: 2000, res_reduction_bp: 1000, res_ignore_bp: 0 },
        result_bp: 9000,
      }),
    );
    expect(row.substituted).toContain('20%');
    expect(row.substituted).toContain('+10%');
    expect(row.result).toBe('×0.90');
  });
});

describe('renderZoneFormula — vuln_sum', () => {
  it('renders 1 + sum vuln', () => {
    const row = renderZoneFormula(
      zf({ template: 'vuln_sum', terms: { sum_vuln_bp: 2500 }, result_bp: 12500 }),
    );
    expect(row.substituted).toContain('+25%');
    expect(row.result).toBe('×1.25');
  });
});

describe('renderZoneFormula — stun_area', () => {
  it('renders the base branch when no override is active', () => {
    const row = renderZoneFormula(
      zf({
        template: 'stun_area',
        terms: { stun_base_mult_bp: 15000, stun_area_override_bp: 0 },
        result_bp: 15000,
      }),
    );
    expect(row.result).toBe('×1.50');
  });

  it('renders the override branch when stun_area_override is active', () => {
    const row = renderZoneFormula(
      zf({
        template: 'stun_area',
        terms: { stun_base_mult_bp: 0, stun_area_override_bp: 11000 },
        result_bp: 21000,
      }),
    );
    expect(row.substituted).toContain('+110%');
    expect(row.result).toBe('×2.10');
  });
});

describe('renderZoneFormula — anomaly zones', () => {
  it('anomaly_prof_area renders AP / 100', () => {
    const row = renderZoneFormula(
      zf({ template: 'anomaly_prof_area', terms: { anomaly_proficiency: 152 }, result_bp: 15200 }),
    );
    expect(row.substituted).toContain('152');
    expect(row.result).toBe('×1.52');
  });

  it('anomaly_level_area renders the level formula', () => {
    const row = renderZoneFormula(
      zf({ template: 'anomaly_level_area', terms: { level: 60 }, result_bp: 11000 }),
    );
    expect(row.substituted).toContain('60');
    expect(row.result).toBe('×1.10');
  });

  it('anomaly_boost_sum renders 1 + sum', () => {
    const row = renderZoneFormula(
      zf({ template: 'anomaly_boost_sum', terms: { sum_anomaly_dmg_pct_bp: 2500 }, result_bp: 12500 }),
    );
    expect(row.substituted).toContain('+25%');
    expect(row.result).toBe('×1.25');
  });

  it('disorder_boost_sum renders 1 + sum', () => {
    const row = renderZoneFormula(
      zf({ template: 'disorder_boost_sum', terms: { sum_disorder_dmg_pct_bp: 5000 }, result_bp: 15000 }),
    );
    expect(row.substituted).toContain('+50%');
    expect(row.result).toBe('×1.50');
  });
});

describe('renderZoneFormula — sheer zones', () => {
  it('sheer_force_components renders the three-term sum as a raw value', () => {
    const row = renderZoneFormula(
      zf({
        template: 'sheer_force_components',
        terms: { atk_pct_bp: 3000, hp_pct_bp: 1000, flat: 50 },
        result_bp: 900,
      }),
    );
    expect(row.substituted).toContain('30%');
    expect(row.substituted).toContain('10%');
    expect(row.substituted).toContain('50');
    expect(row.result).toBe('900');
  });

  it('sheer_boost_sum renders 1 + sum', () => {
    const row = renderZoneFormula(
      zf({ template: 'sheer_boost_sum', terms: { sum_sheer_dmg_pct_bp: 4000 }, result_bp: 14000 }),
    );
    expect(row.substituted).toContain('+40%');
    expect(row.result).toBe('×1.40');
  });
});

describe('renderZoneFormula — direct_dmg_sum', () => {
  it('renders 1 + sum as a multiplier (Windswept Direct DMG zone)', () => {
    const row = renderZoneFormula(
      zf({
        template: 'direct_dmg_sum',
        terms: { sum_direct_dmg_pct_bp: 1000 },
        result_bp: 11000,
      }),
    );
    expect(row.label).toBe('Direct DMG Bonus');
    expect(row.substituted).toContain('+10%');
    expect(row.result).toBe('×1.10');
  });
});
