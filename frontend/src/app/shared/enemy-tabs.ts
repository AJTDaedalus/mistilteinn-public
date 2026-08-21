/**
 * Enemy-picker tab filter (issue #55).
 *
 * `enemy_profiles.rarity` has four tiers, not the three the stale model
 * comment claims; `rarity = 4` is nanoka's own S-rank list — 26 endgame
 * bosses out of 256 profiles (see docs/LOG_issue_backlog.md and
 * DECISIONS.md "OQ2 resolved"). The picker defaults to that tier so a
 * fresh page doesn't dump all 256 enemies on the user; "All Enemies" is
 * the escape hatch. Filtering is client-side — every surface already
 * fetches with limit: 1000, so the whole list is in hand.
 */
export type EnemyTab = 'bosses' | 'all';

export const BOSS_RARITY = 4;

export const ENEMY_TABS: readonly { key: EnemyTab; label: string }[] = [
  { key: 'bosses', label: 'Endgame Bosses' },
  { key: 'all', label: 'All Enemies' },
];

export function filterEnemiesByTab<T extends { rarity: number }>(
  enemies: T[],
  tab: EnemyTab,
): T[] {
  return tab === 'bosses' ? enemies.filter((e) => e.rarity === BOSS_RARITY) : enemies;
}

/**
 * First enemy under the active tab — the id a picker should default to.
 * Falls back to the first enemy overall if the tab is (unexpectedly)
 * empty, so a default-selection path never silently comes up empty.
 */
export function defaultEnemyId<T extends { id: string; rarity: number }>(
  enemies: T[],
  tab: EnemyTab,
): string | null {
  const filtered = filterEnemiesByTab(enemies, tab);
  return filtered[0]?.id ?? enemies[0]?.id ?? null;
}
