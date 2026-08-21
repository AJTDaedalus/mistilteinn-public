import { TestBed } from '@angular/core/testing';
import { ComponentRef } from '@angular/core';
import { describe, it, expect, beforeEach } from 'vitest';

import { BuffDrawerComponent } from './buff-drawer.component';
import type { EquationTerm } from './equation-terms';
import type { components } from '../../api/api.types';

type StepAttribution = components['schemas']['StepAttributionSchema'];
type ContributionSchema = components['schemas']['ContributionSchema'];
type ComboStepResult = components['schemas']['ComboStepResultSchema'];

const DUMMY_STEP: ComboStepResult = {
  label: 'Basic 1', attack_id: 'a', attack_name: 'Basic', scope: 'basic',
  element: 'ice', multiplier: 10000, total: 5000,
  damage_no_crit: 4000, damage_crit: 8000, damage_expected: 5000,
  base_dmg: 2000, boost_mult: 10000, crit_mult: 18400,
  def_mult: 6100, res_mult: 10000, vulnerability_mult: 10000,
  stun_mult: 10000, effective_atk: 2450, is_anomaly: false,
  anomaly_proficiency_mult: 0, anomaly_level_mult: 0, anomaly_dmg_bonus_mult: 10000,
  level_factor: 794, effective_enemy_def: 1275, stun_base_mult: 0,
  attribution: null,
};

function contrib(overrides: Partial<ContributionSchema> & { value: number }): ContributionSchema {
  return {
    source: 'Test Source',
    source_category: null,
    source_kind: null,
    owner_agent_name: null,
    description: null,
    ...overrides,
  };
}

function emptyZone() {
  return { contributions: [], total: 0 };
}

