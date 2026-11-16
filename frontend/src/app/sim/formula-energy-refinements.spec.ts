import { describe, expect, it } from 'vitest';

import { formulaCalibration } from './formula-calibration';
import {
  energyAt,
  energyFactors,
  energyVaries,
  favoniusProcsAt,
  particlesPerRotation,
  rawParticleEnergy,
  requiredEnergyRecharge,
  type FormulaEnergy,
} from './formula-energy';
import type { FormulaRow, FormulaTeam } from './formula-recipe';
import { evaluateRecipe, NO_STATS } from './recipe-eval';
import { searchRecipe } from './recipe-search';
import { type Candidate, type SearchContext, SLOTS } from './search';
import {
  DEFAULT_ENERGY,
  defaultOnField,
  energyInput,
  resonanceProcs,
  subjectOnFieldOf,
  type TeamEnergyData,
} from '../pages/optimize/formula-estimate.service';

/**
 * The owner's four refinements of 2026-11-15 (DECISIONS §49, DESIGN §2.11 "Refinements"):
 * Electro resonance's particles, an on-field subject catching the summons on field, Favonius
 * procs from each candidate's crit rate, and Yae Miko at gcsim's rate. gcsim's own events for
 * the same terms are held in `scripts/verify-formula-recipe.mjs` and
 * `backend/tests/unit/test_formula_energy_refinements_sample.py`.
 */

type Member = TeamEnergyData['members'][number];

const raiden = (over: Partial<Member> = {}): Member => ({
  build_id: 'rd', name: 'Raiden Shogun', element: 'electro', burst_energy_cost: 90,
  burst_cooldown: 18, is_subject: true, status: 'curated',
  sources: [{ label: 'Eye', per: 'second', particles: 0.5, chance: 0.5, interval: 1,
    max_seconds: 25, collector: 'active', citation: 'eye', on: 'skill', shared_icd: false }],
  refunds: [],
  favonius: { weapon: 'Favonius Lance', refinement: 3, chance: 0.8, cooldown_seconds: 9,
    particles: 3, citation: 'favonius.go' },
  energy_recharge: 2.326268198, crit_rate: 0.35,
  ...over,
});

const fischl = (over: Partial<Member> = {}): Member => ({
  build_id: 'fs', name: 'Fischl', element: 'electro', burst_energy_cost: 60,
  burst_cooldown: 15, is_subject: false, status: 'curated',
  sources: [{ label: 'Oz (skill)', per: 'second', particles: 0.67, chance: 0.67, interval: 1,
    max_seconds: 10, collector: 'active', citation: 'oz', on: 'skill', shared_icd: false }],
  refunds: [], favonius: null, energy_recharge: 1.3, crit_rate: 0.6,
  ...over,
});

const xingqiu = (over: Partial<Member> = {}): Member => ({
  build_id: 'xq', name: 'Xingqiu', element: 'hydro', burst_energy_cost: 80,
  burst_cooldown: 20, is_subject: false, status: 'curated',
  sources: [{ label: 'Rainscreen', per: 'cast', particles: 5, collector: 'caster', citation: 'x', on: 'skill', shared_icd: false }],
  refunds: [],
  favonius: { weapon: 'Favonius Sword', refinement: 5, chance: 1, cooldown_seconds: 6,
    particles: 3, citation: 'favonius.go' },
  energy_recharge: 1.8, crit_rate: 0.2,
  ...over,
});

const yae = (over: Partial<Member> = {}): Member => ({
  build_id: 'ym', name: 'Yae Miko', element: 'electro', burst_energy_cost: 90,
  burst_cooldown: 22, is_subject: false, status: 'curated',
  sources: [{ label: 'Sesshou Sakura', per: 'second', particles: 1, interval: 2.933333,
    max_seconds: 25, collector: 'active', citation: 'yae', on: 'skill', shared_icd: true }],
  refunds: [], favonius: null, energy_recharge: 1.2, crit_rate: 0.5,
  ...over,
});

const HIGH_VOLTAGE = {
  name: 'High Voltage', element: 'electro', particles: 1, cooldown_seconds: 5,
  trigger_elements: ['pyro', 'cryo', 'hydro', 'dendro'], team_can_trigger: true,
  note: 'note', citation: 'gcsim setup.go:181-207; KQM',
  default_procs_per_second: 0.12, default_note: 'samples',
};

