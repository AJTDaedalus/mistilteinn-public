import { describe, expect, it, vi } from 'vitest';

import { type StatPool } from './artifact-score';
import { sampleBeatProbability } from './fresh-drop-sampler';
import { evaluateRecipe } from './recipe-eval';
import { candidateStatsFrom, liveQuantitiesFor } from './recipe-search';
import {
  EstimateCancelled, type SlotBeatInput, newBeatCache, slotBeatProbability,
  slotBeatProbabilityAsync, weightSensitivity, weightSensitivityAsync,
} from './upgrade-estimate';
import {
  CIRCLET, FLOWER, LADDERS, MAIN_VALUES, OTHERS, WEIGHTS, syntheticRecipe,
} from './upgrade-fixtures';

/**
 * `docs/TASKS_upgrade_estimator.md` Task 6. The exact pass is judged by the literal sampler
 * (Task 5), which shares nothing with it but the tables and the evaluator.
 */

const recipe = syntheticRecipe(20);
const live = new Set(liveQuantitiesFor(recipe));

/** Damage with `piece` in the circlet slot and the four fixture pieces in the others. */
const circletDamage = (piece: StatPool): number =>
  evaluateRecipe(recipe, candidateStatsFrom([...OTHERS, piece]));

/** A mediocre CRIT circlet: what most players are wearing when they ask. */
const MEDIOCRE = { crit_dmg: 0.622, crit_rate: 0.07, atk_pct: 0.1, flat_def: 40 };
/** A strong one. */
const STRONG = { crit_rate: 0.311, crit_dmg: 0.30, atk_pct: 0.15, energy_recharge: 0.05 };

function input(threshold: number, over: Partial<SlotBeatInput> = {}): SlotBeatInput {
  return {
    mainStatProbabilities: CIRCLET,
    mainStatValues: MAIN_VALUES,
    substatWeights: WEIGHTS,
    ladders: LADDERS,
    fourLineShare: 0.2,
    live,
    evaluate: circletDamage,
    threshold,
    ...over,
  };
}

function sampled(threshold: number, evaluate = circletDamage, mains = CIRCLET) {
  return sampleBeatProbability({
    mainStatProbabilities: mains,
    mainStatValues: MAIN_VALUES,
    substatWeights: WEIGHTS,
    ladders: LADDERS,
    fourLineShare: 0.2,
  }, evaluate, threshold, 60_000, 20261024);
}

/**
 * A sampler spec draws tens of thousands of artifacts. About 2 s alone, but `ci_local` runs the
 * suite beside the backend jobs, and one timed out at vitest's 5 s default there.
 */
const SAMPLER_TIMEOUT = 60_000;

// Every spec here enumerates or samples for real; none is a unit-sized check.
vi.setConfig({ testTimeout: SAMPLER_TIMEOUT });

