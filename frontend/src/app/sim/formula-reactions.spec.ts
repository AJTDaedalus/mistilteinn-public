import { describe, expect, it } from 'vitest';

import {
  additiveFlat, defMultiplier, lunarBase, resMultiplier, transformativeBase,
} from './damage';
import {
  type FormulaRow,
  type FormulaSource,
  type FormulaTeam,
  reactionAssumptions,
  synthesizeRecipe,
} from './formula-recipe';
import { evaluateRecipe, NO_STATS, type CandidateStats } from './recipe-eval';
import { candidateStatsFrom, liveQuantitiesFor, searchRecipe } from './recipe-search';
import type { Candidate, SearchContext } from './search';

/**
 * Math-fallback P3, task 13 — reaction rows and additive reactions in a formula recipe.
 *
 * The GO-cited figures are `backend/tests/fixtures/formula/go_fixtures.json` (nine reaction
 * fixtures, `npm run formula:verify`); the parity of `damage.ts`'s reaction terms with the
 * Python chain is `npm run kernel:verify`. These are the recipe's own rules: what reaches a
 * reaction row and what does not, the candidate's EM and CRIT, the refusals, the bound.
 */

const LV90 = 1446.853515625;

function context(base: Record<string, number> = {}, channel = 'electro'): SearchContext {
  return {
    base: {
      base_atk: 800, atk_pct: 0, flat_atk: 0, base_hp: 12000, hp_pct: 0, flat_hp: 0,
      base_def: 700, def_pct: 0, flat_def: 0, elemental_mastery: 100, crit_rate: 0.05,
      crit_dmg: 0.5, energy_recharge: 1, electro_dmg_bonus: 0.2, ...base,
    },
    hit: {
      multiplier: 2, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0, amplifying: null,
      reactionBonus: 0,
    },
    target: { level: 100, resistance: 0.1, defReduction: 0, defIgnore: 0 },
    characterLevel: 90,
    dmgBonusQuantity: `${channel}_dmg_bonus`,
    reactionLevelMultiplier: LV90,
  };
}

const TEAM: FormulaTeam = {
  element: 'electro', weaponType: 'WEAPON_SWORD_ONE_HAND',
  memberElements: ['electro', 'dendro', 'hydro'],
};

function reactionRow(reaction: FormulaRow['reaction'], count = 1, base = {}): FormulaRow {
  return {
    id: `r-${reaction?.reaction}`, label: 'reaction', move: null, count, context: context(base),
    reaction,
  };
}

/** A source carrying the effects given, every one unconditional. */
function source(effects: FormulaSource['bonus']['effects']): FormulaSource {
  return {
    id: 'set:1:4', label: 'test set', citation: 'test',
    bonus: { conditions: [], effects, unmodelled: [] },
  };
}

const stats = (patch: Partial<CandidateStats>): CandidateStats => ({ ...NO_STATS, ...patch });

