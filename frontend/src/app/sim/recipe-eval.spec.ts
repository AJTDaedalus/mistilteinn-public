import { describe, expect, it } from 'vitest';

import {
  NO_STATS, energyRatio, evaluateHit, evaluateRecipe, type CandidateStats,
} from './recipe-eval';
import { computeDamage } from './damage';
import { parseSample, resolveConversions, type Recipe, type RecipeHit } from './recipe';

/**
 * G.4 — applying a candidate's stats to a calibrated hit.
 *
 * **The fixtures are not here.** `scripts/verify-gcsim-recipe.mjs` runs the real check as its
 * own CI step: it takes a calibration captured at *zero artifact stats*, applies the stats a
 * different gcsim run actually used, and matches that run's own numbers to 1.986e-16.
 *
 * What a stub proves and that gate cannot is the negative space — that a goblet's element
 * bonus reaches only its own element, that crit stays clamped after the candidate's own crit
 * rate is added, and that `flatDamage` is deliberately *not* scaled.
 */

const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
  mine: true,
  owner: 0,
  abil: 'x', attackTag: 1, element: 'cryo', talent: 2, scaling: 'atk', flatDamage: 0,
  // **Deliberately different.** In a valid recipe these are equal — calibration runs at zero
  // artifact stats — so a stub that makes them equal cannot tell `baseStat` from
  // `calibratedScaling`, and the mutation swapping them survives. The gate cannot catch that
  // either, for the same reason, so this is the only place it can be caught.
  calibratedScaling: 1500, bonusDmg: 0, critRate: 0, critDmg: 0,
  conversions: {},
  // **Deliberately not all equal.** These are the three parts a total is built from, and a
  // stub that collapses them cannot tell `base × (1 + pct)` from a re-multiplied total.
  calibratedBase: { atk: 1000, hp: 10000, def: 800 },
  calibratedPercent: { atk: 0, hp: 0, def: 0 },
  calibratedFlat: { atk: 0, hp: 0, def: 0 },
  defMultiplier: 0.5, resMultiplier: 0.9, ampMultiplier: 1, gcsimAverageDamage: 900, ...over,
});

const stats = (over: Partial<CandidateStats> = {}): CandidateStats => ({ ...NO_STATS, ...over });