const data = (members: Member[], resonance: TeamEnergyData['resonance'] = null): TeamEnergyData => ({
  gcsim_commit: 'b107b5dc', members, resonance,
  drip: { particles: 1, interval_seconds: 599.5 / 60, config: 'energy every', citation: 'drip' },
});

const bySource = (input: { sources: { key: string }[] }) =>
  Object.fromEntries(input.sources.map((s) => [s.key, s])) as Record<string, FormulaEnergy['sources'][number]>;

// ── 1. Electro resonance ─────────────────────────────────────────────────────────────────────

describe("Electro resonance's particles (gcsim setup.go:181-207; KQM's resonance table)", () => {
  // Four members, as the resonance needs (and as the sample's party of four, 0.6 off field).
  const zhongli = xingqiu({ build_id: 'zl', name: 'Zhongli', element: 'geo', favonius: null });
  const team = () => data(
    [raiden({ favonius: null }), fischl(), xingqiu({ favonius: null }), zhongli], HIGH_VOLTAGE);

  it("defaults to the samples' rate, 0.12 a second of rotation, when a member can react (§50)", () => {
    const input = energyInput(team(), DEFAULT_ENERGY)!;
    const res = bySource(input)['resonance:electro'];
    expect(res.element).toBe('electro');
    expect(res.particles).toBeCloseTo(0.12 * 18, 12);
    expect(res.citation).toContain('setup.go');
  });

  it("takes the user's procs, bounded by the cooldown", () => {
    const at = (procs: number) => bySource(
      energyInput(team(), { ...DEFAULT_ENERGY, resonanceProcs: procs })!)['resonance:electro'];
    expect(at(3).particles).toBe(3);
    expect(at(10).particles).toBeCloseTo(18 / 5, 12);
    expect(at(0)).toBeUndefined();
    expect(resonanceProcs(HIGH_VOLTAGE, { ...DEFAULT_ENERGY, resonanceProcs: 2 }, 18)).toBe(2);
    expect(resonanceProcs(HIGH_VOLTAGE, DEFAULT_ENERGY, 25)).toBeCloseTo(3, 12);
  });

  it('counts nothing for a team with no member to react with, or without the resonance', () => {
    const inert = data([raiden({ favonius: null }), fischl()],
      { ...HIGH_VOLTAGE, team_can_trigger: false });
    expect(bySource(energyInput(inert, DEFAULT_ENERGY)!)['resonance:electro']).toBeUndefined();
    // …unless the user says reactions happen (a teammate the table cannot see, say).
    expect(bySource(energyInput(inert, { ...DEFAULT_ENERGY, resonanceProcs: 2 })!)[
      'resonance:electro'].particles).toBe(2);
    expect(bySource(energyInput(data([raiden({ favonius: null })]), DEFAULT_ENERGY)!)[
      'resonance:electro']).toBeUndefined();
  });

  it("is caught on field by an on-field subject, off field otherwise; editable", () => {
    expect(bySource(energyInput(team(), DEFAULT_ENERGY, 0, true)!)['resonance:electro']
      .onFieldShare).toBe(1);
    expect(bySource(energyInput(team(), DEFAULT_ENERGY, 0, false)!)['resonance:electro']
      .onFieldShare).toBe(0);
    expect(bySource(energyInput(team(), {
      ...DEFAULT_ENERGY, onField: { 'resonance:electro': 8 / 12 },
    }, 0, true)!)['resonance:electro'].onFieldShare).toBeCloseTo(8 / 12, 12);
  });

  it("reproduces #393's 72.58: 3 procs a rotation, 8 of 12 on field, at Raiden's ER, × 4", () => {
    const input = energyInput(team(), {
      ...DEFAULT_ENERGY, resonanceProcs: 3, onField: { 'resonance:electro': 8 / 12 },
    })!;
    const only: FormulaEnergy = {
      ...input, baseEnergyRecharge: 1, flatSources: [],
      sources: input.sources.filter((s) => s.key === 'resonance:electro'),
    };
    expect(4 * energyAt(only, 2.326268198)).toBeCloseTo(72.5795677776, 9);
  });
});

// ── 2. The on-field subject ──────────────────────────────────────────────────────────────────

