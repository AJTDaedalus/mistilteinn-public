import { describe, expect, it } from 'vitest';

import { rowHits, synthesizeRecipe, type FormulaRow, type FormulaTeam } from './formula-recipe';
import { cappedAmount, type Recipe, type RecipeHit } from './recipe';
import { evaluateHit, evaluateRecipe, NO_STATS } from './recipe-eval';
import { candidateStatsFrom, liveQuantitiesFor, searchRecipe } from './recipe-search';
import { type Candidate, type SearchContext, search, SLOTS } from './search';

/**
 * Capped self-conversions in the formula estimate — owner ruling 2026-11-14 (`docs/DECISIONS.md`
 * §40): *"Price exactly per build."* A kit whose giver is the optimized character and reads one
 * of their artifact-moved stats through a cap (Hu Tao's ATK from HP up to 400% of her base ATK,
 * Clorinde's A1 up to 1,800 flat damage, Nahida's A4 above 200 EM up to 80% / 24%, Furina's,
 * Alhaitham's and Tighnari's A4) is `min(perUnit × max(stat − threshold, 0), cap)` for each
 * candidate.
 *
 * Three properties carry the feature and each has a test here: below the cap the term is
 * linear, above it flat, at it exact; the search's bound stays admissible, so a bounded walk
 * returns exactly what an exhaustive one does; and the planted mistakes — the cap ignored, the
 * stat frozen at the zero-artifact build — are told apart from the right answer (also held
 * against the GO fixtures by `scripts/verify-formula-recipe.mjs`).
 */

const TOLERANCE = 1e-6;

/** A Pyro polearm user at 90: Hu Tao's shape, the kernel's spelling of `/search-context`. */
function context(overrides: Partial<SearchContext['hit']> = {}, base = {}): SearchContext {
  return {
    base: {
      base_atk: 715, atk_pct: 0, flat_atk: 0,
      base_hp: 15552, hp_pct: 0, flat_hp: 0,
      base_def: 876, def_pct: 0, flat_def: 0,
      elemental_mastery: 0, crit_rate: 0.05, crit_dmg: 0.884, energy_recharge: 1.0,
      pyro_dmg_bonus: 0,
      ...base,
    },
    hit: {
      multiplier: 1.152, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0,
      amplifying: null, reactionBonus: 0, ...overrides,
    },
    target: { level: 100, resistance: 0.1, defReduction: 0, defIgnore: 0 },
    characterLevel: 90,
    dmgBonusQuantity: 'pyro_dmg_bonus',
  };
}

const TEAM: FormulaTeam = {
  element: 'pyro', weaponType: 'WEAPON_POLE', memberElements: ['pyro', 'hydro'],
};

const row = (ctx: SearchContext, extra: Partial<FormulaRow> = {}): FormulaRow => ({
  id: 'r1', label: 'Blood Blossom DMG', move: 'skill', count: 1, context: ctx, ...extra,
});

interface Fx {
  stat: string;
  value: number;
  cap?: number;
  threshold?: number;
  elements?: string[];
  moves?: string[];
  per?: string;
}

const KIT = (...effects: Fx[]) => ({
  id: 'kit:x', label: 'X (kit)', citation: 'GO',
  bonus: {
    conditions: [{
      key: 'stacks', label: 'stacks', kind: 'stacks' as const, default: 3,
      default_reason: 'self' as const, max: 3,
    }],
    effects: effects.map((e) => ({ when: [], ...e })),
    unmodelled: [],
  },
});

/** The kernel's score of one piece's stats, the single-hit chain's own arithmetic. */
function kernel(ctx: SearchContext, stats: Record<string, number>): number {
  const piece: Candidate = { id: 'p', slot: 'equip_bracer', setId: 1, stats };
  const filler = SLOTS.slice(1).map((slot, i) => ({ id: `f${i}`, slot, setId: 2, stats: {} }));
  return search([piece, ...filler], { ...ctx, setBonuses: [], topN: 1, prefilterTopK: -1 })
    .builds[0].damage;
}

