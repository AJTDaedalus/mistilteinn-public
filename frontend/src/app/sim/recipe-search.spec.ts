import { describe, expect, it } from 'vitest';

import { candidateStatsFrom, liveQuantitiesFor, searchRecipe } from './recipe-search';
import { search, type Candidate } from './search';
import type { Recipe, RecipeHit } from './recipe';

/**
 * G.8 — searching against a rotation instead of a single hit.
 *
 * The load-bearing test is `a Redhorn build's DEF pieces survive the Pareto layer`. Against
 * today's single-hit chain they do not: DEF is not in its live set, so a DEF piece has an
 * all-zero vector and is dominated by anything — **discarded before it is ever scored**.
 */

const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
  abil: 'x', attackTag: 1, element: 'geo', talent: 2, scaling: 'atk', flatDamage: 0,
  calibratedScaling: 1000, conversions: {},
  calibratedBase: { atk: 1000, hp: 10000, def: 800 },
  calibratedPercent: { atk: 0, hp: 0, def: 0 },
  calibratedFlat: { atk: 0, hp: 0, def: 0 },
  bonusDmg: 0, critRate: 0, critDmg: 0, defMultiplier: 0.5, resMultiplier: 0.9,
  ampMultiplier: 1, gcsimAverageDamage: 900, ...over,
});

const recipe = (hits: RecipeHit[]): Recipe =>
  ({ hits, seed: '1', meta: { seed: '1', staleConversions: [], calibratedSetId: null, minimumEnergyRecharge: null } });

const SLOTS = ['equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring', 'equip_dress'];

/** One DEF piece and one ATK piece per slot, identical otherwise. */
function inventory(): Candidate[] {
  const piece = (slot: string, id: string, stats: Record<string, number>): Candidate =>
    ({ id, slot, setId: 1, stats } as Candidate);
  return SLOTS.flatMap((slot) => [
    piece(slot, `${slot}-def`, { def_pct: 0.3 }),
    piece(slot, `${slot}-atk`, { atk_pct: 0.3 }),
  ]);
}

describe('liveQuantitiesFor', () => {
  it('includes the stat a resolved conversion draws from', () => {
    // The whole point. Redhorn converts DEF into flat damage, so DEF changes the rotation's
    // damage even though no ability scales off it.
    const r = recipe([hit({
      flatDamage: 320, conversions: { flatDamage: { from: 'def', perUnit: 0.4 } },
    })]);

    expect(liveQuantitiesFor(r)).toEqual(expect.arrayContaining(['def_pct', 'flat_def']));
  });

  it('does not include a stat nothing reads', () => {
    // An over-broad live set is not harmless: it keeps pieces the Pareto layer could have
    // dropped, and the search then walks combinations that cannot win.
    expect(liveQuantitiesFor(recipe([hit()]))).not.toEqual(expect.arrayContaining(['hp_pct']));
  });

  it('includes every element the rotation actually deals damage in', () => {
    const r = recipe([hit({ element: 'geo' }), hit({ element: 'physical' })]);

    expect(liveQuantitiesFor(r)).toEqual(
      expect.arrayContaining(['geo_dmg_bonus', 'physical_dmg_bonus']),
    );
  });

  it('includes elemental mastery when a hit amplifies', () => {
    expect(liveQuantitiesFor(recipe([hit({ ampMultiplier: 1.5 })])))
      .toContain('elemental_mastery');
  });
});

describe('candidateStatsFrom', () => {
  it('reads an element bonus under gcsim’s own element name', () => {
    const stats = candidateStatsFrom([{ cryo_dmg_bonus: 0.466 }]);

    expect(stats.elementBonus["cryo"]).toBeCloseTo(0.466, 6);
  });

  it('sums a quantity across every pool', () => {
    expect(candidateStatsFrom([{ atk_pct: 0.2 }, { atk_pct: 0.3 }]).atkPercent)
      .toBeCloseTo(0.5, 6);
  });
});

