import { describe, it, expect } from 'vitest';
import { equationTerms } from './equation-terms';
import type { components } from '../../api/api.types';

type ComboStepResult = components['schemas']['ComboStepResultSchema'];

function makeStep(overrides: Partial<ComboStepResult> = {}): ComboStepResult {
  return {
    label: 'Basic 1',
    attack_id: 'basic_1',
    attack_name: 'Basic Attack',
    scope: 'basic',
    element: 'ice',
    multiplier: 10000,     // 100% MV in bp
    total: 10000,
    damage_no_crit: 8000,
    damage_crit: 15000,
    damage_expected: 10000,
    base_dmg: 2450,
    boost_mult: 10000,     // 1.0× in bp
    crit_mult: 18400,      // 1.84× in bp
    def_mult: 6100,        // 0.61× in bp
    res_mult: 10000,       // 1.0× in bp
    vulnerability_mult: 10000,
    stun_mult: 10000,
    effective_atk: 2450,
    is_anomaly: false,
    anomaly_proficiency_mult: 0,
    anomaly_level_mult: 0,
    anomaly_dmg_bonus_mult: 10000,  // 1.0× in bp
    level_factor: 794,
    effective_enemy_def: 1275,
    stun_base_mult: 0,
    attribution: null,
    ...overrides,
  };
}

function makeAttr(
  overrides: Partial<components['schemas']['StepAttributionSchema']> = {},
): components['schemas']['StepAttributionSchema'] {
  const emptyZone = (): components['schemas']['ZoneAttributionSchema'] => ({
    contributions: [],
    total: 0,
  });
  return {
    atk_components: emptyZone(),
    atk_pct_components: emptyZone(),
    crit_rate: emptyZone(),
    crit_dmg: emptyZone(),
    boost_bonuses: emptyZone(),
    pen_ratio: emptyZone(),
    pen_flat: emptyZone(),
    res_reduction: emptyZone(),
    res_ignore: emptyZone(),
    def_ignore: emptyZone(),
    vulnerability: emptyZone(),
    stun_bonuses: emptyZone(),
    ...overrides,
  };
}

// ── Standard hit ─────────────────────────────────────────────────────────────