describe('evaluateHit', () => {
  it('reproduces the calibration when the candidate contributes nothing', () => {
    // base 2*1000 = 2000; 2000 * 1 * 0.5 * 0.9 = 900.
    expect(evaluateHit(hit(), stats())).toBeCloseTo(900, 9);
  });

  it('applies a percentage stat to the base, not to the calibrated total', () => {
    // baseStat 1000 at +46.4% → 1464; 2*1464*0.5*0.9 = 1317.6. Using calibratedScaling here
    // would compound the calibration's own artifacts on top of the candidate's.
    expect(evaluateHit(hit(), stats({ atkPercent: 0.464 }))).toBeCloseTo(1317.6, 6);
  });

  it('adds flat stats after the percentage', () => {
    expect(evaluateHit(hit(), stats({ atkPercent: 1, atkFlat: 500 }))).toBeCloseTo(2250, 6);
  });

  it.each([
    // base 10000, doubled by +100% HP → 20000; talent 2 → 40000; × 0.5 × 0.9 = 18000.
    ['hp', { hpPercent: 1 }, 18000, 9000],
    // base 800, doubled → 1600; talent 2 → 3200; × 0.45 = 1440.
    ['def', { defPercent: 1 }, 1440, 720],
  ] as const)('scales off %s when the ability does', (scaling, over, moved, unmoved) => {
    expect(evaluateHit(hit({ scaling }), stats(over))).toBeCloseTo(moved, 6);
    // …and is unmoved by a stat it does not scale off.
    expect(evaluateHit(hit({ scaling }), stats({ atkPercent: 1 }))).toBeCloseTo(unmoved, 6);
  });

  it('takes elemental mastery whole, since it has no base or percentage form', () => {
    // scaling = 200; talent 2 → 400; × 0.45 = 180.
    expect(evaluateHit(hit({ scaling: 'em' }), stats({ elementalMastery: 200 })))
      .toBeCloseTo(180, 6);
  });

  it('lets a goblet reach only its own element', () => {
    // The reason RecipeHit.element must carry gcsim's name rather than its internal enum.
    const cryo = stats({ elementBonus: { cryo: 0.5 } });

    expect(evaluateHit(hit({ element: 'cryo' }), cryo)).toBeCloseTo(1350, 6);
    expect(evaluateHit(hit({ element: 'physical' }), cryo)).toBeCloseTo(900, 6);
  });

  it('lets an all-element bonus reach every hit', () => {
    const all = stats({ allElementBonus: 0.5 });

    expect(evaluateHit(hit({ element: 'physical' }), all)).toBeCloseTo(1350, 6);
  });

  it('adds the candidate crit to the calibration crit', () => {
    // calibrated cr 0.25/cd 1, candidate +0.25/+1 → 0.5 * 2 = 1.0 → doubled.
    const h = hit({ critRate: 0.25, critDmg: 1 });
    expect(evaluateHit(h, stats({ critRate: 0.25, critDmg: 1 })))
      .toBeCloseTo(evaluateHit(h, stats()) / 1.25 * 2, 6);
  });

  it('clamps crit rate after adding the candidate, not before', () => {
    // A build stacking past 100% must not be credited for the overflow.
    const h = hit({ critRate: 0.8, critDmg: 1 });
    expect(evaluateHit(h, stats({ critRate: 0.9 }))).toBeCloseTo(evaluateHit(h, stats({ critRate: 0.2 })), 6);
  });

  it('does not scale flat damage by the candidate', () => {
    // flatDamage is baked in at calibration. For a conversion passive like Redhorn — flat
    // damage from DEF — it goes stale when the candidate's DEF differs, and pretending
    // otherwise would silently invent a number gcsim never computed.
    //
    // **Perturbing the stat this hit actually scales off.** The first version of this test
    // moved `defPercent` on an ATK-scaling hit, so the mutation that scaled flat damage by
    // the candidate changed nothing and survived.
    const h = hit({ flatDamage: 1000, scaling: 'atk' });

    // baseStat 1000 at +100% → 2000. base = 2*2000 + 1000 = 5000; x 0.5 x 0.9 = 2250.
    // Were flatDamage scaled too it would be 2*2000 + 2000 = 6000 → 2700.
    expect(evaluateHit(h, stats({ atkPercent: 1 }))).toBeCloseTo(2250, 6);
    expect(evaluateHit(h, stats({ atkPercent: 1 }))).not.toBeCloseTo(2700, 6);
  });

  it('applies the amplifying multiplier last', () => {
    expect(evaluateHit(hit({ ampMultiplier: 2 }), stats())).toBeCloseTo(1800, 9);
  });
});

describe('conversions', () => {
  it('rescales a resolved conversion from the candidate’s own total', () => {
    // Redhorn: flat damage is 40% of DEF. base DEF 800 → flat 320; at +100% DEF the total is
    // 1600 → flat 640. base = 2*1000 + 640 = 2640; x 0.45 = 1188.
    const h = hit({
      flatDamage: 320,
      conversions: { flatDamage: { from: 'def', perUnit: 0.4 } },
    });

    expect(evaluateHit(h, stats({ defPercent: 1 }))).toBeCloseTo(1188, 6);
  });

  it('leaves an unresolved conversion frozen rather than guessing a source', () => {
    // Inventing a scaling for a term whose source was never identified would put a confident
    // wrong number in every hit that carries it.
    const h = hit({ flatDamage: 320 });

    expect(evaluateHit(h, stats({ defPercent: 1 }))).toBeCloseTo(evaluateHit(h, stats()), 9);
  });

  it('rescales a conversion that landed in flat ATK, feeding the scaling stat', () => {
    // Noelle's burst converts DEF into flat ATK. At +100% DEF the flat ATK doubles, and it is
    // added *after* the ATK percentage — a percentage multiplies base only.
    const h = hit({
      calibratedFlat: { atk: 400, hp: 0, def: 0 },
      conversions: { flatAtk: { from: 'def', perUnit: 0.5 } },
    });

    // scaling = 1000 * 1 + (0.5 * 1600) = 1800; talent 2 → 3600; x 0.45 = 1620.
    expect(evaluateHit(h, stats({ defPercent: 1 }))).toBeCloseTo(1620, 6);
  });

  it('adds the calibration percentage to the candidate’s rather than compounding', () => {
    // base 1000 at a calibrated +50% and a candidate +50% is 1000*(1+0.5+0.5) = 2000, not
    // 1000*1.5*1.5 = 2250. Compounding is invisible whenever the calibration has no buffs.
    const h = hit({ calibratedPercent: { atk: 0.5, hp: 0, def: 0 } });

    expect(evaluateHit(h, stats({ atkPercent: 0.5 }))).toBeCloseTo(2 * 2000 * 0.45, 6);
  });
});