describe('searchRecipe', () => {
  it('keeps DEF pieces that the single-hit search discards', () => {
    // G.8's acceptance, stated as the contrast it is. The single-hit chain does not model
    // Redhorn's conversion, so DEF is not in its live set — every DEF piece is dominated and
    // pruned *before scoring*, and the search returns a confident answer having never
    // considered them.
    const inv = inventory();
    const withConversion = recipe([hit({
      flatDamage: 320, conversions: { flatDamage: { from: 'def', perUnit: 0.4 } },
    })]);

    const singleHit = search(inv, {
      base: { base_atk: 1000, crit_rate: 0.05, crit_dmg: 0.5 },
      hit: {
        multiplier: 2, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0,
        amplifying: null, reactionBonus: 0,
      },
      target: { level: 90, resistance: 0.1, defReduction: 0, defIgnore: 0 },
      characterLevel: 90, dmgBonusQuantity: 'geo_dmg_bonus', topN: 32,
    });
    const viaRecipe = searchRecipe(inv, { recipe: withConversion, topN: 32 });

    expect(singleHit.paretoRemoved).toBe(5);
    expect(singleHit.evaluated).toBe(1);
    expect(viaRecipe.paretoRemoved).toBe(0);
    expect(viaRecipe.evaluated).toBe(32);
  });

  it('prunes DEF while the conversion is frozen, and keeps it once resolved', () => {
    // The frozen case behaves exactly like the single-hit chain — and correctly so: a frozen
    // conversion genuinely does not respond to DEF, so DEF genuinely is not live. Resolving
    // it is what makes DEF matter, and the Pareto layer follows the objective rather than
    // being told about Redhorn.
    const inv = inventory();
    const frozen = recipe([hit({ flatDamage: 320 })]);
    const resolved = recipe([hit({
      flatDamage: 320, conversions: { flatDamage: { from: 'def', perUnit: 0.4 } },
    })]);

    expect(searchRecipe(inv, { recipe: frozen, topN: 32 }).paretoRemoved).toBe(5);
    expect(searchRecipe(inv, { recipe: resolved, topN: 32 }).paretoRemoved).toBe(0);
  });

  it('scores a combination from exactly the candidate’s own stats', () => {
    // Pins the absolute number, not just the ordering. Without this, an extra stat pool
    // folded into the score — the base pool the context deliberately no longer carries —
    // changes every damage figure while leaving pruning, ordering and exactness untouched.
    //
    // Five ATK pieces at +30% → atk% 1.5 → scaling 1000 * 2.5 = 2500; talent 2 → 5000;
    // x 0.5 x 0.9 = 2250.
    const atkOnly = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: 1, stats: { atk_pct: 0.3 } } as Candidate));

    const out = searchRecipe(atkOnly, { recipe: recipe([hit()]), topN: 1 });

    expect(out.builds[0].damage).toBeCloseTo(2250, 3);
  });

  it('does not add the bonuses of the set the recipe was calibrated with', () => {
    // Equipping a set to calibrate also applies its 2-piece — measured as an exact
    // cryo% +0.150 for Blizzard Strayer — so it is already in every term of the recipe.
    // Adding the tier here would land it twice.
    const calibrated: Recipe = {
      hits: [hit()], seed: '1',
      meta: { seed: '1', staleConversions: [], calibratedSetId: 1, minimumEnergyRecharge: null },
    };
    const uncalibrated: Recipe = {
      hits: [hit()], seed: '1',
      meta: { seed: '1', staleConversions: [], calibratedSetId: null, minimumEnergyRecharge: null },
    };
    const bonuses = [{ setId: 1, piecesRequired: 4, stats: { atk_pct: 1 } }];
    const inv = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: 1, stats: {} } as Candidate));

    const withSkip = searchRecipe(inv, { recipe: calibrated, setBonuses: bonuses, topN: 1 });
    const without = searchRecipe(inv, { recipe: uncalibrated, setBonuses: bonuses, topN: 1 });

    expect(withSkip.builds[0].damage).toBeLessThan(without.builds[0].damage);
    // Precisely: the skipped run sees no ATK bonus at all — 2*1000*0.45 = 900.
    expect(withSkip.builds[0].damage).toBeCloseTo(900, 6);
  });

  it('still adds the bonuses of a set the calibration did not hold', () => {
    // A 2+2 split has a second set whose static bonus is genuinely not in the recipe.
    const calibrated: Recipe = {
      hits: [hit()], seed: '1',
      meta: { seed: '1', staleConversions: [], calibratedSetId: 1, minimumEnergyRecharge: null },
    };
    const inv = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: 2, stats: {} } as Candidate));

    const out = searchRecipe(inv, {
      recipe: calibrated,
      setBonuses: [{ setId: 2, piecesRequired: 4, stats: { atk_pct: 1 } }],
      topN: 1,
    });

    // ATK doubled → 2*2000*0.45 = 1800.
    expect(out.builds[0].damage).toBeCloseTo(1800, 6);
  });

  it('reports the search as exact, because there is no lossy layer', () => {
    expect(searchRecipe(inventory(), { recipe: recipe([hit()]) }).isExact).toBe(true);
  });

  it('refuses a topN below one', () => {
    expect(() => searchRecipe(inventory(), { recipe: recipe([hit()]), topN: 0 }))
      .toThrow(/topN/);
  });
});
