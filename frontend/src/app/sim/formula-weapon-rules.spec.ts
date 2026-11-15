import { describe, expect, it } from 'vitest';

import {
  procAssumptions, rowHits, synthesizeRecipe, type FormulaRow, type FormulaSource,
  type FormulaTeam,
} from './formula-recipe';
import { evaluateRecipe, NO_STATS } from './recipe-eval';
import { liveQuantitiesFor } from './recipe-search';

/**
 * The owner's approvals of 2026-11-14 after #389 (`DECISIONS.md` §45), in the browser's recipe:
 * the wielder conversions, Millennial Movement non-stacking, and weapon proc rows. The GO
 * figures for each are in `formula:verify`; these pin the rules a figure cannot show alone.
 */

const TEAM: FormulaTeam = { element: 'pyro', weaponType: 'WEAPON_POLE', memberElements: [] };

function row(extra: Partial<FormulaRow> = {}): FormulaRow {
  return {
    id: 'r1', label: 'Pyronado', move: 'burst', count: 1,
    context: {
      base: { base_atk: 1000, base_hp: 10000, base_def: 700, crit_rate: 0.05, crit_dmg: 0.5,
        energy_recharge: 1, elemental_mastery: 0 },
      hit: { multiplier: 1, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0,
        amplifying: null, reactionBonus: 0, extraTerms: [] },
      target: { level: 90, resistance: 0.1, defReduction: 0, defIgnore: 0 },
      characterLevel: 90,
      dmgBonusQuantity: 'pyro_dmg_bonus',
    },
    ...extra,
  };
}

const toggle = (key: string) => ({
  key, label: key, kind: 'toggle' as const, default: 1, default_reason: 'teammate' as const,
});

function millennial(id: string, rank: string, atk: number): FormulaSource {
  return {
    id, label: id, citation: 'GO', stack_rank: rank,
    bonus: {
      conditions: [toggle('on')], unmodelled: [],
      effects: [{ stat: 'atk_pct', value: atk, when: [{ condition: 'on', values: [1] }],
        non_stack: 'millenialatk' }],
    },
  };
}

const score = (sources: FormulaSource[], state = {}, rows = [row()]) =>
  evaluateRecipe(synthesizeRecipe(rows, sources, TEAM, state), NO_STATS);

describe('GO non-stacking buffs (Millennial Movement: one)', () => {
  const elegy = millennial('weapon:elegy_for_the_end', 'Venti', 0.4);
  const sworn = millennial('weapon:freedom_sworn', 'KaedeharaKazuha', 0.2);

  it('applies one — the wielder whose GO key sorts first, not the larger buff', () => {
    expect(score([elegy, sworn])).toBeCloseTo(score([sworn]), 9);
    expect(score([sworn, elegy])).toBeCloseTo(score([sworn]), 9);
    expect(score([elegy, sworn])).toBeLessThan(score([elegy]));
  });

  it('a winner whose condition is off writes nothing, so the other applies', () => {
    const off = { 'weapon:freedom_sworn/on': 0 };
    expect(score([elegy, sworn], off)).toBeCloseTo(score([elegy], off), 9);
  });

  it('says which source was not applied and why', () => {
    const recipe = synthesizeRecipe([row()], [elegy, sworn], TEAM);
    expect(recipe.meta.formula!.assumptions.join('\n'))
      .toMatch(/weapon:elegy_for_the_end: atk_pct not applied — weapon:freedom_sworn holds the same non-stacking buff/);
  });
});