describe('equationTerms — standard hit', () => {
  it('always includes base and atk chips', () => {
    const terms = equationTerms(makeStep());
    const keys = terms.map((t) => t.key);
    expect(keys).toContain('base');
    expect(keys).toContain('atk');
  });

  it('base chip is clickable and drills into the "base" zone_formula', () => {
    const terms = equationTerms(makeStep());
    const base = terms.find((t) => t.key === 'base')!;
    expect(base.clickable).toBe(true);
    expect(base.formulaKey).toBe('base');
  });

  it('atk chip has no formulaKey on the non-sheer path (no backend formula for a raw sum)', () => {
    const terms = equationTerms(makeStep());
    const atk = terms.find((t) => t.key === 'atk')!;
    expect(atk.formulaKey).toBeNull();
  });

  it('crit/dmg/def/res/vuln/stun chips carry their matching formulaKey', () => {
    const step = makeStep({
      boost_mult: 23500,
      crit_mult: 18400,
      res_mult: 12000,
      vulnerability_mult: 12500,
      stun_mult: 15000,
    });
    const terms = equationTerms(step);
    expect(terms.find((t) => t.key === 'crit')!.formulaKey).toBe('crit');
    expect(terms.find((t) => t.key === 'dmg')!.formulaKey).toBe('boost');
    expect(terms.find((t) => t.key === 'def')!.formulaKey).toBe('def');
    expect(terms.find((t) => t.key === 'res')!.formulaKey).toBe('res');
    expect(terms.find((t) => t.key === 'vuln')!.formulaKey).toBe('vulnerability');
    expect(terms.find((t) => t.key === 'stun')!.formulaKey).toBe('stun');
  });

  it('base chip displayValue is MV% without ATK suffix', () => {
    const step = makeStep({ multiplier: 17500 }); // 175%
    const base = equationTerms(step).find((t) => t.key === 'base')!;
    expect(base.displayValue).toBe('175%');
  });

  it('DMG% chip omitted when boost_mult == 10000 and no attribution total', () => {
    const step = makeStep({ boost_mult: 10000, attribution: makeAttr() });
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).not.toContain('dmg');
  });

  it('DMG% chip present when boost_mult != 10000', () => {
    const step = makeStep({ boost_mult: 23500 }); // +135% DMG bonus
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).toContain('dmg');
  });

  it('DMG% chip displayValue is bp-corrected', () => {
    const step = makeStep({ boost_mult: 13500 }); // +35%
    const chip = equationTerms(step).find((t) => t.key === 'dmg')!;
    expect(chip.displayValue).toBe('+35%');
  });

  it('DMG% chip present when attribution boost_bonuses.total != 0', () => {
    const attr = makeAttr({ boost_bonuses: { contributions: [], total: 500 } });
    const step = makeStep({ boost_mult: 10000, attribution: attr });
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).toContain('dmg');
  });

  it('Stun chip omitted when stun_mult == 10000', () => {
    const step = makeStep({ stun_mult: 10000 });
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).not.toContain('stun');
  });

  it('Stun chip present when stun_mult != 10000', () => {
    const step = makeStep({ stun_mult: 15000 }); // 1.5×
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).toContain('stun');
  });

  it('Stun chip displayValue is bp-corrected', () => {
    const step = makeStep({ stun_mult: 19500 }); // 1.95×
    const chip = equationTerms(step).find((t) => t.key === 'stun')!;
    expect(chip.displayValue).toBe('×1.95');
  });

  it('RES chip omitted when res_mult == 10000', () => {
    const step = makeStep({ res_mult: 10000 });
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).not.toContain('res');
  });

  it('RES chip present when res_mult != 10000', () => {
    const step = makeStep({ res_mult: 12000 }); // 1.2×
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).toContain('res');
  });

  it('Vuln chip omitted when vulnerability_mult == 10000', () => {
    const step = makeStep({ vulnerability_mult: 10000 });
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).not.toContain('vuln');
  });

  it('Crit chip present on standard hit with non-zero crit_mult', () => {
    const step = makeStep({ crit_mult: 18400 }); // 1.84×
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).toContain('crit');
  });

  it('Crit chip displayValue is bp-corrected', () => {
    const step = makeStep({ crit_mult: 18400 });
    const chip = equationTerms(step).find((t) => t.key === 'crit')!;
    expect(chip.displayValue).toBe('×1.84');
  });

  it('Crit chip omitted on standard hit when crit_mult == 0 and attribution empty', () => {
    const step = makeStep({ crit_mult: 0, attribution: makeAttr() });
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).not.toContain('crit');
  });

  it('DEF chip always present', () => {
    const terms = equationTerms(makeStep({ def_mult: 6100 }));
    const keys = terms.map((t) => t.key);
    expect(keys).toContain('def');
  });

  it('DEF chip displayValue is bp-corrected', () => {
    const step = makeStep({ def_mult: 3800 }); // ×0.38
    const chip = equationTerms(step).find((t) => t.key === 'def')!;
    expect(chip.displayValue).toBe('×0.38');
  });

  it('no anomaly chips on standard hit', () => {
    const terms = equationTerms(makeStep());
    const keys = terms.map((t) => t.key);
    expect(keys).not.toContain('anomaly_prof');
    expect(keys).not.toContain('anomaly_level');
    expect(keys).not.toContain('anomaly_bonus');
    expect(keys).not.toContain('anomaly_crit');
  });
});

// ── Anomaly hit ───────────────────────────────────────────────────────────────

