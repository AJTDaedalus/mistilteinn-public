import { describe, expect, it } from 'vitest';

import type { Recipe, RecipeHit } from './recipe';
import type { StatPool } from './artifact-score';
import type { DrawModel, Piece } from './artifact-projection';
import { grade, idealFor, rankArtifact } from './artifact-ranking';
import { evaluateRecipe } from './recipe-eval';
import { candidateStatsFrom } from './recipe-search';

/**
 * `TASKS_artifact_ranking.md` A.6 — the five numbers, the grade, and the refusals.
 *
 * The recipe is the same minimal fixture `artifact-score.spec.ts` uses, so a failure here is
 * about the ranking rather than about the evaluator.
 */

const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
  mine: true,
  owner: 0,
  abil: 'x', attackTag: 1, element: 'cryo', talent: 2, scaling: 'atk', flatDamage: 0,
  calibratedScaling: 1000, bonusDmg: 0, critRate: 0, critDmg: 0,
  conversions: {},
  calibratedBase: { atk: 1000, hp: 10000, def: 800 },
  calibratedPercent: { atk: 0, hp: 0, def: 0 },
  calibratedFlat: { atk: 0, hp: 0, def: 0 },
  defMultiplier: 0.5, resMultiplier: 0.9, ampMultiplier: 1, gcsimAverageDamage: 900, ...over,
});

const recipe = (over: Partial<Recipe['meta']> = {}): Recipe => ({
  hits: [hit()],
  seed: '1',
  meta: {
    seed: '1', staleConversions: [], characters: [], unstable: [],
    calibratedSetIds: [], minimumEnergyRecharge: null, ...over,
  },
});

const MODEL: DrawModel = {
  rollTiers: {
    '5': [
      { quantity: 'atk_pct', values: [0.04, 0.05, 0.06, 0.07] },
      { quantity: 'crit_rate', values: [0.02, 0.03, 0.035, 0.039] },
      { quantity: 'crit_dmg', values: [0.05, 0.06, 0.07, 0.078] },
      { quantity: 'flat_hp', values: [200, 230, 260, 300] },
      { quantity: 'energy_recharge', values: [0.04, 0.05, 0.06, 0.065] },
    ],
  },
  substatWeights: {
    atk_pct: 4, crit_rate: 3, crit_dmg: 3, flat_hp: 6, energy_recharge: 4,
  },
  weightsCaveat: 'cited, not derived',
};

const bare = (): StatPool[] => [{}, {}, {}, {}, {}];

function piece(over: Partial<Piece> = {}): Piece & { id: string } {
  return {
    id: 'a1',
    rarity: 5,
    // A sands with an ATK% main. **The main stat is never also a substat** — Genshin cannot
    // produce that piece, and a fixture that did would make `eligibleNewLines` look wrong.
    stats: { atk_pct: 0.466, crit_rate: 0.039, crit_dmg: 0.078 },
    mainStatQuantity: 'atk_pct',
    potential: {
      rollsRemaining: 5, rollsTotal: 5, gainsASubstat: true,
      substatQuantities: ['crit_rate', 'crit_dmg'],
    },
    ...over,
  } as Piece & { id: string };
}

/** The build's own damage, which every delta is measured against. */
function baselineOf(r: Recipe, equipped: readonly StatPool[]): number {
  return evaluateRecipe(r, candidateStatsFrom(equipped));
}

function contextFor(r: Recipe, equipped: readonly StatPool[], slot: number, p: Piece) {
  const empty = [...equipped];
  empty[slot] = {};
  const mainOnlyPools = [...equipped];
  mainOnlyPools[slot] = p.mainStatQuantity ? { [p.mainStatQuantity]: 0.466 } : {};
  return {
    baseline: baselineOf(r, equipped),
    emptySlot: evaluateRecipe(r, candidateStatsFrom(empty)),
    // The grade's zero point: the piece's main stat with nothing rolled on it.
    mainOnly: evaluateRecipe(r, candidateStatsFrom(mainOnlyPools)),
    ideal: idealFor(r, equipped, slot, {
      rarity: p.rarity,
      mainStatQuantity: p.mainStatQuantity,
      mainStatValue: 0.466,
      rollsTotal: p.potential?.rollsTotal ?? 5,
    }, MODEL),
  };
}

