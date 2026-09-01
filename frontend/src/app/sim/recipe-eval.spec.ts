import { describe, expect, it } from 'vitest';

import {
  NO_STATS, energyRatio, evaluateHit, evaluateRecipe, type CandidateStats,
} from './recipe-eval';
import type { Recipe, RecipeHit } from './recipe';

/**
 * G.4 — applying a candidate's stats to a calibrated hit.
 *
 * **The fixtures are not here.** `scripts/verify-gcsim-recipe.mjs` runs the real check as its
 * own CI step: it takes a calibration captured at *zero artifact stats*, applies the stats a
 * different gcsim run actually used, and matches that run's own numbers to 1.986e-16.
 *
 * What a stub proves and that gate cannot is the negative space — that a goblet's element
 * bonus reaches only its own element, that crit stays clamped after the candidate's own crit
 * rate is added, and that `flatDamage` is deliberately *not* scaled.
 */

const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
  mine: true,
  owner: 0,
  abil: 'x', attackTag: 1, element: 'cryo', talent: 2, scaling: 'atk', flatDamage: 0,
  // **Deliberately different.** In a valid recipe these are equal — calibration runs at zero
  // artifact stats — so a stub that makes them equal cannot tell `baseStat` from
  // `calibratedScaling`, and the mutation swapping them survives. The gate cannot catch that
  // either, for the same reason, so this is the only place it can be caught.
  calibratedScaling: 1500, bonusDmg: 0, critRate: 0, critDmg: 0,
  conversions: {},
  // **Deliberately not all equal.** These are the three parts a total is built from, and a
  // stub that collapses them cannot tell `base × (1 + pct)` from a re-multiplied total.
  calibratedBase: { atk: 1000, hp: 10000, def: 800 },
  calibratedPercent: { atk: 0, hp: 0, def: 0 },
  calibratedFlat: { atk: 0, hp: 0, def: 0 },
  defMultiplier: 0.5, resMultiplier: 0.9, ampMultiplier: 1, gcsimAverageDamage: 900, ...over,
});

const stats = (over: Partial<CandidateStats> = {}): CandidateStats => ({ ...NO_STATS, ...over });

