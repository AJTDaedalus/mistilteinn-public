import { describe, expect, it } from 'vitest';

import type { components } from '../api/api.types';

import {
  type FormulaInput,
  type FormulaResonance,
  type FormulaRow,
  type FormulaSetTier,
  type FormulaTeam,
  rowHits,
  suggestMove,
  synthesizeRecipe,
  synthesizeRecipeSet,
} from './formula-recipe';
import { evaluateHit, evaluateRecipe } from './recipe-eval';
import { candidateStatsFrom, liveQuantitiesFor, searchRecipe } from './recipe-search';
import { type Candidate, type SearchContext, type SetBonus, search, SLOTS } from './search';

/**
 * Math-fallback P1, task 5 — a recipe synthesised from formulas.
 *
 * The acceptance the task states: **with no buffs, a synthesised hit scores a candidate
 * exactly as the single-hit kernel does**, and a multi-row target is the weighted sum of its
 * rows. Then the buffs: resonance, a conditional 4-piece with stacks, per-row conditionals, a
 * move-scoped 2-piece pool, Emblem's ER conversion and Echoes' ATK conversion.
 *
 * The GO-cited fixtures are not here — they live in `backend/tests/fixtures/formula/` and
 * `scripts/verify-formula-recipe.mjs` reads them, because the Angular test builder targets the
 * browser and has no `node:fs` (the same split `damage.spec.ts` explains).
 */

const TOLERANCE = 1e-6;

/**
 * The buff shapes here are the API's, passed through unmapped. These assignments fail to
 * compile the day `app/schemas/formula.py` and `formula-recipe.ts` stop agreeing.
 */
type Schemas = components['schemas'];
export const API_SHAPES_AGREE: [FormulaSetTier, FormulaResonance] = [
  {} as Schemas['FormulaSetTierRead'],
  {} as Schemas['FormulaResonanceRead'],
];

/** A Pyro catalyst user at 90 with a weapon: the kernel's spelling of `/search-context`. */
function context(overrides: Partial<SearchContext['hit']> = {}, base = {}): SearchContext {
  return {
    base: {
      base_atk: 900, atk_pct: 0.2, flat_atk: 0,
      base_hp: 12000, hp_pct: 0, flat_hp: 0,
      base_def: 700, def_pct: 0, flat_def: 0,
      elemental_mastery: 100, crit_rate: 0.05, crit_dmg: 0.5, energy_recharge: 1.0,
      pyro_dmg_bonus: 0.1,
      ...base,
    },
    hit: {
      multiplier: 2.5, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0,
      amplifying: null, reactionBonus: 0, ...overrides,
    },
    target: { level: 100, resistance: 0.1, defReduction: 0, defIgnore: 0 },
    characterLevel: 90,
    dmgBonusQuantity: 'pyro_dmg_bonus',
  };
}

const TEAM: FormulaTeam = {
  element: 'pyro', weaponType: 'WEAPON_CATALYST', memberElements: ['pyro', 'pyro', 'hydro', 'cryo'],
};

/** Five pieces, one per slot. */
const PIECES: Candidate[] = [
  { id: 'a', slot: 'equip_bracer', setId: 15006, stats: { flat_hp: 4780, crit_rate: 0.1 } },
  { id: 'b', slot: 'equip_necklace', setId: 15006, stats: { flat_atk: 311, crit_dmg: 0.2 } },
  { id: 'c', slot: 'equip_shoes', setId: 15006, stats: { atk_pct: 0.466, elemental_mastery: 40 } },
  { id: 'd', slot: 'equip_ring', setId: 15006, stats: { pyro_dmg_bonus: 0.466, crit_rate: 0.07 } },
  { id: 'e', slot: 'equip_dress', setId: 99, stats: { crit_dmg: 0.622, energy_recharge: 0.11 } },
];

/** The kernel's score of exactly these five pieces. */
function kernelScore(ctx: SearchContext, setBonuses: SetBonus[] = []): number {
  return search(PIECES, { ...ctx, setBonuses, topN: 1, prefilterTopK: -1 }).builds[0].damage;
}

