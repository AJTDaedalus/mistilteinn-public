import { describe, expect, it } from 'vitest';

import {
  raiseRow, synthesizeRecipe, type FormulaRaisedTalent, type FormulaRow, type FormulaSource,
  type FormulaTeam,
} from './formula-recipe';
import { type Recipe, type RecipeHit } from './recipe';
import { evaluateRecipe } from './recipe-eval';
import { candidateStatsFrom, liveQuantitiesFor, searchRecipe } from './recipe-search';
import { type Candidate, type SearchContext, search, SLOTS } from './search';

/**
 * The two mechanics of owner approval 2026-11-14 (`docs/DECISIONS.md` §42): a kit's talent-level
 * raise read on the receiver's rows (`raiseRow`), and CRIT Rate / CRIT DMG from the hit owner's
 * own Max HP, each capped alone (Nilou's and Sigewinne's C6). Both are also held against GO
 * fixtures by `scripts/verify-formula-recipe.mjs`.
 */

const TOLERANCE = 1e-6;

/** A Hydro sword user at 90, the kernel's spelling of `/search-context`. */
function context(overrides: Partial<SearchContext['hit']> = {}, base = {}): SearchContext {
  return {
    base: {
      base_atk: 230, atk_pct: 0, flat_atk: 0,
      base_hp: 15185, hp_pct: 0.288, flat_hp: 0,
      base_def: 727, def_pct: 0, flat_def: 0,
      elemental_mastery: 0, crit_rate: 0.05, crit_dmg: 0.5, energy_recharge: 1.0,
      hydro_dmg_bonus: 0,
      ...base,
    },
    hit: {
      multiplier: 0.0710, scalingStat: 'hp', flatDamage: 0, baseDamageBonus: 0,
      amplifying: null, reactionBonus: 0, ...overrides,
    },
    target: { level: 100, resistance: 0.1, defReduction: 0, defIgnore: 0 },
    characterLevel: 90,
    dmgBonusQuantity: 'hydro_dmg_bonus',
  };
}

const TEAM: FormulaTeam = {
  element: 'hydro', weaponType: 'WEAPON_SWORD_ONE_HAND', memberElements: ['hydro', 'cryo'],
};