describe('the wielder conversions', () => {
  it('ATK% from ER moves with the candidate ER, to its cap, and makes ER live', () => {
    const engulfing: FormulaSource = {
      id: 'weapon:engulfing_lightning', label: 'EL', citation: 'GO',
      bonus: { conditions: [], unmodelled: [], effects: [
        { stat: 'atk_pct_from_er', value: 0.28, threshold: 1, cap: 0.8, when: [] }] },
    };
    const recipe = synthesizeRecipe([row()], [engulfing], TEAM);
    const at = (er: number) => evaluateRecipe(recipe, { ...NO_STATS, energyRecharge: er });
    expect(at(0.5)).toBeGreaterThan(at(0));
    expect(at(3)).toBeCloseTo(at(4), 6);
    expect(liveQuantitiesFor(recipe)).toContain('energy_recharge');
  });

  it('EM from Max HP reaches an EM reader and makes HP live', () => {
    const key: FormulaSource = {
      id: 'weapon:key_of_khaj_nisut', label: 'Key', citation: 'GO',
      bonus: { conditions: [], unmodelled: [], effects: [
        { stat: 'em_from_hp', value: 0.002, when: [] },
        { stat: 'dmg_bonus_from_em', value: 0.001, elements: ['pyro'], when: [] }] },
    };
    const recipe = synthesizeRecipe([row()], [key], TEAM);
    const at = (hp: number) => evaluateRecipe(recipe, { ...NO_STATS, hpPercent: hp });
    expect(at(0.5)).toBeGreaterThan(at(0));
    expect(liveQuantitiesFor(recipe)).toEqual(expect.arrayContaining(['base_hp', 'hp_pct']));
  });

  it('ATK from EM and DMG from DEF each move with their source', () => {
    const sources: FormulaSource[] = [{
      id: 'weapon:x', label: 'x', citation: 'GO',
      bonus: { conditions: [], unmodelled: [], effects: [
        { stat: 'flat_atk_from_em', value: 0.24, when: [] },
        { stat: 'dmg_bonus_from_def', value: 0.00008, cap: 0.256,
          elements: ['pyro'], when: [] }] },
    }];
    const recipe = synthesizeRecipe([row()], sources, TEAM);
    const em = evaluateRecipe(recipe, { ...NO_STATS, elementalMastery: 200 });
    const def = evaluateRecipe(recipe, { ...NO_STATS, defFlat: 500 });
    expect(em).toBeGreaterThan(evaluateRecipe(recipe, NO_STATS));
    expect(def).toBeGreaterThan(evaluateRecipe(recipe, NO_STATS));
    // Past the 3,200-DEF stat cap the DMG% stops growing.
    const far = evaluateRecipe(recipe, { ...NO_STATS, defFlat: 5000 });
    expect(far).toBeCloseTo(evaluateRecipe(recipe, { ...NO_STATS, defFlat: 6000 }), 6);
  });
});

describe('weapon proc rows', () => {
  const aquila: FormulaSource = {
    id: 'weapon:aquila_favonia', label: 'Aquila', citation: 'GO',
    procs: [{ key: 'falcon', label: 'Falcon', multiplier: 2, element: 'physical',
      stat_layer: 'premod' }],
    bonus: { conditions: [], unmodelled: [], effects: [
      { stat: 'dmg_bonus', value: 0.5, moves: ['burst'], when: [] }] },
  };
  const proc = row({ id: 'p', label: 'Falcon', move: null, count: 3,
    proc: { source: 'weapon:aquila_favonia', key: 'falcon' } });

  it('prices count × multiplier × ATK in the proc element, with no move-scoped bonus', () => {
    const { hits, skipped } = rowHits(proc, [aquila], TEAM, {});
    expect(hits).toHaveLength(1);
    expect(hits[0].element).toBe('physical');
    expect(hits[0].talent).toBeCloseTo(6, 9);
    expect(hits[0].bonusDmg).toBe(0);
    expect(skipped).toEqual([]);
  });

  it('deals nothing with another weapon, and says so', () => {
    const { hits, skipped } = rowHits(proc, [], TEAM, {});
    expect(hits).toEqual([]);
    expect(skipped.join()).toMatch(/not dealt/);
  });

  it('states its count as an assumption', () => {
    expect(procAssumptions([proc], [aquila], 'Kaeya').join('\n')).toMatch(/3× Falcon dealt by Kaeya/);
  });
});