/** The recipe's score of the same pieces, set pools included. */
function recipeScore(rows: FormulaRow[], setBonuses: SetBonus[] = []): number {
  const recipe = synthesizeRecipe(rows, [], TEAM);
  const counts: Record<number, number> = {};
  for (const p of PIECES) counts[p.setId] = (counts[p.setId] ?? 0) + 1;
  const pools = PIECES.map((p) => p.stats as Record<string, number>);
  for (const bonus of setBonuses) {
    if ((counts[bonus.setId] ?? 0) >= bonus.piecesRequired) pools.push(bonus.stats);
  }
  return evaluateRecipe(recipe, candidateStatsFrom(pools));
}

const row = (ctx: SearchContext, extra: Partial<FormulaRow> = {}): FormulaRow => ({
  id: 'r1', label: 'Skill DMG', move: 'skill', count: 1, context: ctx, ...extra,
});

describe('with no buffs, the synthetic recipe is the single-hit kernel', () => {
  const cases: [string, SearchContext][] = [
    ['an ATK hit', context()],
    ['an HP hit', context({ scalingStat: 'hp', multiplier: 0.18 })],
    ['a DEF hit', context({ scalingStat: 'def', multiplier: 1.4 })],
    ['an EM hit', context({ scalingStat: 'elemental_mastery', multiplier: 3.2 })],
    // Nahida's Tri-Karma shape: one hit, ATK and EM terms.
    ['a mixed ATK + EM hit', context({
      multiplier: 1.858, extraTerms: [{ stat: 'elemental_mastery', multiplier: 3.715 }],
    })],
    // The EM term of the amplifying multiplier must move with the candidate's EM.
    ['a vaporized hit', context({ amplifying: 'vaporize' })],
    ['a reverse-melted hit', context({ amplifying: 'reverse_melt', reactionBonus: 0.15 })],
  ];
  for (const [name, ctx] of cases) {
    it(name, () => {
      const kernel = kernelScore(ctx);
      expect(Math.abs(recipeScore([row(ctx)]) - kernel) / kernel).toBeLessThan(TOLERANCE);
    });
  }

  it('static set bonuses reach both the same way', () => {
    const bonuses: SetBonus[] = [
      { setId: 15006, piecesRequired: 2, stats: { pyro_dmg_bonus: 0.15 } },
    ];
    const kernel = kernelScore(context(), bonuses);
    expect(Math.abs(recipeScore([row(context())], bonuses) - kernel) / kernel)
      .toBeLessThan(TOLERANCE);
  });

  it('the zero-artifact damage it records is the kernel at zero artifacts', () => {
    const { hits } = rowHits(row(context()), [], TEAM, {});
    const bare = search(
      SLOTS.map((slot, i) => ({ id: String(i), slot, setId: -1, stats: {} })),
      { ...context(), topN: 1 },
    ).builds[0].damage;
    expect(Math.abs(hits[0].gcsimAverageDamage - bare) / bare).toBeLessThan(TOLERANCE);
  });
});

describe('a multi-row target', () => {
  it('is the weighted sum of its rows', () => {
    const skill = context();
    const normal = context({ multiplier: 0.9 });
    const one = (ctx: SearchContext) => kernelScore(ctx);
    const total = recipeScore([
      row(skill, { id: 'skill', count: 3 }),
      row(normal, { id: 'normal', label: '1-Hit DMG', move: 'normal', count: 1.5 }),
    ]);
    const expected = 3 * one(skill) + 1.5 * one(normal);
    expect(Math.abs(total - expected) / expected).toBeLessThan(TOLERANCE);
  });

  it('refuses a non-positive count and repeated row ids', () => {
    expect(() => synthesizeRecipe([row(context(), { count: 0 })], [], TEAM)).toThrow(/positive/);
    expect(() => synthesizeRecipe([row(context()), row(context())], [], TEAM)).toThrow(/repeat/);
  });

  it('carries the counts and the estimate marker in its meta', () => {
    const recipe = synthesizeRecipe([row(context(), { count: 2 })], [], TEAM);
    expect(recipe.meta.formula?.kind).toBe('formula-estimate');
    expect(recipe.meta.formula?.comparator).toBe('genshin-optimizer');
    expect(recipe.meta.formula?.rows).toEqual([{ id: 'r1', label: 'Skill DMG', count: 2, move: 'skill' }]);
    expect(recipe.meta.formula?.assumptions.join(' ')).toMatch(/No kit buffs/);
    expect(recipe.meta.calibratedSetIds).toEqual([]);
  });
});

// ── Buffs ───────────────────────────────────────────────────────────────────────────────────

