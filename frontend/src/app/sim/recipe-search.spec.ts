import { describe, expect, it } from 'vitest';

import {
  candidateStatsFrom,
  fourPieceSetOf,
  liveQuantitiesFor,
  pairKey,
  searchRecipe,
} from './recipe-search';
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
  mine: true,
  owner: 0,
  abil: 'x', attackTag: 1, element: 'geo', talent: 2, scaling: 'atk', flatDamage: 0,
  calibratedScaling: 1000, conversions: {},
  calibratedBase: { atk: 1000, hp: 10000, def: 800 },
  calibratedPercent: { atk: 0, hp: 0, def: 0 },
  calibratedFlat: { atk: 0, hp: 0, def: 0 },
  bonusDmg: 0, critRate: 0, critDmg: 0, defMultiplier: 0.5, resMultiplier: 0.9,
  ampMultiplier: 1, gcsimAverageDamage: 900, ...over,
});

/** A recipe set with a single fallback — the shape most of these tests need. */
const only = (r: Recipe) => ({ byFourPieceSet: new Map<number, Recipe>(), noFourPiece: r });

const recipe = (hits: RecipeHit[]): Recipe =>
  ({ hits, seed: '1', meta: { seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [], minimumEnergyRecharge: null } });

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
    // Covering set 1 matters: every piece `inventory()` makes is set 1, so a recipe set that
    // covers only the no-4-piece state scores **nothing** — the earlier fixture walked all 32
    // combinations and rejected each, then asserted the walk count of a search that returned
    // no builds at all.
    const viaRecipe = searchRecipe(inv, {
      recipes: { byFourPieceSet: new Map([[1, withConversion]]), noFourPiece: withConversion },
      topN: 32,
    });

    expect(singleHit.paretoRemoved).toBe(5);
    expect(singleHit.evaluated).toBe(1);
    expect(viaRecipe.paretoRemoved).toBe(0);
    expect(viaRecipe.evaluated).toBe(32);
    expect(viaRecipe.builds).toHaveLength(32);
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

    expect(searchRecipe(inv, { recipes: only(frozen), topN: 32 }).paretoRemoved).toBe(5);
    expect(searchRecipe(inv, { recipes: only(resolved), topN: 32 }).paretoRemoved).toBe(0);
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

    const base = recipe([hit()]);
    const out = searchRecipe(atkOnly, {
      recipes: { byFourPieceSet: new Map([[1, base]]), noFourPiece: base }, topN: 1,
    });

    expect(out.builds[0].damage).toBeCloseTo(2250, 3);
  });

  it('does not add the bonuses of the set the recipe was calibrated with', () => {
    // Equipping a set to calibrate also applies its 2-piece — measured as an exact
    // cryo% +0.150 for Blizzard Strayer — so it is already in every term of the recipe.
    // Adding the tier here would land it twice.
    const calibrated: Recipe = {
      hits: [hit()], seed: '1',
      meta: { seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [1], minimumEnergyRecharge: null },
    };
    const uncalibrated: Recipe = {
      hits: [hit()], seed: '1',
      meta: { seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [], minimumEnergyRecharge: null },
    };
    const bonuses = [{ setId: 1, piecesRequired: 4, stats: { atk_pct: 1 } }];
    const inv = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: 1, stats: {} } as Candidate));

    // Five pieces of set 1 reach a 4-piece, so the recipe must be registered for that set —
    // which is the realistic arrangement anyway: a recipe calibrated with set 1 is the one a
    // 4-piece of set 1 is scored against.
    const forSet1 = (r: Recipe) => ({ byFourPieceSet: new Map([[1, r]]), noFourPiece: r });
    const withSkip = searchRecipe(inv, { recipes: forSet1(calibrated), setBonuses: bonuses, topN: 1 });
    const without = searchRecipe(inv, { recipes: forSet1(uncalibrated), setBonuses: bonuses, topN: 1 });

    expect(withSkip.builds[0].damage).toBeLessThan(without.builds[0].damage);
    // Precisely: the skipped run sees no ATK bonus at all — 2*1000*0.45 = 900.
    expect(withSkip.builds[0].damage).toBeCloseTo(900, 6);
  });

  it('still adds the bonuses of a set the calibration did not hold', () => {
    // A 2+2 split has a second set whose static bonus is genuinely not in the recipe.
    const calibrated: Recipe = {
      hits: [hit()], seed: '1',
      meta: { seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [1], minimumEnergyRecharge: null },
    };
    const inv = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: 2, stats: {} } as Candidate));

    const out = searchRecipe(inv, {
      recipes: { byFourPieceSet: new Map([[2, calibrated]]), noFourPiece: calibrated },
      setBonuses: [{ setId: 2, piecesRequired: 4, stats: { atk_pct: 1 } }],
      topN: 1,
    });

    // ATK doubled → 2*2000*0.45 = 1800.
    expect(out.builds[0].damage).toBeCloseTo(1800, 6);
  });

  it('reports the search as exact, because there is no lossy layer', () => {
    expect(searchRecipe(inventory(), { recipes: only(recipe([hit()])) }).isExact).toBe(true);
  });

  it('refuses a topN below one', () => {
    expect(() => searchRecipe(inventory(), { recipes: only(recipe([hit()])), topN: 0 }))
      .toThrow(/topN/);
  });
});


