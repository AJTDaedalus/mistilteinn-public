import { describe, expect, it } from 'vitest';

import {
  energyAt,
  energyFactors,
  flatEnergyAt,
  flatSourceAt,
  raidenA4Multiplier,
  rawParticleEnergy,
  requiredEnergyRecharge,
  type FormulaEnergy,
} from './formula-energy';
import {
  DEFAULT_ENERGY,
  defaultFavoniusHits,
  energyInput,
  favoniusProcs,
  refundSource,
  subjectHitsOf,
  type TeamEnergyData,
} from '../pages/optimize/formula-estimate.service';

/**
 * The follow-ups to #392 (owner rulings 2026-11-15, DECISIONS §48): Wait by default, summons
 * from a cited chance and cadence, Favonius procs and flat refunds. gcsim's own events for the
 * same terms are held in `scripts/verify-formula-recipe.mjs` and
 * `backend/tests/unit/test_formula_energy_summon_sample.py`.
 */

type Member = TeamEnergyData['members'][number];

const raiden = (over: Partial<Member> = {}): Member => ({
  build_id: 'rd', name: 'Raiden Shogun', element: 'electro', burst_energy_cost: 90,
  burst_cooldown: 18, is_subject: true, status: 'curated',
  sources: [{ label: 'Eye', per: 'second', particles: 0.5, chance: 0.5, interval: 1,
    max_seconds: 25, collector: 'active', citation: 'eye', on: 'skill' }],
  refunds: [{ label: 'Musou Isshin', per: 'burst', count: 5, recipients: 'team',
    scaling: 'raiden_a4', amount: 2.4, citation: 'burst.go' }],
  favonius: { weapon: 'Favonius Lance', refinement: 3, chance: 0.8, cooldown_seconds: 9,
    particles: 3, citation: 'favonius.go' },
  energy_recharge: 2.326268198, crit_rate: 0.35,
  ...over,
});

const fischl = (over: Partial<Member> = {}): Member => ({
  build_id: 'fs', name: 'Fischl', element: 'electro', burst_energy_cost: 60,
  burst_cooldown: 15, is_subject: false, status: 'curated',
  sources: [
    { label: 'Oz (skill)', per: 'second', particles: 0.67, chance: 0.67, interval: 1,
      max_seconds: 10, collector: 'active', citation: 'oz', on: 'skill' },
    { label: 'Oz (burst)', per: 'second', particles: 0.67, chance: 0.67, interval: 1,
      max_seconds: 10, collector: 'active', citation: 'oz', on: 'burst' },
  ],
  refunds: [], favonius: null, energy_recharge: 1.3, crit_rate: 0.6,
  ...over,
});

const sara = (over: Partial<Member> = {}): Member => ({
  build_id: 'sr', name: 'Kujou Sara', element: 'electro', burst_energy_cost: 80,
  burst_cooldown: 20, is_subject: false, status: 'curated',
  sources: [{ label: 'Ambush', per: 'cast', particles: 3, collector: 'caster', citation: 's', on: 'skill' }],
  refunds: [{ label: 'Decorum', per: 'cast', count: 1, recipients: 'team', scaling: 'per_er',
    amount: 1.2, citation: 'asc.go' }],
  favonius: { weapon: 'Favonius Warbow', refinement: 5, chance: 1, cooldown_seconds: 6,
    particles: 3, citation: 'favonius.go' },
  energy_recharge: 2.5, crit_rate: 0.2,
  ...over,
});

const data = (members: Member[]): TeamEnergyData => ({
  gcsim_commit: 'b107b5dc', members,
  drip: { particles: 1, interval_seconds: 599.5 / 60, config: 'energy every', citation: 'drip' },
});

describe('Wait is the default (owner, 2026-11-15)', () => {
  it('DEFAULT_ENERGY prices ER by waiting, and steps back to skip with the drip off', () => {
    expect(DEFAULT_ENERGY.mode).toBe('wait');
    expect(energyInput(data([raiden()]), DEFAULT_ENERGY)!.mode).toBe('wait');
    expect(energyInput(data([raiden()]), { ...DEFAULT_ENERGY, drip: false })!.mode).toBe('skip');
  });
});

describe("Raiden's A4 and flat sources (gcsim raiden/asc.go:42, sara/asc.go:32)", () => {
  it('counts whole percents of ER above 100 %, as gcsim truncates int(er * 100)', () => {
    // The committed sample: Raiden at 232.6268 % restores 2.4 × 1.792 = 4.3008 a proc.
    expect(2.4 * raidenA4Multiplier(2.326268198)).toBeCloseTo(4.3008, 12);
    expect(raidenA4Multiplier(1.0099)).toBe(1);
    expect(raidenA4Multiplier(0.9)).toBe(1);
    expect(raidenA4Multiplier(1.01)).toBeCloseTo(1.006, 12);
  });

  it('a flat source is never multiplied by ER unless its giver is the subject', () => {
    const none = { key: 'k', label: 'l', energy: 16, scaling: 'none' as const, citation: '' };
    expect(flatSourceAt(none, 3)).toBe(16);
    expect(flatSourceAt({ ...none, scaling: 'per_er' }, 1.5)).toBeCloseTo(24, 12);
  });
});