describe('rankArtifact', () => {
  const r = recipe();
  const equipped = bare();
  const p = piece();
  const ctx = contextFor(r, equipped, 2, p);
  const row = rankArtifact(r, equipped, 2, p, MODEL, ctx);

  it('orders worst <= current <= average <= best', () => {
    // The band is the point of showing four numbers rather than one: a +0 with a wide band is a
    // lottery ticket, and a narrow one is a known quantity.
    expect(row.worst).toBeLessThanOrEqual(row.current);
    expect(row.current).toBeLessThanOrEqual(row.average);
    expect(row.average).toBeLessThanOrEqual(row.best);
  });

  it('signs the delta against the build as it stands', () => {
    expect(row.delta).toBeCloseTo(row.current - ctx.baseline, 6);
    expect(row.averageDelta).toBeCloseTo(row.average - ctx.baseline, 6);
    // The slot is empty in this fixture, so any real piece is an upgrade.
    expect(row.delta).toBeGreaterThan(0);
  });

  it('gives a piece worse than what is worn a negative delta', () => {
    const worn = bare();
    worn[2] = { atk_pct: 0.6 };
    const context = contextFor(r, worn, 2, p);
    const found = rankArtifact(r, worn, 2, p, MODEL, context);
    expect(found.delta).toBeLessThan(0);
  });

  it('takes best from the real damage function, not from a substat-weight guess', () => {
    // flat_hp carries the heaviest draw weight (6) and contributes nothing to an ATK-scaling
    // hit. A heuristic that picked the target line by weight would land there and understate
    // the piece; enumerating against the evaluator cannot.
    const onlyHp = { ...MODEL, substatWeights: { ...MODEL.substatWeights, flat_hp: 99 } };
    const found = rankArtifact(r, equipped, 2, p, onlyHp, ctx);
    expect(found.best).toBeCloseTo(row.best, 6);
  });

  it('reports the main stat rather than folding it into the score', () => {
    // DESIGN §6 asks for a wrong main stat to be a separate fact. With a real damage chain the
    // low number it produces is *correct and comparable*, so it is reported, never voided.
    const hp = piece({
      mainStatQuantity: 'flat_hp',
      stats: { flat_hp: 4780, crit_rate: 0.039, crit_dmg: 0.078 },
      potential: {
        rollsRemaining: 5, rollsTotal: 5, gainsASubstat: true,
        substatQuantities: ['crit_rate', 'crit_dmg'],
      },
    });
    const found = rankArtifact(r, equipped, 2, hp, MODEL, contextFor(r, equipped, 2, hp));
    expect(found.mainStatQuantity).toBe('flat_hp');
    expect(found.refusal).toBeNull();
    expect(Number.isFinite(found.current)).toBe(true);
  });

  it('carries the recipe\'s caveats onto every row derived from it', () => {
    // Dropping these went wrong once already: a cached recipe came back with its instability
    // forgotten and the page affirmatively called the ranking sound.
    const caveated = recipe({
      unstable: ['burst'],
      staleConversions: [{ term: 'hp_to_atk', damageShare: 0.4, label: 'x' } as never],
    });
    const found = rankArtifact(caveated, equipped, 2, p, MODEL, ctx);
    expect(found.caveats.unstable).toEqual(['burst']);
    expect(found.caveats.staleConversions).toEqual(['hp_to_atk']);
  });

  describe('refusals — never a zero standing in for a number', () => {
    it('refuses a piece the committed schedule cannot answer for', () => {
      const found = rankArtifact(
        r, equipped, 2, piece({ potential: null }), MODEL, ctx,
      );
      expect(found.refusal).toBe('noSchedule');
      expect(Number.isNaN(found.current)).toBe(true);
      expect(found.grade).toBe('');
    });

    it('refuses a rarity the draw model has no ladders for', () => {
      const found = rankArtifact(r, equipped, 2, piece({ rarity: 4 }), MODEL, ctx);
      expect(found.refusal).toBe('noLadders');
      expect(Number.isNaN(found.best)).toBe(true);
    });
  });
});