describe('fourPieceSetOf', () => {
  it('names the set a combination reaches four pieces of', () => {
    expect(fourPieceSetOf({ 1: 4, 2: 1 })).toBe(1);
  });

  it('is null when nothing reaches four', () => {
    // A 2+2+1 split. Its 2-piece bonuses are static and the kernel already has them.
    expect(fourPieceSetOf({ 1: 2, 2: 2, 3: 1 })).toBeNull();
  });

  it('counts five of a set as a four-piece', () => {
    expect(fourPieceSetOf({ 1: 5 })).toBe(1);
  });
});

describe('searchRecipe over several recipes', () => {
  const withSets = (map: Record<number, Recipe>, fallback: Recipe) => ({
    byFourPieceSet: new Map(Object.entries(map).map(([k, v]) => [Number(k), v])),
    noFourPiece: fallback,
  });

  it('scores a four-piece combination against that set’s recipe', () => {
    // The whole point: a 4-piece bonus is conditional and lives only inside a calibration
    // that equipped the set. Scoring against the fallback would drop it entirely.
    const strong = recipe([hit({ talent: 4 })]);
    const weak = recipe([hit({ talent: 2 })]);
    const inv = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: 7, stats: {} } as Candidate));

    const out = searchRecipe(inv, { recipes: withSets({ 7: strong }, weak), topN: 1 });

    // talent 4 x 1000 x 0.45 = 1800, against the fallback's 900.
    expect(out.builds[0].damage).toBeCloseTo(1800, 6);
  });

  it('scores a combination reaching no four-piece against the fallback', () => {
    const strong = recipe([hit({ talent: 4 })]);
    const weak = recipe([hit({ talent: 2 })]);
    // 2+2+1 across five slots reaches no 4-piece.
    const inv = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: i < 2 ? 7 : i < 4 ? 8 : 9, stats: {} } as Candidate));

    const out = searchRecipe(inv, { recipes: withSets({ 7: strong }, weak), topN: 1 });

    expect(out.builds[0].damage).toBeCloseTo(900, 6);
  });

  it('scores a 2+2 with its two-piece bonuses, and differently without them', () => {
    // **B.1.** `runRotation` passed no `setBonuses` at all. Harmless while only 4-piece
    // states are searched — those leave one spare piece, and a lone piece grants nothing —
    // but a 2+2 combination holds two live 2-piece bonuses, and omitting them understates it
    // by exactly the thing the user picked the pair for.
    //
    // The assertion is that the two scores **differ**. A test that passed with the wiring
    // dead would be decorative.
    const r = recipe([hit()]);
    const inv = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: i < 2 ? 7 : i < 4 ? 8 : 9, stats: {} } as Candidate));
    const recipes = { byFourPieceSet: new Map<number, Recipe>(), noFourPiece: r };

    const without = searchRecipe(inv, { recipes, topN: 1, fourPieceSets: [null] });
    const with_ = searchRecipe(inv, {
      recipes, topN: 1, fourPieceSets: [null],
      setBonuses: [
        { setId: 7, piecesRequired: 2, stats: { atk_pct: 0.18 } },
        { setId: 8, piecesRequired: 2, stats: { crit_rate: 0.12 } },
        // Not reached: only one piece of set 9 is in the combination.
        { setId: 9, piecesRequired: 2, stats: { atk_pct: 9 } },
      ],
    });

    expect(without.builds).toHaveLength(1);
    expect(with_.builds).toHaveLength(1);
    expect(with_.builds[0].damage).toBeGreaterThan(without.builds[0].damage);
  });

  it('does not pay a set bonus the combination has too few pieces for', () => {
    // The 1-piece leftover of a 2+2+1 must contribute nothing, or every scattered build gets
    // a bonus the game does not give.
    const r = recipe([hit()]);
    const inv = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: i < 2 ? 7 : i < 4 ? 8 : 9, stats: {} } as Candidate));
    const recipes = { byFourPieceSet: new Map<number, Recipe>(), noFourPiece: r };

    const base = searchRecipe(inv, { recipes, topN: 1, fourPieceSets: [null] });
    const withLoner = searchRecipe(inv, {
      recipes, topN: 1, fourPieceSets: [null],
      setBonuses: [{ setId: 9, piecesRequired: 2, stats: { atk_pct: 5 } }],
    });

    expect(withLoner.builds[0].damage).toBeCloseTo(base.builds[0].damage, 6);
  });

  it('reports a set it has no recipe for rather than substituting one', () => {
    // Scoring a Blizzard Strayer build against the no-set recipe understates it by the whole
    // 4-piece bonus and looks like an ordinary result.
    const inv = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: 99, stats: {} } as Candidate));

    const out = searchRecipe(inv, {
      recipes: withSets({ 7: recipe([hit()]) }, recipe([hit()])), topN: 1,
    });

    expect(out.builds).toHaveLength(0);
    // Named per set, not per combination: for a real inventory the old shape was thousands
    // of rows all saying the one thing a reader needs — *calibrate this set*.
    expect(out.uncoveredSets).toEqual([99]);
  });

  it('takes the UNION of every recipe’s live quantities', () => {
    // R.6, and the one place a bug here gives a wrong answer rather than a slow one. DEF is
    // dead weight for one recipe and decisive for another; intersecting would prune the
    // second's winner before it was ever scored.
    const defRecipe = recipe([hit({
      flatDamage: 320, conversions: { flatDamage: { from: 'def', perUnit: 0.4 } },
    })]);
    const atkRecipe = recipe([hit()]);

    const union = liveQuantitiesFor(atkRecipe, defRecipe);

    expect(union).toEqual(expect.arrayContaining(['atk_pct', 'def_pct', 'flat_def']));
    // …and neither recipe alone would have produced it.
    expect(liveQuantitiesFor(atkRecipe)).not.toContain('def_pct');
  });

  it('does not prune a piece that only one recipe values', () => {
    // The behavioural consequence of the union, not just its contents.
    const defRecipe = recipe([hit({
      flatDamage: 320, conversions: { flatDamage: { from: 'def', perUnit: 0.4 } },
    })]);
    const atkRecipe = recipe([hit()]);
    const inv = inventory();

    const both = searchRecipe(inv, {
      recipes: withSets({ 1: defRecipe }, atkRecipe), topN: 32,
    });
    const atkOnly = searchRecipe(inv, { recipes: only(atkRecipe), topN: 32 });

    expect(atkOnly.paretoRemoved).toBe(5);
    expect(both.paretoRemoved).toBe(0);
  });
});