const FERVENT: FormulaResonance = {
  key: 'fervent_flames', name: 'Fervent Flames', element: 'pyro', citation: 'GO',
  bonus: { conditions: [], effects: [{ stat: 'atk_pct', value: 0.25, when: [] }], unmodelled: [] },
};

/** Crimson Witch 4pc as `/formula/set-effects` resolves it. */
const WITCH: FormulaSetTier = {
  set_id: 15006, set_name: 'Crimson Witch of Flames', pieces: 4, status: 'partial', citation: 'GO',
  bonus: {
    conditions: [{
      key: 'stacks', label: 'Elemental Skill stacks', kind: 'stacks', default: 3,
      default_reason: 'self', max: 3,
    }],
    effects: [
      { stat: 'reaction_bonus', value: 0.15, reactions: ['vaporize', 'reverse_vaporize'], when: [] },
      { stat: 'dmg_bonus', value: 0.075, elements: ['pyro'], per: 'stacks', when: [] },
    ],
    unmodelled: [{ what: 'Overloaded DMG', reason: 'transformative reactions are not modelled' }],
  },
};

const WITCH_SOURCE = {
  id: 'set:15006:4', label: 'Crimson Witch of Flames 4pc', bonus: WITCH.bonus, citation: 'GO',
};

describe('buffs reach the hit as the kernel would see them as stats', () => {
  it('a static resonance is a base stat', () => {
    const recipe = synthesizeRecipe(
      [row(context())], [{ id: 'resonance:fervent_flames', label: 'Fervent Flames',
        bonus: FERVENT.bonus, citation: 'GO' }], TEAM,
    );
    const kernel = kernelScore(context({}, { atk_pct: 0.2 + 0.25 }));
    const got = evaluateRecipe(recipe, candidateStatsFrom(PIECES.map((p) => p.stats)));
    expect(Math.abs(got - kernel) / kernel).toBeLessThan(TOLERANCE);
  });

  it('stacks multiply, and a row may override the team value', () => {
    const at = (stacks: number) => rowHits(
      row(context(), { conditionals: { 'set:15006:4/stacks': stacks } }), [WITCH_SOURCE], TEAM, {},
    ).hits[0].bonusDmg;
    expect(at(0)).toBeCloseTo(0.1, 12);
    expect(at(2)).toBeCloseTo(0.1 + 0.15, 12);
    // Default: the wearer triggers it, so three stacks.
    expect(rowHits(row(context()), [WITCH_SOURCE], TEAM, {}).hits[0].bonusDmg)
      .toBeCloseTo(0.1 + 0.225, 12);
  });

  it('a reaction bonus reaches only the reaction it names', () => {
    const vape = rowHits(row(context({ amplifying: 'vaporize' })), [WITCH_SOURCE], TEAM, {});
    const melt = rowHits(row(context({ amplifying: 'melt' })), [WITCH_SOURCE], TEAM, {});
    expect(vape.hits[0].amplifying?.reactionBonus).toBeCloseTo(0.15, 12);
    expect(melt.hits[0].amplifying?.reactionBonus).toBe(0);
  });

  it('per-row conditionals: one row after the skill, the next not', () => {
    const heart = {
      id: 'set:15016:4', label: 'Heart of Depth 4pc', citation: 'GO',
      bonus: {
        conditions: [{ key: 'after_skill', label: 'After skill', kind: 'toggle' as const,
          default: 1, default_reason: 'self' as const }],
        effects: [{ stat: 'dmg_bonus', value: 0.3, moves: ['normal', 'charged'],
          when: [{ condition: 'after_skill', values: [1] }] }],
        unmodelled: [],
      },
    };
    const recipe = synthesizeRecipe([
      row(context(), { id: 'after', label: 'N1 after', move: 'normal' }),
      row(context(), { id: 'before', label: 'N1 before', move: 'normal',
        conditionals: { 'set:15016:4/after_skill': 0 } }),
    ], [heart], TEAM);
    expect(recipe.hits.map((h) => h.bonusDmg)).toEqual([0.1 + 0.3, 0.1]);
    expect(recipe.meta.formula?.assumptions.join('\n')).toMatch(/N1 before — Heart of Depth 4pc: After skill = off \(set by you\)/);
  });

  it('a move-scoped bonus on a row whose move is unknown is skipped and said', () => {
    const heart = {
      id: 'set:15016:4', label: 'Heart of Depth 4pc', citation: 'GO',
      bonus: { conditions: [], unmodelled: [],
        effects: [{ stat: 'dmg_bonus', value: 0.3, moves: ['normal'], when: [] }] },
    };
    const recipe = synthesizeRecipe([row(context(), { move: null })], [heart], TEAM);
    expect(recipe.hits[0].bonusDmg).toBeCloseTo(0.1, 12);
    expect(recipe.meta.formula?.assumptions.join('\n')).toMatch(/move is unknown/);
  });

  it("Emblem's burst bonus follows the candidate's Energy Recharge, to its cap", () => {
    const emblem = {
      id: 'set:15020:4', label: 'Emblem 4pc', citation: 'GO',
      bonus: { conditions: [], unmodelled: [], effects: [{
        stat: 'dmg_bonus_from_energy_recharge', value: 0.25, cap: 0.75, moves: ['burst'], when: [],
      }] },
    };
    const [hit] = rowHits(row(context(), { move: 'burst' }), [emblem], TEAM, {}).hits;
    const at = (er: number) => evaluateHit(hit, candidateStatsFrom([{ energy_recharge: er }]));
    const bare = evaluateHit({ ...hit, bonusFromEnergyRecharge: undefined },
      candidateStatsFrom([{}]));
    // ER 100% → +25%; 200% → +50%; 400% → capped at +75%.
    expect(at(0) / bare).toBeCloseTo((1 + 0.1 + 0.25) / 1.1, 6);
    expect(at(1) / bare).toBeCloseTo((1 + 0.1 + 0.5) / 1.1, 6);
    expect(at(3) / bare).toBeCloseTo((1 + 0.1 + 0.75) / 1.1, 6);
    expect(liveQuantitiesFor(synthesizeRecipe([row(context(), { move: 'burst' })], [emblem], TEAM)))
      .toContain('energy_recharge');
  });

  it("Echoes' flat damage is 70% of the candidate's total ATK", () => {
    const echoes = {
      id: 'set:15024:4', label: 'Echoes 4pc', citation: 'GO',
      bonus: { conditions: [], unmodelled: [], effects: [{
        stat: 'flat_damage_from_atk', value: 0.7, moves: ['normal'], when: [],
      }] },
    };
    const ctx = context({ multiplier: 1 });
    const [hit] = rowHits(row(ctx, { move: 'normal' }), [echoes], TEAM, {}).hits;
    const stats = candidateStatsFrom([{ atk_pct: 0.5 }]);
    const without = evaluateHit({ ...hit, conversions: {} }, stats);
    // Base becomes ATK × (1 + 0.7): the conversion is a flat term of 0.7 × total ATK.
    expect(evaluateHit(hit, stats) / without).toBeCloseTo(1.7, 6);
  });

  it('Gilded Dreams counts teammates as GO does', () => {
    const gilded = {
      id: 'set:15026:4', label: 'Gilded 4pc', citation: 'GO',
      bonus: { conditions: [], unmodelled: [], effects: [
        { stat: 'atk_pct', value: 0.14, per_team: 'same_element_others' as const,
          per_team_max: 3, when: [] },
        { stat: 'elemental_mastery', value: 50, per_team: 'different_element' as const,
          per_team_max: 3, when: [] },
      ] },
    };
    const [hit] = rowHits(row(context()), [gilded], TEAM, {}).hits;
    // Pyro wearer with one other Pyro, a Hydro and a Cryo: +14% ATK, +100 EM.
    expect(hit.calibratedPercent.atk).toBeCloseTo(0.2 + 0.14, 12);
    expect(hit.calibratedEm).toBeCloseTo(100 + 100, 12);
  });

  it('a weapon-gated effect needs the class', () => {
    const gladiator = {
      id: 'set:15001:4', label: 'Gladiator 4pc', citation: 'GO',
      bonus: { conditions: [], unmodelled: [], effects: [{
        stat: 'dmg_bonus', value: 0.35, moves: ['normal'], when: [],
        weapon_types: ['WEAPON_SWORD_ONE_HAND', 'WEAPON_CLAYMORE', 'WEAPON_POLE'],
      }] },
    };
    const normal = row(context(), { move: 'normal' });
    expect(rowHits(normal, [gladiator], TEAM, {}).hits[0].bonusDmg).toBeCloseTo(0.1, 12);
    expect(rowHits(normal, [gladiator], { ...TEAM, weaponType: 'WEAPON_CLAYMORE' }, {})
      .hits[0].bonusDmg).toBeCloseTo(0.45, 12);
  });
});