const row = (ctx: SearchContext, extra: Partial<FormulaRow> = {}): FormulaRow => ({
  id: 'r1', label: 'Skill DMG', move: 'skill', count: 1, context: ctx, ...extra,
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

// ── CRIT from Max HP ─────────────────────────────────────────────────────────────────────────

/** Nilou's C6: 0.6% CRIT Rate and 1.2% CRIT DMG per 1,000 Max HP, capped at 30% and 60%. */
const NILOU_C6: FormulaSource = {
  id: 'kit:nilou', label: 'Nilou (kit)', citation: 'GO',
  bonus: {
    conditions: [],
    effects: [
      { stat: 'crit_rate_from_hp', value: 0.006 / 1000, cap: 0.3, when: [] },
      { stat: 'crit_dmg_from_hp', value: 0.012 / 1000, cap: 0.6, when: [] },
    ],
    unmodelled: [],
  },
};

describe("CRIT from Max HP (Nilou's C6), each capped alone", () => {
  const hp = (hpPct: number, flatHp: number) => 15185 * (1 + 0.288 + hpPct) + flatHp;

  it('is the kernel with the converted CRIT added, below both caps', () => {
    const recipe = synthesizeRecipe([row(context())], [NILOU_C6], TEAM);
    const stats = { hp_pct: 1.0, flat_hp: 4780 };
    const total = hp(1.0, 4780);
    expect(0.006 * total / 1000).toBeLessThan(0.3);
    close(evaluateRecipe(recipe, candidateStatsFrom([stats])), kernel(context({}, {
      crit_rate: 0.05 + 0.006 * total / 1000, crit_dmg: 0.5 + 0.012 * total / 1000,
    }), stats));
  });

  it('is flat past both caps: more HP buys only its own scaling', () => {
    const recipe = synthesizeRecipe([row(context())], [NILOU_C6], TEAM);
    const stats = { hp_pct: 2.4, flat_hp: 4780 };
    expect(0.012 * hp(2.4, 4780) / 1000).toBeGreaterThan(0.6);
    close(evaluateRecipe(recipe, candidateStatsFrom([stats])),
      kernel(context({}, { crit_rate: 0.35, crit_dmg: 1.1 }), stats));
  });

  it('caps each term alone, not their sum', () => {
    // CRIT Rate past its cap, CRIT DMG not: a shared cap would read neither right.
    const odd: FormulaSource = {
      ...NILOU_C6,
      bonus: {
        ...NILOU_C6.bonus,
        effects: [
          { stat: 'crit_rate_from_hp', value: 0.006 / 1000, cap: 0.05, when: [] },
          { stat: 'crit_dmg_from_hp', value: 0.012 / 1000, cap: 5, when: [] },
        ],
      },
    };
    const stats = { hp_pct: 1.0, flat_hp: 4780 };
    const total = hp(1.0, 4780);
    close(evaluateRecipe(synthesizeRecipe([row(context())], [odd], TEAM),
      candidateStatsFrom([stats])),
    kernel(context({}, { crit_rate: 0.1, crit_dmg: 0.5 + 0.012 * total / 1000 }), stats));
  });

  it('keeps HP live on a hit that does not scale off it', () => {
    const recipe = synthesizeRecipe([row(context({ scalingStat: 'atk', multiplier: 1 }))],
      [NILOU_C6], TEAM);
    expect(liveQuantitiesFor(recipe)).toEqual(expect.arrayContaining(['hp_pct', 'flat_hp']));
  });
});

describe('the search bound stays admissible with CRIT from HP deciding the winner', () => {
  const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
    mine: true, owner: 0, abil: 'x', attackTag: 4, element: 'hydro', talent: 2,
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

  /** Three pieces per slot, one set, 3^5 = 243 combinations. HP is worth a lot of CRIT until the
   * caps bind (two or three HP pieces) and nothing after, so the winner mixes HP with ATK. */
  const inventory = (): Candidate[] => SLOTS.flatMap((slot, s) =>
    ([
      { atk_pct: 0.25 + 0.001 * s },
      { hp_pct: 2.0 + 0.001 * s },
      { crit_dmg: 0.1 + 0.001 * s },
    ] as Record<string, number>[])
      .map((stats, k) => ({ id: `${slot}-${k}`, slot, setId: 1, stats } as Candidate)));

  it('bounded == exhaustive, the cap decides the mix', () => {
    const capped = recipe([hit({
      statConversions: [
        { into: 'critRate', from: 'hp', perUnit: 0.006 / 1000, cap: 0.3 },
        { into: 'critDmg', from: 'hp', perUnit: 0.012 / 1000, cap: 0.6 },
      ],
    })]);
    const inv = inventory();
    const recipes = { byFourPieceSet: new Map([[1, capped]]), noFourPiece: capped };
    const exhaustive = searchRecipe(inv, { recipes, topN: 100000, fourPieceSets: [1] });
    const bounded = searchRecipe(inv, { recipes, topN: 3, fourPieceSets: [1] });

    expect(exhaustive.evaluated).toBe(243);
    expect(exhaustive.boundPruned).toBe(0);
    expect(bounded.boundPruned).toBeGreaterThan(0);
    expect(bounded.builds).toEqual(exhaustive.builds.slice(0, 3));
    const ids = exhaustive.builds[0].artifactIds;
    const hpPieces = ids.filter((id) => id.endsWith('-1')).length;
    expect(hpPieces).toBeGreaterThan(0);
    expect(hpPieces).toBeLessThan(5);
    // Ignoring the caps ranks differently: the uncapped winner is all HP.
    const uncapped = recipe(capped.hits.map((h) => ({
      ...h, statConversions: h.statConversions?.map(({ cap: _c, ...c }) => c),
    })));
    const naive = searchRecipe(inv, {
      recipes: { byFourPieceSet: new Map([[1, uncapped]]), noFourPiece: uncapped },
      topN: 1, fourPieceSets: [1],
    });
    expect(naive.builds[0].artifactIds).not.toEqual(ids);
  });
});

// ── A kit's talent-level raise ───────────────────────────────────────────────────────────────

const talentLevel = (
  id: string, talent: string, when: FormulaSource['bonus']['effects'][number]['when'] = [],
  conditions: FormulaSource['bonus']['conditions'] = [],
): FormulaSource => ({
  id, label: `${id.slice(4)} (kit)`, citation: 'GO',
  bonus: { conditions, effects: [{ stat: 'talent_level', value: 1, talent, when }], unmodelled: [] },
});

const TARTAGLIA = talentLevel('kit:tartaglia', 'normal_attack');
const HIGH_SPIRITS = talentLevel('kit:lohen', 'elemental_skill',
  [{ condition: 'high_spirits', values: [1] }],
  [{ key: 'high_spirits', label: 'High Spirits', kind: 'toggle', default: 1,
    default_reason: 'self' }]);
const SKIRK = talentLevel('kit:skirk', 'elemental_skill');

const RAISED: FormulaRaisedTalent[] = [{
  talent: 'elemental_skill', level: 13, max_raise: 2,
  rows: [
    { label: '1-Hit DMG', index: 0, raise_by: 1, multiplier: 2.0529, scaling_stat: 'atk',
      extra_terms: [] },
    { label: '1-Hit DMG', index: 0, raise_by: 2, multiplier: 2.1659, scaling_stat: 'atk',
      extra_terms: [] },
  ],
  unavailable: [],
}, {
  talent: 'normal_attack', level: 10, max_raise: 1,
  rows: [{ label: '1-Hit DMG', index: 0, raise_by: 1, multiplier: 0.8985, scaling_stat: 'atk',
    extra_terms: [] }],
  unavailable: [],
}];

const skillRow = (extra: Partial<FormulaRow> = {}) => row(
  context({ multiplier: 1.9399, scalingStat: 'atk' }),
  { label: 'Masterstroke 1-Hit', move: 'normal',
    hit: { talent: 'elemental_skill', label: '1-Hit DMG', index: 0 }, ...extra },
);

describe('raiseRow: a kit raises the receiver\'s talent level', () => {
  it('reads the row at the raised level, and says so', () => {
    const { row: lifted, notes } = raiseRow(skillRow(), [HIGH_SPIRITS], {}, RAISED);
    expect(lifted.context.hit.multiplier).toBe(2.0529);
    expect(notes).toEqual(['Masterstroke 1-Hit: Elemental Skill read at level 14 (13 + lohen +1)']);
  });

  it('sums raises from two kits: 10 + 3 + 1 + 1 = 15', () => {
    const { row: lifted, notes } = raiseRow(skillRow(), [HIGH_SPIRITS, SKIRK], {}, RAISED);
    expect(lifted.context.hit.multiplier).toBe(2.1659);
    expect(notes[0]).toContain('level 15 (13 + lohen +1, skirk +1)');
  });

  it('follows the row\'s own conditions: High Spirits off on this row reads it unraised', () => {
    const r = skillRow({ conditionals: { 'kit:lohen/high_spirits': 0 } });
    expect(raiseRow(r, [HIGH_SPIRITS], {}, RAISED).row).toBe(r);
    expect(raiseRow(skillRow(), [HIGH_SPIRITS], { 'kit:lohen/high_spirits': 0 }, RAISED).row
      .context.hit.multiplier).toBe(1.9399);
  });

  it('raises only its own talent', () => {
    const r = skillRow();
    expect(raiseRow(r, [TARTAGLIA], {}, RAISED).row).toBe(r);
  });

  it('never guesses: an unknown talent row, or no published row, leaves the row as it was', () => {
    const unnamed = skillRow({ hit: null });
    const a = raiseRow(unnamed, [SKIRK], {}, RAISED);
    expect(a.row).toBe(unnamed);
    expect(a.notes[0]).toMatch(/talent row is unknown/);

    const past: FormulaRaisedTalent[] = [{
      talent: 'elemental_skill', level: 15, max_raise: 1, rows: [],
      unavailable: [{ raise_by: 1, reason: 'elemental_skill has no published row at level 16' }],
    }];
    const b = raiseRow(skillRow(), [SKIRK], {}, past);
    expect(b.row.context.hit.multiplier).toBe(1.9399);
    expect(b.notes[0]).toMatch(/not applied — elemental_skill has no published row at level 16/);

    const c = raiseRow(skillRow(), [SKIRK], {}, []);
    expect(c.notes[0]).toMatch(/no row was published at that level/);
  });

  it('is what synthesizeRecipe scores, and changes nothing else in the hit', () => {
    const plain = synthesizeRecipe([skillRow()], [], TEAM);
    const lifted = synthesizeRecipe([skillRow()], [HIGH_SPIRITS], TEAM, {}, [], undefined, RAISED);
    expect(lifted.hits[0].talent / plain.hits[0].talent).toBeCloseTo(2.0529 / 1.9399, 12);
    expect({ ...lifted.hits[0], talent: 0, gcsimAverageDamage: 0 })
      .toEqual({ ...plain.hits[0], talent: 0, gcsimAverageDamage: 0 });
    expect(lifted.meta.formula?.assumptions).toContain(
      'Masterstroke 1-Hit: Elemental Skill read at level 14 (13 + lohen +1)');
  });
});