describe('the branch-and-bound layer', () => {
  /**
   * Three pieces per slot, all one set, so 3^5 = 243 combinations.
   *
   * **Each piece is best at exactly one thing**, so none dominates another and all three
   * survive the Pareto layer. The first draft gave every piece a bit of everything; one piece
   * per slot then dominated the rest and the "exhaustive" walk was 8 combinations, not 243 —
   * a fixture that would have measured the Pareto layer while claiming to measure the bound.
   */
  const spread = (): Candidate[] =>
    SLOTS.flatMap((slot, s) =>
      ([
        { atk_pct: 0.5 + 0.01 * s },
        { crit_rate: 0.3 + 0.01 * s },
        { crit_dmg: 0.6 + 0.01 * s },
      ] as Record<string, number>[])
        .map((stats, k) => ({ id: `${slot}-${k}`, slot, setId: 1, stats } as Candidate)),
    );

  const covering = () => {
    const r = recipe([hit({ critRate: 0.05, critDmg: 0.5 })]);
    return { byFourPieceSet: new Map([[1, r]]), noFourPiece: r };
  };

  it('returns exactly what an exhaustive walk returns', () => {
    // **The property the whole layer rests on.** `isExact: true` is a claim that pruning
    // discarded only combinations it had *proved* could not place. A bound that is slightly
    // too tight still returns a plausible ranking — with the winner quietly missing — so the
    // guard has to be the answer itself, not the speed.
    const inv = spread();
    const recipes = covering();

    // topN above the combination count means the heap never fills, so the bound never fires.
    const exhaustive = searchRecipe(inv, { recipes, topN: 100000, fourPieceSets: [1] });
    const bounded = searchRecipe(inv, { recipes, topN: 3, fourPieceSets: [1] });

    expect(exhaustive.evaluated).toBe(243);
    expect(exhaustive.boundPruned).toBe(0);

    // **Non-vacuous or the assertion below proves nothing.** If the bound never fired, this
    // test would be comparing an exhaustive walk against itself and would pass on a bound
    // that was wired up backwards.
    expect(bounded.boundPruned).toBeGreaterThan(0);
    expect(bounded.evaluated).toBeLessThan(exhaustive.evaluated);

    expect(bounded.builds).toEqual(exhaustive.builds.slice(0, 3));
    expect(bounded.isExact).toBe(true);
  });

  it('searches only the 4-piece states it was asked for', () => {
    // The filter is what makes a real inventory finish at all: unrestricted it is 4.26e10
    // combinations. `docs/FINDINGS_shakedown.md` F2.
    const strong = recipe([hit({ talent: 4 })]);
    const weak = recipe([hit({ talent: 2 })]);
    const inv = SLOTS.map((slot, i) =>
      ({ id: `p${i}`, slot, setId: 1, stats: {} } as Candidate));

    const recipes = { byFourPieceSet: new Map([[1, strong]]), noFourPiece: weak };

    // Pinned to set 1: the five-piece combination is found and scored against set 1's recipe.
    const pinned = searchRecipe(inv, { recipes, topN: 1, fourPieceSets: [1] });
    expect(pinned.builds).toHaveLength(1);
    expect(pinned.builds[0].setCounts).toEqual({ 1: 5 });

    // Restricted to the no-4-piece state, the same inventory yields nothing — every
    // combination it can form reaches a 4-piece, which belongs to set 1's state.
    const none = searchRecipe(inv, { recipes, topN: 1, fourPieceSets: [null] });
    expect(none.builds).toHaveLength(0);
  });

  it('names a set it never searched rather than leaving it out silently', () => {
    // A user who pins one set should still be told the other sets exist and were not looked
    // at — otherwise "the best build" means "the best build among choices you did not know
    // you had made".
    const r = recipe([hit()]);
    const inv = [
      ...SLOTS.map((slot, i) => ({ id: `a${i}`, slot, setId: 1, stats: {} } as Candidate)),
      ...SLOTS.map((slot, i) => ({ id: `b${i}`, slot, setId: 2, stats: {} } as Candidate)),
    ];

    const out = searchRecipe(inv, {
      recipes: { byFourPieceSet: new Map([[1, r], [2, r]]), noFourPiece: r },
      topN: 1,
      fourPieceSets: [1],
    });

    expect(out.uncoveredSets).toEqual([2]);
  });
});

