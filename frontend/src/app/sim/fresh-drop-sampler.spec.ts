import { describe, expect, it } from 'vitest';

import { sampleBeatProbability, sampleFreshDrop, seededRandom } from './fresh-drop-sampler';
import { CIRCLET, LADDERS, MAIN_VALUES, WEIGHTS } from './upgrade-fixtures';

const MODEL = {
  mainStatProbabilities: CIRCLET,
  mainStatValues: MAIN_VALUES,
  substatWeights: WEIGHTS,
  ladders: LADDERS,
  fourLineShare: 0.2,
};

/** `docs/TASKS_upgrade_estimator.md` Task 5 — the oracle has to be right before it judges. */
/**
 * A sampler spec draws tens of thousands of artifacts. About 2 s alone, but `ci_local` runs the
 * suite beside the backend jobs, and one timed out at vitest's 5 s default there.
 */
const SAMPLER_TIMEOUT = 60_000;

describe('fresh-drop sampler', () => {
  it('makes pieces with a main stat and four distinct substats', () => {
    const random = seededRandom(7);
    for (let i = 0; i < 200; i += 1) {
      const piece = sampleFreshDrop(MODEL, random);
      expect(Object.keys(piece)).toHaveLength(5);
    }
  });

  it('agrees with a closed form on a linear evaluator', () => {
    // P(the piece has a CRIT DMG line) on a flower (main flat HP) has a closed form under the
    // weighted draw: 1 − P(CD missed in four draws). Enumerated exactly here, no shared code.
    const pool: Record<string, number> = { ...WEIGHTS };
    delete pool['flat_hp'];
    let miss = 0;
    const walk = (left: Record<string, number>, depth: number, acc: number): void => {
      if (depth === 4) { miss += acc; return; }
      const total = Object.values(left).reduce((a, b) => a + b, 0);
      for (const [q, w] of Object.entries(left)) {
        if (q === 'crit_dmg') continue;
        const next = { ...left };
        delete next[q];
        walk(next, depth + 1, acc * (w / total));
      }
    };
    walk(pool, 0, 1);
    const flower = { ...MODEL, mainStatProbabilities: { flat_hp: 1 } };
    const sampled = sampleBeatProbability(flower, (s) => s['crit_dmg'] ?? 0, 0, 40_000, 11);
    expect(sampled.low).toBeLessThanOrEqual(1 - miss);
    expect(sampled.high).toBeGreaterThanOrEqual(1 - miss);
  }, SAMPLER_TIMEOUT);
});
