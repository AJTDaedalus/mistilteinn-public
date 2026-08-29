/**
 * The order main stats are offered in, and which are worth offering at all.
 *
 * Owner audit (`BACKLOG_frontend.md` §2, §6): *"Main stat selector should be ordered, flat stats
 * can be excluded. Elemental damage all together and alphabetical, stat% together, EM and ER in
 * between."*
 *
 * Shared because two surfaces need the same order — the inventory's filter and the optimizer's
 * per-slot constraint — and the audit asks for it in both. Two orderings would eventually
 * disagree, and the one a user met second would look like the broken one.
 *
 * ## Why this is a rank and not a sorted list of names
 *
 * The groups are not alphabetical with respect to each other: Elemental Mastery sits between
 * the damage bonuses and the percentages because that is where a player looks for it, not
 * because "E" falls there. So the order is stated, and only *within* the damage bonuses is it
 * alphabetical — which is the audit's own wording.
 */

/** Group ranks, low first. Anything unlisted sorts last, in name order. */
const GROUP = {
  elementalDamage: 0,
  mastery: 1,
  percentage: 2,
  other: 3,
} as const;

const ELEMENTAL_DAMAGE = /^FIGHT_PROP_(FIRE|WATER|GRASS|ELEC|WIND|ICE|ROCK|PHYSICAL)_ADD_HURT$/;

/**
 * Flat stats, excluded from a *filter*.
 *
 * Not from the game: a flower is always flat HP and a plume always flat ATK, so offering them
 * as a choice is offering the only option there is. They remain perfectly real artifacts —
 * this hides a control, never a piece.
 */
const FLAT = new Set(['FIGHT_PROP_HP', 'FIGHT_PROP_ATTACK', 'FIGHT_PROP_DEFENSE']);

function group(key: string): number {
  if (ELEMENTAL_DAMAGE.test(key)) return GROUP.elementalDamage;
  if (key === 'FIGHT_PROP_ELEMENT_MASTERY' || key === 'FIGHT_PROP_CHARGE_EFFICIENCY') {
    return GROUP.mastery;
  }
  if (key.endsWith('_PERCENT')) return GROUP.percentage;
  return GROUP.other;
}

/** Whether a main stat is worth offering as a filter. */
export function isFilterableMainStat(key: string): boolean {
  return !FLAT.has(key);
}

/**
 * Sort main stats into the owner's order, by **display name within each group**.
 *
 * Display rather than key, because `FIGHT_PROP_ELEC_ADD_HURT` sorts before
 * `FIGHT_PROP_FIRE_ADD_HURT` while "Electro DMG Bonus" and "Pyro DMG Bonus" do not — and the
 * user is reading the display.
 */
export function sortMainStats<T extends { key: string; display: string }>(stats: T[]): T[] {
  return [...stats].sort((a, b) => {
    const byGroup = group(a.key) - group(b.key);
    return byGroup !== 0 ? byGroup : a.display.localeCompare(b.display);
  });
}