const close = (got: number, want: number) =>
  expect(Math.abs(got - want) / Math.abs(want)).toBeLessThan(TOLERANCE);

describe('cappedAmount', () => {
  it('is linear below the cap, flat above it, and exact at it', () => {
    expect(cappedAmount(0.5, 100, undefined, 80)).toBe(50);
    expect(cappedAmount(0.5, 160, undefined, 80)).toBe(80);
    expect(cappedAmount(0.5, 1000, undefined, 80)).toBe(80);
    expect(cappedAmount(0.5, 159.999, undefined, 80)).toBeCloseTo(79.9995, 12);
  });

  it('counts only the stat above a threshold, and never below zero', () => {
    // Nahida's A4: 0.1% per EM above 200, 800 counted at most (80%).
    expect(cappedAmount(0.001, 150, 200, 0.8)).toBe(0);
    expect(cappedAmount(0.001, 200, 200, 0.8)).toBe(0);
    expect(cappedAmount(0.001, 700, 200, 0.8)).toBeCloseTo(0.5, 12);
    expect(cappedAmount(0.001, 1000, 200, 0.8)).toBeCloseTo(0.8, 12);
    expect(cappedAmount(0.001, 1400, 200, 0.8)).toBeCloseTo(0.8, 12);
  });

  it('is non-decreasing in the stat: the property the search bound rests on', () => {
    let last = -Infinity;
    for (let s = 0; s <= 2000; s += 7) {
      const v = cappedAmount(0.001, s, 200, 0.8);
      expect(v).toBeGreaterThanOrEqual(last);
      last = v;
    }
  });
});

describe("Hu Tao's ATK from her Max HP, capped at 400% of her base ATK", () => {
  // 6.256% of HP, at most 4 × 715 = 2,860 ATK.
  const fx = { stat: 'flat_atk_from_hp', value: 0.06256, cap: 2860 };
  const hpTotal = (hpPct: number, flatHp: number) => 15552 * (1 + hpPct) + flatHp;

  it('is the kernel with the converted ATK as flat ATK, below the cap', () => {
    const recipe = synthesizeRecipe([row(context())], [KIT(fx)], TEAM);
    const stats = { hp_pct: 0.466, flat_hp: 4780 };
    const atk = 0.06256 * hpTotal(0.466, 4780);
    expect(atk).toBeLessThan(2860);
    close(evaluateRecipe(recipe, candidateStatsFrom([stats])),
      kernel(context({}, { flat_atk: atk }), stats));
  });

  it('is flat past the cap: more HP buys nothing', () => {
    const recipe = synthesizeRecipe([row(context())], [KIT(fx)], TEAM);
    const big = { hp_pct: 2.5, flat_hp: 4780 };
    const bigger = { hp_pct: 3.5, flat_hp: 4780 };
    expect(0.06256 * hpTotal(2.5, 4780)).toBeGreaterThan(2860);
    const a = evaluateRecipe(recipe, candidateStatsFrom([big]));
    const b = evaluateRecipe(recipe, candidateStatsFrom([bigger]));
    close(a, kernel(context({}, { flat_atk: 2860 }), big));
    expect(b).toBeCloseTo(a, 9);
  });

  it('is exact at the cap', () => {
    const recipe = synthesizeRecipe([row(context())], [KIT(fx)], TEAM);
    // The HP% at which 6.256% of HP is exactly 2,860.
    const hpPct = (2860 / 0.06256) / 15552 - 1;
    const stats = { hp_pct: hpPct };
    close(evaluateRecipe(recipe, candidateStatsFrom([stats])),
      kernel(context({}, { flat_atk: 2860 }), stats));
  });

  it('lands in flat ATK beside a teammate\'s flat ATK, and keeps HP live', () => {
    const teammate = { stat: 'flat_atk', value: 800 };
    const recipe = synthesizeRecipe([row(context())], [KIT(fx, teammate)], TEAM);
    expect(recipe.hits[0].conversions.flatAtk).toEqual(
      { from: 'hp', perUnit: 0.06256, cap: 2860, offset: 800 },
    );
    expect(liveQuantitiesFor(recipe)).toEqual(expect.arrayContaining(['hp_pct', 'flat_hp']));
    const stats = { hp_pct: 3 };
    close(evaluateRecipe(recipe, candidateStatsFrom([stats])),
      kernel(context({}, { flat_atk: 800 + 2860 }), stats));
  });

  it('refuses a second conversion into flat ATK on the same hit', () => {
    expect(() => synthesizeRecipe([row(context())],
      [KIT(fx, { stat: 'flat_atk_from_def', value: 0.5 })], TEAM)).toThrow(/two conversions/);
  });
});

