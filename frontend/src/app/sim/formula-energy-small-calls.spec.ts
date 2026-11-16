import { describe, expect, it } from 'vitest';

import {
  absorbedElement,
  DEFAULT_ENERGY,
  energyInput,
  refundKey,
  refundSource,
  resonanceProcs,
  type TeamEnergyData,
} from '../pages/optimize/formula-estimate.service';

/**
 * The owner's three small calls of 2026-11-15 (DECISIONS §50, DESIGN §2.11 "Small calls"):
 * Electro resonance at the samples' rate, the drip caught on field by an on-field subject, and
 * Venti's absorbed-element 15 with the constellation refunds gcsim implements as `AddEnergy`.
 * gcsim's own events for these terms are held in `scripts/verify-formula-recipe.mjs` and
 * `backend/tests/unit/test_formula_energy_small_calls*.py`.
 */

type Member = TeamEnergyData['members'][number];
type Refund = NonNullable<Member['refunds']>[number];

const member = (over: Partial<Member>): Member => ({
  build_id: 'x', name: 'X', element: 'pyro', burst_energy_cost: 80, burst_cooldown: 20,
  is_subject: false, status: 'curated', sources: [], refunds: [], favonius: null,
  energy_recharge: 1.2, crit_rate: 0.5, ...over,
});

const HIGH_VOLTAGE = {
  name: 'High Voltage', element: 'electro', particles: 1, cooldown_seconds: 5,
  trigger_elements: ['pyro', 'cryo', 'hydro', 'dendro'], team_can_trigger: true,
  note: 'note', citation: 'gcsim setup.go:181-207; KQM',
  default_procs_per_second: 0.12, default_note: '3 per 25 s rotation (samples)',
};

const data = (members: Member[], resonance: TeamEnergyData['resonance'] = null): TeamEnergyData => ({
  gcsim_commit: 'b107b5dc', members, resonance,
  drip: { particles: 1, interval_seconds: 599.5 / 60, config: 'energy every', citation: 'drip' },
});

const bySource = (input: { sources: { key: string }[] }) =>
  Object.fromEntries(input.sources.map((s) => [s.key, s])) as unknown as Record<string, { particles: number; onFieldShare: number }>;

// ── 1. Electro resonance at the samples' rate ────────────────────────────────────────────────

describe("Electro resonance's default: the samples' rate, under the ceiling", () => {
  it('defaults to 0.12 a second of rotation: 3 in 25 s, 2.16 in 18 s', () => {
    expect(resonanceProcs(HIGH_VOLTAGE, DEFAULT_ENERGY, 25)).toBeCloseTo(3, 12);
    expect(resonanceProcs(HIGH_VOLTAGE, DEFAULT_ENERGY, 18)).toBeCloseTo(2.16, 12);
  });

  it('is still capped by one every cooldown, and still editable', () => {
    const fast = { ...HIGH_VOLTAGE, default_procs_per_second: 1 };
    expect(resonanceProcs(fast, DEFAULT_ENERGY, 25)).toBe(5);
    expect(resonanceProcs(HIGH_VOLTAGE, { ...DEFAULT_ENERGY, resonanceProcs: 4 }, 25)).toBe(4);
    expect(resonanceProcs(HIGH_VOLTAGE, { ...DEFAULT_ENERGY, resonanceProcs: 9 }, 25)).toBe(5);
  });

  it('is none when no member can react with Electro', () => {
    expect(resonanceProcs({ ...HIGH_VOLTAGE, team_can_trigger: false }, DEFAULT_ENERGY, 25)).toBe(0);
  });

  it('flows into the model as the resonance source', () => {
    const subject = member({ build_id: 'rd', element: 'electro', is_subject: true, burst_cooldown: 25 });
    const team = data([subject, member({ build_id: 'fs', element: 'electro' }),
      member({ build_id: 'xq', element: 'hydro' }), member({ build_id: 'bn' })], HIGH_VOLTAGE);
    expect(bySource(energyInput(team, DEFAULT_ENERGY)!)['resonance:electro'].particles)
      .toBeCloseTo(3, 12);
  });
});

// ── 2. The drip follows on field ─────────────────────────────────────────────────────────────

