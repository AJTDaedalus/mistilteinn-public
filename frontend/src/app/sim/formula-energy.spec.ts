import { describe, expect, it } from 'vitest';

import { formulaCalibration } from './formula-calibration';
import {
  artifactEnergyRequirement,
  burstFraction,
  energyAt,
  energyFactors,
  energyVaries,
  fieldMultiplier,
  offFieldMultiplier,
  particlesPerRotation,
  particleValue,
  rawParticleEnergy,
  requiredEnergyRecharge,
  waitSeconds,
  type FormulaEnergy,
} from './formula-energy';
import type { FormulaRow, FormulaTeam } from './formula-recipe';
import { evaluateRecipe, NO_STATS } from './recipe-eval';
import { liveQuantitiesFor, searchRecipe } from './recipe-search';
import { type Candidate, type SearchContext, SLOTS } from './search';
import {
  DEFAULT_ENERGY,
  energyInput,
  type TeamEnergyData,
} from '../pages/optimize/formula-estimate.service';

/**
 * The formula estimate's energy model (math-fallback P3, task 14; DESIGN §2.11). The rules are
 * gcsim's at the pin and KQM's Energy library page; gcsim's own events for the owner's
 * National team are held in `scripts/verify-formula-recipe.mjs` and
 * `backend/tests/unit/test_formula_energy_gcsim_sample.py`. Here: the arithmetic, each mode's
 * factor, monotonicity (what keeps the search's bound admissible), the requirement in the
 * existing ER-floor field, and a search ER moves.
 */

/** Xiangling's rotation in the committed gcsim sample, as the model takes it. */
const NATIONAL: FormulaEnergy = {
  mode: 'off', cost: 80, element: 'pyro', partyCount: 4, rotationSeconds: 20, flatEnergy: 0,
  sources: [
    { key: 'b', label: 'Bennett (hold)', element: 'pyro', particles: 3, onFieldShare: 0, citation: '' },
    { key: 'g', label: 'Guoba', element: 'pyro', particles: 4, onFieldShare: 0.5, citation: '' },
    { key: 'x', label: 'Xingqiu', element: 'hydro', particles: 5, onFieldShare: 0, citation: '' },
    { key: 'y', label: 'Yelan', element: 'hydro', particles: 4, onFieldShare: 0, citation: '' },
  ],
  drip: null,
  baseEnergyRecharge: 1.6594,
};

describe('the rules (gcsim energy.go at the pin; KQM Energy page)', () => {
  it('values a particle 3 same, 2 clear, 1 other', () => {
    expect(particleValue('pyro', 'pyro')).toBe(3);
    expect(particleValue('pyro', null)).toBe(2);
    expect(particleValue('pyro', 'hydro')).toBe(1);
  });

  it('takes 60% off field in four, 70% in three, 80% in two', () => {
    expect(offFieldMultiplier(4)).toBeCloseTo(0.6, 12);
    expect(offFieldMultiplier(3)).toBeCloseTo(0.7, 12);
    expect(offFieldMultiplier(2)).toBeCloseTo(0.8, 12);
    expect(fieldMultiplier(0.5, 4)).toBeCloseTo(0.8, 12);
    expect(fieldMultiplier(1, 4)).toBe(1);
  });

  it("banks gcsim's 39.97176 over the National rotation at ER 1.9594", () => {
    expect(rawParticleEnergy(NATIONAL)).toBeCloseTo(20.4, 12);
    expect(energyAt(NATIONAL, 1.9594)).toBeCloseTo(39.97176, 9);
    // Flat energy is added after ER, never multiplied by it (energy.go:35-43).
    expect(energyAt({ ...NATIONAL, flatEnergy: 10 }, 2)).toBeCloseTo(2 * 20.4 + 10, 12);
  });

  it("requires gcsim's max((cost − flat) / raw, 1)", () => {
    expect(requiredEnergyRecharge(NATIONAL)).toBeCloseTo(80 / 20.4, 12);
    expect(artifactEnergyRequirement(NATIONAL)).toBeCloseTo(80 / 20.4 - 1.6594, 12);
    // Flat energy is not multiplied: 40 flat halves what particles must pay.
    expect(requiredEnergyRecharge({ ...NATIONAL, flatEnergy: 40 })).toBeCloseTo(40 / 20.4, 12);
    // Never below 100%, as gcsim clamps.
    expect(requiredEnergyRecharge({ ...NATIONAL, cost: 10 })).toBe(1);
    // No particle and no flat: unanswerable, not "no requirement".
    expect(requiredEnergyRecharge({ ...NATIONAL, sources: [] })).toBeNull();
  });

  it('counts a per-second source over the rotation, capped by its duration', () => {
    const salon = { per: 'second' as const, particles: 1, interval: 3.25, max_seconds: 28.933 };
    expect(particlesPerRotation(salon, 1, 20)).toBeCloseTo(20 / 3.25, 12);
    expect(particlesPerRotation(salon, 1, 40)).toBeCloseTo(28.933 / 3.25, 12);
    expect(particlesPerRotation({ per: 'cast', particles: 2.25 }, 2, 20)).toBe(4.5);
  });
});

