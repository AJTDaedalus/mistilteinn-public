import type { Recipe } from './recipe';
import { evaluateHit } from './recipe-eval';
import type { CandidateStats } from './recipe-eval';

/**
 * How much of a rotation's damage each character actually contributes.
 *
 * gcsim reports this and this app did not, which is how "the character being optimized is 14%
 * of their own rotation" stayed invisible while every ranking rested on it. It is also the
 * number that makes the frozen-teammate rule legible: a build whose teammates are 86% of the
 * damage will see small deltas from its own artifacts, and that is correct rather than broken.
 *
 * **Evaluated, not calibrated.** The share is computed with the candidate's own stats applied,
 * so it is the share *for this result row* — the optimized character's slice grows as their
 * artifacts improve, while teammates stay where gcsim measured them. Using
 * `gcsimAverageDamage` would report the calibration's split for every row alike and quietly
 * describe a build nobody is looking at.
 */
export interface CharacterShare {
  /** The gcsim key, or the index as a string when the recipe carries no names. */
  name: string;
  damage: number;
  /** Of the rotation's total, as a fraction. */
  share: number;
  /** Whether this is the character whose artifacts the search is choosing. */
  mine: boolean;
}

export function damageShare(recipe: Recipe, stats: CandidateStats): CharacterShare[] {
  const byOwner = new Map<number, { damage: number; mine: boolean }>();
  for (const hit of recipe.hits) {
    const seen = byOwner.get(hit.owner) ?? { damage: 0, mine: hit.mine };
    seen.damage += evaluateHit(hit, stats);
    // A character's hits agree on this, but `||` keeps one mislabelled hit from hiding whose
    // row it is — losing the marker is worse than carrying it on a hit that did not need it.
    seen.mine = seen.mine || hit.mine;
    byOwner.set(hit.owner, seen);
  }

  const total = [...byOwner.values()].reduce((sum, entry) => sum + entry.damage, 0);
  return [...byOwner]
    .map(([owner, entry]) => ({
      name: recipe.meta.characters?.[owner] ?? `character ${owner + 1}`,
      damage: entry.damage,
      // Zero total is reachable — a rotation that lands nothing — and `0/0` is `NaN`, which
      // Angular renders into the page rather than refusing.
      share: total > 0 ? entry.damage / total : 0,
      mine: entry.mine,
    }))
    .sort((a, b) => b.damage - a.damage);
}
