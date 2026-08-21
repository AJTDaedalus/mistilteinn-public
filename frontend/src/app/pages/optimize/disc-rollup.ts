import type { OptimizerDiscSummary } from './optimizer.service';

export interface SubstatRollup {
  stat_type: string;
  rolls: number;
  value: number;
}

/**
 * Canonical substat display order — the order the game lists disc substats
 * in, which is also ZOD's `allDiscSubStatKeys` order (ZO reference:
 * `/tmp/genshin-optimizer/libs/zzz/consts/src/disc.ts`), mapped onto our
 * internal stat keys. Tools in this space present substats in game order
 * rather than ranking them, so the position of a stat is stable between
 * builds and a reader can scan for one by muscle memory.
 */
const SUBSTAT_GAME_ORDER: readonly string[] = [
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
];

/**
 * Aggregate substat rolls across all 6 discs in a build, for substats that
 * got at least one upgrade roll beyond their guaranteed initial roll (a
 * signal for "which stats this build got lucky RNG on" — a substat present
 * on every disc at its baseline is not interesting here).
 *
 * The displayed `rolls` is the TOTAL roll count (issue #65 / DECISIONS.md
 * "OQ1 resolved" — total rolls everywhere, matching disc-card and
 * rank-table); the filter still uses upgrades-beyond-baseline, since that's
 * what makes an entry notable.
 *
 * Output is in `SUBSTAT_GAME_ORDER`, not ranked — the view does no sorting
 * of its own. Ranking by upgrade count while displaying totals (the first
 * cut of this fix) made the chips read as unordered, since the sort key
 * wasn't the number on screen.
 */
export function rollupSubstats(discs: OptimizerDiscSummary[]): SubstatRollup[] {
  const byType = new Map<string, { rolls: number; value: number; discCount: number }>();

  for (const disc of discs) {
    for (const sub of disc.substats ?? []) {
      const existing = byType.get(sub.stat_type);
      if (existing) {
        existing.rolls += sub.rolls;
        existing.value += sub.value;
        existing.discCount += 1;
      } else {
        byType.set(sub.stat_type, { rolls: sub.rolls, value: sub.value, discCount: 1 });
      }
    }
  }

  const rank = (stat: string): number => {
    const i = SUBSTAT_GAME_ORDER.indexOf(stat);
    return i === -1 ? SUBSTAT_GAME_ORDER.length : i; // unknown keys last, order preserved
  };

  return Array.from(byType.entries())
    .filter(([, { rolls, discCount }]) => rolls - discCount > 0)
    .map(([stat_type, { rolls, value }]) => ({ stat_type, rolls, value }))
    .sort((a, b) => rank(a.stat_type) - rank(b.stat_type));
}