describe("Clorinde's A1: flat damage from her ATK per stack, the total capped", () => {
  // 20% of ATK per stack, three stacks, at most 1,800 (GO `min(max, prod(ratio, atk, stacks))`).
  const fx = { stat: 'flat_damage_from_atk', value: 0.2, cap: 1800, per: 'stacks' };

  it('caps the stacked total, not each stack, and folds a count into the cap', () => {
    const ctx = context({ multiplier: 2.28384 });
    const [hit] = rowHits(row(ctx, { count: 5, move: 'burst' }), [KIT(fx)], TEAM, {}).hits;
    // Three stacks × 0.2, five hits: slope 3 per ATK, cap 9,000.
    const flat = hit.conversions.flatDamage!;
    expect([flat.from, flat.cap, flat.threshold]).toEqual(['atk', 9000, undefined]);
    expect(flat.perUnit).toBeCloseTo(3, 12);

    const lowAtk = { atk_pct: 0 };     // ATK 715: 0.6 × 715 = 429, below 1,800
    const highAtk = { atk_pct: 3 };    // ATK 2,860: 0.6 × 2,860 = 1,716, below
    const pastCap = { atk_pct: 4 };    // ATK 3,575: 2,145 > 1,800, capped
    const one = (stats: Record<string, number>, flat: number) =>
      5 * kernel(context({ multiplier: 2.28384, flatDamage: flat }), stats);
    close(evaluateHit(hit, candidateStatsFrom([lowAtk])), one(lowAtk, 0.6 * 715));
    close(evaluateHit(hit, candidateStatsFrom([highAtk])), one(highAtk, 0.6 * 2860));
    close(evaluateHit(hit, candidateStatsFrom([pastCap])), one(pastCap, 1800));
  });

  it('refuses a capped flat conversion beside another from the same stat', () => {
    expect(() => rowHits(row(context()), [KIT(fx, { stat: 'flat_damage_from_atk', value: 0.1 })],
      TEAM, {})).toThrow(/capped flat-damage conversion/);
  });
});