describe('evaluateRecipe', () => {
  const recipe = (hits: RecipeHit[]): Recipe =>
    ({ hits, seed: '1', meta: { seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [], minimumEnergyRecharge: null } });

  it('sums every hit', () => {
    expect(evaluateRecipe(recipe([hit(), hit(), hit()]), stats())).toBeCloseTo(2700, 6);
  });

  it('is zero for a recipe with no hits, rather than throwing', () => {
    expect(evaluateRecipe(recipe([]), stats())).toBe(0);
  });

  it('respects each hit’s own element', () => {
    const mixed = recipe([hit({ element: 'cryo' }), hit({ element: 'physical' })]);

    expect(evaluateRecipe(mixed, stats({ elementBonus: { cryo: 1 } }))).toBeCloseTo(2700, 6);
  });
});

describe('energyRatio — weighing Energy Recharge', () => {
  /**
   * The owner's ask: *"it doesn't do anything above the threshold where the character can burst
   * on time, but if they can't, the DPS gain from ER should be evaluated in whether or not the
   * reduced delay is worth the cost of dropping dps stats."*
   *
   * And their correction, which is why this measures DPS rather than burst damage: *"The burst
   * causes a delay, which reduces team DPS significantly. And her burst provides a buff
   * teamwide so it carries more weight than its full damage."*
   */
  const SWEEP = [
    { energyRecharge: 0.2, burstInstances: 2, standardDeviation: 0, dps: 160000 },
    { energyRecharge: 0.45, burstInstances: 3, standardDeviation: 0, dps: 180000 },
    { energyRecharge: 0.8, burstInstances: 4, standardDeviation: 0, dps: 200000 },
  ];

  const recipeWith = (meta: Record<string, unknown>) => ({
    hits: [],
    meta: {
      seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [],
      minimumEnergyRecharge: null, ...meta,
    },
  } as unknown as Recipe);

  const withEr = (energyRecharge: number) => ({ ...NO_STATS, energyRecharge });

  it('is 1 at the ER the calibration ran at', () => {
    const recipe = recipeWith({ energySweep: SWEEP, calibratedEnergyDps: 180000 });
    expect(energyRatio(recipe, withEr(0.45))).toBe(1);
  });

  it('is below 1 for a candidate that cannot burst on time', () => {
    // Not "fewer burst hits" — less team DPS, which is what the delay and the missing buff
    // actually cost.
    const recipe = recipeWith({ energySweep: SWEEP, calibratedEnergyDps: 180000 });
    expect(energyRatio(recipe, withEr(0.2))).toBeCloseTo(160000 / 180000);
  });

  it('rewards ER that buys a burst the calibration did not have', () => {
    const recipe = recipeWith({ energySweep: SWEEP, calibratedEnergyDps: 180000 });
    expect(energyRatio(recipe, withEr(0.9))).toBeCloseTo(200000 / 180000);
  });

  it('is a step function between rungs, because each rung is a run', () => {
    const recipe = recipeWith({ energySweep: SWEEP, calibratedEnergyDps: 180000 });
    expect(energyRatio(recipe, withEr(0.79))).toBeCloseTo(1);
  });

  it('is 1 when no ladder was measured', () => {
    expect(energyRatio(recipeWith({ calibratedEnergyDps: 180000 }), withEr(0))).toBe(1);
  });

  it('is 1 when a ladder carries no DPS', () => {
    // An older cached recipe, or a rung gcsim would not price. Nothing is scaled.
    const bare = SWEEP.map(({ dps: _dps, ...rest }) => rest);
    expect(energyRatio(recipeWith({ energySweep: bare, calibratedEnergyDps: 180000 }),
      withEr(0.2))).toBe(1);
  });
});