describe('slotBeatProbability', () => {
  it('lies inside the sampler interval against a mediocre circlet, +1%', () => {
    const threshold = circletDamage(MEDIOCRE) * 1.01;
    const exact = slotBeatProbability(input(threshold)).pBeat;
    const mc = sampled(threshold);
    expect(exact).toBeGreaterThan(1e-2);
    expect(exact).toBeGreaterThanOrEqual(mc.low);
    expect(exact).toBeLessThanOrEqual(mc.high);
  }, SAMPLER_TIMEOUT);

  it('lies inside the sampler interval on a flower, where only substats move', () => {
    const flowerDamage = (piece: StatPool) =>
      evaluateRecipe(recipe, candidateStatsFrom([piece, ...OTHERS.slice(1), MEDIOCRE]));
    const threshold = flowerDamage(OTHERS[0]);
    const exact = slotBeatProbability(input(threshold, {
      mainStatProbabilities: FLOWER, evaluate: flowerDamage,
    })).pBeat;
    const mc = sampled(threshold, flowerDamage, FLOWER);
    expect(exact).toBeGreaterThan(1e-2);
    expect(exact).toBeGreaterThanOrEqual(mc.low);
    expect(exact).toBeLessThanOrEqual(mc.high);
  }, SAMPLER_TIMEOUT);

  it('lies inside the sampler interval on a linear toy evaluator', () => {
    const linear = (s: StatPool) => 3 * (s['crit_rate'] ?? 0) + (s['crit_dmg'] ?? 0)
      + 0.5 * (s['atk_pct'] ?? 0);
    const threshold = 0.45;
    const exact = slotBeatProbability(input(threshold, {
      evaluate: linear, live: new Set(['crit_rate', 'crit_dmg', 'atk_pct']),
    })).pBeat;
    const mc = sampled(threshold, linear);
    expect(exact).toBeGreaterThan(1e-2);
    expect(exact).toBeGreaterThanOrEqual(mc.low);
    expect(exact).toBeLessThanOrEqual(mc.high);
  }, SAMPLER_TIMEOUT);

  it('proves zero for a bar no drop can clear, without enumerating', () => {
    const found = slotBeatProbability(input(circletDamage(STRONG) * 10));
    expect(found.pBeat).toBe(0);
    // Two bound checks per question and nothing else.
    expect(found.evaluations).toBeLessThanOrEqual(2 * found.questions);
  });

  it('is certain for a bar every drop clears', () => {
    expect(slotBeatProbability(input(0)).pBeat).toBeCloseTo(1, 12);
  });

  it('gets the same answer with the dead-stat collapse as without it', () => {
    const threshold = circletDamage(MEDIOCRE) * 1.01;
    const collapsed = slotBeatProbability(input(threshold));
    const full = slotBeatProbability(input(threshold, { live: new Set(Object.keys(WEIGHTS)) }));
    expect(collapsed.pBeat).toBeCloseTo(full.pBeat, 12);
    expect(collapsed.questions).toBeLessThan(full.questions);
    // Without the collapse every stat is enumerated: that is the cost the collapse removes, and
    // under jsdom it is tens of seconds.
  }, 120_000);

  it('reports a smaller probability against a stronger piece', () => {
    const weak = slotBeatProbability(input(circletDamage(MEDIOCRE) * 1.01)).pBeat;
    const strong = slotBeatProbability(input(circletDamage(STRONG) * 1.01)).pBeat;
    expect(strong).toBeLessThan(weak);
    expect(strong).toBeGreaterThan(0);
  });

  it('splits the slot by main stat, and the split recombines', () => {
    const found = slotBeatProbability(input(circletDamage(MEDIOCRE) * 1.01));
    const recombined = found.byMain.reduce((a, r) => a + r.pMain * r.pBeat, 0);
    expect(recombined).toBeCloseTo(found.pBeat, 14);
    // A healing-bonus circlet cannot beat a CRIT circlet on a damage build.
    expect(found.byMain.find((r) => r.main === 'healing_bonus')!.pBeat).toBe(0);
  });
});

describe('the evaluator is monotone, which the bounds rely on', () => {
  it('never loses damage when any substat rises', () => {
    let seed = 1;
    const random = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let trial = 0; trial < 300; trial += 1) {
      const piece: Record<string, number> = {};
      for (const q of Object.keys(LADDERS)) piece[q] = random() * 6 * LADDERS[q][3];
      const before = circletDamage(piece);
      const q = Object.keys(LADDERS)[Math.floor(random() * 10)];
      const after = circletDamage({ ...piece, [q]: piece[q] + LADDERS[q][0] });
      expect(after).toBeGreaterThanOrEqual(before);
    }
  });
});

describe('weightSensitivity', () => {
  it('brackets the unperturbed answer and reuses the enumeration', () => {
    const cache = newBeatCache();
    const base = input(circletDamage(MEDIOCRE) * 1.01);
    const first = slotBeatProbability(base, cache);
    const range = weightSensitivity(base, cache);
    expect(range.low).toBeLessThanOrEqual(first.pBeat);
    expect(range.high).toBeGreaterThanOrEqual(first.pBeat);
    expect(range.high).toBeGreaterThan(range.low);
  });
});

describe('slotBeatProbabilityAsync', () => {
  it('gives exactly the synchronous answer', async () => {
    const base = input(circletDamage(MEDIOCRE) * 1.01);
    const sync = slotBeatProbability(base);
    const async = await slotBeatProbabilityAsync(base, newBeatCache(), { budgetMs: 0 });
    expect(async.pBeat).toBe(sync.pBeat);
    const cache = newBeatCache();
    slotBeatProbability(base, cache);
    expect(await weightSensitivityAsync(base, cache)).toEqual(weightSensitivity(base, cache));
  }, 60_000);

  it('stops when asked', async () => {
    const base = input(circletDamage(MEDIOCRE) * 1.01);
    await expect(
      slotBeatProbabilityAsync(base, newBeatCache(), { budgetMs: 0, shouldCancel: () => true }),
    ).rejects.toBeInstanceOf(EstimateCancelled);
  });
});