describe("Nahida's A4: DMG% and CRIT Rate from EM above 200, capped at 80% / 24%", () => {
  const dmg = { stat: 'dmg_bonus_from_em', value: 0.001, threshold: 200, cap: 0.8,
    elements: ['pyro'] };
  const cr = { stat: 'crit_rate_from_em', value: 0.0003, threshold: 200, cap: 0.24 };
  const ctx = context({}, { elemental_mastery: 115 });

  for (const [name, em, counted] of [
    ['below the threshold', 50, 0],          // 165 EM: nothing
    ['between threshold and cap', 400, 315], // 515 EM: 315 counted
    ['at the cap', 885, 800],                // 1,000 EM: exactly 800 counted
    ['past the cap', 1200, 800],             // 1,315 EM: 800 counted
  ] as const) {
    it(name, () => {
      const recipe = synthesizeRecipe([row(ctx)], [KIT(dmg, cr)], TEAM);
      const stats = { elemental_mastery: em };
      close(evaluateRecipe(recipe, candidateStatsFrom([stats])),
        kernel(context({}, {
          elemental_mastery: 115, pyro_dmg_bonus: 0.001 * counted,
          crit_rate: 0.05 + 0.0003 * counted,
        }), stats));
    });
  }

  it('prices each cap alone, keeps EM live, and leaves an uncapped EM conversion as it was', () => {
    const recipe = synthesizeRecipe([row(ctx)], [KIT(dmg, cr)], TEAM);
    const [hit] = recipe.hits;
    expect(hit.statConversions).toEqual([
      { into: 'bonusDmg', from: 'em', perUnit: 0.001, threshold: 200, cap: 0.8 },
      { into: 'critRate', from: 'em', perUnit: 0.0003, threshold: 200, cap: 0.24 },
    ]);
    expect(hit.bonusFromEm).toBeUndefined();
    expect(liveQuantitiesFor(recipe)).toContain('elemental_mastery');
    // Kazuha's A4 has neither a cap nor a threshold: still the plain per-EM term.
    const kazuha = synthesizeRecipe([row(ctx)],
      [KIT({ stat: 'dmg_bonus_from_em', value: 0.0004, elements: ['pyro'] })], TEAM);
    expect(kazuha.hits[0].bonusFromEm).toBeCloseTo(0.0004, 12);
    expect(kazuha.hits[0].statConversions).toBeUndefined();
  });

  it('tells the planted mistakes apart: the cap ignored, the EM frozen', () => {
    const recipe = synthesizeRecipe([row(ctx)], [KIT(dmg, cr)], TEAM);
    const stats = candidateStatsFrom([{ elemental_mastery: 1200 }]);
    const right = evaluateRecipe(recipe, stats);
    const uncapped = synthesizeRecipe([row(ctx)],
      [KIT({ ...dmg, cap: undefined }, { ...cr, cap: undefined })], TEAM);
    expect(evaluateRecipe(uncapped, stats)).toBeGreaterThan(right * 1.05);
    // Frozen at the zero-artifact EM (115, below the threshold): worth nothing.
    const frozen = synthesizeRecipe([row(ctx)], [], TEAM);
    expect(evaluateRecipe(frozen, stats)).toBeLessThan(right / 1.05);
  });
});

describe("Furina's A4: Salon DMG% from her Max HP, capped at 28%", () => {
  it('reads HP per 1,000 through the cap, and keeps HP live', () => {
    const fx = { stat: 'dmg_bonus_from_hp', value: 0.007 / 1000, cap: 0.28, moves: ['skill'] };
    const ctx = context({ scalingStat: 'hp', multiplier: 0.14918 });
    const recipe = synthesizeRecipe([row(ctx)], [KIT(fx)], TEAM);
    for (const hpPct of [0.5, 1.5]) {
      const stats = { hp_pct: hpPct };
      const hp = 15552 * (1 + hpPct);
      close(evaluateRecipe(recipe, candidateStatsFrom([stats])),
        kernel(context({ scalingStat: 'hp', multiplier: 0.14918 },
          { pyro_dmg_bonus: Math.min(0.007 * hp / 1000, 0.28) }), stats));
    }
    expect(liveQuantitiesFor(recipe)).toEqual(expect.arrayContaining(['hp_pct', 'flat_hp']));
  });

  it('refuses a DMG% conversion that names no element, move or row', () => {
    expect(() => synthesizeRecipe([row(context())],
      [KIT({ stat: 'dmg_bonus_from_hp', value: 0.000007, cap: 0.28 })], TEAM))
      .toThrow(/names the element, move or row/);
  });
});

