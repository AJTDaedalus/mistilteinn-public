import { describe, expect, it } from 'vitest';

import {
  FORMULA_LABEL,
  conditionGroups,
  formulaCalibration,
  gcsimRefusal,
  isFormulaRecipe,
  type FormulaCalibrationInput,
} from './formula-calibration';
import {
  synthesizeRecipeSet,
  type FormulaResonance,
  type FormulaRow,
  type FormulaSetTier,
  type FormulaTeam,
} from './formula-recipe';
import { evaluateRecipe } from './recipe-eval';
import { candidateStatsFrom, searchRecipe } from './recipe-search';
import type { Candidate, SearchContext, SetBonus } from './search';

/**
 * Math-fallback P1, task 8 — a formula estimate in the shape a gcsim calibration has.
 *
 * The property that matters: a 4-piece state's recipe **carries the set's whole bonus** and
 * says so in `calibratedSetIds`, exactly as a gcsim recipe calibrated with the set worn does.
 * So the search (which adds pools for every set not calibrated) and Rank/Upgrade (which add
 * none) both see the same set bonus — proved here by scoring the same pieces both ways.
 */

const TEAM: FormulaTeam = {
  element: 'pyro', weaponType: 'WEAPON_CATALYST', memberElements: ['pyro', 'pyro', 'hydro', 'cryo'],
};

function context(): SearchContext {
  return {
    base: {
      base_atk: 900, atk_pct: 0.2, flat_atk: 0, base_hp: 12000, hp_pct: 0, flat_hp: 0,
      base_def: 700, def_pct: 0, flat_def: 0, elemental_mastery: 100, crit_rate: 0.05,
      crit_dmg: 0.5, energy_recharge: 1.0, pyro_dmg_bonus: 0.1,
    },
    hit: {
      multiplier: 2.5, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0,
      amplifying: null, reactionBonus: 0,
    },
    target: { level: 100, resistance: 0.1, defReduction: 0, defIgnore: 0 },
    characterLevel: 90,
    dmgBonusQuantity: 'pyro_dmg_bonus',
  };
}

const ROWS: FormulaRow[] = [
  { id: 'r1', label: 'Skill DMG', move: 'skill', count: 2, context: context() },
  { id: 'r2', label: 'Burst DMG', move: 'burst', count: 1, context: context() },
];

const FERVENT: FormulaResonance = {
  key: 'fervent_flames', name: 'Fervent Flames', element: 'pyro', citation: 'GO Resonance.tsx',
  bonus: { conditions: [], effects: [{ stat: 'atk_pct', value: 0.25, when: [] }], unmodelled: [] },
};

/** Crimson Witch 4pc, conditional, with its static 2pc in the kernel pools below. */
const WITCH: FormulaSetTier = {
  set_id: 15006, set_name: 'Crimson Witch of Flames', pieces: 4, status: 'partial',
  citation: 'GO CrimsonWitchOfFlames/index.tsx',
  bonus: {
    conditions: [{
      key: 'stacks', label: 'Elemental Skill stacks', kind: 'stacks', default: 3,
      default_reason: 'self', max: 3,
    }],
    effects: [{ stat: 'dmg_bonus', value: 0.075, elements: ['pyro'], per: 'stacks', when: [] }],
    unmodelled: [{ what: 'Overloaded DMG', reason: 'transformative reactions are not modelled' }],
  },
};

/** A move-scoped conditional 2-piece, with no static stats. */
const GAMBLER: FormulaSetTier = {
  set_id: 10008, set_name: 'Gambler', pieces: 2, status: 'modelled', citation: 'GO',
  bonus: { conditions: [], unmodelled: [],
    effects: [{ stat: 'dmg_bonus', value: 0.2, moves: ['skill'], when: [] }] },
};

const STALE: FormulaSetTier = {
  set_id: 15020, set_name: 'Emblem', pieces: 4, status: 'stale', citation: 'GO',
  problem: 'param_list changed', bonus: { conditions: [], effects: [], unmodelled: [] },
};