describe('energyRatio — the denominator is the same ladder', () => {
  /**
   * It was `dpsAt(sweep, candidateEr) / calibratedEnergyDps`: a numerator floored onto a
   * 20-iteration rung over a denominator that was a 100-iteration aggregate at the build's
   * exact ER. Two different measurements of the same quantity, so the ratio at the calibration
   * point was **not 1** — 0.928 for the owner's Furina, whose 0.279 artifact ER floored onto
   * the 0.20 rung (142,380) while the aggregate read 153,417.
   */
  const sweep = [
    { energyRecharge: 0.2, burstInstances: 2, standardDeviation: 0, dps: 142380 },
    { energyRecharge: 0.279, burstInstances: 2, standardDeviation: 0, dps: 151000 },
    { energyRecharge: 0.8, burstInstances: 3, standardDeviation: 0, dps: 158306 },
  ];

  const recipeWith = (meta: Record<string, unknown>) => ({
    hits: [], seed: '1',
    meta: {
      seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [],
      minimumEnergyRecharge: null, energySweep: sweep, calibratedEnergyDps: 153417, ...meta,
    },
  } as unknown as Parameters<typeof energyRatio>[0]);

  const at = (er: number) => ({ ...NO_STATS, energyRecharge: er });

  it('is exactly 1 at the ER the calibration ran at', () => {
    expect(energyRatio(recipeWith({ calibratedEnergyRecharge: 0.279 }), at(0.279))).toBe(1);
  });

  it('pays a candidate for crossing a rung, measured against that same point', () => {
    expect(energyRatio(recipeWith({ calibratedEnergyRecharge: 0.279 }), at(0.8)))
      .toBeCloseTo(158306 / 151000, 9);
  });

  it('charges a candidate that falls below it', () => {
    expect(energyRatio(recipeWith({ calibratedEnergyRecharge: 0.279 }), at(0.2)))
      .toBeCloseTo(142380 / 151000, 9);
  });

  it('falls back to the aggregate for a recipe cached before the field existed', () => {
    // A graceful fallback rather than a throw — but `SCHEMA` 5 makes those entries miss, so
    // this is the belt to that braces.
    expect(energyRatio(recipeWith({}), at(0.279))).toBeCloseTo(151000 / 153417, 9);
  });
});

/**
 * Elemental Mastery on a **gcsim** recipe — the defect PR #368 found and the owner approved
 * fixing on 2026-11-13.
 *
 * gcsim publishes the snapshot EM on every `calc` event (`em`), and for a melt or vaporize hit
 * the reaction (`reaction_type`), its base multiplier (`react_mult`) and the reaction bonus
 * (`react_bonus`) — `pkg/enemy/damage.go:105-116` at the pin. A recipe that read none of them
 * scored an EM-scaling hit off the candidate's EM alone (a zero-EM calibration made it zero
 * damage) and froze the amplifying multiplier at the calibration's EM, so **artifact EM was
 * worth nothing** to a vaporize or melt build however much of it a candidate carried.
 *
 * Each expectation is the Python oracle's own answer —
 * `backend/app/formula/genshin/damage.py:compute_damage` with the inputs named beside it — so
 * the recipe path and the damage chain cannot quietly disagree. Tolerance is `1e-6` relative
 * where the amplifying term is involved, because it goes through `damage.ts`, which rounds to
 * f32 as the GPU must (`docs/CROSSVAL_gcsim.md` measures that at 3.51e-07 worst case).
 */