describe('the search bound stays admissible with a capped conversion deciding the winner', () => {
  const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
    mine: true, owner: 0, abil: 'x', attackTag: 4, element: 'dendro', talent: 2,
    scaling: 'atk', flatDamage: 0, calibratedScaling: 1000, conversions: {},
    calibratedBase: { atk: 1000, hp: 10000, def: 800 },
    calibratedPercent: { atk: 0, hp: 0, def: 0 },
    calibratedFlat: { atk: 0, hp: 0, def: 0 },
    bonusDmg: 0, critRate: 0.2, critDmg: 0.5, defMultiplier: 0.5, resMultiplier: 0.9,
    ampMultiplier: 1, gcsimAverageDamage: 900, ...over,
  });
  const recipe = (hits: RecipeHit[]): Recipe => ({
    hits, seed: 'formula', meta: {
      seed: 'formula', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [],
      minimumEnergyRecharge: null,
    },
  });

  /**
   * Three pieces per slot, one set, 3^5 = 243 combinations. EM is worth a lot until the cap
   * binds (≈ three EM pieces) and nothing after, so the winner mixes EM with CRIT DMG — which
   * only a bound that respects the cap could reach by pruning. Each piece is best at one thing,
   * so all survive the Pareto layer.
   */
  const inventory = (): Candidate[] => SLOTS.flatMap((slot, s) =>
    ([
      { atk_pct: 0.02 + 0.001 * s },
      { elemental_mastery: 187 + s },
      { crit_dmg: 0.3 + 0.01 * s },
    ] as Record<string, number>[])
      .map((stats, k) => ({ id: `${slot}-${k}`, slot, setId: 1, stats } as Candidate)));

  for (const [name, capped] of [
    ['a capped DMG% and CRIT Rate from EM (Nahida)', recipe([hit({
      calibratedEm: 300,
      statConversions: [
        { into: 'bonusDmg', from: 'em', perUnit: 0.001, threshold: 200, cap: 0.8 },
        { into: 'critRate', from: 'em', perUnit: 0.0003, threshold: 200, cap: 0.24 },
      ],
    })])],
    ['a capped flat ATK from HP (Hu Tao)', recipe([hit({
      conversions: { flatAtk: { from: 'hp', perUnit: 0.06, cap: 1200, offset: 0 } },
    })])],
  ] as const) {
    it(name, () => {
      const inv = name.includes('Hu Tao')
        ? inventory().map((c) => (c.stats['elemental_mastery']
          ? { ...c, stats: { hp_pct: 0.466 + 0.001 * SLOTS.indexOf(c.slot) } } : c))
        : inventory();
      const recipes = { byFourPieceSet: new Map([[1, capped]]), noFourPiece: capped };
      const exhaustive = searchRecipe(inv, { recipes, topN: 100000, fourPieceSets: [1] });
      const bounded = searchRecipe(inv, { recipes, topN: 3, fourPieceSets: [1] });

      expect(exhaustive.evaluated).toBe(243);
      expect(exhaustive.boundPruned).toBe(0);
      // Non-vacuous: the bound fired, and the winner is a mix — some capped-stat pieces, not
      // all of them — so the cap is what decided it.
      expect(bounded.boundPruned).toBeGreaterThan(0);
      expect(bounded.builds).toEqual(exhaustive.builds.slice(0, 3));
      const ids = exhaustive.builds[0].artifactIds;
      const capping = ids.filter((id) => id.endsWith('-1')).length;
      expect(capping).toBeGreaterThan(0);
      expect(capping).toBeLessThan(5);
      // And ignoring the cap would have ranked differently: the uncapped winner is all-in.
      const uncappedHits = capped.hits.map((h) => ({
        ...h,
        statConversions: h.statConversions?.map(({ cap: _c, ...c }) => c),
        conversions: h.conversions.flatAtk
          ? { flatAtk: { ...h.conversions.flatAtk, cap: undefined } } : h.conversions,
      }));
      const uncapped = recipe(uncappedHits);
      const naive = searchRecipe(inv, {
        recipes: { byFourPieceSet: new Map([[1, uncapped]]), noFourPiece: uncapped },
        topN: 1, fourPieceSets: [1],
      });
      expect(naive.builds[0].artifactIds).not.toEqual(ids);
    });
  }

  it('scores the zero-artifact candidate at its own (uncapped) stat', () => {
    const r = recipe([hit({
      calibratedEm: 300,
      statConversions: [{ into: 'bonusDmg', from: 'em', perUnit: 0.001, threshold: 200,
        cap: 0.8 }],
    })]);
    const bare = recipe([hit({ calibratedEm: 300, bonusDmg: 0.1 })]);
    close(evaluateRecipe(r, NO_STATS), evaluateRecipe(bare, NO_STATS));
  });
});
