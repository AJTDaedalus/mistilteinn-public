import { describe, expect, it } from 'vitest';
import type { OptimizerDiscSummary } from './optimizer.service';
import { rollupSubstats } from './disc-rollup';

function makeDisc(substats: OptimizerDiscSummary['substats']): OptimizerDiscSummary {
  return {
    disc_id: 'd',
    slot: 1,
    set_id: 1,
    set_name: '',
    main_stat_type: 'atk_pct',
    main_stat_value: 3000,
    rarity: 'S',
    substats: substats ?? [],
    score: null,
    icon_path: '',
  };
}

describe('rollupSubstats', () => {
  it('returns empty array for discs with no substats', () => {
    const discs = Array.from({ length: 6 }, () => makeDisc([]));
    expect(rollupSubstats(discs)).toEqual([]);
  });

  it('displays total rolls (issue #65), filtered to substats with at least one upgrade', () => {
    const discs = [
      makeDisc([{ stat_type: 'crit_dmg', value: 480, rolls: 1 }]),   // 0 upgrades
      makeDisc([{ stat_type: 'crit_dmg', value: 960, rolls: 2 }]),   // 1 upgrade
      makeDisc([{ stat_type: 'atk_pct', value: 300, rolls: 1 }]),    // 0 upgrades
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
    ];
    const result = rollupSubstats(discs);
    const cd = result.find((r) => r.stat_type === 'crit_dmg')!;
    // Total across both crit_dmg discs (1 + 2 = 3), not the upgrade-only count (1).
    expect(cd.rolls).toBe(3);
    expect(cd.value).toBe(1440);
    // atk_pct has 0 upgrades and should be filtered out
    expect(result.find((r) => r.stat_type === 'atk_pct')).toBeUndefined();
  });

  it('filters out substats with no upgrades (initial roll only)', () => {
    const discs = [
      makeDisc([{ stat_type: 'crit_rate', value: 240, rolls: 1 }]),
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
    ];
    expect(rollupSubstats(discs)).toEqual([]);
  });

  it('returns entries in game order, not ranked by rolls', () => {
    const discs = [
      makeDisc([
        { stat_type: 'crit_rate', value: 240, rolls: 1 },   // 0 upgrades → filtered
        { stat_type: 'crit_dmg', value: 1440, rolls: 3 },   // 2 upgrades, total 3
        { stat_type: 'atk_pct', value: 600, rolls: 2 },     // 1 upgrade, total 2
      ]),
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
    ];
    const result = rollupSubstats(discs);
    expect(result).toHaveLength(2);
    // atk_pct precedes crit_dmg in game order despite having fewer rolls,
    // and despite crit_dmg being encountered first in the input.
    expect(result[0]).toEqual({ stat_type: 'atk_pct', rolls: 2, value: 600 });
    expect(result[1]).toEqual({ stat_type: 'crit_dmg', rolls: 3, value: 1440 });
  });

  it('orders the full substat pool exactly as the game lists it', () => {
    const discs = [
      makeDisc([
        { stat_type: 'anomaly_proficiency', value: 18, rolls: 2 },
        { stat_type: 'crit_dmg', value: 960, rolls: 2 },
        { stat_type: 'hp', value: 224, rolls: 2 },
        { stat_type: 'pen_flat', value: 18, rolls: 2 },
      ]),
      makeDisc([
        { stat_type: 'def_pct', value: 960, rolls: 2 },
        { stat_type: 'atk', value: 38, rolls: 2 },
        { stat_type: 'crit_rate', value: 480, rolls: 2 },
        { stat_type: 'hp_pct', value: 600, rolls: 2 },
      ]),
      makeDisc([
        { stat_type: 'def', value: 30, rolls: 2 },
        { stat_type: 'atk_pct', value: 600, rolls: 2 },
      ]),
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
    ];
    expect(rollupSubstats(discs).map((r) => r.stat_type)).toEqual([
      'hp',
      'atk',
      'def',
      'hp_pct',
      'atk_pct',
      'def_pct',
      'pen_flat',
      'crit_rate',
      'crit_dmg',
      'anomaly_proficiency',
    ]);
  });

  it('places unrecognized stat keys last without dropping them', () => {
    const discs = [
      makeDisc([
        { stat_type: 'mystery_stat', value: 100, rolls: 2 },
        { stat_type: 'crit_rate', value: 480, rolls: 2 },
      ]),
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
      makeDisc([]),
    ];
    expect(rollupSubstats(discs).map((r) => r.stat_type)).toEqual(['crit_rate', 'mystery_stat']);
  });
});