describe('an on-field subject catches the summons on field (owner, 2026-11-15)', () => {
  const row = (over: Partial<FormulaRow>): Pick<FormulaRow, 'move' | 'hit' | 'reaction' | 'proc'> =>
    ({ move: null, hit: null, ...over });

  it('is on field when a row is a normal, charged or plunging attack, whatever talent publishes it', () => {
    expect(subjectOnFieldOf([row({ move: 'normal' })])).toBe(true);
    expect(subjectOnFieldOf([row({ move: 'charged' })])).toBe(true);
    // Raiden's Musou Isshin attacks are burst-talent rows; the label says they are attacks.
    expect(subjectOnFieldOf([row({ move: 'burst',
      hit: { talent: 'elemental_burst', label: '1-Hit DMG' } })])).toBe(true);
    expect(subjectOnFieldOf([row({ move: 'burst',
      hit: { talent: 'elemental_burst', label: 'Charged Attack DMG' } })])).toBe(true);
    // Skills and bursts alone are cast and left: Xiangling's Pyronado, Guoba.
    expect(subjectOnFieldOf([row({ move: 'burst', hit: { talent: 'elemental_burst', label: 'Pyronado DMG' } }),
      row({ move: 'skill' })])).toBe(false);
    // A reaction or proc row is not an attack the subject performs.
    expect(subjectOnFieldOf([row({ move: 'normal', reaction: { reaction: 'overloaded' } as FormulaRow['reaction'] })]))
      .toBe(false);
    expect(subjectOnFieldOf([])).toBe(false);
  });

  it("defaults every 'active' generator to 100 % on field, the subject's own and a teammate's", () => {
    const team = data([raiden(), fischl(), xingqiu(), yae()]);
    const on = bySource(energyInput(team, DEFAULT_ENERGY, 20, true)!);
    expect(on['rd:0'].onFieldShare).toBe(1); // her own Eye
    expect(on['fs:0'].onFieldShare).toBe(1); // Oz
    expect(on['ym:0'].onFieldShare).toBe(1); // Yae's totems
    // A caster's own particles land while the caster is on field; a teammate's Favonius procs
    // only while its holder is on field. The drip follows on field since the small calls
    // (DECISIONS §50; formula-energy-small-calls.spec.ts).
    expect(on['xq:0'].onFieldShare).toBe(0);
    expect(on['xq:favonius'].onFieldShare).toBe(0);
    expect(on['drip'].onFieldShare).toBe(1);
    const off = bySource(energyInput(team, DEFAULT_ENERGY, 20, false)!);
    expect(off['rd:0'].onFieldShare).toBe(0);
    expect(off['fs:0'].onFieldShare).toBe(0);
  });

  it('takes the user: the toggle over the rows, and a share over the toggle', () => {
    const team = data([raiden(), fischl()]);
    expect(bySource(energyInput(team, { ...DEFAULT_ENERGY, subjectOnField: false }, 20, true)!)[
      'fs:0'].onFieldShare).toBe(0);
    expect(bySource(energyInput(team, { ...DEFAULT_ENERGY, subjectOnField: true }, 20, false)!)[
      'fs:0'].onFieldShare).toBe(1);
    expect(bySource(energyInput(team, { ...DEFAULT_ENERGY, onField: { 'fs:0': 0.25 } }, 20, true)!)[
      'fs:0'].onFieldShare).toBe(0.25);
    expect(defaultOnField(fischl(), { collector: 'active' }, true)).toBe(1);
    expect(defaultOnField(fischl(), { collector: 'caster' }, true)).toBe(0);
    expect(defaultOnField(raiden(), { collector: 'caster' }, false)).toBe(1);
  });
});

// ── 3. Favonius from each candidate's crit ───────────────────────────────────────────────────