describe('what each mode does to the score', () => {
  it('off: nothing', () => {
    expect(energyFactors(NATIONAL, 0)).toEqual({ burst: 1, all: 1 });
    expect(energyVaries(NATIONAL)).toBe(false);
  });

  it('skip: burst rows land min(1, energy / cost) as often', () => {
    const skip = { ...NATIONAL, mode: 'skip' as const };
    const at = energyFactors(skip, 0);
    expect(at.all).toBe(1);
    expect(at.burst).toBeCloseTo(1.6594 * 20.4 / 80, 12);
    expect(burstFraction(skip, 5)).toBe(1);
    expect(energyVaries(skip)).toBe(true);
  });

  it('wait: the whole sequence over rotation + wait, the drip paying the deficit', () => {
    const drip = { particlesPerSecond: 1 / (599.5 / 60), onFieldShare: 0 };
    const wait = { ...NATIONAL, mode: 'wait' as const, drip };
    const deficit = 80 - 1.6594 * 20.4;
    const perSecond = drip.particlesPerSecond * 2 * 0.6 * 1.6594;
    expect(waitSeconds(wait, 1.6594)).toBeCloseTo(deficit / perSecond, 9);
    expect(energyFactors(wait, 0).all).toBeCloseTo(20 / (20 + deficit / perSecond), 12);
    expect(energyFactors(wait, 0).burst).toBe(1);
    expect(() => waitSeconds({ ...wait, drip: null }, 1.6594)).toThrow(/drip/);
  });

  it('never lowers the score for more ER (the bound stays admissible)', () => {
    const drip = { particlesPerSecond: 0.1, onFieldShare: 0 };
    for (const mode of ['skip', 'wait'] as const) {
      const model = { ...NATIONAL, mode, drip };
      let previous = { burst: 0, all: 0 };
      for (let er = 0; er <= 3; er += 0.05) {
        const f = energyFactors(model, er);
        expect(f.burst).toBeGreaterThanOrEqual(previous.burst - 1e-15);
        expect(f.all).toBeGreaterThanOrEqual(previous.all - 1e-15);
        previous = f;
      }
      expect(previous).toEqual({ burst: 1, all: 1 });
    }
  });
});

// ── In a recipe and a search ────────────────────────────────────────────────────────────

function context(): SearchContext {
  return {
    base: {
      base_atk: 900, atk_pct: 0, flat_atk: 0, base_hp: 10000, hp_pct: 0, flat_hp: 0,
      base_def: 600, def_pct: 0, flat_def: 0, elemental_mastery: 0, crit_rate: 0.05,
      crit_dmg: 0.5, energy_recharge: 1.2, pyro_dmg_bonus: 0,
    },
    hit: {
      multiplier: 1.5, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0, amplifying: null,
      reactionBonus: 0,
    },
    target: { level: 100, resistance: 0.1, defReduction: 0, defIgnore: 0 },
    characterLevel: 90,
    dmgBonusQuantity: 'pyro_dmg_bonus',
  };
}

const TEAM: FormulaTeam = {
  element: 'pyro', weaponType: 'WEAPON_POLE', memberElements: ['pyro', 'hydro', 'pyro', 'hydro'],
};