describe('the drip is caught on field by an on-field subject (gcsim DistributeParticle)', () => {
  const team = () => data([member({ build_id: 's', is_subject: true }), member({ build_id: 't' })]);

  it('defaults to 100 % on field when the subject is on field, 0 % otherwise', () => {
    const on = energyInput(team(), DEFAULT_ENERGY, 0, true)!;
    const off = energyInput(team(), DEFAULT_ENERGY, 0, false)!;
    expect(bySource(on)['drip'].onFieldShare).toBe(1);
    expect(on.drip!.onFieldShare).toBe(1);
    expect(bySource(off)['drip'].onFieldShare).toBe(0);
    expect(off.drip!.onFieldShare).toBe(0);
    // The toggle overrides the rows.
    expect(energyInput(team(), { ...DEFAULT_ENERGY, subjectOnField: true }, 0, false)!
      .drip!.onFieldShare).toBe(1);
  });

  it('keeps an entered share', () => {
    const input = energyInput(team(), { ...DEFAULT_ENERGY, onField: { drip: 0.25 } }, 0, true)!;
    expect(input.drip!.onFieldShare).toBe(0.25);
    expect(bySource(input)['drip'].onFieldShare).toBe(0.25);
  });
});

// ── 3. Venti's absorbed element and constellation refunds ───────────────────────────────────

const ABSORBED: Refund = {
  label: "Stairway to Heaven (A4): 15 to the absorbed element's members", per: 'burst', count: 1,
  recipients: 'absorbed', scaling: 'none', amount: 15, citation: 'venti/asc.go:19',
  absorbs: ['pyro', 'hydro', 'electro', 'cryo'], basis: 'kit',
};
const SELF15: Refund = {
  label: 'Stairway to Heaven (A4): 15 energy back', per: 'burst', count: 1, recipients: 'self',
  scaling: 'none', amount: 15, citation: 'venti/asc.go:13',
};
const venti = (over: Partial<Member> = {}) => member({
  build_id: 'vt', name: 'Venti', element: 'anemo', refunds: [SELF15, ABSORBED], ...over,
});

describe("Venti's A4: 15 to every member of the absorbed element", () => {
  it("defaults to the first of gcsim's order (Pyro, Hydro, Electro, Cryo) a teammate carries", () => {
    const members = [venti(), member({ build_id: 'xq', element: 'hydro' }),
      member({ build_id: 'xl', element: 'pyro' })];
    expect(absorbedElement(members[0], ABSORBED, DEFAULT_ENERGY, members)).toBe('pyro');
    const noPyro = [venti(), member({ build_id: 'xq', element: 'hydro' }),
      member({ build_id: 'ay', element: 'cryo' })];
    expect(absorbedElement(noPyro[0], ABSORBED, DEFAULT_ENERGY, noPyro)).toBe('hydro');
    const none = [venti(), member({ build_id: 'zl', element: 'geo' })];
    expect(absorbedElement(none[0], ABSORBED, DEFAULT_ENERGY, none)).toBeNull();
  });

  it('reaches a subject of the absorbed element as 15 flat a Venti burst, and no one else', () => {
    const subject = member({ build_id: 'xl', element: 'pyro', is_subject: true });
    const members = [venti(), subject, member({ build_id: 'xq', element: 'hydro' })];
    const ctx = { members, subjectOnField: false, rotationSeconds: 20 };
    const flat = refundSource(members[0], 1, DEFAULT_ENERGY, ctx)!;
    expect(flat.energy).toBe(15);
    expect(flat.scaling).toBe('none');
    expect(refundSource(members[0], 1, { ...DEFAULT_ENERGY, bursts: { vt: 2 } }, ctx)!.energy).toBe(30);
    // A Hydro subject is not of the absorbed element (Pyro first in gcsim's order).
    const hydro = [venti(), member({ build_id: 'xl', element: 'pyro' }),
      member({ build_id: 'xq', element: 'hydro', is_subject: true })];
    expect(refundSource(hydro[0], 1, DEFAULT_ENERGY, { ...ctx, members: hydro })).toBeNull();
    // …unless the user says the burst absorbed Hydro; or none at all.
    const key = refundKey('vt', 1);
    expect(refundSource(hydro[0], 1, { ...DEFAULT_ENERGY, absorbed: { [key]: 'hydro' } },
      { ...ctx, members: hydro })!.energy).toBe(15);
    expect(refundSource(members[0], 1, { ...DEFAULT_ENERGY, absorbed: { [key]: 'none' } }, ctx))
      .toBeNull();
  });

  it('lands in the model beside his own 15, which stays his', () => {
    const subject = member({ build_id: 'xl', element: 'pyro', is_subject: true });
    const input = energyInput(data([venti(), subject]), DEFAULT_ENERGY)!;
    expect(input.flatSources!.map((s) => s.key)).toEqual([refundKey('vt', 1)]);
    const own = energyInput(data([venti({ is_subject: true }), subject]), DEFAULT_ENERGY)!;
    expect(own.flatSources!.map((s) => [s.key, s.energy])).toEqual([[refundKey('vt', 0), 15]]);
  });
});