describe('evaluateHit', () => {
  it('reproduces the calibration when the candidate contributes nothing', () => {
    // base 2*1000 = 2000; 2000 * 1 * 0.5 * 0.9 = 900.
    expect(evaluateHit(hit(), stats())).toBeCloseTo(900, 9);
  });

  it('applies a percentage stat to the base, not to the calibrated total', () => {
    // baseStat 1000 at +46.4% → 1464; 2*1464*0.5*0.9 = 1317.6. Using calibratedScaling here
    // would compound the calibration's own artifacts on top of the candidate's.
    expect(evaluateHit(hit(), stats({ atkPercent: 0.464 }))).toBeCloseTo(1317.6, 6);
  });

  it('adds flat stats after the percentage', () => {
    expect(evaluateHit(hit(), stats({ atkPercent: 1, atkFlat: 500 }))).toBeCloseTo(2250, 6);
  });

  it.each([
    // base 10000, doubled by +100% HP → 20000; talent 2 → 40000; × 0.5 × 0.9 = 18000.
    ['hp', { hpPercent: 1 }, 18000, 9000],
    // base 800, doubled → 1600; talent 2 → 3200; × 0.45 = 1440.
    ['def', { defPercent: 1 }, 1440, 720],
  ] as const)('scales off %s when the ability does', (scaling, over, moved, unmoved) => {
    expect(evaluateHit(hit({ scaling }), stats(over))).toBeCloseTo(moved, 6);
    // …and is unmoved by a stat it does not scale off.
    expect(evaluateHit(hit({ scaling }), stats({ atkPercent: 1 }))).toBeCloseTo(unmoved, 6);
  });

  it('takes elemental mastery whole, since it has no base or percentage form', () => {
    // scaling = 200; talent 2 → 400; × 0.45 = 180.
    expect(evaluateHit(hit({ scaling: 'em' }), stats({ elementalMastery: 200 })))
      .toBeCloseTo(180, 6);
  });

  it('lets a goblet reach only its own element', () => {
    // The reason RecipeHit.element must carry gcsim's name rather than its internal enum.
    const cryo = stats({ elementBonus: { cryo: 0.5 } });

    expect(evaluateHit(hit({ element: 'cryo' }), cryo)).toBeCloseTo(1350, 6);
    expect(evaluateHit(hit({ element: 'physical' }), cryo)).toBeCloseTo(900, 6);
  });

  it('lets an all-element bonus reach every hit', () => {
    const all = stats({ allElementBonus: 0.5 });

    expect(evaluateHit(hit({ element: 'physical' }), all)).toBeCloseTo(1350, 6);
  });

  it('adds the candidate crit to the calibration crit', () => {
    // calibrated cr 0.25/cd 1, candidate +0.25/+1 → 0.5 * 2 = 1.0 → doubled.
    const h = hit({ critRate: 0.25, critDmg: 1 });
    expect(evaluateHit(h, stats({ critRate: 0.25, critDmg: 1 })))
      .toBeCloseTo(evaluateHit(h, stats()) / 1.25 * 2, 6);
  });

  it('clamps crit rate after adding the candidate, not before', () => {
    // A build stacking past 100% must not be credited for the overflow.
    const h = hit({ critRate: 0.8, critDmg: 1 });
    expect(evaluateHit(h, stats({ critRate: 0.9 }))).toBeCloseTo(evaluateHit(h, stats({ critRate: 0.2 })), 6);
  });

  it('does not scale flat damage by the candidate', () => {
    // flatDamage is baked in at calibration. For a conversion passive like Redhorn — flat
    // damage from DEF — it goes stale when the candidate's DEF differs, and pretending
    // otherwise would silently invent a number gcsim never computed.
    //
    // **Perturbing the stat this hit actually scales off.** The first version of this test
    // moved `defPercent` on an ATK-scaling hit, so the mutation that scaled flat damage by
    // the candidate changed nothing and survived.
    const h = hit({ flatDamage: 1000, scaling: 'atk' });

    // baseStat 1000 at +100% → 2000. base = 2*2000 + 1000 = 5000; x 0.5 x 0.9 = 2250.
    // Were flatDamage scaled too it would be 2*2000 + 2000 = 6000 → 2700.
    expect(evaluateHit(h, stats({ atkPercent: 1 }))).toBeCloseTo(2250, 6);
    expect(evaluateHit(h, stats({ atkPercent: 1 }))).not.toBeCloseTo(2700, 6);
  });

  it('applies the amplifying multiplier last', () => {
    expect(evaluateHit(hit({ ampMultiplier: 2 }), stats())).toBeCloseTo(1800, 9);
  });
});

describe('conversions', () => {
  it('rescales a resolved conversion from the candidate’s own total', () => {
    // Redhorn: flat damage is 40% of DEF. base DEF 800 → flat 320; at +100% DEF the total is
    // 1600 → flat 640. base = 2*1000 + 640 = 2640; x 0.45 = 1188.
    const h = hit({
      flatDamage: 320,
      conversions: { flatDamage: { from: 'def', perUnit: 0.4 } },
    });

    expect(evaluateHit(h, stats({ defPercent: 1 }))).toBeCloseTo(1188, 6);
  });

  it('leaves an unresolved conversion frozen rather than guessing a source', () => {
    // Inventing a scaling for a term whose source was never identified would put a confident
    // wrong number in every hit that carries it.
    const h = hit({ flatDamage: 320 });

    expect(evaluateHit(h, stats({ defPercent: 1 }))).toBeCloseTo(evaluateHit(h, stats()), 9);
  });

  it('rescales a conversion that landed in flat ATK, feeding the scaling stat', () => {
    // Noelle's burst converts DEF into flat ATK. At +100% DEF the flat ATK doubles, and it is
    // added *after* the ATK percentage — a percentage multiplies base only.
    const h = hit({
      calibratedFlat: { atk: 400, hp: 0, def: 0 },
      conversions: { flatAtk: { from: 'def', perUnit: 0.5 } },
    });

    // scaling = 1000 * 1 + (0.5 * 1600) = 1800; talent 2 → 3600; x 0.45 = 1620.
    expect(evaluateHit(h, stats({ defPercent: 1 }))).toBeCloseTo(1620, 6);
  });

  it('adds the calibration percentage to the candidate’s rather than compounding', () => {
    // base 1000 at a calibrated +50% and a candidate +50% is 1000*(1+0.5+0.5) = 2000, not
    // 1000*1.5*1.5 = 2250. Compounding is invisible whenever the calibration has no buffs.
    const h = hit({ calibratedPercent: { atk: 0.5, hp: 0, def: 0 } });

    expect(evaluateHit(h, stats({ atkPercent: 0.5 }))).toBeCloseTo(2 * 2000 * 0.45, 6);
  });
});