describe('elemental mastery on a gcsim-calibrated recipe', () => {
  /** Character 90 against enemy 100: `190 / (190 + 200)`, gcsim `damage.go`. */
  const DEF_MOD = 190 / 390;
  const RES_MOD = 0.9;

  /** A calc/damage pair as gcsim logs it, with the EM and amplifying fields populated. */
  function sample(over: Record<string, number | string | boolean>): RecipeHit {
    const logs: Record<string, number | string | boolean> = {
      abil: 'Skill', talent: 2, total_scaling: 1000, base_atk: 1000, atk_per: 0, flat_atk: 0,
      base_hp: 10000, base_def: 800, flat_dmg: 0, flat_hp: 0, flat_def: 0, hp_per: 0,
      def_per: 0, bonus_dmg: 0.5, cr: 0.25, cd: 1, def_mod: DEF_MOD, res_mod: RES_MOD,
      amp_mult_total: 0, use_hp: false, use_def: false, use_em: false, em: 0,
      melt_vape: false, reaction_type: '', react_mult: 0, react_bonus: 0,
      avg_crit_dmg_react: 0, damage: 1, ele: 0, ...over,
    };
    const n = (k: string) => logs[k] as number;
    const preCrit = n('talent') * n('total_scaling') * (1 + n('bonus_dmg')) * DEF_MOD * RES_MOD;
    // gcsim's own relations, `damage.go:164` and `:173-177`.
    logs['avg_crit_dmg'] = preCrit * (1 + n('cr') * n('cd'));
    if (logs['melt_vape']) {
      const amp = n('react_mult') * (1 + (2.78 * n('em')) / (1400 + n('em')) + n('react_bonus'));
      logs['amp_mult_total'] = amp;
      logs['avg_crit_dmg_react'] = n('avg_crit_dmg') * amp;
    }
    return parseSample({
      logs: [
        { event: 'calc', char_index: 0, logs } as never,
        { event: 'damage', logs: { abil: 'Skill', ele: 'pyro', 'attack-tag': 4 } },
      ],
    }).hits[0];
  }

  describe('an EM-scaling hit', () => {
    // 120 EM before artifacts: character, weapon, set and team buffs, as gcsim measured them.
    const emHit = () => sample({ use_em: true, em: 120, total_scaling: 120 });

    it('counts the EM the character already has, not only the candidate’s', () => {
      // damage.py: multiplier 2, EM 120, dmg_bonus 0.5, cr 0.25, cd 1, lvl 90 vs 100, res 0.1.
      expect(evaluateHit(emHit(), stats())).toBeCloseTo(197.3076923076923, 6);
    });

    it('adds artifact EM on top of it, by exactly what the damage chain says', () => {
      // damage.py with EM 320 = 120 + the candidate's 200.
      const gain = evaluateHit(emHit(), stats({ elementalMastery: 200 }))
        - evaluateHit(emHit(), stats());
      expect(gain).toBeCloseTo(526.1538461538462 - 197.3076923076923, 6);
    });
  });

  describe('a vaporize hit', () => {
    // Pyro onto Hydro is the 1.5× side — `pkg/reactable/vaporize.go:26` at the pin.
    const vape = () => sample({
      melt_vape: true, reaction_type: 'vaporize', react_mult: 1.5, em: 100, react_bonus: 0.15,
    });

    it('carries gcsim’s amplified average, not the pre-reaction one', () => {
      // `avg_crit_dmg` is written *before* the amplifying multiplier (`damage.go:164`), so a
      // vaporizing teammate's frozen hit read as a fraction of its damage. damage.py at EM 100.
      expect(vape().gcsimAverageDamage).toBeCloseTo(3293.394230769231, 6);
    });

    it('reproduces the calibration when the candidate carries no EM', () => {
      const h = vape();
      expect(Math.abs(evaluateHit(h, stats()) / h.gcsimAverageDamage - 1)).toBeLessThan(1e-6);
    });

    it('pays for artifact EM through the amplifying multiplier', () => {
      // damage.py, reverse_vaporize, reaction_bonus 0.15, EM 400 = 100 + the candidate's 300.
      const h = vape();
      const predicted = evaluateHit(h, stats({ elementalMastery: 300 }));
      expect(Math.abs(predicted / 4359.951923076922 - 1)).toBeLessThan(1e-6);
      // And it agrees with the browser chain the single-hit kernel uses.
      const chain = computeDamage({
        hit: {
          multiplier: 2, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0,
          amplifying: 'reverse_vaporize', reactionBonus: 0.15,
        },
        scalingValue: 1000, dmgBonus: 0.5, critRate: 0.25, critDmg: 1, elementalMastery: 400,
        characterLevel: 90, target: { level: 100, resistance: 0.1, defReduction: 0, defIgnore: 0 },
      });
      expect(Math.abs(predicted / chain - 1)).toBeLessThan(1e-6);
    });

    it.each([
      ['melt', 2, 'melt'],
      ['melt', 1.5, 'reverse_melt'],
      ['vaporize', 2, 'vaporize'],
      ['vaporize', 1.5, 'reverse_vaporize'],
    ] as const)('reads %s at ×%s as %s', (type, mult, expected) => {
      const h = sample({ melt_vape: true, reaction_type: type, react_mult: mult, em: 50 });
      expect(h.amplifying).toEqual({ reaction: expected, reactionBonus: 0 });
      expect(h.calibratedEm).toBe(50);
    });

    it('keeps an amplifying multiplier it cannot name frozen rather than guessing', () => {
      // A base multiplier gcsim does not use for melt or vaporize: the hit replays as measured
      // and EM does not move it — the honest default. `ampMultiplier ≠ 1` keeps EM live for
      // pruning regardless, which over-states the bound and is the safe direction.
      const h = sample({ melt_vape: true, reaction_type: 'vaporize', react_mult: 1.75, em: 50 });
      expect(h.amplifying).toBeUndefined();
      expect(evaluateHit(h, stats({ elementalMastery: 500 })))
        .toBeCloseTo(evaluateHit(h, stats()), 9);
    });
  });

  it('leaves a hit that neither scales off EM nor amplifies untouched by EM', () => {
    const plain = sample({ em: 80 });
    expect(evaluateHit(plain, stats({ elementalMastery: 500 })))
      .toBeCloseTo(plain.gcsimAverageDamage, 9);
  });
});