const ROWS: FormulaRow[] = [
  { id: 'q', label: 'Pyronado DMG', move: 'burst', count: 12, context: context() },
  { id: 'e', label: 'Guoba DMG', move: 'skill', count: 4, context: context() },
];

function calibrate(mode: 'off' | 'skip' | 'wait') {
  return formulaCalibration({
    rows: ROWS, team: TEAM, resonances: [], setTiers: [], staticSetBonuses: [],
    fourPieceSetIds: [], characters: ['Xiangling'],
    energy: {
      ...NATIONAL, mode,
      drip: { particlesPerSecond: 1 / (599.5 / 60), onFieldShare: 0 },
    },
  });
}

describe('a formula recipe with an energy model', () => {
  it("reads the recipe's own ER and puts the requirement in the existing ER-floor field", () => {
    const { noFourPiece } = calibrate('off');
    expect(noFourPiece.meta.formulaEnergy?.baseEnergyRecharge).toBeCloseTo(1.2, 12);
    expect(noFourPiece.meta.minimumEnergyRecharge).toBeCloseTo(80 / 20.4 - 1.2, 12);
    expect(noFourPiece.meta.formula?.assumptions.some((a) => a.includes('Xiangling needs 392.2%')))
      .toBe(true);
  });

  it('skip scales only the burst rows; wait scales every row; off neither', () => {
    const off = calibrate('off').noFourPiece;
    const skip = calibrate('skip').noFourPiece;
    const wait = calibrate('wait').noFourPiece;
    const burstOnly = { ...off, hits: off.hits.filter((h) => h.move === 'burst') };
    const skillOnly = { ...off, hits: off.hits.filter((h) => h.move !== 'burst') };
    const b = evaluateRecipe(burstOnly, NO_STATS);
    const s = evaluateRecipe(skillOnly, NO_STATS);
    const f = 1.2 * 20.4 / 80;
    expect(evaluateRecipe(off, NO_STATS)).toBeCloseTo(b + s, 6);
    expect(evaluateRecipe(skip, NO_STATS)).toBeCloseTo(b * f + s, 6);
    const factor = energyFactors(wait.meta.formulaEnergy!, 0).all;
    expect(factor).toBeLessThan(1);
    expect(evaluateRecipe(wait, NO_STATS)).toBeCloseTo((b + s) * factor, 6);
    // Enough artifact ER and both modes score what off does.
    const plenty = { ...NO_STATS, energyRecharge: 3 };
    expect(evaluateRecipe(skip, plenty)).toBeCloseTo(evaluateRecipe(off, plenty), 6);
    expect(evaluateRecipe(wait, plenty)).toBeCloseTo(evaluateRecipe(off, plenty), 6);
  });

  it('makes ER live only when a priced mode leaves a requirement unmet', () => {
    expect(liveQuantitiesFor(calibrate('off').noFourPiece)).not.toContain('energy_recharge');
    expect(liveQuantitiesFor(calibrate('skip').noFourPiece)).toContain('energy_recharge');
    const met = calibrate('skip').noFourPiece;
    met.meta.formulaEnergy = { ...met.meta.formulaEnergy!, baseEnergyRecharge: 5 };
    expect(liveQuantitiesFor(met)).not.toContain('energy_recharge');
  });

  /**
   * Three pieces per slot: ATK%, CRIT DMG, ER. Under `off` no ER piece can place; under `skip`
   * the winner takes ER until the bursts are funded and damage after — and the bounded walk
   * returns exactly what the exhaustive one does.
   */
  const inventory = (): Candidate[] => SLOTS.flatMap((slot, s) =>
    ([
      { atk_pct: 0.15 + 0.001 * s },
      { crit_dmg: 0.25 + 0.001 * s },
      { energy_recharge: 0.55 + 0.001 * s },
    ] as Record<string, number>[])
      .map((stats, k) => ({ id: `${slot}-${k}`, slot, setId: 1, stats } as Candidate)));

  for (const mode of ['skip', 'wait'] as const) {
    it(`${mode}: ER moves the ranking, and the bound stays exact`, () => {
      const priced = calibrate(mode).noFourPiece;
      const recipes = { byFourPieceSet: new Map([[1, priced]]), noFourPiece: priced };
      const exhaustive = searchRecipe(inventory(), { recipes, topN: 100000, fourPieceSets: [1] });
      const bounded = searchRecipe(inventory(), { recipes, topN: 3, fourPieceSets: [1] });
      expect(exhaustive.evaluated).toBe(243);
      expect(bounded.builds).toEqual(exhaustive.builds.slice(0, 3));
      const ers = exhaustive.builds[0].artifactIds.filter((id) => id.endsWith('-2')).length;
      expect(ers).toBeGreaterThan(0);

      const off = calibrate('off').noFourPiece;
      const plain = searchRecipe(inventory(), {
        recipes: { byFourPieceSet: new Map([[1, off]]), noFourPiece: off },
        topN: 1, fourPieceSets: [1],
      });
      expect(plain.builds[0].artifactIds.filter((id) => id.endsWith('-2'))).toEqual([]);
    });
  }
});

