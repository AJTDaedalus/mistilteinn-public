import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { FormulaEstimateService } from '../../pages/optimize/formula-estimate.service';
import type { ConditionGroup } from '../../sim/formula-calibration';
import { FormulaLabel } from './formula-label';
import { FormulaPanel } from './formula-panel';

/**
 * Math-fallback P1, task 8 — the formula target and the assumptions panel.
 *
 * Owner, 2026-11-13: every conditional is a visible control showing its default (self-triggered
 * on, situational off), refused hits are shown greyed with their reason, and every control has
 * an accessible name.
 */

const HITS = [
  { talent: 'elemental_skill', label: 'Skill DMG', index: 0, multiplier: 2, hits: 1,
    exclusive: false, scaling_stat: 'atk', extra_terms: [] },
  { talent: 'normal_attack', label: '1-Hit DMG', index: 0, multiplier: 0.5, hits: 1,
    exclusive: false, scaling_stat: 'atk', extra_terms: [] },
];

const REFUSED = [{
  talent: 'normal_attack', label: 'Windsunder Arrow DMG', spec: '{param12:F1P} Normal Attack DMG',
  reason: "a multiple of the character's Normal Attack DMG, not of a stat",
}];

const GROUPS: ConditionGroup[] = [
  {
    sourceId: 'set:15006:4', label: 'Crimson Witch of Flames 4pc', citation: 'GO CrimsonWitch',
    conditions: [{ key: 'stacks', label: 'Skill stacks', kind: 'stacks', default: 3,
      default_reason: 'self', max: 3 }],
    unmodelled: [{ what: 'Overloaded DMG', reason: 'transformative reactions are not modelled' }],
  },
  {
    sourceId: 'resonance:shattering_ice', label: 'Shattering Ice', citation: 'GO Resonance.tsx',
    conditions: [{ key: 'affected', label: 'Enemy Cryo or Frozen', kind: 'toggle', default: 0,
      default_reason: 'situational' }],
    unmodelled: [],
  },
];

function render() {
  TestBed.configureTestingModule({ imports: [FormulaPanel] });
  const service = TestBed.inject(FormulaEstimateService);
  service.ensureTarget('b1', HITS as never);
  const fixture = TestBed.createComponent(FormulaPanel);
  fixture.componentRef.setInput('hits', HITS);
  fixture.componentRef.setInput('refusedHits', REFUSED);
  fixture.componentRef.setInput('groups', GROUPS);
  fixture.detectChanges();
  return { el: fixture.nativeElement as HTMLElement, fixture, service };
}

describe('FormulaPanel', () => {
  it('names every control', () => {
    const { el } = render();
    for (const control of el.querySelectorAll('select, input')) {
      // Each is inside a <label> with text, which is its accessible name.
      const label = control.closest('label');
      expect(label?.textContent?.trim().length ?? 0).toBeGreaterThan(0);
    }
    const remove = el.querySelector('.formula__remove')!;
    expect(remove.getAttribute('aria-label')).toContain('Skill DMG');
  });

  it('shows a refused hit greyed in the picker and with its reason beside it', () => {
    const { el } = render();
    const disabled = [...el.querySelectorAll('option[disabled]')].map((o) => o.textContent);
    expect(disabled.join('')).toContain('Windsunder Arrow DMG · not scored');
    expect(el.querySelector('refused-hits')?.textContent).toContain('Normal Attack DMG');
  });

  it('draws every conditional with its default and its source', () => {
    const { el } = render();
    const text = el.querySelector('.assumptions')!.textContent!;
    expect(text).toContain('Default 3 — the wearer triggers it');
    expect(text).toContain('Default off — depends on the situation');
    expect(text).toContain('Source: GO CrimsonWitch');
    expect(text).toContain('Not applied: Overloaded DMG');
    const box = el.querySelector<HTMLInputElement>('.assumptions__toggle input')!;
    expect(box.checked).toBe(false);
  });

  it('a toggle writes the team-level conditional and marks it changed', () => {
    const { el, fixture, service } = render();
    const box = el.querySelector<HTMLInputElement>('.assumptions__toggle input')!;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(service.conditionals()['resonance:shattering_ice/affected']).toBe(1);
    expect(el.querySelector('.assumptions__default--changed')).toBeTruthy();
  });

  it('adds a row, keeps a count that is not positive from being written, and removes a row', () => {
    const { el, fixture, service } = render();
    el.querySelector<HTMLButtonElement>('.formula__actions button')!.click();
    fixture.detectChanges();
    expect(service.rows()).toHaveLength(2);

    const count = el.querySelector<HTMLInputElement>('.formula__field--count input')!;
    count.value = '0';
    count.dispatchEvent(new Event('change'));
    expect(service.rows()[0].count).toBe(1);
    count.value = '2.5';
    count.dispatchEvent(new Event('change'));
    expect(service.rows()[0].count).toBe(2.5);

    // Per-row overrides appear once there are two rows.
    fixture.detectChanges();
    expect(el.querySelector('.formula__overrides')).toBeTruthy();

    el.querySelector<HTMLButtonElement>('.formula__remove')!.click();
    expect(service.rows()).toHaveLength(1);
  });
});

describe('FormulaPanel picker identity', () => {
  it('tells two rows of one talent apart when both are part 0', () => {
    // Driven: Kachina's 1-Hit and Low/High Plunge rows are both `normal_attack` part 0, and a
    // `talent#index` key showed the plunge over a target that held the 1-Hit row.
    const hits = [
      { ...HITS[1], label: '1-Hit DMG' },
      { ...HITS[1], label: 'Low/High Plunge DMG' },
    ];
    TestBed.configureTestingModule({ imports: [FormulaPanel] });
    TestBed.inject(FormulaEstimateService).ensureTarget('b1', hits as never);
    const fixture = TestBed.createComponent(FormulaPanel);
    fixture.componentRef.setInput('hits', hits);
    fixture.detectChanges();
    const select = (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLSelectElement>('.formula__field--hit select')!;
    expect(select.selectedOptions[0].textContent?.trim()).toBe('1-Hit DMG');
  });
});

describe('FormulaLabel', () => {
  it('says formula estimate, no simulation, and never DPS', () => {
    TestBed.configureTestingModule({ imports: [FormulaLabel] });
    const fixture = TestBed.createComponent(FormulaLabel);
    fixture.detectChanges();
    const text = (fixture.nativeElement as HTMLElement).textContent!;
    expect(text).toContain('Formula estimate — no simulation');
    expect(text).toContain('Damage for the chosen sequence');
    expect(text).not.toMatch(/\bDPS\b/);
  });
});
