/**
 * The damage chain's stat accounts, grouped the way a player reads a build.
 *
 * Owner: *"The stats table is still confusing… It should be aggregated into chunks like
 * 'effective attack' which takes in its elements (flat, base, pct) into one unit, showing how
 * the entire effective attack is built. Same with crit, damage %, HP, def, EM, and ER. All of
 * the effective stats, and how they're derived. Right now it's just a list of random chunks of
 * the math."*
 *
 * The server publishes one account per quantity — `base_atk`, `atk_pct`, `flat_atk`, `atk` —
 * flat and in whatever order they were recorded. Every number a reader wants is there; the
 * relationships between them are not, so `atk` sits beside its own inputs looking like a
 * sibling rather than their result.
 *
 * ## What this does not do
 *
 * **It does not recompute anything.** The group's total is the server's own derived account
 * (`atk`), never a sum of the inputs — `sum_of_parts` is documented upstream as *"the
 * arithmetic sum of the parts, which is not necessarily the stat"*, because
 * `base * (1 + pct) + flat` is not addition. A UI that added the inputs and printed the result
 * as effective ATK would be a second, wrong implementation of the damage chain.
 *
 * **It drops nothing.** A quantity that matches no family lands in `Other`, in the order the
 * server sent it. A grouping that silently hid an unrecognised stat would be worse than the
 * flat list it replaces, because the flat list at least showed everything.
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

/** A readable stat and the accounts that produced it. */
export interface StatGroup {
  /** What a player calls it — `Effective ATK`. */
  label: string;
  /**
   * The server's own derived account for this stat, when it published one.
   *
   * Null for a family that has no single total — CRIT is a rate and a multiplier, not one
   * number — and for a family whose total this hit did not need.
   */
  total: StatAccount | null;
  /** The accounts that feed the total, in a fixed reading order rather than arrival order. */
  inputs: StatAccount[];
}

/**
 * `{family: [the quantity that is the total, ...the quantities that build it]}`.
 *
 * Order inside a family is the reading order — base, then percentage, then flat — which is
 * also the order the arithmetic applies them in. It is not the order the server sends.
 */
const FAMILIES: readonly { label: string; total: string | null; inputs: string[] }[] = [
  { label: 'Effective ATK', total: 'atk', inputs: ['base_atk', 'atk_pct', 'flat_atk'] },
  { label: 'Effective HP', total: 'hp', inputs: ['base_hp', 'hp_pct', 'flat_hp'] },
  { label: 'Effective DEF', total: 'def', inputs: ['base_def', 'def_pct', 'flat_def'] },
  { label: 'CRIT', total: null, inputs: ['crit_rate', 'crit_dmg'] },
  { label: 'Damage bonus', total: null, inputs: ['dmg_bonus'] },
  { label: 'Elemental Mastery', total: null, inputs: ['elemental_mastery'] },
  { label: 'Energy Recharge', total: null, inputs: ['energy_recharge'] },
];

/** Element-scoped bonuses — `pyro_dmg_bonus` — belong with the plain one. */
const DMG_BONUS_SUFFIX = '_dmg_bonus';

/**
 * Group the accounts, keeping every one of them.
 *
 * A family with nothing to show is omitted entirely: a build whose talent scales off ATK
 * records no HP quantities, and an empty "Effective HP" row would be a question the page
 * cannot answer presented as an answer it can.
 */
export function groupStats(accounts: readonly StatAccount[]): StatGroup[] {
  const byQuantity = new Map(accounts.map((a) => [a.quantity, a]));
  const claimed = new Set<string>();
  const groups: StatGroup[] = [];

  for (const family of FAMILIES) {
    const total = family.total ? byQuantity.get(family.total) ?? null : null;
    const inputs = family.inputs
      .map((q) => byQuantity.get(q))
      .filter((a): a is StatAccount => a !== undefined);

    // Element-scoped damage bonuses join the damage family rather than falling to Other,
    // where `pyro_dmg_bonus` would read as an unrelated stat.
    if (family.label === 'Damage bonus') {
      for (const account of accounts) {
        if (account.quantity.endsWith(DMG_BONUS_SUFFIX) && !inputs.includes(account)) {
          inputs.push(account);
        }
      }
    }

    if (total === null && inputs.length === 0) continue;
    if (total) claimed.add(total.quantity);
    for (const input of inputs) claimed.add(input.quantity);
    groups.push({ label: family.label, total, inputs });
  }

  const rest = accounts.filter((a) => !claimed.has(a.quantity));
  if (rest.length > 0) {
    // Named `Other`, not dropped. See the module docstring.
    groups.push({ label: 'Other', total: null, inputs: rest });
  }
  return groups;
}