describe('a transformative reaction row', () => {
  it('reads the candidate\'s EM and nothing else that artifacts move', () => {
    const recipe = synthesizeRecipe([reactionRow({ reaction: 'hyperbloom' }, 3)], [], TEAM);
    const em = 100 + 400;
    const expected = 3 * transformativeBase('hyperbloom', LV90, em) * resMultiplier(0.1);
    expect(evaluateRecipe(recipe, stats({ elementalMastery: 400 }))).toBeCloseTo(expected, 2);
    // ATK%, CRIT and DMG% on the candidate change nothing.
    expect(evaluateRecipe(recipe, stats({
      elementalMastery: 400, atkPercent: 1, critRate: 1, critDmg: 2,
      elementBonus: { dendro: 0.6, electro: 0.6 }, allElementBonus: 0.5,
    }))).toBeCloseTo(expected, 2);
  });

  it('takes a reaction bonus naming it, a RES shred on its element and its own CRIT', () => {
    const effects: FormulaSource['bonus']['effects'] = [
      { stat: 'reaction_bonus', value: 0.4, reactions: ['hyperbloom', 'bloom'], when: [] },
      { stat: 'reaction_bonus', value: 9, reactions: ['overloaded'], when: [] },
      { stat: 'enemy_res', value: -0.4, elements: ['dendro'], when: [] },
      { stat: 'enemy_res', value: -0.4, elements: ['electro'], when: [] },
      { stat: 'reaction_crit_rate', value: 0.2, reactions: ['hyperbloom'], when: [] },
      { stat: 'reaction_crit_dmg', value: 1, reactions: ['hyperbloom'], when: [] },
      { stat: 'dmg_bonus', value: 5, when: [] },
      { stat: 'atk_pct', value: 5, when: [] },
      { stat: 'dmg_bonus', value: 5, moves: ['normal'], when: [] },
    ];
    const recipe = synthesizeRecipe([reactionRow({ reaction: 'hyperbloom' })], [source(effects)],
      TEAM);
    const expected = transformativeBase('hyperbloom', LV90, 100, 0.4) * resMultiplier(-0.3) * 1.2;
    expect(evaluateRecipe(recipe, NO_STATS)).toBeCloseTo(expected, 2);
    // A move-scoped buff simply does not reach a reaction row; it is not reported as unapplied.
    expect(recipe.meta.formula!.assumptions.join('\n')).not.toContain('move is unknown');
  });

  it('meets the swirled element\'s RES, and refuses a swirl with no element', () => {
    const shred = source([{ stat: 'enemy_res', value: -0.4, elements: ['pyro'], when: [] }]);
    const pyro = synthesizeRecipe([reactionRow({ reaction: 'swirl', swirled: 'pyro' })], [shred],
      TEAM);
    const hydro = synthesizeRecipe([reactionRow({ reaction: 'swirl', swirled: 'hydro' })],
      [shred], TEAM);
    expect(evaluateRecipe(pyro, NO_STATS) / evaluateRecipe(hydro, NO_STATS))
      .toBeCloseTo(resMultiplier(-0.3) / resMultiplier(0.1), 6);
    expect(() => synthesizeRecipe([reactionRow({ reaction: 'swirl' })], [], TEAM))
      .toThrow(/swirl carries one of/);
  });

  it('refuses a CRIT on a reaction that cannot crit, and a missing level multiplier', () => {
    const crit = source([
      { stat: 'reaction_crit_rate', value: 0.2, reactions: ['bloom'], when: [] },
    ]);
    // A bloom CRIT does not name overloaded, so overloaded stays uncrittable and fine.
    expect(() => synthesizeRecipe([reactionRow({ reaction: 'overloaded' })], [crit], TEAM))
      .not.toThrow();
    const row = reactionRow({ reaction: 'bloom' });
    row.context = { ...row.context, reactionLevelMultiplier: undefined };
    expect(() => synthesizeRecipe([row], [], TEAM)).toThrow(/reaction level multiplier/);
  });

  it('ignores DEF, as gcsim does, where a talent hit takes it', () => {
    const recipe = synthesizeRecipe([reactionRow({ reaction: 'superconduct' })], [source([
      { stat: 'def_reduction', value: 0.5, when: [] },
    ])], TEAM);
    expect(recipe.hits[0].defMultiplier).toBe(1);
    expect(evaluateRecipe(recipe, NO_STATS)).toBeCloseTo(
      transformativeBase('superconduct', LV90, 100) * resMultiplier(0.1), 2,
    );
  });
});

describe('a Lunar reaction row', () => {
  it('crits with the character\'s own CRIT, the candidate\'s included', () => {
    const recipe = synthesizeRecipe([reactionRow({ reaction: 'lunar_charged' }, 2)], [source([
      { stat: 'crit_rate', value: 0.3, when: [] },
      { stat: 'lunar_base_dmg_bonus', value: 0.2, reactions: ['lunar_charged'], when: [] },
    ])], TEAM);
    const candidate = stats({ elementalMastery: 200, critRate: 0.4, critDmg: 1 });
    const crit = 1 + Math.min(0.05 + 0.3 + 0.4, 1) * (0.5 + 1);
    const expected = 2 * lunarBase('lunar_charged', LV90, 300, 0, 0.2) * resMultiplier(0.1) * crit;
    expect(evaluateRecipe(recipe, candidate)).toBeCloseTo(expected, 2);
  });

  it('scales by a stated contributor weight, refusing one outside (0, 1]', () => {
    const whole = synthesizeRecipe([reactionRow({ reaction: 'lunar_crystallize' })], [], TEAM);
    const ranked = synthesizeRecipe([reactionRow({ reaction: 'lunar_crystallize', weight: 0.6 })],
      [], TEAM);
    expect(evaluateRecipe(ranked, NO_STATS) / evaluateRecipe(whole, NO_STATS)).toBeCloseTo(0.6, 9);
    expect(() => synthesizeRecipe([reactionRow({ reaction: 'lunar_charged', weight: 2 })], [],
      TEAM)).toThrow(/weight/);
  });
});

