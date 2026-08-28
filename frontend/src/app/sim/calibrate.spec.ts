import { describe, expect, it } from 'vitest';

import { calibrate, type CalibrationRuns } from './calibrate';

/**
 * R.4 — the only place a recipe is born.
 *
 * The load-bearing test is `sets calibratedSetIds`. A recipe without it silently double-counts
 * the calibrated set's 2-piece — 15–25 % on the set the user most likely cares about — and a
 * `null` id is indistinguishable from a genuine no-set calibration, so **nothing can detect
 * the omission afterwards**. Building it here is what removes the window.
 */

function dmg(over: Record<string, unknown> = {}) {
  return { event: 'damage', logs: { abil: 'Burst', ele: 'cryo', 'attack-tag': 4, ...over } };
}

function calc(over: Record<string, unknown> = {}) {
  return {
    event: 'calc',
    logs: {
      abil: 'Burst', talent: 2, total_scaling: 1000, base_atk: 1000, atk_per: 0, flat_atk: 0,
      base_hp: 10000, base_def: 800, hp_per: 0, def_per: 0, flat_dmg: 0, flat_hp: 0,
      flat_def: 0, bonus_dmg: 0, cr: 0, cd: 0, def_mod: 0.5, res_mod: 0.9,
      amp_mult_total: 0, use_hp: false, use_def: false, use_em: false,
      base_dmg: 2000, pre_crit_dmg: 900, avg_crit_dmg: 900, damage: 900, ele: 14, ...over,
    },
  };
}

const runs = (over: Partial<CalibrationRuns> = {}): CalibrationRuns => ({
  baseline: JSON.stringify({ seed: '1', logs: [dmg(), calc()] }),
  probe: JSON.stringify({ seed: '1', logs: [dmg(), calc({ def_per: 0.5 })] }),
  instances: { Burst: { mean: 3, sd: 0 } },
  ...over,
});

describe('calibrate', () => {
  it('records which set the recipe was calibrated with', () => {
    // Without this the search cannot know to skip that set's bonuses, and a null id looks
    // exactly like a calibration that equipped no set at all.
    expect(calibrate(runs(), { setIds: [15025] }).recipe.meta.calibratedSetIds).toEqual([15025]);
  });

  it('records a genuine no-set calibration as null', () => {
    expect(calibrate(runs(), { setIds: [] }).recipe.meta.calibratedSetIds).toEqual([]);
  });

  it('reports an unstable rotation rather than refusing to build a recipe', () => {
    // Refusing would leave a caller unable to say *why* it has no answer. The flag and the
    // offending ability names are more useful than an exception.
    const out = calibrate(
      runs({ instances: { Burst: { mean: 2.75, sd: 0.44 } } }), { setIds: [] },
    );

    expect(out.stable).toBe(false);
    expect(out.unstable).toEqual(['Burst']);
    expect(out.recipe.hits.length).toBeGreaterThan(0);
  });

  it('reports a stable rotation', () => {
    const out = calibrate(runs(), { setIds: [] });

    expect(out.stable).toBe(true);
    expect(out.unstable).toEqual([]);
  });

  it('resolves a conversion from the probe', () => {
    // A flat-damage term that moves with DEF, exactly as Redhorn's does. The first version of
    // this test used a fixture with **no conversion at all**, so "never resolve anything"
    // survived as a mutation — the assertion was true either way.
    const baseline = JSON.stringify({ seed: '1', logs: [dmg(), calc({ flat_dmg: 320 })] });
    // base DEF 800 → 1200 at +50 %, a ratio of 1.5; the flat term moves by the same 1.5.
    const probe = JSON.stringify({
      seed: '1', logs: [dmg(), calc({ flat_dmg: 480, def_per: 0.5 })],
    });

    const out = calibrate(runs({ baseline, probe }), { setIds: [] });

    expect(out.resolved).toBe(1);
    expect(out.unresolved).toBe(0);
    expect(out.recipe.hits[0].conversions.flatDamage).toEqual({ from: 'def', perUnit: 0.4 });
  });

  it('reports a conversion it could not resolve rather than dropping it', () => {
    const baseline = JSON.stringify({ seed: '1', logs: [dmg(), calc({ flat_dmg: 320 })] });
    // Moves by a factor no stat ratio matches — a snapshotted conversion looks like this.
    const probe = JSON.stringify({
      seed: '1', logs: [dmg(), calc({ flat_dmg: 400, def_per: 0.5 })],
    });

    const out = calibrate(runs({ baseline, probe }), { setIds: [] });

    expect(out.unresolved).toBe(1);
    expect(out.recipe.meta.staleConversions.map((c) => c.term)).toEqual(['flatDamage']);
  });

  it('finds the minimum ER when a sweep was run', () => {
    const out = calibrate(
      runs({
        energySweep: [
          { energyRecharge: 0.2, burstInstances: 0.5, standardDeviation: 0.4 },
          { energyRecharge: 0.3, burstInstances: 1, standardDeviation: 0 },
        ],
      }),
      { setIds: [], burstAbility: 'Burst' },
    );

    expect(out.recipe.meta.minimumEnergyRecharge).toBeCloseTo(0.3, 9);
  });

  it('leaves the minimum null when no sweep was run', () => {
    // An unmeasured threshold is not a passed one — but it is the caller who skipped the
    // sweep, so it is the caller that has to say so.
    expect(calibrate(runs(), { setIds: [], burstAbility: 'Burst' })
      .recipe.meta.minimumEnergyRecharge).toBeNull();
  });

  it('leaves the minimum null when no burst ability was named', () => {
    // "Performs as calibrated" is meaningless without knowing which ability defines it.
    const out = calibrate(
      runs({ energySweep: [{ energyRecharge: 0.3, burstInstances: 1, standardDeviation: 0 }] }),
      { setIds: [] },
    );

    expect(out.recipe.meta.minimumEnergyRecharge).toBeNull();
  });

  it('counts the calibration’s own burst instances rather than assuming one', () => {
    // The sweep is compared against what the calibration actually did. A recipe with three
    // bursts needs the ER for three, and hardcoding 1 would pass every build.
    const three = JSON.stringify({ seed: '1', logs: [dmg(), calc(), dmg(), calc(), dmg(), calc()] });
    const out = calibrate(
      runs({
        baseline: three,
        probe: three,
        energySweep: [
          { energyRecharge: 0.2, burstInstances: 1, standardDeviation: 0 },
          { energyRecharge: 0.6, burstInstances: 3, standardDeviation: 0 },
        ],
      }),
      { setIds: [], burstAbility: 'Burst' },
    );

    expect(out.recipe.meta.minimumEnergyRecharge).toBeCloseTo(0.6, 9);
  });
});