function makeAttr(overrides: Partial<StepAttribution> = {}): StepAttribution {
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

const DMG_TERM: EquationTerm = {
  key: 'dmg',
  label: 'DMG%',
  displayValue: '+135%',
  rawValue: 2.35,
  zones: ['boost_bonuses'],
  clickable: true,
  formulaKey: 'boost',
};

const DEF_TERM: EquationTerm = {
  key: 'def',
  label: 'DEF',
  displayValue: '×0.61',
  rawValue: 0.61,
  zones: ['pen_ratio', 'pen_flat', 'def_ignore'],
  clickable: true,
  formulaKey: 'def',
};

function setup(term: EquationTerm, attribution: StepAttribution | null, activeAgentName = '', step: ComboStepResult = DUMMY_STEP) {
  TestBed.configureTestingModule({ imports: [BuffDrawerComponent] });
  const f = TestBed.createComponent(BuffDrawerComponent);
  const ref = f.componentRef as ComponentRef<BuffDrawerComponent>;
  ref.setInput('term', term);
  ref.setInput('step', step);
  ref.setInput('attribution', attribution);
  ref.setInput('activeAgentName', activeAgentName);
  f.detectChanges();
  return f;
}

describe('BuffDrawerComponent', () => {
  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('renders nothing when attribution is null', () => {
    const f = setup(DMG_TERM, null);
    const el = f.nativeElement as HTMLElement;
    expect(el.querySelectorAll('.drawer__section')).toHaveLength(0);
  });

  it('shows "No contributions recorded" when the zone is empty', () => {
    const f = setup(DMG_TERM, makeAttr(), 'Ellen Joe');
    const el = f.nativeElement as HTMLElement;
    expect(el.querySelector('.drawer__empty')?.textContent?.trim()).toBeTruthy();
  });

  it('renders an Agent row for an agent-category contribution', () => {
    const f = setup(
      DMG_TERM,
      makeAttr({
        boost_bonuses: {
          total: 3000,
          contributions: [
            contrib({ value: 3000, source: 'Core Passive', source_category: 'agent', owner_agent_name: 'Ellen Joe' }),
          ],
        },
      }),
      'Ellen Joe',
    );
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;

    const sections = el.querySelectorAll('.drawer__section');
    expect(sections).toHaveLength(1);
    expect(sections[0].querySelector('.drawer__section-head')?.textContent?.trim()).toBe('Agent');
    expect(sections[0].querySelector('.drawer__source')?.textContent).toContain('Core Passive');
  });

  // Simulates the Ellen+Nicole combo: Nicole's "Cunning Hares" appears under
  // Agent with the "(Nicole Demara)" owner suffix.
  it('shows owner suffix when contributor is a team member, not the active agent', () => {
    const f = setup(
      DMG_TERM,
      makeAttr({
        boost_bonuses: {
          total: 4000,
          contributions: [
            contrib({ value: 2000, source: 'Cunning Hares', source_category: 'agent', owner_agent_name: 'Nicole Demara' }),
            contrib({ value: 2000, source: 'Core Passive', source_category: 'agent', owner_agent_name: 'Ellen Joe' }),
          ],
        },
      }),
      'Ellen Joe',
    );
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;

    const rows = el.querySelectorAll('.drawer__row');
    // Both rows are in Agent section, sorted by |value| desc (equal here — stable order).
    expect(rows).toHaveLength(2);

    // Find the Cunning Hares row.
    const cunningRow = Array.from(rows).find((r) => r.querySelector('.drawer__source')?.textContent?.includes('Cunning Hares'));
    expect(cunningRow).toBeTruthy();
    expect(cunningRow!.querySelector('.drawer__owner')?.textContent?.trim()).toBe('(Nicole Demara)');
  });

  it('omits owner suffix when contributor is the active agent', () => {
    const f = setup(
      DMG_TERM,
      makeAttr({
        boost_bonuses: {
          total: 2000,
          contributions: [
            contrib({ value: 2000, source: 'Core Passive', source_category: 'agent', owner_agent_name: 'Ellen Joe' }),
          ],
        },
      }),
      'Ellen Joe',
    );
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;

    const row = el.querySelector('.drawer__row');
    expect(row?.querySelector('.drawer__owner')).toBeNull();
  });

  it('shows zone sub-headers when term spans multiple zones', () => {
    const f = setup(
      DEF_TERM,
      makeAttr({
        pen_ratio: {
          total: 800,
          contributions: [contrib({ value: 800, source: 'Deep Sea R1', source_category: 'wengine' })],
        },
      }),
      'Ellen Joe',
    );
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;

    // With 3 zones, each zone gets a sub-header.
    const zoneHeads = el.querySelectorAll('.drawer__zone-head');
    expect(zoneHeads.length).toBeGreaterThan(0);
    const labels = Array.from(zoneHeads).map((h) => h.querySelector('.drawer__zone-label')?.textContent?.trim());
    expect(labels).toContain('PEN Ratio');
  });

  it('formats basis-point values as percent', () => {
    const f = setup(
      DMG_TERM,
      makeAttr({
        boost_bonuses: {
          total: 3000,
          contributions: [contrib({ value: 3000, source: 'Core Passive', source_category: 'agent' })],
        },
      }),
      '',
    );
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    expect(el.querySelector('.drawer__value')?.textContent?.trim()).toBe('+30%');
  });

  it('formats flat ATK values as signed integers', () => {
    const atkTerm: EquationTerm = {
      key: 'atk',
      label: 'ATK',
      displayValue: '2,450',
      rawValue: 2450,
      zones: ['atk_components', 'atk_pct_components'],
      clickable: true,
      formulaKey: null,
    };
    const f = setup(
      atkTerm,
      makeAttr({
        atk_components: {
          total: 2450,
          contributions: [contrib({ value: 2450, source: 'Base ATK', source_category: 'base' })],
        },
      }),
      '',
    );
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    const values = Array.from(el.querySelectorAll('.drawer__value')).map((v) => v.textContent?.trim());
    expect(values).toContain('+2,450');
  });

  it('renders different category sections in correct order', () => {
    const f = setup(
      DMG_TERM,
      makeAttr({
        boost_bonuses: {
          total: 6000,
          contributions: [
            contrib({ value: 1000, source: 'Food Buff', source_category: 'external' }),
            contrib({ value: 2000, source: 'Deep Sea', source_category: 'wengine' }),
            contrib({ value: 3000, source: 'Core Passive', source_category: 'agent' }),
          ],
        },
      }),
      '',
    );
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;

    const heads = Array.from(el.querySelectorAll('.drawer__section-head')).map((h) => h.textContent?.trim());
    // agent before wengine before external
    expect(heads.indexOf('Agent')).toBeLessThan(heads.indexOf('W-Engine'));
    expect(heads.indexOf('W-Engine')).toBeLessThan(heads.indexOf('External'));
  });
});