describe('equationTerms — anomaly hit', () => {
  const anomalyBase: Partial<ComboStepResult> = {
    is_anomaly: true,
    anomaly_proficiency_mult: 15200,  // 1.52× in bp
    anomaly_level_mult: 13000,        // 1.30× in bp
    anomaly_dmg_bonus_mult: 10000,    // 1.0× (no bonus)
    crit_mult: 0,
    attribution: makeAttr(),
  };

  it('anomaly_prof and anomaly_level chips always appear on anomaly hits', () => {
    const step = makeStep(anomalyBase);
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).toContain('anomaly_prof');
    expect(keys).toContain('anomaly_level');
  });

  it('anomaly_prof displayValue is bp-corrected', () => {
    const step = makeStep(anomalyBase);
    const chip = equationTerms(step).find((t) => t.key === 'anomaly_prof')!;
    expect(chip.displayValue).toBe('×1.52');
  });

  it('anomaly_prof/anomaly_level chips are clickable with matching formulaKey', () => {
    const step = makeStep(anomalyBase);
    const terms = equationTerms(step);
    const prof = terms.find((t) => t.key === 'anomaly_prof')!;
    const level = terms.find((t) => t.key === 'anomaly_level')!;
    expect(prof.clickable).toBe(true);
    expect(prof.formulaKey).toBe('anomaly_prof');
    expect(level.clickable).toBe(true);
    expect(level.formulaKey).toBe('anomaly_level');
  });

  it('anomaly_bonus chip omitted when anomaly_dmg_bonus_mult == 10000', () => {
    const step = makeStep({ ...anomalyBase, anomaly_dmg_bonus_mult: 10000 });
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).not.toContain('anomaly_bonus');
  });

  it('anomaly_bonus chip present when anomaly_dmg_bonus_mult != 10000', () => {
    const step = makeStep({ ...anomalyBase, anomaly_dmg_bonus_mult: 12500 }); // 1.25×
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).toContain('anomaly_bonus');
  });

  it('Crit chip omitted on anomaly hits when both crit zones are empty', () => {
    const attr = makeAttr({
      crit_rate: { contributions: [], total: 0 },
      crit_dmg: { contributions: [], total: 0 },
    });
    const step = makeStep({ ...anomalyBase, crit_mult: 0, attribution: attr });
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).not.toContain('crit');
    expect(keys).not.toContain('anomaly_crit');
  });

  // Jane Doe regression test — anomaly hit with non-zero crit zones
  it('Anomaly Crit chip included on anomaly hit when both crit zones non-zero (Jane Doe)', () => {
    const attr = makeAttr({
      crit_rate: { contributions: [], total: 5000 }, // 50% crit rate in bp
      crit_dmg: { contributions: [], total: 12000 }, // 120% crit dmg in bp
    });
    const step = makeStep({
      ...anomalyBase,
      crit_mult: 16000, // 1.60× in bp
      attribution: attr,
    });
    const terms = equationTerms(step);
    const keys = terms.map((t) => t.key);
    expect(keys).toContain('anomaly_crit');
    expect(keys).not.toContain('crit');

    const chip = terms.find((t) => t.key === 'anomaly_crit')!;
    expect(chip.label).toBe('Anomaly Crit');
    expect(chip.clickable).toBe(true);
    expect(chip.displayValue).toBe('×1.60');
    // No backend zone_formula exists for "crit" on the anomaly path.
    expect(chip.formulaKey).toBeNull();
  });

  it('standard crit chip does not appear on anomaly hits', () => {
    const step = makeStep(anomalyBase);
    const keys = equationTerms(step).map((t) => t.key);
    expect(keys).not.toContain('crit');
  });
});

// ── Term ordering ─────────────────────────────────────────────────────────────

describe('equationTerms — ordering', () => {
  it('standard terms follow formula order: base, atk, crit, dmg, def, res, vuln, stun', () => {
    const step = makeStep({
      boost_mult: 23500,      // +135% DMG
      crit_mult: 18400,       // 1.84×
      res_mult: 12000,        // 1.2×
      vulnerability_mult: 12500, // 1.25×
      stun_mult: 15000,       // 1.5×
    });
    const keys = equationTerms(step).map((t) => t.key);
    const baseIdx = keys.indexOf('base');
    const atkIdx = keys.indexOf('atk');
    const critIdx = keys.indexOf('crit');
    const dmgIdx = keys.indexOf('dmg');
    const defIdx = keys.indexOf('def');
    const resIdx = keys.indexOf('res');
    const vulnIdx = keys.indexOf('vuln');
    const stunIdx = keys.indexOf('stun');

    expect(baseIdx).toBeLessThan(atkIdx);
    expect(atkIdx).toBeLessThan(critIdx);
    expect(critIdx).toBeLessThan(dmgIdx);
    expect(dmgIdx).toBeLessThan(defIdx);
    expect(defIdx).toBeLessThan(resIdx);
    expect(resIdx).toBeLessThan(vulnIdx);
    expect(vulnIdx).toBeLessThan(stunIdx);
  });

  it('anomaly terms follow formula order: base, atk, anomaly_prof, anomaly_level, [bonus], def, res, ...', () => {
    const attr = makeAttr();
    const step = makeStep({
      is_anomaly: true,
      anomaly_proficiency_mult: 15200, // 1.52×
      anomaly_level_mult: 13000,       // 1.30×
      anomaly_dmg_bonus_mult: 12500,   // 1.25×
      attribution: attr,
    });
    const keys = equationTerms(step).map((t) => t.key);
    const atkIdx = keys.indexOf('atk');
    const profIdx = keys.indexOf('anomaly_prof');
    const levelIdx = keys.indexOf('anomaly_level');
    const bonusIdx = keys.indexOf('anomaly_bonus');
    const defIdx = keys.indexOf('def');

    expect(atkIdx).toBeLessThan(profIdx);
    expect(profIdx).toBeLessThan(levelIdx);
    expect(levelIdx).toBeLessThan(bonusIdx);
    expect(bonusIdx).toBeLessThan(defIdx);
  });
});