const STATICS: SetBonus[] = [
  { setId: 15006, piecesRequired: 2, stats: { pyro_dmg_bonus: 0.15 } },
  { setId: 99, piecesRequired: 2, stats: { atk_pct: 0.18 } },
  // A conditional tier arrives with empty stats from `/artifacts/set-bonuses`.
  { setId: 10008, piecesRequired: 2, stats: {} },
];

const INPUT: FormulaCalibrationInput = {
  rows: ROWS, team: TEAM, resonances: [FERVENT], setTiers: [WITCH, GAMBLER, STALE],
  staticSetBonuses: STATICS, fourPieceSetIds: [15006, 15020, 99],
};

/** Four Witch pieces and one other, one per slot. */
const PIECES: Candidate[] = [
  { id: 'a', slot: 'equip_bracer', setId: 15006, stats: { flat_hp: 4780, crit_rate: 0.1 } },
  { id: 'b', slot: 'equip_necklace', setId: 15006, stats: { flat_atk: 311, crit_dmg: 0.2 } },
  { id: 'c', slot: 'equip_shoes', setId: 15006, stats: { atk_pct: 0.466 } },
  { id: 'd', slot: 'equip_ring', setId: 15006, stats: { pyro_dmg_bonus: 0.466 } },
  { id: 'e', slot: 'equip_dress', setId: 99, stats: { crit_dmg: 0.622 } },
];

describe('formulaCalibration', () => {
  it('builds a recipe per scorable 4-piece, withholds a stale one, and marks each as its set', () => {
    const made = formulaCalibration(INPUT);
    expect([...made.byFourPieceSet.keys()].sort()).toEqual([15006, 99]);
    expect(made.withheld).toEqual([{ setId: 15020, reason: 'param_list changed' }]);
    expect(made.byFourPieceSet.get(15006)!.meta.calibratedSetIds).toEqual([15006]);
    expect(made.noFourPiece.meta.calibratedSetIds).toEqual([]);
    expect(made.byPair.size).toBe(0);
  });

  it('a 4-piece recipe alone scores the set bonus a pool would have added (Rank/Upgrade)', () => {
    const made = formulaCalibration(INPUT);
    const pools = PIECES.map((p) => p.stats as Record<string, number>);
    // What Rank does: the recipe, the five pieces, no pools.
    const ranked = evaluateRecipe(made.byFourPieceSet.get(15006)!, candidateStatsFrom(pools));
    // The same, built the task-5 way: no set inside the recipe, the static 2pc as a pool.
    const pooled = synthesizeRecipeSet({
      rows: ROWS, team: TEAM, resonances: [FERVENT], setTiers: [WITCH],
      fourPieceSetIds: [15006],
    }).recipes.byFourPieceSet.get(15006)!;
    const expected = evaluateRecipe(pooled, candidateStatsFrom([...pools, STATICS[0].stats]));
    // 1e-6, `formula-recipe.spec.ts`'s tolerance: pools sum in f32, a folded base in f64.
    expect(Math.abs(ranked - expected) / expected).toBeLessThan(1e-6);
  });

  it('the search finds the same winner and damage as the pooled construction', () => {
    const made = formulaCalibration(INPUT);
    const found = searchRecipe(PIECES, {
      recipes: { noFourPiece: made.noFourPiece, byFourPieceSet: made.byFourPieceSet },
      setBonuses: made.setBonuses, fourPieceSets: [15006], topN: 1,
    });
    const task5 = synthesizeRecipeSet({
      rows: ROWS, team: TEAM, resonances: [FERVENT], setTiers: [WITCH, GAMBLER],
      fourPieceSetIds: [15006],
    });
    const reference = searchRecipe(PIECES, {
      recipes: task5.recipes, setBonuses: [...STATICS, ...task5.setBonuses],
      fourPieceSets: [15006], topN: 1,
    });
    expect(found.builds[0].artifactIds).toEqual(reference.builds[0].artifactIds);
    expect(found.builds[0].damage).toBeCloseTo(reference.builds[0].damage, 3);
  });

  it('the search does not add a folded set\'s pools a second time', () => {
    const made = formulaCalibration(INPUT);
    const once = searchRecipe(PIECES, {
      recipes: { noFourPiece: made.noFourPiece, byFourPieceSet: made.byFourPieceSet },
      setBonuses: made.setBonuses, fourPieceSets: [15006], topN: 1,
    }).builds[0].damage;
    const withoutPools = searchRecipe(PIECES, {
      recipes: { noFourPiece: made.noFourPiece, byFourPieceSet: made.byFourPieceSet },
      setBonuses: [], fourPieceSets: [15006], topN: 1,
    }).builds[0].damage;
    expect(once).toBeCloseTo(withoutPools, 3);
  });

  it('hands the search the static pools and the conditional 2-piece pools', () => {
    const made = formulaCalibration(INPUT);
    expect(made.setBonuses).toContainEqual(
      { setId: 10008, piecesRequired: 2, stats: { 'formula:dmg_bonus:skill': 0.2 } },
    );
    expect(made.setBonuses).toContainEqual(STATICS[1]);
  });

  it('carries the estimate\'s assumptions and conditionals', () => {
    const made = formulaCalibration({ ...INPUT, conditionals: { 'set:15006:4/stacks': 1 } });
    expect(made.assumptions.join('\n')).toMatch(/Formula estimate: no simulation/);
    const witch = made.byFourPieceSet.get(15006)!;
    expect(witch.meta.formula?.assumptions.join('\n')).toMatch(/stacks = 1 \(set by you\)/);
    expect(witch.meta.formula?.assumptions.join('\n')).toMatch(/Overloaded DMG/);
  });

  it('every recipe it builds is recognisably a formula estimate', () => {
    const made = formulaCalibration(INPUT);
    expect(isFormulaRecipe(made.noFourPiece)).toBe(true);
    for (const recipe of made.byFourPieceSet.values()) expect(isFormulaRecipe(recipe)).toBe(true);
    expect(isFormulaRecipe(null)).toBe(false);
  });
});

