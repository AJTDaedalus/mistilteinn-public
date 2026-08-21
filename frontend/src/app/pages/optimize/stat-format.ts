import { statMeta } from '../../shared/stat-meta';

export { statMeta };

/**
 * Format a disc stat value for display — no sign prefix, in-game units.
 * Basis-point stats (unit==='bp') render as a percentage with one decimal.
 * Raw stats render as an integer.
 *
 * Examples:
 *   formatStatValue('crit_dmg', 3120)  → '31.2%'
 *   formatStatValue('flat_atk', 540)   → '540'
 *   formatStatValue('atk_pct', 300)    → '3.0%'
 */
export function formatStatValue(stat_type: string, value: number): string {
  const { unit } = statMeta(stat_type);
  if (unit === 'bp') {
    return `${(value / 100).toFixed(1)}%`;
  }
  return String(value);
}

/** In-game label for a stat key (e.g. 'crit_rate' → 'CRIT Rate'). */
export function formatStatLabel(stat_type: string): string {
  return statMeta(stat_type).label;
}