describe('2+2 pair search', () => {
  const pairRecipe = (talent: number, ids: number[]): Recipe => ({
    hits: [hit({ talent })],
    seed: '1',
    meta: {
      seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: ids, minimumEnergyRecharge: null,
    },
  });

  /** Two pieces of set 7 and 8 in every slot, plus one of set 9, so a spare exists. */
  const pairInventory = (): Candidate[] =>
    SLOTS.flatMap((slot) => [
      { id: `${slot}-7`, slot, setId: 7, stats: { atk_pct: 0.1 } },
      { id: `${slot}-8`, slot, setId: 8, stats: { atk_pct: 0.1 } },
      { id: `${slot}-9`, slot, setId: 9, stats: { atk_pct: 0.1 } },
    ] as Candidate[]);

  it('enumerates thirty slot assignments, and no combination twice', () => {
    // C(5,2) x C(3,2) = 30. The count is worth pinning, but the **distinctness** is the part
    // that bites: allowing the spare piece to belong to A or B makes the same five pieces
    // reachable from two assignments, and a duplicate build silently occupies two of the
    // top N.
    const r = pairRecipe(2, [7, 8]);
    const out = searchRecipe(pairInventory(), {
      recipes: {
        byFourPieceSet: new Map(), noFourPiece: r,
        byPair: new Map([[pairKey(7, 8), r]]),
      },
      topN: 100000,
      fourPieceSets: [],
      twoPiecePairs: [[7, 8]],
    });

    const seen = out.builds.map((b) => [...b.artifactIds].sort().join(','));
    expect(new Set(seen).size).toBe(seen.length);
    expect(out.evaluated).toBe(seen.length);
  });

  it('scores every combination it returns as a real 2+2', () => {
    const r = pairRecipe(2, [7, 8]);
    const out = searchRecipe(pairInventory(), {
      recipes: {
        byFourPieceSet: new Map(), noFourPiece: r,
        byPair: new Map([[pairKey(7, 8), r]]),
      },
      topN: 100000, fourPieceSets: [], twoPiecePairs: [[7, 8]],
    });

    expect(out.builds.length).toBeGreaterThan(0);
    for (const build of out.builds) {
      expect(build.setCounts[7]).toBeGreaterThanOrEqual(2);
      expect(build.setCounts[8]).toBeGreaterThanOrEqual(2);
      // Never a 4-piece: that is a different state with a different recipe.
      expect(Math.max(...Object.values(build.setCounts))).toBeLessThan(4);
    }
  });

  it('keys a pair the same however it is named', () => {
    // (7, 8) and (8, 7) are the same five slots. Keying them apart would calibrate the state
    // twice and let the two recipes disagree.
    expect(pairKey(7, 8)).toBe(pairKey(8, 7));
  });

  it('reports a pair it has no recipe for rather than scoring it against something else', () => {
    const r = pairRecipe(2, []);
    const out = searchRecipe(pairInventory(), {
      recipes: { byFourPieceSet: new Map(), noFourPiece: r, byPair: new Map() },
      topN: 1, fourPieceSets: [], twoPiecePairs: [[7, 8]],
    });

    expect(out.builds).toHaveLength(0);
    expect(out.uncoveredPairs).toEqual([pairKey(7, 8)]);
  });

  it('does not pay the pair’s own bonuses twice', () => {
    // Both sets are inside the calibration, so `score` must skip both. Skipping only one is
    // the bug the plural `calibratedSetIds` exists to prevent.
    const r = pairRecipe(2, [7, 8]);
    const recipes = {
      byFourPieceSet: new Map(), noFourPiece: r, byPair: new Map([[pairKey(7, 8), r]]),
    };
    const args = { topN: 1, fourPieceSets: [] as (number | null)[],
      twoPiecePairs: [[7, 8]] as [number, number][] };

    const plain = searchRecipe(pairInventory(), { recipes, ...args });
    const withBonuses = searchRecipe(pairInventory(), {
      recipes, ...args,
      setBonuses: [
        { setId: 7, piecesRequired: 2, stats: { atk_pct: 9 } },
        { setId: 8, piecesRequired: 2, stats: { atk_pct: 9 } },
      ],
    });

    expect(withBonuses.builds[0].damage).toBeCloseTo(plain.builds[0].damage, 6);
  });
});
