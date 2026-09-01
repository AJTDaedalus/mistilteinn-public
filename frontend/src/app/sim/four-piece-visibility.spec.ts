import { describe, expect, it } from 'vitest';

import type { Recipe, RecipeHit } from './recipe';
import { fourPieceSetOf, searchRecipe } from './recipe-search';
import { search, type Candidate, type SetBonus } from './search';

/**
 * R.7 — a conditional 4-piece bonus changes the ranking, and did not before.
 *
 * **This is the test the whole chunk is for.** `RESEARCH_conditional_sets.md`: every 4-piece
 * bonus in the game is conditional, so `_bonus_stats` hands the kernel an **empty stat dict**
 * for all 60 of them. R.2 measured what that costs — the kernel understates a set by
 * **15–25 %** — and the single-hit search therefore ranks four-piece sets as though their
 * headline effect did not exist.
 *
 * The contrast below is the claim: **the same inventory, ranked one way by `search` and the
 * other way by `searchRecipe`.**
 */

const SLOTS = ['equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring', 'equip_dress'];

/** The set whose 4-piece is conditional — the kernel sees nothing from it. */
const CONDITIONAL = 1;
/** A set whose bonus is plain stats — the kernel already gets this one right. */
const STATIC = 2;

const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
  mine: true,
  owner: 0,
  abil: 'x', attackTag: 1, element: 'cryo', talent: 2, scaling: 'atk', flatDamage: 0,
  calibratedScaling: 1000, conversions: {},
  calibratedBase: { atk: 1000, hp: 10000, def: 800 },
  calibratedPercent: { atk: 0, hp: 0, def: 0 },
  calibratedFlat: { atk: 0, hp: 0, def: 0 },
  bonusDmg: 0, critRate: 0, critDmg: 0, defMultiplier: 0.5, resMultiplier: 0.9,
  ampMultiplier: 1, gcsimAverageDamage: 900, ...over,
});

const recipe = (hits: RecipeHit[], calibratedSetId: number | null = null): Recipe => ({
  hits,
  seed: '1',
  meta: {
    seed: '1',
    staleConversions: [], characters: [], unstable: [],
    // Plural since B.3: a 2+2 calibration equips two sets. This helper still takes one,
    // because every case here is a 4-piece or none.
    calibratedSetIds: calibratedSetId === null ? [] : [calibratedSetId],
    minimumEnergyRecharge: null, energyDelays: [],
  },
});

/** Five pieces of one set, identical stats, so only the set bonus can separate them. */
function piecesOf(setId: number): Candidate[] {
  return SLOTS.map((slot, i) =>
    ({ id: `${setId}-${i}`, slot, setId, stats: { atk_pct: 0.1 } } as Candidate));
}

/**
 * What the kernel is given: the **static** tier only.
 *
 * The conditional set's 4-piece contributes an **empty stat dict**, which is exactly what
 * `builds.py:_bonus_stats` produces for a tier whose props are all `FIGHT_PROP_NONE`.
 */
const KERNEL_BONUSES: SetBonus[] = [
  { setId: CONDITIONAL, piecesRequired: 4, stats: {} },
  { setId: STATIC, piecesRequired: 4, stats: { atk_pct: 0.2 } },
];

describe('a conditional 4-piece bonus', () => {
  const inventory = [...piecesOf(CONDITIONAL), ...piecesOf(STATIC)];

  it('is invisible to the single-hit search, which ranks the static set first', () => {
    // The conditional set contributes nothing, so the static set's +20% ATK wins by default.
    // This is today's behaviour, and it is the bug.
    const out = search(inventory, {
      base: { base_atk: 1000, crit_rate: 0.05, crit_dmg: 0.5 },
      hit: {
        multiplier: 2, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0,
        amplifying: null, reactionBonus: 0,
      },
      target: { level: 90, resistance: 0.1, defReduction: 0, defIgnore: 0 },
      characterLevel: 90, dmgBonusQuantity: 'cryo_dmg_bonus', topN: 1,
      setBonuses: KERNEL_BONUSES,
    });

    // Asserted as "reaches a 4-piece of", not "is five pieces of": the pieces are identical,
    // so a 4+1 mix ties with 5+0 and the tie-break decides between them. Which 4-piece bonus
    // the winner gets is the claim; how the fifth slot fell is not.
    expect(fourPieceSetOf(out.builds[0].setCounts)).toBe(STATIC);
  });

  it('changes the ranking once a recipe holds it', () => {
    // The conditional set's recipe was calibrated with the set equipped, so gcsim applied its
    // 4-piece and it is baked into every term — here, a talent worth 40% more damage than the
    // static set's +20% ATK buys.
    const out = searchRecipe(inventory, {
      recipes: {
        byFourPieceSet: new Map([
          [CONDITIONAL, recipe([hit({ talent: 2.8 })], CONDITIONAL)],
          [STATIC, recipe([hit()], STATIC)],
        ]),
        noFourPiece: recipe([hit()]),
      },
      setBonuses: KERNEL_BONUSES,
      topN: 1,
    });

    expect(fourPieceSetOf(out.builds[0].setCounts)).toBe(CONDITIONAL);
  });

  it('is the same inventory and the same set bonuses in both', () => {
    // Guards the contrast from being an artefact of two different setups. If this ever fails,
    // the two tests above are not comparing what they claim to.
    expect(inventory).toHaveLength(10);
    expect(KERNEL_BONUSES.find((b) => b.setId === CONDITIONAL)!.stats).toEqual({});
  });
});