describe('conditionGroups', () => {
  it('lists every active resonance and the usable tiers of the sets in scope only', () => {
    const groups = conditionGroups([FERVENT], [WITCH, GAMBLER, STALE], new Set([15006, 15020]));
    // Fervent Flames has nothing to set and is still named; Gambler is out of scope; the stale
    // Emblem tier is not usable.
    expect(groups.map((g) => g.sourceId)).toEqual(['resonance:fervent_flames', 'set:15006:4']);
    expect(groups[0].conditions).toEqual([]);
    expect(groups[1].conditions[0].default).toBe(3);
    expect(groups[1].citation).toMatch(/CrimsonWitch/);
  });

  it('includes a conditional resonance', () => {
    const cryo: FormulaResonance = {
      key: 'shattering_ice', name: 'Shattering Ice', element: 'cryo', citation: 'GO',
      bonus: {
        conditions: [{ key: 'affected', label: 'Enemy Cryo or Frozen', kind: 'toggle',
          default: 0, default_reason: 'situational' }],
        effects: [{ stat: 'crit_rate', value: 0.15, when: [{ condition: 'affected', values: [1] }] }],
        unmodelled: [],
      },
    };
    expect(conditionGroups([cryo], [], new Set()).map((g) => g.sourceId))
      .toEqual(['resonance:shattering_ice']);
  });
});

describe('gcsimRefusal', () => {
  it('reads the member out of the calibrate 422', () => {
    const message = "gcsim has no character key for 'Lohen' (normalised 'lohen') at pin b107b5dc5cb8. "
      + 'It is most likely released after the pin.';
    expect(gcsimRefusal(message)).toEqual({ kind: 'character', name: 'Lohen', message });
  });

  it('reads a weapon and a set refusal', () => {
    expect(gcsimRefusal("gcsim has no weapon key for 'New Blade' (normalised 'newblade')")?.kind)
      .toBe('weapon');
    expect(gcsimRefusal("gcsim has no artifact set key for 'New Set' (x)")?.name).toBe('New Set');
  });

  it('is null for any other failure, which stays an error', () => {
    expect(gcsimRefusal('Network error')).toBeNull();
    expect(gcsimRefusal('rotation X is for a team that does not include Furina')).toBeNull();
  });
});

it('the label says what the number is', () => {
  expect(FORMULA_LABEL).toBe('Formula estimate — no simulation');
});