describe("the optimized character's Favonius, priced from each candidate's crit rate", () => {
  it('is carried apart from the sources, with the holder\'s hits, chance and cooldown', () => {
    const input = energyInput(data([raiden(), xingqiu()]), DEFAULT_ENERGY, 20)!;
    expect(bySource(input)['rd:favonius']).toBeUndefined();
    const fav = input.subjectFavonius!;
    expect([fav.hits, fav.chance, fav.cooldownSeconds, fav.particles, fav.onFieldShare])
      .toEqual([20, 0.8, 9, 3, 1]);
    expect(fav.buildCritRate).toBe(0.35);
    // A teammate's Favonius stays a source at their build's crit rate.
    expect(bySource(input)['xq:favonius'].particles).toBeCloseTo(3 * Math.min(18 / 6, 1 * 0.2 * 1), 12);
  });

  it('procs: min(rotation ÷ cooldown, hits × crit × chance), clamped to a probability', () => {
    const fav = energyInput(data([raiden()]), DEFAULT_ENERGY, 2)!.subjectFavonius!;
    expect(favoniusProcsAt(fav, 18, 0.35)).toBeCloseTo(2 * 0.35 * 0.8, 12);
    expect(favoniusProcsAt(fav, 18, 1.4)).toBeCloseTo(2 * 1 * 0.8, 12);
    expect(favoniusProcsAt({ ...fav, hits: 40 }, 18, 0.5)).toBeCloseTo(2, 12); // the cooldown
    expect(favoniusProcsAt(fav, 18, -0.1)).toBe(0);
  });

  const model = (base: number): FormulaEnergy => {
    const input = energyInput(data([raiden({ sources: [] })]), { ...DEFAULT_ENERGY, drip: false }, 3)!;
    return { ...input, baseEnergyRecharge: 1,
      subjectFavonius: { ...input.subjectFavonius!, baseCritRate: base } };
  };

  it("a candidate's artifact crit adds procs; its energy is base crit + artifact crit", () => {
    const m = model(0.05);
    const low = rawParticleEnergy(m, 0.05);
    const high = rawParticleEnergy(m, 0.65);
    expect(high).toBeGreaterThan(low);
    // 3 hits × crit × 0.8 procs, 3 clear particles, worth 2, caught on field.
    expect(high - low).toBeCloseTo(3 * 0.6 * 0.8 * 3 * 2, 12);
    const m2 = { ...m, mode: 'skip' as const };
    expect(energyFactors(m2, 0, 0.6).burst).toBeCloseTo(
      Math.min(1, energyAt(m2, 1, 0.65) / 90), 12);
  });

  it('every factor is non-decreasing in crit and in ER together (the bound stays admissible)', () => {
    for (const mode of ['skip', 'wait'] as const) {
      const m = { ...model(0.05), mode, drip: { particlesPerSecond: 0.1, onFieldShare: 0 } };
      for (let er = 0; er <= 2; er += 0.25) {
        let last = -Infinity;
        for (let cr = 0; cr <= 1.2; cr += 0.05) {
          const f = energyFactors(m, er, cr);
          expect(f.burst * f.all).toBeGreaterThanOrEqual(last - 1e-12);
          expect(energyFactors(m, er + 0.1, cr).burst * energyFactors(m, er + 0.1, cr).all)
            .toBeGreaterThanOrEqual(f.burst * f.all - 1e-12);
          last = f.burst * f.all;
        }
      }
    }
  });

  it('ER is live when the requirement is unmet at the lowest crit, the base without artifacts', () => {
    const m = { ...model(0.05), mode: 'wait' as const,
      drip: { particlesPerSecond: 0.1, onFieldShare: 0 } };
    const atBuild = requiredEnergyRecharge(m)!; // reported at the build's crit, 35 %
    const atBase = requiredEnergyRecharge(m, 0.05)!;
    expect(atBase).toBeGreaterThan(atBuild);
    // Base ER between the two: met at the build's crit, unmet at the base's — still live.
    expect(energyVaries({ ...m, baseEnergyRecharge: (atBase + atBuild) / 2 })).toBe(true);
    expect(energyVaries({ ...m, baseEnergyRecharge: atBase + 0.01 })).toBe(false);
  });
});

function context(): SearchContext {
  return {
    base: {
      base_atk: 900, atk_pct: 0, flat_atk: 0, base_hp: 10000, hp_pct: 0, flat_hp: 0,
      base_def: 600, def_pct: 0, flat_def: 0, elemental_mastery: 0, crit_rate: 0.05,
      crit_dmg: 0.5, energy_recharge: 1.0, electro_dmg_bonus: 0,
    },
    hit: {
      multiplier: 1.5, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0, amplifying: null,
      reactionBonus: 0,
    },
    target: { level: 100, resistance: 0.1, defReduction: 0, defIgnore: 0 },
    characterLevel: 90,
    dmgBonusQuantity: 'electro_dmg_bonus',
  };
}

