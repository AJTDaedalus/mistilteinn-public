import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import {
  FormulaEstimateService,
  refundKey,
  type TeamEnergyData,
} from '../../pages/optimize/formula-estimate.service';
import { FormulaPanel } from './formula-panel';

/**
 * The owner's small calls of 2026-11-15 in the panel's Energy section (DECISIONS §50): the
 * drip's on-field share, Venti's absorbed element, and constellation refunds — counted, a
 * toggle off by default, or listed with the reason they are not counted.
 */

const HITS = [{ talent: 'normal_attack', label: '1-Hit DMG', index: 0, multiplier: 0.8,
  hits: 1, exclusive: false, scaling_stat: 'atk', extra_terms: [] }];

type Member = TeamEnergyData['members'][number];
const member = (over: Partial<Member>): Member => ({
  build_id: 'x', name: 'X', element: 'pyro', burst_energy_cost: 80, burst_cooldown: 20,
  is_subject: false, status: 'curated', sources: [], refunds: [], favonius: null,
  energy_recharge: 1.2, crit_rate: 0.5, ...over,
});

const DATA: TeamEnergyData = {
  gcsim_commit: 'b107b5dc',
  drip: { particles: 1, interval_seconds: 599.5 / 60, config: 'energy every', citation: 'drip cite' },
  resonance: null,
  members: [
    member({ build_id: 'xl', name: 'Xiangling', is_subject: true }),
    member({ build_id: 'vt', name: 'Venti', element: 'anemo', refunds: [
      { label: 'Stairway to Heaven (A4): 15 energy back', per: 'burst', count: 1,
        recipients: 'self', scaling: 'none', amount: 15, citation: 'venti/asc.go:13' },
      { label: "Stairway to Heaven (A4): 15 to the absorbed element's members", per: 'burst',
        count: 1, recipients: 'absorbed', scaling: 'none', amount: 15,
        citation: 'venti/asc.go:19', absorbs: ['pyro', 'hydro', 'electro', 'cryo'] },
    ] }),
    member({ build_id: 'kl', name: 'Klee', refunds: [
      { label: 'C6: 3 flat energy to every other member, 3 times a burst', per: 'burst',
        count: 3, recipients: 'others', scaling: 'none', amount: 3, citation: 'klee/burst.go:92',
        requires_constellation: 6, basis: 'kit' },
    ] }),
    member({ build_id: 'tg', name: 'Tartaglia', element: 'hydro', refunds: [
      { label: 'C2: 4 flat energy, per trigger', per: 'cast', count: 1, recipients: 'self',
        scaling: 'none', amount: 4, citation: 'tartaglia/riptide.go:268',
        requires_constellation: 2, basis: 'fight', condition: 'Fires only on a kill.' },
      { label: 'C9: 5 flat energy, a skill cast', per: 'cast', count: 1, recipients: 'team',
        scaling: 'none', amount: 5, citation: 'made up for the toggle', requires_constellation: 1,
        basis: 'assumption', condition: 'Assumes the mark is up.' },
    ] }),
  ],
};

function render() {
  TestBed.configureTestingModule({ imports: [FormulaPanel] });
  const service = TestBed.inject(FormulaEstimateService);
  service.ensureTarget('xl', HITS as never);
  service.teamEnergy.set(DATA);
  const fixture = TestBed.createComponent(FormulaPanel);
  fixture.componentRef.setInput('hits', HITS);
  fixture.detectChanges();
  return { el: fixture.nativeElement as HTMLElement, fixture, service };
}

const text = (el: HTMLElement) => el.querySelector('.energy')?.textContent?.replace(/\s+/g, ' ') ?? '';
const box = (el: HTMLElement, label: string) => ([...el.querySelectorAll('.energy input[type=number]')] as HTMLInputElement[])
  .find((b) => b.closest('label')?.textContent?.includes(label))!;

describe('FormulaPanel energy small calls', () => {
  it('the drip is caught on field by an on-field subject, editable', () => {
    const { el, service } = render();
    const drip = box(el, 'Enemy particles caught by');
    expect(drip.value).toBe('100');
    expect(text(el)).toContain('Default: 100% — on field, it lands on them.');
    drip.value = '40';
    drip.dispatchEvent(new Event('change'));
    expect(service.energy().onField['drip']).toBeCloseTo(0.4, 12);
  });

  it("Venti's absorbed element defaults to Pyro here and reaches a Pyro subject; editable", () => {
    const { el, fixture, service } = render();
    expect(text(el)).toContain('Default (pyro)');
    expect(text(el)).toContain("the first of gcsim's order (pyro, hydro, electro, cryo) a teammate carries");
    const select = [...el.querySelectorAll('.energy select')].find(
      (s) => s.closest('label')?.textContent?.includes('the element absorbed')) as HTMLSelectElement;
    select.value = 'hydro';
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(service.energy().absorbed[refundKey('vt', 1)]).toBe('hydro');
    expect(text(el)).toContain('Xiangling is not of the absorbed element.');
    select.value = 'default';
    select.dispatchEvent(new Event('change'));
    expect(service.energy().absorbed).toEqual({});
  });

  it("lists a fight refund with its reason, and an assumption one as a toggle, off", () => {
    const { el, fixture, service } = render();
    const shown = text(el);
    expect(shown).toContain('C2: 4 flat energy, per trigger: not counted — Fires only on a kill.');
    expect(shown).toContain('C9: 5 flat energy, a skill cast: count it — off by default');
    expect(shown).toContain('Assumes: Assumes the mark is up.');
    expect(shown).toContain('C6: 3 flat energy to every other member, 3 times a burst: times per burst');
    const toggle = [...el.querySelectorAll('.energy input[type=checkbox]')].find(
      (b) => b.closest('label')?.textContent?.includes('count it')) as HTMLInputElement;
    toggle.checked = true;
    toggle.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(service.energy().refundToggles[refundKey('tg', 1)]).toBe(true);
    expect(text(el)).toContain('Counted, on its assumption: Assumes the mark is up.');
  });
});