describe('summons, refunds and Favonius through energyInput', () => {
  it("counts Oz from the burst per burst and from the skill per cast, each capped at 10 s", () => {
    const team = data([raiden({ favonius: null, refunds: [] }), fischl()]);
    const input = energyInput(team, { ...DEFAULT_ENERGY, casts: { fs: 1 }, bursts: { fs: 2 } })!;
    const by = Object.fromEntries(input.sources.map((s) => [s.key, s]));
    expect(by['fs:0'].particles).toBeCloseTo(6.7, 12);
    expect(by['fs:1'].particles).toBeCloseTo(13.4, 12);
    // Raiden's Eye: KQM's one strike a second for 18 s of an 18 s rotation, half a particle each.
    expect(by['rd:0'].particles).toBeCloseTo(9, 12);
  });

  it("Raiden's refund reaches every member, at her own ER when she is the subject", () => {
    const input = energyInput(data([raiden()]), DEFAULT_ENERGY)!;
    const [flat] = input.flatSources!;
    expect(flat.energy).toBeCloseTo(12, 12); // 2.4 × 5 restorations × 1 burst
    expect(flat.scaling).toBe('raiden_a4');
    const model: FormulaEnergy = { ...input, baseEnergyRecharge: 1 };
    expect(flatEnergyAt(model, 2.326268198)).toBeCloseTo(5 * 4.3008, 12);
  });

  it("a teammate's ER-scaled refund is applied at their build's ER, a constant", () => {
    const sub = raiden({ refunds: [], favonius: null });
    const flat = refundSource(sara(), 0, DEFAULT_ENERGY)!;
    expect(flat.scaling).toBe('none');
    expect(flat.energy).toBeCloseTo(1.2 * 2.5, 12);
    const viaRaiden = refundSource(raiden({ is_subject: false }), 0, DEFAULT_ENERGY)!;
    expect(viaRaiden.energy).toBeCloseTo(12 * raidenA4Multiplier(2.326268198), 12);
    expect(energyInput(data([sub, sara()]), DEFAULT_ENERGY)!.flatSources).toHaveLength(1);
  });

  it("a teammate's self refund does not reach the subject; an unavailable one counts nothing", () => {
    const jean: Member = { ...sara(), build_id: 'jn', name: 'Jean',
      refunds: [{ label: 'A4', per: 'burst', count: 1, recipients: 'self', scaling: 'none',
        amount: 16, citation: 'jean' }] };
    expect(refundSource(jean, 0, DEFAULT_ENERGY)).toBeNull();
    expect(refundSource({ ...jean, is_subject: true }, 0, DEFAULT_ENERGY)!.energy).toBe(16);
    const short = sara({ refunds: [{ ...sara().refunds![0], unavailable: 'needs ascension 4' }] });
    expect(refundSource(short, 0, DEFAULT_ENERGY)).toBeNull();
    // A count of 0 turns it off.
    expect(refundSource(sara(), 0, { ...DEFAULT_ENERGY, refundCounts: { 'sr:refund:0': 0 } })!
      .energy).toBe(0);
  });

  it('Favonius procs: min(rotation ÷ cooldown, hits × crit rate × chance)', () => {
    expect(favoniusProcs(raiden(), 20, 18)).toBeCloseTo(2, 12); // cooldown-bound: 18 / 9
    expect(favoniusProcs(raiden(), 2, 18)).toBeCloseTo(2 * 0.35 * 0.8, 12);
    expect(favoniusProcs(fischl(), 50, 18)).toBe(0);
    // Default hits: the subject's direct-hit rows; a teammate's skill casts.
    expect(defaultFavoniusHits(raiden(), DEFAULT_ENERGY, 17)).toBe(17);
    expect(defaultFavoniusHits(sara(), { ...DEFAULT_ENERGY, casts: { sr: 2 } }, 17)).toBe(2);
  });

  it("the subject's Favonius is caught on field, a teammate's off field (gcsim favonius.go:44)", () => {
    const sub = raiden({ refunds: [] });
    const input = energyInput(data([sub, sara()]), DEFAULT_ENERGY, 20)!;
    const by = Object.fromEntries(input.sources.map((s) => [s.key, s]));
    expect(by['rd:favonius'].element).toBeNull();
    expect(by['rd:favonius'].onFieldShare).toBe(1);
    expect(by['rd:favonius'].particles).toBeCloseTo(3 * 2, 12);
    expect(by['sr:favonius'].onFieldShare).toBe(0);
    expect(by['sr:favonius'].particles).toBeCloseTo(3 * 1 * 0.2 * 1, 12);
  });

  it('subjectHitsOf counts direct-hit rows only', () => {
    expect(subjectHitsOf([{ count: 10 }, { count: 4, reaction: 'swirl' }, { count: 2, proc: {} },
      { count: 3 }])).toBe(13);
  });
});

describe('the requirement with an ER-scaled refund, and monotonicity', () => {
  const model = (): FormulaEnergy => ({
    ...energyInput(data([raiden({ favonius: null })]), DEFAULT_ENERGY)!, baseEnergyRecharge: 1,
  });

  it('is the least ER whose energy funds the burst', () => {
    const m = model();
    const need = requiredEnergyRecharge(m)!;
    expect(energyAt(m, need)).toBeGreaterThanOrEqual(m.cost - 1e-9);
    expect(energyAt(m, need - 1e-6)).toBeLessThan(m.cost);
    // Without the A4 it is the closed form: (cost − flat) / raw.
    const flat = { ...m, flatSources: m.flatSources!.map((s) => ({ ...s, scaling: 'none' as const })) };
    expect(requiredEnergyRecharge(flat)).toBeCloseTo((90 - 12) / rawParticleEnergy(m), 12);
  });

  it("both priced factors stay non-decreasing in ER (the search's bound)", () => {
    for (const mode of ['skip', 'wait'] as const) {
      const m = { ...model(), mode };
      let last = -Infinity;
      for (let er = 0; er <= 3; er += 0.0037) {
        const f = energyFactors(m, er);
        const v = f.burst * f.all;
        expect(v).toBeGreaterThanOrEqual(last - 1e-12);
        last = v;
      }
    }
  });
});
