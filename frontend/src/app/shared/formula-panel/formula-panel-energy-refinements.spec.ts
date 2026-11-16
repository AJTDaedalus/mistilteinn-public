import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import {
  FormulaEstimateService,
  type TeamEnergyData,
} from '../../pages/optimize/formula-estimate.service';
import { FormulaPanel } from './formula-panel';

/**
 * The owner's refinements of 2026-11-15 in the panel's Energy section (DECISIONS §49): the
 * on-field toggle, Electro resonance's procs, the per-candidate Favonius note and Yae's
 * shared ICD — each shown with its default and citation, each editable.
 */

const HITS = [{ talent: 'elemental_burst', label: '1-Hit DMG', index: 0, multiplier: 0.8,
  hits: 1, exclusive: false, scaling_stat: 'atk', extra_terms: [] }];

const DATA: TeamEnergyData = {
  gcsim_commit: 'b107b5dc',
  drip: { particles: 1, interval_seconds: 599.5 / 60, config: 'energy every', citation: 'drip cite' },
  resonance: {
    name: 'High Voltage', element: 'electro', particles: 1, cooldown_seconds: 5,
    trigger_elements: ['pyro', 'cryo', 'hydro', 'dendro'], team_can_trigger: true,
    note: 'One Electro particle a qualifying reaction.', citation: 'gcsim pkg/simulation/setup.go:185',
    default_procs_per_second: 0.12, default_note: 'Default procs: 3 per 25 s rotation.',
  },
  members: [
    { build_id: 'rd', name: 'Raiden Shogun', element: 'electro', burst_energy_cost: 90,
      burst_cooldown: 18, is_subject: true, status: 'curated', energy_recharge: 1.3,
      crit_rate: 0.4, refunds: [],
      sources: [{ label: 'Eye', per: 'second', particles: 0.5, chance: 0.5, interval: 1,
        max_seconds: 25, collector: 'active', citation: 'raiden/skill.go:93', on: 'skill',
        shared_icd: false }],
      favonius: { weapon: 'Favonius Lance', refinement: 3, chance: 0.8, cooldown_seconds: 9,
        particles: 3, citation: 'weapons/common/favonius.go:44' } },
    { build_id: 'ym', name: 'Yae Miko', element: 'electro', burst_energy_cost: 90,
      burst_cooldown: 22, is_subject: false, status: 'curated', refunds: [],
      sources: [{ label: 'Sesshou Sakura', per: 'second', particles: 1, interval: 2.933333,
        max_seconds: 25, collector: 'active', citation: 'yaemiko/skill.go:43,46,47',
        on: 'skill', shared_icd: true, note: "KQM's library disagrees." }] },
    { build_id: 'xq', name: 'Xingqiu', element: 'hydro', burst_energy_cost: 80,
      burst_cooldown: 20, is_subject: false, status: 'curated', refunds: [],
      sources: [{ label: 'Rainscreen', per: 'cast', particles: 5, collector: 'caster',
        citation: 'xingqiu/skill.go:99', on: 'skill', shared_icd: false }] },
    { build_id: 'zl', name: 'Zhongli', element: 'geo', burst_energy_cost: 40,
      burst_cooldown: 12, is_subject: false, status: 'curated', refunds: [], sources: [] },
  ],
};

function render() {
  TestBed.configureTestingModule({ imports: [FormulaPanel] });
  const service = TestBed.inject(FormulaEstimateService);
  service.ensureTarget('rd', HITS as never);
  service.teamEnergy.set(DATA);
  const fixture = TestBed.createComponent(FormulaPanel);
  fixture.componentRef.setInput('hits', HITS);
  fixture.detectChanges();
  return { el: fixture.nativeElement as HTMLElement, fixture, service };
}

const text = (el: HTMLElement) => el.querySelector('.energy')?.textContent?.replace(/\s+/g, ' ') ?? '';
const boxes = (el: HTMLElement) => [...el.querySelectorAll('.energy input[type=number]')] as HTMLInputElement[];
const box = (el: HTMLElement, label: string, nth = 0) => boxes(el).filter(
  (b) => b.closest('label')?.textContent?.includes(label))[nth];

describe('FormulaPanel energy refinements', () => {
  it("reads Raiden's burst attacks as on field, and catches the summons on field by default", () => {
    const { el } = render();
    const shown = text(el);
    expect(shown).toContain('Raiden Shogun on field');
    expect(shown).toContain('From the rows (yes)');
    // Her Eye, her own Favonius, Yae's totems, the resonance: 100 %; Xingqiu's own: 0 %.
    const shares = boxes(el).filter((b) => b.closest('label')?.textContent?.includes('Caught by'));
    expect(shares.map((b) => b.value)).toEqual(['100', '100', '100', '0', '100']);
  });

  it('the toggle overrides the rows', () => {
    const { el, fixture, service } = render();
    const select = [...el.querySelectorAll('.energy select')].find(
      (s) => s.closest('label')?.textContent?.includes('on field')) as HTMLSelectElement;
    select.value = 'off';
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(service.energy().subjectOnField).toBe(false);
    expect(box(el, 'Caught by').value).toBe('0');
    select.value = 'default';
    select.dispatchEvent(new Event('change'));
    expect(service.energy().subjectOnField).toBeNull();
  });

  it("shows Electro resonance at the samples' rate (§50), editable, cited", () => {
    const { el, service } = render();
    const shown = text(el);
    expect(shown).toContain('Electro resonance (High Voltage)');
    expect(shown).toContain('at most one every 5 s');
    expect(shown).toContain('Default: 0.12 a second of rotation, at most one every 5 s.');
    expect(shown).toContain('Default procs: 3 per 25 s rotation.');
    expect(shown).toContain('gcsim pkg/simulation/setup.go:185');
    const procs = box(el, 'Procs per rotation');
    expect(Number(procs.value)).toBeCloseTo(0.12 * 18, 9);
    procs.value = '3';
    procs.dispatchEvent(new Event('change'));
    expect(service.energy().resonanceProcs).toBe(3);
  });

  it("says the optimized holder's Favonius moves with each candidate's crit, and Yae's ICD is shared", () => {
    const { el } = render();
    const shown = text(el);
    expect(shown).toContain("the estimate prices each candidate's own crit rate");
    expect(shown).toContain('One particle ICD shared by every totem');
    expect(shown).toContain("KQM's library disagrees.");
    expect(shown).not.toContain('Not counted unless entered: constellation refunds, Electro');
  });
});
