import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import {
  FormulaEstimateService,
  type TeamEnergyData,
} from '../../pages/optimize/formula-estimate.service';
import { FormulaPanel } from './formula-panel';

/**
 * Task 14 — the panel's Energy section (DESIGN §2.10): the requirement, every assumption with
 * its default and citation, each editable, and Wait as the default mode (owner, 2026-11-15).
 */

const HITS = [{ talent: 'elemental_burst', label: 'Pyronado DMG', index: 0, multiplier: 1.4,
  hits: 1, exclusive: false, scaling_stat: 'atk', extra_terms: [] }];

const DATA: TeamEnergyData = {
  gcsim_commit: 'b107b5dc',
  drip: { particles: 1, interval_seconds: 599.5 / 60, config: 'energy every', citation: 'drip cite' },
  members: [
    { build_id: 'xl', name: 'Xiangling', element: 'pyro', burst_energy_cost: 80,
      burst_cooldown: 20, is_subject: true, status: 'curated', refunds: [],
      sources: [{ label: 'Guoba Attack', per: 'cast', particles: 4, collector: 'active',
        citation: 'gcsim xiangling/skill.go:79', on: 'skill' }] },
    { build_id: 'xq', name: 'Xingqiu', element: 'hydro', burst_energy_cost: 80,
      burst_cooldown: 20, is_subject: false, status: 'curated', refunds: [],
      sources: [{ label: 'Rainscreen', per: 'cast', particles: 5, collector: 'caster',
        citation: 'gcsim xingqiu/skill.go:99', on: 'skill' }] },
    { build_id: 'rd', name: 'Raiden Shogun', element: 'electro', burst_energy_cost: 90,
      burst_cooldown: 18, is_subject: false, status: 'no_particle_data', refunds: [], sources: [] },
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

describe('FormulaPanel energy', () => {
  it('states the requirement from the closed form', () => {
    const { el } = render();
    // Guoba 4 × 3 × 0.7 off field (party of three) + Xingqiu 5 × 1 × 0.7 + the drip
    // 20 s / 9.99 s × 2 × 0.7 = 8.4 + 3.5 + 2.8023 = 14.7023; 80 / that = 544.1 %.
    const raw = 4 * 3 * 0.7 + 5 * 0.7 + (20 / (599.5 / 60)) * 2 * 0.7;
    expect(text(el)).toContain(`${(80 / raw * 100).toFixed(1)}%`);
    expect(text(el)).toContain(raw.toFixed(2));
    expect(text(el)).toContain("Default: Xiangling's burst cooldown (game data).");
    expect(text(el)).toContain('gcsim xiangling/skill.go:79');
    expect(text(el)).toContain('No particle count is curated for Raiden Shogun');
  });

  it('defaults to waiting (owner, 2026-11-15) and offers skip and report only', () => {
    const { el, fixture, service } = render();
    const select = el.querySelector('.energy select') as HTMLSelectElement;
    const options = [...select.options].map((o) => o.value);
    expect(options).toEqual(['off', 'skip', 'wait']);
    expect(service.energy().mode).toBe('wait');
    expect(select.options[select.selectedIndex].value).toBe('wait');
    expect(text(el)).toContain('Default: wait');
    select.value = 'off';
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(service.energy().mode).toBe('off');
  });

  it('takes an edit on change, and refuses an emptied box', () => {
    const { el, fixture, service } = render();
    const boxes = [...el.querySelectorAll('.energy input[type=number]')] as HTMLInputElement[];
    const rotation = boxes[0];
    rotation.value = '';
    rotation.dispatchEvent(new Event('change'));
    expect(rotation.value).toBe('20');
    expect(service.energy().rotationSeconds).toBeNull();
    rotation.value = '25';
    rotation.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(service.energy().rotationSeconds).toBe(25);
    // Raiden's manual particles: entered, then counted.
    const manual = boxes.find((b) => b.closest('label')?.textContent?.includes('Particles per rotation'))!;
    manual.value = '6';
    manual.dispatchEvent(new Event('change'));
    expect(service.energy().manual).toEqual({ rd: 6 });
  });

  it('turning the drip off steps waiting back to skipping', () => {
    const { el, fixture, service } = render();
    service.setEnergy({ mode: 'wait' });
    fixture.detectChanges();
    const drip = el.querySelector('.energy input[type=checkbox]') as HTMLInputElement;
    drip.checked = false;
    drip.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(service.energy()).toMatchObject({ drip: false, mode: 'skip' });
    const wait = [...el.querySelectorAll('.energy option')].find(
      (o) => (o as HTMLOptionElement).value === 'wait') as HTMLOptionElement;
    expect(wait.disabled).toBe(true);
  });

  it('names every control', () => {
    const { el } = render();
    for (const control of el.querySelectorAll('.energy select, .energy input')) {
      expect(control.closest('label')?.textContent?.trim().length ?? 0).toBeGreaterThan(0);
    }
  });

  it('shows a summon, a Favonius holder and a refund, each editable and cited', () => {
    TestBed.configureTestingModule({ imports: [FormulaPanel] });
    const service = TestBed.inject(FormulaEstimateService);
    service.ensureTarget('rd', HITS as never);
    service.teamEnergy.set({
      ...DATA,
      members: [
        { build_id: 'rd', name: 'Raiden Shogun', element: 'electro', burst_energy_cost: 90,
          burst_cooldown: 18, is_subject: true, status: 'curated', energy_recharge: 1.3,
          crit_rate: 0.4,
          sources: [{ label: 'Eye', per: 'second', particles: 0.5, chance: 0.5, interval: 1,
            max_seconds: 25, collector: 'active', citation: 'raiden/skill.go:93', on: 'skill' }],
          refunds: [{ label: 'Musou Isshin', per: 'burst', count: 5, recipients: 'team',
            scaling: 'raiden_a4', amount: 2.4, citation: 'raiden/burst.go:99' }],
          favonius: { weapon: 'Favonius Lance', refinement: 3, chance: 0.8, cooldown_seconds: 9,
            particles: 3, citation: 'weapons/common/favonius.go:44' } },
        { build_id: 'fs', name: 'Fischl', element: 'electro', burst_energy_cost: 60,
          burst_cooldown: 15, is_subject: false, status: 'curated', refunds: [],
          sources: [{ label: 'Oz (burst)', per: 'second', particles: 0.67, chance: 0.67,
            interval: 1, max_seconds: 10, collector: 'active', citation: 'fischl/burst.go:115',
            on: 'burst' }] },
      ],
    });
    const fixture = TestBed.createComponent(FormulaPanel);
    fixture.componentRef.setInput('hits', HITS);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const shown = text(el);
    expect(shown).toContain('50% chance of a particle a hit');
    expect(shown).toContain('67% chance of a particle a hit · counted per burst');
    expect(shown).toContain('Favonius Lance R3: 80% a crit, every 9 s at most, 3 clear particles');
    expect(shown).toContain('weapons/common/favonius.go:44');
    expect(shown).toContain('Musou Isshin: times per burst (2.4 flat each)');
    expect(shown).toContain('raiden/burst.go:99');
    const boxes = [...el.querySelectorAll('.energy input[type=number]')] as HTMLInputElement[];
    const find = (label: string) => boxes.find(
      (b) => b.closest('label')?.textContent?.includes(label))!;
    const hits = find('Hits on field per rotation');
    hits.value = '12';
    hits.dispatchEvent(new Event('change'));
    expect(service.energy().favoniusHits).toEqual({ rd: 12 });
    const restorations = find('Musou Isshin');
    restorations.value = '3';
    restorations.dispatchEvent(new Event('change'));
    expect(service.energy().refundCounts).toEqual({ 'rd:refund:0': 3 });
    const bursts = find('Bursts per rotation');
    bursts.value = '2';
    bursts.dispatchEvent(new Event('change'));
    expect(Object.values(service.energy().bursts)).toContain(2);
  });
});
