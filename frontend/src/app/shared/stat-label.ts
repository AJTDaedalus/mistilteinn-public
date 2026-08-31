/**
 * Turning a stat key and a raw value into the line a reader sees.
 *
 * Both of these were private to the artifacts page. The optimize page's artifact cards (§16)
 * need the identical rendering, and "identical" is the whole point: a card showing `46.6%`
 * beside an inventory row showing `0.466` for the same piece would look like two different
 * artifacts. One owner, so that cannot drift.
 */

/** What the server publishes about a stat key. */
export interface StatVocabulary {
  display: string;
  percentage: boolean;
}

/**
 * `0.466` → `46.6%`, `4780` → `4,780`. The flag decides; the caller does not guess.
 *
 * Non-numeric input is rendered rather than thrown on. `substats` is a JSONB column with no
 * schema behind it, so a row written by an older importer or by hand can hold anything — and
 * `.toFixed` on that is a `TypeError` inside a computed, which takes out **the entire
 * inventory** rather than one substat. Showing the raw value keeps the bad row visible and
 * the other 799 readable.
 */
export function formatStat(value: unknown, percentage: boolean): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return String(value);
  return percentage
    ? `${(value * 100).toFixed(1)}%`
    : value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

/** `FIGHT_PROP_ATTACK_PERCENT`, `0.466` → `ATK 46.6%`, using the server's own vocabulary. */
export function describeStat(
  key: string,
  value: unknown,
  stats: Map<string, StatVocabulary>,
): string {
  const stat = stats.get(key);
  // Falls back to the raw key rather than hiding the stat: a piece carrying something the
  // vocabulary does not know is worth seeing, not worth silently dropping from the row.
  if (!stat) return `${key} ${value}`;
  return `${stat.display} ${formatStat(value, stat.percentage)}`;
}
