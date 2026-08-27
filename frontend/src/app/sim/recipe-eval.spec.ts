import { describe, expect, it } from 'vitest';

import { NO_STATS, evaluateHit, evaluateRecipe, type CandidateStats } from './recipe-eval';
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
  abil: 'x', attackTag: 1, element: 'cryo', talent: 2, scaling: 'atk', flatDamage: 0,
  // **Deliberately different.** In a valid recipe these are equal — calibration runs at zero
  // artifact stats — so a stub that makes them equal cannot tell `baseStat` from
  // `calibratedScaling`, and the mutation swapping them survives. The gate cannot catch that
  // either, for the same reason, so this is the only place it can be caught.
  calibratedScaling: 1500, baseStat: 1000, bonusDmg: 0, critRate: 0, critDmg: 0,
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
    ['hp', { hpPercent: 1 }],
    ['def', { defPercent: 1 }],
  ] as const)('scales off %s when the ability does', (scaling, over) => {
    expect(evaluateHit(hit({ scaling }), stats(over))).toBeCloseTo(1800, 6);
    // …and is unmoved by a stat it does not scale off.
    expect(evaluateHit(hit({ scaling }), stats({ atkPercent: 1 }))).toBeCloseTo(900, 6);
  });

  it('takes elemental mastery whole, since it has no percentage form', () => {
    expect(evaluateHit(hit({ scaling: 'em' }), stats({ elementalMastery: 200 })))
      .toBeCloseTo(1080, 6);
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

describe('evaluateRecipe', () => {
  const recipe = (hits: RecipeHit[]): Recipe =>
    ({ hits, seed: '1', meta: { seed: '1', staleConversions: [] } });

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