describe('constellation refunds: recipients, bases and rates', () => {
  const giver = (refund: Refund, over: Partial<Member> = {}) =>
    member({ build_id: 'g', name: 'Giver', element: 'cryo', refunds: [refund], ...over });
  const subject = member({ build_id: 's', element: 'pyro', is_subject: true });
  const ctx = (members: Member[], on = false) => ({ members, subjectOnField: on, rotationSeconds: 20 });

  it('`others` reaches every member but the giver', () => {
    const r: Refund = { label: 'C6', per: 'burst', count: 3, recipients: 'others', scaling: 'none',
      amount: 3, citation: 'klee/burst.go:92', requires_constellation: 6 };
    expect(refundSource(giver(r), 0, DEFAULT_ENERGY, ctx([giver(r), subject]))!.energy).toBe(9);
    expect(refundSource(giver(r, { is_subject: true }), 0, DEFAULT_ENERGY,
      ctx([giver(r, { is_subject: true })]))).toBeNull();
  });

  it('`active` reaches the subject its on-field share: 1 on field, 0 off, editable', () => {
    const r: Refund = { label: 'C1', per: 'cast', count: 1, recipients: 'active', scaling: 'none',
      amount: 6, citation: 'chevreuse/cons.go:50', basis: 'kit' };
    const team = [giver(r), subject];
    expect(refundSource(team[0], 0, DEFAULT_ENERGY, ctx(team, true))!.energy).toBe(6);
    expect(refundSource(team[0], 0, DEFAULT_ENERGY, ctx(team, false))).toBeNull();
    expect(refundSource(team[0], 0, { ...DEFAULT_ENERGY, onField: { [refundKey('g', 0)]: 0.5 } },
      ctx(team, false))!.energy).toBe(3);
  });

  it('a `fight` refund is never counted; an `assumption` one only when switched on', () => {
    const fight: Refund = { label: 'on kill', per: 'cast', count: 1, recipients: 'team',
      scaling: 'none', amount: 4, citation: 'x', basis: 'fight', condition: 'on a kill' };
    const assumed: Refund = { ...fight, basis: 'assumption', condition: 'full stacks' };
    expect(refundSource(giver(fight), 0, DEFAULT_ENERGY, ctx([giver(fight), subject]))).toBeNull();
    expect(refundSource(giver(fight), 0, { ...DEFAULT_ENERGY,
      refundToggles: { [refundKey('g', 0)]: true } }, ctx([giver(fight), subject]))).toBeNull();
    expect(refundSource(giver(assumed), 0, DEFAULT_ENERGY, ctx([giver(assumed), subject])))
      .toBeNull();
    expect(refundSource(giver(assumed), 0, { ...DEFAULT_ENERGY,
      refundToggles: { [refundKey('g', 0)]: true } }, ctx([giver(assumed), subject]))!.energy).toBe(4);
  });

  it('a per-second refund counts every interval while it runs, capped at its duration', () => {
    const r: Refund = { label: 'C4', per: 'second', count: 1, recipients: 'self', scaling: 'none',
      amount: 4, citation: 'furina/cons.go:51', interval: 5, max_seconds: 30, on: 'skill' };
    const self = giver(r, { is_subject: true });
    expect(refundSource(self, 0, DEFAULT_ENERGY, ctx([self]))!.energy).toBeCloseTo(16, 12);
    const long = { members: [self], subjectOnField: false, rotationSeconds: 40 };
    expect(refundSource(self, 0, DEFAULT_ENERGY, long)!.energy).toBeCloseTo(24, 12);
    // Two casts, two Salons.
    expect(refundSource(self, 0, { ...DEFAULT_ENERGY, casts: { g: 2 } }, ctx([self]))!.energy)
      .toBeCloseTo(32, 12);
  });

  it('a whole-fight rate (`on: rotation`) counts the rotation, not the casts', () => {
    const r: Refund = { label: 'C1', per: 'second', count: 1, recipients: 'self', scaling: 'none',
      amount: 1, citation: 'barbara/cons.go:13', interval: 10, on: 'rotation', basis: 'kit' };
    const self = giver(r, { is_subject: true });
    expect(refundSource(self, 0, { ...DEFAULT_ENERGY, casts: { g: 3 } }, ctx([self]))!.energy)
      .toBeCloseTo(2, 12);
  });
});