describe('an additive reaction on a talent row', () => {
  function talentRow(additive: FormulaRow['additive'], channel = 'electro'): FormulaRow {
    return {
      id: 'skill', label: 'Skill DMG', move: 'skill', count: 2, context: context({}, channel),
      additive,
    };
  }

  it('adds its flat term inside the base, under DMG%, DEF, RES and CRIT, at the candidate\'s EM', () => {
    const recipe = synthesizeRecipe([talentRow('aggravate')], [source([
      { stat: 'reaction_bonus', value: 0.2, reactions: ['aggravate'], when: [] },
    ])], TEAM);
    const candidate = stats({ elementalMastery: 300, critRate: 0.5, critDmg: 1 });
    const atk = 800;
    const flat = additiveFlat('aggravate', LV90, 400, 0.2);
    const expected = 2 * (2 * atk + flat) * 1.2 * defMultiplier(90, 100) * resMultiplier(0.1)
      * (1 + 0.55 * 1.5);
    expect(evaluateRecipe(recipe, candidate)).toBeCloseTo(expected, 1);
  });

  it('is refused on a hit of the wrong element', () => {
    expect(() => synthesizeRecipe([talentRow('spread')], [], TEAM)).toThrow(/dendro hit/);
  });
});

describe('the search over reaction rows', () => {
  const pieces: Candidate[] = [
    { id: 'a', slot: 'equip_bracer', setId: 101, stats: { elemental_mastery: 40, atk_pct: 0.2 } },
    { id: 'a2', slot: 'equip_bracer', setId: 102, stats: { crit_rate: 0.1, atk_pct: 0.3 } },
    { id: 'b', slot: 'equip_necklace', setId: 103, stats: { flat_atk: 311 } },
    { id: 'c', slot: 'equip_shoes', setId: 104, stats: { elemental_mastery: 187 } },
    { id: 'c2', slot: 'equip_shoes', setId: 105, stats: { atk_pct: 0.466 } },
    { id: 'd', slot: 'equip_ring', setId: 106, stats: { elemental_mastery: 187 } },
    { id: 'd2', slot: 'equip_ring', setId: 107, stats: { electro_dmg_bonus: 0.466 } },
    { id: 'e', slot: 'equip_dress', setId: 108, stats: { elemental_mastery: 187 } },
    { id: 'e2', slot: 'equip_dress', setId: 109, stats: { crit_dmg: 0.622 } },
  ];

  it('keeps EM live and finds the all-EM build a hyperbloom target wants', () => {
    const recipe = synthesizeRecipe([reactionRow({ reaction: 'hyperbloom' }, 4)], [], TEAM);
    expect(liveQuantitiesFor(recipe)).toContain('elemental_mastery');
    const result = searchRecipe(pieces, {
      recipes: { noFourPiece: recipe, byFourPieceSet: new Map() }, topN: 1,
    });
    expect(result.builds[0].artifactIds.sort()).toEqual(['a', 'b', 'c', 'd', 'e']);
    expect(result.builds[0].damage).toBeCloseTo(evaluateRecipe(recipe, candidateStatsFrom(
      pieces.filter((p) => ['a', 'b', 'c', 'd', 'e'].includes(p.id)).map((p) => p.stats),
    )), 6);
  });
});

describe('the reaction assumptions', () => {
  it('say what each reaction row counts, who triggers it, and the recorded divergences', () => {
    const lines = reactionAssumptions(
      [reactionRow({ reaction: 'hyperbloom' }, 3), reactionRow({ reaction: 'lunar_charged' })],
      'Fischl',
    );
    expect(lines.join('\n')).toContain('3× hyperbloom triggered by Fischl');
    expect(lines.join('\n')).toContain('ignore DEF');
    expect(lines.join('\n')).toContain('0.6/0.3/0.05/0.05');
    expect(reactionAssumptions([], 'Fischl')[0]).toContain('No reaction rows');
  });
});