describe('grade', () => {
  it('uses Fribbels\' 5% steps, so the letters mean what a user already knows', () => {
    expect(grade(0)).toBe('F');
    expect(grade(0.049)).toBe('F');
    expect(grade(0.05)).toBe('F+');
    expect(grade(0.5)).toBe('S');
    expect(grade(0.9)).toBe('AEON');
    expect(grade(1.2)).toBe('AEON');
  });
});

describe('idealFor', () => {
  const r = recipe();

  it('is at least as good as any real piece with the same main stat', () => {
    // The denominator of the grade. If a real piece could beat it, a grade above 100% would be
    // reachable and the scale would mean nothing.
    const equipped = bare();
    const p = piece();
    const ctx = contextFor(r, equipped, 2, p);
    const row = rankArtifact(r, equipped, 2, p, MODEL, ctx);
    expect(row.best).toBeLessThanOrEqual(ctx.ideal + 1e-6);
    expect(row.fraction).toBeLessThanOrEqual(1);
    expect(row.fraction).toBeGreaterThanOrEqual(0);
  });

  it('grades a piece with nothing rolled at the bottom of the scale', () => {
    // The other end of the normalisation. If a bare piece did not land on F the scale would
    // have no floor, and every grade above it would be measuring from somewhere unstated.
    const equipped = bare();
    const empty = piece({
      stats: {},
      mainStatQuantity: null,
      potential: {
        rollsRemaining: 0, rollsTotal: 5, gainsASubstat: false, substatQuantities: [],
      },
    });
    const found = rankArtifact(
      r, equipped, 2, empty, MODEL, contextFor(r, equipped, 2, empty),
    );
    expect(found.fraction).toBeCloseTo(0, 6);
    expect(found.grade).toBe('F');
  });

  it('does not let a big main stat drag every grade to the top', () => {
    // **The regression this test exists for.** With `emptySlot` as the zero point the main stat
    // sat in both ends of the ratio, and on the owner's real inventory every ATK% sands graded
    // `WTF+` — 46.6% before a single substat drowns whatever was rolled. A grade that cannot
    // separate a good piece from a poor one is not a grade.
    const equipped = bare();
    const poor = piece({
      // The full main stat, and substats barely worth anything.
      stats: { atk_pct: 0.466, crit_rate: 0.02, crit_dmg: 0.05 },
      potential: {
        rollsRemaining: 0, rollsTotal: 5, gainsASubstat: false,
        substatQuantities: ['crit_rate', 'crit_dmg'],
      },
    });
    const found = rankArtifact(
      r, equipped, 2, poor, MODEL, contextFor(r, equipped, 2, poor),
    );
    expect(found.fraction).toBeLessThan(0.5);
    expect(found.grade).not.toBe('AEON');
  });

  it('grades a maxed real piece near the top without exceeding it', () => {
    const equipped = bare();
    // Four lines, every roll spent, main stat at full value: about as good as a real ATK% sands
    // gets. It must be high and it must not break the ceiling.
    const maxed = piece({
      // ATK% main, four substat lines, every one of the five upgrades spent on CRIT DMG: one
      // initial roll each plus five more on one line is six, which is the real ceiling.
      stats: {
        atk_pct: 0.466,
        crit_rate: 0.039,
        crit_dmg: 0.078 * 6,
        flat_hp: 300,
        energy_recharge: 0.065,
      },
      potential: {
        rollsRemaining: 0, rollsTotal: 5, gainsASubstat: false,
        substatQuantities: ['crit_rate', 'crit_dmg', 'flat_hp', 'energy_recharge'],
      },
    });
    const found = rankArtifact(
      r, equipped, 2, maxed, MODEL, contextFor(r, equipped, 2, maxed),
    );
    // Tight on purpose. This piece dumps every upgrade into the line the ideal would also
    // pick, so it should land very close to the ceiling without breaking it. A loose bound
    // here would have let the first draft's 117% through.
    expect(found.fraction).toBeGreaterThan(0.9);
    expect(found.fraction).toBeLessThanOrEqual(1);
  });
});