describe('evaluateRecipe', () => {
  const recipe = (hits: RecipeHit[]): Recipe =>
    ({ hits, seed: '1', meta: { seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [], minimumEnergyRecharge: null } });

  it('sums every hit', () => {
    expect(evaluateRecipe(recipe([hit(), hit(), hit()]), stats())).toBeCloseTo(2700, 6);
  });

  it('is zero for a recipe with no hits, rather than throwing', () => {
    expect(evaluateRecipe(recipe([]), stats())).toBe(0);
  });

  it('respects each hit’s own element', () => {
    const mixed = recipe([hit({ element: 'cryo' }), hit({ element: 'physical' })]);

    expect(evaluateRecipe(mixed, stats({ elementBonus: { cryo: 1 } }))).toBeCloseTo(2700, 6);
  });
});

describe('energyRatio — weighing Energy Recharge', () => {
  /**
   * The owner's ask: *"it doesn't do anything above the threshold where the character can burst
   * on time, but if they can't, the DPS gain from ER should be evaluated in whether or not the
   * reduced delay is worth the cost of dropping dps stats."*
   *
   * And their correction, which is why this measures DPS rather than burst damage: *"The burst
   * causes a delay, which reduces team DPS significantly. And her burst provides a buff
   * teamwide so it carries more weight than its full damage."*
   */
  const SWEEP = [
    { energyRecharge: 0.2, burstInstances: 2, standardDeviation: 0, dps: 160000 },
    { energyRecharge: 0.45, burstInstances: 3, standardDeviation: 0, dps: 180000 },
    { energyRecharge: 0.8, burstInstances: 4, standardDeviation: 0, dps: 200000 },
  ];

  const recipeWith = (meta: Record<string, unknown>) => ({
    hits: [],
    meta: {
      seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [],
      minimumEnergyRecharge: null, ...meta,
    },
  } as unknown as Recipe);

  const withEr = (energyRecharge: number) => ({ ...NO_STATS, energyRecharge });

  it('is 1 at the ER the calibration ran at', () => {
    const recipe = recipeWith({ energySweep: SWEEP, calibratedEnergyDps: 180000 });
    expect(energyRatio(recipe, withEr(0.45))).toBe(1);
  });

  it('is below 1 for a candidate that cannot burst on time', () => {
    // Not "fewer burst hits" — less team DPS, which is what the delay and the missing buff
    // actually cost.
    const recipe = recipeWith({ energySweep: SWEEP, calibratedEnergyDps: 180000 });
    expect(energyRatio(recipe, withEr(0.2))).toBeCloseTo(160000 / 180000);
  });

  it('rewards ER that buys a burst the calibration did not have', () => {
    const recipe = recipeWith({ energySweep: SWEEP, calibratedEnergyDps: 180000 });
    expect(energyRatio(recipe, withEr(0.9))).toBeCloseTo(200000 / 180000);
  });

  it('is a step function between rungs, because each rung is a run', () => {
    const recipe = recipeWith({ energySweep: SWEEP, calibratedEnergyDps: 180000 });
    expect(energyRatio(recipe, withEr(0.79))).toBeCloseTo(1);
  });

  it('is 1 when no ladder was measured', () => {
    expect(energyRatio(recipeWith({ calibratedEnergyDps: 180000 }), withEr(0))).toBe(1);
  });

  it('is 1 when a ladder carries no DPS', () => {
    // An older cached recipe, or a rung gcsim would not price. Nothing is scaled.
    const bare = SWEEP.map(({ dps: _dps, ...rest }) => rest);
    expect(energyRatio(recipeWith({ energySweep: bare, calibratedEnergyDps: 180000 }),
      withEr(0.2))).toBe(1);
  });
});
