/**
 * The order main stats are offered in, and which are worth offering at all.
 *
 * Owner audit (`BACKLOG_frontend.md` §2, §6), as revised on seeing it rendered: *"swap stat % to
 * the beginning, elemental damage to the end."* EM and ER stay between them.
 *
 * So: **percentages → Elemental Mastery and Energy Recharge → elemental damage bonuses**, the
 * last group alphabetical among itself.
 *
 * Shared because two surfaces need the same order — the inventory's filter and the optimizer's
 * per-slot constraint — and the audit asks for it in both. Two orderings would eventually
 * disagree, and the one a user met second would look like the broken one.
 *
 * ## Why this is a rank and not a sorted list of names
 *
 * The groups are not alphabetical with respect to each other: Elemental Mastery sits between
 * the percentages and the damage bonuses because that is where a player looks for it, not
 * because "E" falls there. So the order is stated, and it is alphabetical only *within* a
 * group.
 */

/** Group ranks, low first. Anything unlisted sorts last, in name order. */
const GROUP = {
  percentage: 0,
  mastery: 1,
  elementalDamage: 2,
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

/**
 * CRIT Rate, CRIT DMG and Healing Bonus are percentages too — their keys simply do not say so.
 *
 * Grouping them by key alone would have stranded CRIT DMG after the damage bonuses, which is
 * nowhere a player looks for it. Listed rather than pattern-matched, because there is no
 * pattern: `FIGHT_PROP_CRITICAL` and `FIGHT_PROP_HEAL_ADD` share nothing but their meaning.
 */
const PERCENTAGE_BY_MEANING = new Set([
  'FIGHT_PROP_CRITICAL',
  'FIGHT_PROP_CRITICAL_HURT',
  'FIGHT_PROP_HEAL_ADD',
]);

function group(key: string): number {
  if (ELEMENTAL_DAMAGE.test(key)) return GROUP.elementalDamage;
  if (key === 'FIGHT_PROP_ELEMENT_MASTERY' || key === 'FIGHT_PROP_CHARGE_EFFICIENCY') {
    return GROUP.mastery;
  }
  if (key.endsWith('_PERCENT') || PERCENTAGE_BY_MEANING.has(key)) return GROUP.percentage;
  // Anything unlisted sorts with the damage bonuses rather than ahead of the percentages: a
  // stat this file has never seen is more likely to be a new element than a new percentage,
  // and either way it should not lead the list.
  return GROUP.elementalDamage;
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