describe('a Favonius subject in a recipe and a search', () => {
  const TEAM: FormulaTeam = {
    element: 'electro', weaponType: 'WEAPON_POLE',
    memberElements: ['electro', 'electro', 'hydro', 'geo'],
  };
  const ROWS: FormulaRow[] = [
    { id: 'n', label: '1-Hit DMG', move: 'burst', count: 20, context: context(),
      hit: { talent: 'elemental_burst', label: '1-Hit DMG' } },
  ];

  const calibrate = () => {
    const input = energyInput(data([raiden({ sources: [] })]),
      { ...DEFAULT_ENERGY, rotationSeconds: 20 }, 20, true)!;
    return formulaCalibration({
      rows: ROWS, team: TEAM, resonances: [], setTiers: [], staticSetBonuses: [],
      fourPieceSetIds: [], characters: ['Raiden Shogun'], energy: input,
    }).noFourPiece;
  };

  it("takes the recipe's own pre-artifact crit as the base", () => {
    const recipe = calibrate();
    expect(recipe.meta.formulaEnergy!.subjectFavonius!.baseCritRate).toBeCloseTo(0.05, 12);
    // The requirement in the ER-floor field is reported at the build's crit rate.
    expect(recipe.meta.minimumEnergyRecharge).toBeCloseTo(
      requiredEnergyRecharge(recipe.meta.formulaEnergy!, 0.35)! - 1, 12);
    expect(recipe.meta.formula!.assumptions.some((a) => a.includes('each candidate\'s crit rate')))
      .toBe(true);
  });

  it("scores a candidate's crit through its Favonius procs as well as its damage", () => {
    const recipe = calibrate();
    const at = (critRate: number) => evaluateRecipe(recipe, { ...NO_STATS, critRate });
    const noEnergy = { ...recipe, meta: { ...recipe.meta, formulaEnergy: undefined } };
    const plain = (critRate: number) => evaluateRecipe(noEnergy, { ...NO_STATS, critRate });
    // More crit, more procs, a shorter wait: the energy factor rises with crit.
    expect(at(0.3) / plain(0.3)).toBeGreaterThan(at(0) / plain(0));
  });

  /** Per slot: CRIT Rate, ATK%, ER. The bounded walk must return what the exhaustive one does. */
  const inventory = (): Candidate[] => SLOTS.flatMap((slot, s) =>
    ([
      { crit_rate: 0.12 + 0.001 * s },
      { atk_pct: 0.2 + 0.001 * s },
      { energy_recharge: 0.3 + 0.001 * s },
    ] as Record<string, number>[])
      .map((stats, k) => ({ id: `${slot}-${k}`, slot, setId: 1, stats } as Candidate)));

  it('the bound stays exact with crit buying energy', () => {
    const recipe = calibrate();
    const recipes = { byFourPieceSet: new Map([[1, recipe]]), noFourPiece: recipe };
    const exhaustive = searchRecipe(inventory(), { recipes, topN: 100000, fourPieceSets: [1] });
    for (const topN of [1, 3, 10]) {
      const bounded = searchRecipe(inventory(), { recipes, topN, fourPieceSets: [1] });
      expect(bounded.builds).toEqual(exhaustive.builds.slice(0, topN));
    }
  });
});

// ── 4. Yae Miko: gcsim's rate ────────────────────────────────────────────────────────────────

describe("Yae's totems: one particle a strike under an ICD shared by every totem", () => {
  it('more casts add no particles; the rotation and the 25 s cap still bound it', () => {
    const source = yae().sources[0];
    expect(particlesPerRotation(source, 3, 22)).toBeCloseTo(22 / 2.933333, 9);
    expect(particlesPerRotation(source, 3, 22)).toBe(particlesPerRotation(source, 1, 22));
    expect(particlesPerRotation(source, 1, 40)).toBeCloseTo(25 / 2.933333, 9);
    expect(particlesPerRotation(source, 0, 22)).toBe(0);
    const input = energyInput(data([raiden(), yae()]), { ...DEFAULT_ENERGY, casts: { ym: 3 } })!;
    expect(bySource(input)['ym:0'].particles).toBeCloseTo(18 / 2.933333, 9);
  });
});