describe('energyInput: the server data and the settings', () => {
  const data: TeamEnergyData = {
    gcsim_commit: 'b107b5dc',
    drip: { particles: 1, interval_seconds: 599.5 / 60, config: 'energy every', citation: 'drip' },
    members: [
      { build_id: 'xl', name: 'Xiangling', element: 'pyro', burst_energy_cost: 80,
        burst_cooldown: 20, is_subject: true, status: 'curated', refunds: [],
        sources: [{ label: 'Guoba', per: 'cast', particles: 4, collector: 'active', citation: 'g', on: 'skill' }] },
      { build_id: 'bn', name: 'Bennett', element: 'pyro', burst_energy_cost: 60,
        burst_cooldown: 15, is_subject: false, status: 'curated', refunds: [],
        sources: [{ label: 'Tap', per: 'cast', particles: 2.25, collector: 'caster', citation: 'b', on: 'skill' }] },
      { build_id: 'rd', name: 'Raiden Shogun', element: 'electro', burst_energy_cost: 90,
        burst_cooldown: 18, is_subject: false, status: 'no_particle_data', refunds: [], sources: [] },
    ],
  };

  it('defaults: one cast each, the burst cooldown, the drip, own active particles off field', () => {
    const input = energyInput(data, DEFAULT_ENERGY)!;
    expect(input.rotationSeconds).toBe(20);
    expect(input.partyCount).toBe(3);
    // Wait is the default (owner, 2026-11-15, DECISIONS §48).
    expect(input.mode).toBe('wait');
    const by = Object.fromEntries(input.sources.map((s) => [s.key, s]));
    expect(by['xl:0'].particles).toBe(4);
    expect(by['xl:0'].onFieldShare).toBe(0);
    expect(by['bn:0'].particles).toBe(2.25);
    expect(by['bn:0'].onFieldShare).toBe(0);
    expect(by['drip'].particles).toBeCloseTo(20 / (599.5 / 60), 12);
    // An uncurated member counts nothing until the user says otherwise.
    expect(input.sources.some((s) => s.key.startsWith('rd'))).toBe(false);
  });

  it('takes the user: casts, a hold, a share, a manual count, no drip', () => {
    const input = energyInput(data, {
      ...DEFAULT_ENERGY, mode: 'wait', drip: false, rotationSeconds: 25,
      casts: { bn: 2 }, particles: { 'bn:0': 3 }, onField: { 'xl:0': 0.5 }, manual: { rd: 6 },
    })!;
    const by = Object.fromEntries(input.sources.map((s) => [s.key, s]));
    expect(by['bn:0'].particles).toBe(6);
    expect(by['xl:0'].onFieldShare).toBe(0.5);
    expect(by['rd:manual'].particles).toBe(6);
    expect(by['drip']).toBeUndefined();
    // Waiting without a drip never ends; the input steps back to skip, and its sentence says so.
    expect(input.mode).toBe('skip');
    expect(input.rotationSeconds).toBe(25);
  });

  it('is null for a subject with no burst cost', () => {
    const none = { ...data, members: data.members.map((m) => (
      m.is_subject ? { ...m, burst_energy_cost: null } : m)) };
    expect(energyInput(none, DEFAULT_ENERGY)).toBeNull();
  });
});
