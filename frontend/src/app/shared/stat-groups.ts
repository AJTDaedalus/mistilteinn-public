/**
 * The damage chain's stat accounts, grouped and totalled the way a player reads a build.
 *
 * Owner: *"The 'groups', like 'effective atk', should have their values shown. Essentially the
 * final 'acting' value used in the optimizer… In cases where multiple sources contribute to a
 * stat (crit rate, crit damage, cryo dmg) we should list them out as their own rows with the
 * 'total' appearing there."*
 *
 * ## Where the total comes from, and where it does not
 *
 * **From the server, resolved by the same graph that produced the damage.** `stats.TOTALS`
 * holds a node per quantity and its docstring names this exact consumer — *"the optimizer's
 * scoring pass and the 'explain this number' path both want this shape"* — it was simply never
 * published. `ExplainResponse.totals` publishes it now.
 *
 * It is emphatically **not** the sum of the rows below it. A contribution is an *input*:
 * `base_atk`, `atk_pct` and `flat_atk` compose as `base * (1 + pct) + flat`, which is not
 * addition, and `sum_of_parts` is documented upstream as *"the arithmetic sum of the parts,
 * which is not necessarily the stat"*. Adding the rows up in the UI would be a second
 * implementation of the damage chain, and a wrong one — worse than showing nothing, because it
 * would look right.
 *
 * A group whose total the server did not publish shows its rows with no headline rather than a
 * computed stand-in.
 *
 * ## It drops nothing
 *
 * A quantity matching no group lands in `Other`, in the order the server sent it. A grouping
 * that silently hid an unrecognised stat would be worse than the flat list it replaces, which
 * at least showed everything.
 */

/** One contribution to a quantity, as the API publishes it. */
export interface StatPart {
  quantity: string;
  value: number;
  source: string;
  note?: string;
}

/** One quantity and everything recorded against it. Mirrors `StatAccountRead`. */
export interface StatAccount {
  quantity: string;
  parts: StatPart[];
  sum_of_parts: number;
  sources: string[];
}

/** One contribution, ready to render. */
export interface StatRow {
  /** The quantity it registered under — `atk_pct`. */
  quantity: string;
  value: number;
  /** Where it came from, in the server's words. */
  source: string;
  /** Whether `value` is a fraction to render as a percentage. */
  percent: boolean;
}

/** A stat, its resolved value, and every contribution behind it. */
export interface StatGroup {
  /** What a player calls it — `Effective ATK`. */
  label: string;
  /**
   * The resolved value the optimizer actually acts on, or null when the server published none.
   *
   * Never computed here. See the module docstring.
   */
  total: number | null;
  /** Whether `total` is a fraction to render as a percentage. */
  percent: boolean;
  /** One row per contribution, not per quantity — the owner asked for the sources listed. */
  rows: StatRow[];
}

/**
 * `{total quantity: [label, the input quantities that compose it]}`.
 *
 * A stat whose only input is itself — CRIT rate, EM — still belongs here: it has a resolved
 * total and a list of contributions, which is the same shape as ATK with fewer moving parts.
 */
const GROUPS: readonly { total: string; label: string; inputs: readonly string[] }[] = [
  { total: 'atk', label: 'Effective ATK', inputs: ['base_atk', 'atk_pct', 'flat_atk'] },
  { total: 'hp', label: 'Effective HP', inputs: ['base_hp', 'hp_pct', 'flat_hp'] },
  { total: 'def', label: 'Effective DEF', inputs: ['base_def', 'def_pct', 'flat_def'] },
  { total: 'crit_rate', label: 'CRIT Rate', inputs: ['crit_rate'] },
  { total: 'crit_dmg', label: 'CRIT DMG', inputs: ['crit_dmg'] },
  { total: 'elemental_mastery', label: 'Elemental Mastery', inputs: ['elemental_mastery'] },
  { total: 'energy_recharge', label: 'Energy Recharge', inputs: ['energy_recharge'] },
];

/**
 * Quantities whose value is a fraction — `0.624` means 62.4%.
 *
 * Named rather than inferred from the value's magnitude: a 0.9 could be 90% CRIT DMG or nine
 * tenths of a point of something, and guessing from the number is how a display invents a unit.
 * Anything ending `_pct` or `_dmg_bonus` is a percentage by construction of those names.
 */
const PERCENT_QUANTITIES = new Set([
  'crit_rate',
  'crit_dmg',
  'energy_recharge',
  'dmg_bonus',
  'healing_bonus',
  'incoming_healing_bonus',
  'shield_strength',
]);

/** Whether a quantity's value is a fraction to be shown as a percentage. */
export function isPercent(quantity: string): boolean {
  return (
    PERCENT_QUANTITIES.has(quantity)
    || quantity.endsWith('_pct')
    || quantity.endsWith('_dmg_bonus')
  );
}

/** A damage bonus for one element — `cryo_dmg_bonus`. */
const DMG_BONUS_SUFFIX = '_dmg_bonus';

/** `cryo_dmg_bonus` → `Cryo DMG Bonus`. */
function damageBonusLabel(quantity: string): string {
  const element = quantity.slice(0, -DMG_BONUS_SUFFIX.length);
  return `${element.charAt(0).toUpperCase()}${element.slice(1)} DMG Bonus`;
}

function rowsFrom(accounts: readonly StatAccount[]): StatRow[] {
  return accounts.flatMap((account) =>
    account.parts.map((part) => ({
      // The part's own quantity, not the account's: a contribution registered under
      // `atk_pct` inside the ATK group should say so rather than inherit `atk`.
      quantity: part.quantity || account.quantity,
      value: part.value,
      source: part.source,
      percent: isPercent(part.quantity || account.quantity),
    })),
  );
}

/**
 * Group the accounts and attach the resolved totals.
 *
 * `totals` is `ExplainResponse.totals` — `{quantity: resolved value}`. Passing an empty map is
 * valid and yields groups with no headline, which is what a server that has not been updated
 * produces.
 */
export function groupStats(
  accounts: readonly StatAccount[],
  totals: Readonly<Record<string, number>> = {},
): StatGroup[] {
  const byQuantity = new Map(accounts.map((a) => [a.quantity, a]));
  const claimed = new Set<string>();
  const groups: StatGroup[] = [];

  for (const group of GROUPS) {
    const mine = group.inputs
      .map((q) => byQuantity.get(q))
      .filter((a): a is StatAccount => a !== undefined);
    const total = totals[group.total];

    // A group with neither a total nor a contribution is a question this build cannot answer,
    // and an empty row would present that as an answer. A build whose talent scales off ATK
    // records no HP quantities at all.
    if (mine.length === 0 && total === undefined) continue;

    for (const account of mine) claimed.add(account.quantity);
    groups.push({
      label: group.label,
      total: total ?? null,
      percent: isPercent(group.total),
      rows: rowsFrom(mine),
    });
  }

  // One group per element, because a build carrying Cryo and Physical bonuses has two
  // different numbers and a single "Damage bonus" row would have to pick one.
  for (const account of accounts) {
    if (!account.quantity.endsWith(DMG_BONUS_SUFFIX) || claimed.has(account.quantity)) continue;
    claimed.add(account.quantity);
    groups.push({
      label: damageBonusLabel(account.quantity),
      total: totals[account.quantity] ?? null,
      percent: true,
      rows: rowsFrom([account]),
    });
  }

  const rest = accounts.filter((a) => !claimed.has(a.quantity));
  if (rest.length > 0) {
    groups.push({ label: 'Other', total: null, percent: false, rows: rowsFrom(rest) });
  }
  return groups;
}