describe('the recipe set the search runs on', () => {
  const gambler: FormulaSetTier = {
    set_id: 10008, set_name: 'Gambler', pieces: 2, status: 'modelled', citation: 'GO',
    bonus: { conditions: [], unmodelled: [],
      effects: [{ stat: 'dmg_bonus', value: 0.2, moves: ['skill'], when: [] }] },
  };
  const stale: FormulaSetTier = {
    set_id: 15020, set_name: 'Emblem', pieces: 4, status: 'stale', citation: 'GO',
    problem: 'param_list changed', bonus: { conditions: [], effects: [], unmodelled: [] },
  };
  const input = (rows: FormulaRow[]): FormulaInput => ({
    rows, team: TEAM, resonances: [FERVENT], setTiers: [WITCH, gambler, stale],
    fourPieceSetIds: [15006, 15020, 99],
  });

  it('has a recipe per scorable 4-piece, withholds a stale one, and pools a 2-piece', () => {
    const made = synthesizeRecipeSet(input([row(context())]));
    expect([...made.recipes.byFourPieceSet.keys()].sort()).toEqual([15006, 99]);
    expect(made.withheld).toEqual([{ setId: 15020, reason: 'param_list changed' }]);
    expect(made.setBonuses).toEqual([
      { setId: 10008, piecesRequired: 2, stats: { 'formula:dmg_bonus:skill': 0.2 } },
    ]);
    // The witch state carries its stacks; the no-set state does not.
    const witch = made.recipes.byFourPieceSet.get(15006)!;
    expect(witch.hits[0].bonusDmg).toBeCloseTo(0.1 + 0.225, 12);
    expect(made.recipes.noFourPiece.hits[0].bonusDmg).toBeCloseTo(0.1, 12);
    expect(witch.meta.formula?.assumptions.join('\n')).toMatch(/Overloaded DMG/);
  });

  it('a move-scoped 2-piece pool reaches a skill row and not a normal one', () => {
    const made = synthesizeRecipeSet(input([row(context())]));
    const pools = [{ 'formula:dmg_bonus:skill': 0.2 }];
    const skill = evaluateRecipe(made.recipes.noFourPiece, candidateStatsFrom(pools));
    const none = evaluateRecipe(made.recipes.noFourPiece, candidateStatsFrom([{}]));
    expect(skill / none).toBeCloseTo((1 + 0.1 + 0.2) / 1.1, 6);

    const normalSet = synthesizeRecipeSet(input([row(context(), { move: 'normal' })]));
    expect(evaluateRecipe(normalSet.recipes.noFourPiece, candidateStatsFrom(pools)))
      .toBeCloseTo(evaluateRecipe(normalSet.recipes.noFourPiece, candidateStatsFrom([{}])), 9);
  });

  it('searchRecipe runs on it unchanged and scores the 4-piece state with its bonus', () => {
    const made = synthesizeRecipeSet(input([row(context())]));
    const result = searchRecipe(PIECES, {
      recipes: made.recipes, setBonuses: made.setBonuses, topN: 1,
    });
    expect(result.builds[0].setCounts[15006]).toBe(4);
    const expected = evaluateRecipe(
      made.recipes.byFourPieceSet.get(15006)!, candidateStatsFrom(PIECES.map((p) => p.stats)),
    );
    expect(result.builds[0].damage).toBeCloseTo(expected, 6);
  });
});

describe('suggestMove', () => {
  it('names only what the label leaves no doubt about', () => {
    expect(suggestMove('elemental_skill', 'Skill DMG')).toBe('skill');
    expect(suggestMove('elemental_burst', 'Burst DMG')).toBe('burst');
    expect(suggestMove('normal_attack', '1-Hit DMG')).toBe('normal');
    expect(suggestMove('normal_attack', 'Charged Attack DMG')).toBe('charged');
    expect(suggestMove('normal_attack', 'Fully-Charged Aimed Shot')).toBe('charged');
    expect(suggestMove('normal_attack', 'Low/High Plunge DMG')).toBe('plunge');
    // A charged attack by another name: left for the user, not guessed.
    expect(suggestMove('normal_attack', 'Arataki Kesagiri Combo Slash DMG')).toBeNull();
  });
});
