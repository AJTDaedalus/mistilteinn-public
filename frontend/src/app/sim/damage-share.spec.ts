import { describe, expect, it } from 'vitest';

import { damageShare } from './damage-share';
import { NO_STATS } from './recipe-eval';
import type { Recipe, RecipeHit } from './recipe';

/**
 * gcsim reports who deals a rotation's damage and this app did not — which is how "the
 * character being optimized is 14% of their own rotation" stayed invisible.
 */
const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
  mine: true, owner: 0,
  abil: 'x', attackTag: -1, element: 'cryo', talent: 2, scaling: 'atk', flatDamage: 0,
  conversions: {},
  calibratedBase: { atk: 1000, hp: 10000, def: 800 },
  calibratedPercent: { atk: 0, hp: 0, def: 0 },
  calibratedFlat: { atk: 0, hp: 0, def: 0 },
  calibratedScaling: 1000, bonusDmg: 0, critRate: 0, critDmg: 0,
  defMultiplier: 0.5, resMultiplier: 0.9, ampMultiplier: 1, gcsimAverageDamage: 900,
  ...over,
});

const recipe = (hits: RecipeHit[], characters: string[] = []): Recipe => ({
  hits, seed: '1',
  meta: {
    seed: '1', staleConversions: [], unstable: [], characters,
    calibratedSetIds: [], minimumEnergyRecharge: null,
  },
} as unknown as Recipe);

describe('damageShare', () => {
  it('names each character and splits the damage between them', () => {
    const found = damageShare(recipe([
      hit({ owner: 0, mine: true }),
      hit({ owner: 1, mine: false, gcsimAverageDamage: 2700 }),
    ], ['skirk', 'furina']), NO_STATS);

    expect(found.map((c) => c.name)).toEqual(['furina', 'skirk']);
    expect(found.reduce((sum, c) => sum + c.share, 0)).toBeCloseTo(1, 9);
  });

  it('sorts by damage, so the biggest contributor is first', () => {
    const found = damageShare(recipe([
      hit({ owner: 0, mine: true }),
      hit({ owner: 1, mine: false, gcsimAverageDamage: 999999 }),
    ], ['skirk', 'furina']), NO_STATS);

    expect(found[0].name).toBe('furina');
    expect(found[0].share).toBeGreaterThan(found[1].share);
  });

  it('marks the character the search is choosing for', () => {
    // On a support-heavy team this row is a small slice, and saying which slice is the point:
    // a build whose teammates are most of the damage cannot move the total much.
    const found = damageShare(recipe([
      hit({ owner: 0, mine: true }),
      hit({ owner: 1, mine: false }),
    ], ['skirk', 'furina']), NO_STATS);

    expect(found.find((c) => c.mine)?.name).toBe('skirk');
    expect(found.filter((c) => c.mine)).toHaveLength(1);
  });

  it("grows the optimized character's slice as their artifacts improve", () => {
    // **Evaluated, not calibrated.** Using `gcsimAverageDamage` would report the calibration's
    // split for every row alike and describe a build nobody is looking at.
    const build = recipe([
      hit({ owner: 0, mine: true }),
      hit({ owner: 1, mine: false }),
    ], ['skirk', 'furina']);

    const bare = damageShare(build, NO_STATS).find((c) => c.mine)!.share;
    const buffed = damageShare(build, { ...NO_STATS, atkPercent: 2 }).find((c) => c.mine)!.share;

    expect(buffed).toBeGreaterThan(bare);
  });

  it('falls back to an index when the recipe carries no names', () => {
    // A recipe cached before the field existed, or a server that does not publish the order.
    const found = damageShare(recipe([hit({ owner: 2 })], []), NO_STATS);

    expect(found[0].name).toBe('character 3');
  });

  it('reports zero rather than NaN when nothing landed', () => {
    // `0/0` renders into the page as NaN rather than being refused.
    const found = damageShare(recipe([hit({ mine: false, gcsimAverageDamage: 0 })]), NO_STATS);

    expect(found[0].share).toBe(0);
  });
});