/**
 * EM folded into flat damage — the gap DECISIONS §39 left open.
 *
 * gcsim writes the EM part of a hit such as Nahida's Tri-Karma Purification as `FlatDmg = em ×
 * triKarmaEM` (`internal/characters/nahida/skill.go:219-220`), so a candidate's EM has to move
 * that term — through the same resolved-conversion path a Redhorn DEF term already takes.
 *
 * Expected values are `backend/app/formula/genshin/damage.py:compute_damage` with the EM part
 * as an `extra_terms` `ScalingTerm(ELEMENTAL_MASTERY, 3.5088)`, the inputs being a real
 * Tri-Karma `calc` event (talent 9, A Thousand Floating Dreams, seed 12345).
 */
describe('elemental mastery converted into flat damage', () => {
  /** One Tri-Karma `calc`, as gcsim logged it, at a given snapshot EM. */
  function triKarma(em: number, over: Record<string, number> = {}): Recipe {
    const logs = {
      abil: 'Tri-Karma Purification', talent: 1.7544, total_scaling: 1008.9632796,
      base_atk: 840.802733, atk_per: 0.2, flat_atk: 0, base_hp: 10360.0405293, hp_per: 0,
      flat_hp: 0, base_def: 630.2145834, def_per: 0, flat_def: 0,
      flat_dmg: 3.5088 * em, bonus_dmg: 0.6298144000000001, cr: 0.10394432, cd: 0.5,
      def_mod: 0.48717948717948717, res_mod: 1.2, amp_mult_total: 0, use_hp: false,
      use_def: false, use_em: false, em, melt_vape: false, react_mult: 0, react_bonus: 0,
      avg_crit_dmg: 3110.061174171217, avg_crit_dmg_react: 0, damage: 1, ele: 18, ...over,
    };
    return parseSample({
      logs: [
        { event: 'calc', char_index: 0, logs } as never,
        { event: 'damage', logs: { abil: logs.abil, ele: 'dendro', 'attack-tag': 4 } },
      ],
    });
  }

  /** The baseline, resolved against a probe that moved EM by 100 and ATK% by 0.5. */
  function resolved(): RecipeHit {
    const baseline = triKarma(379.81440000000003);
    resolveConversions(baseline, triKarma(479.81440000000003, { atk_per: 0.7 }));
    return baseline.hits[0];
  }

  it('reproduces the calibration when the candidate carries no EM', () => {
    // damage.py, EM 379.8144: 3110.0611741712173 — gcsim's own `avg_crit_dmg` to the digit.
    expect(evaluateHit(resolved(), stats())).toBeCloseTo(3110.0611741712173, 6);
  });

  it('pays for artifact EM through the flat term, by exactly what the damage chain says', () => {
    // damage.py with the extra term at EM 579.8144 = 379.8144 + the candidate's 200.
    expect(evaluateHit(resolved(), stats({ elementalMastery: 200 })))
      .toBeCloseTo(3813.4593653187458, 6);
  });

  it('left frozen, the same hit valued artifact EM at nothing — the defect this closes', () => {
    const frozen = triKarma(379.81440000000003).hits[0];
    expect(evaluateHit(frozen, stats({ elementalMastery: 200 })))
      .toBeCloseTo(evaluateHit(frozen, stats()), 9);
  });
});
