/**
 * From "one drop in N beats this piece" to "this much resin", in closed form.
 *
 * `docs/TASKS_upgrade_estimator.md` Task 7; `docs/DESIGN_upgrade_estimator.md` §4. **No
 * simulation**: the number of claims until the first success is geometric, so every quantile is
 * a formula and the histogram is the geometric PMF.
 *
 * ## Which drops count (owner, 2026-10-24)
 *
 * *"Just assume we're farming the right one for each set (so half of artifacts could be a
 * replacement). For off-pieces, it should be any artifact."* So a slot inside an active set
 * bonus accepts half the domain's drops — the half that are its set — and the off-piece accepts
 * all of them. No domain → set map is needed. Standard domain claims only: no Strongbox, no
 * Stygian Onslaught.
 *
 * A replacement of the right set keeps every active bonus, so the build stays in the recipe it
 * was calibrated under — which is why `upgrade-estimate.ts` can score every candidate against
 * one recipe. A rainbow build, where no set bonus is active, accepts every drop and ignores any
 * 2-piece a new piece would create: a lower bound, and said so on the page.
 */

/** The constants a claim is priced with. `FreshDropInputs` on the inventory payload. */
export interface ClaimModel {
  /** Mean 5-stars per claim. At least one is guaranteed; the shape is `1 + Bernoulli`. */
  fiveStarPerRun: number;
  setShare: number;
  slotShare: number;
  resinPerRun: number;
}

/** The resin distribution for one slot. Every figure is in resin; days are not offered. */
export interface ResinEstimate {
  /** `P(one 5-star drop is an upgrade for this slot)`. */
  perDrop: number;
  /** `P(one claim yields at least one upgrade)`. */
  perRun: number;
  /** No drop can beat the piece. Every figure below is null, never `Infinity`. */
  unreachable: boolean;
  mean: number | null;
  p25: number | null;
  median: number | null;
  p75: number | null;
  p90: number | null;
}

/**
 * The share of a domain's drops that could replace this slot's piece.
 *
 * `½` when the slot's set has an active bonus — two or more of it on the build, counting this
 * piece — and `1` for the off-piece, a setless piece, or an empty slot.
 */
export function setFactor(
  slotSetId: number | null,
  setCounts: Readonly<Record<number, number>>,
  setShare: number,
): number {
  if (slotSetId === null) return 1;
  return (setCounts[slotSetId] ?? 0) >= 2 ? setShare : 1;
}

/**
 * `P(at least one upgrade in a claim)` with `N = 1 + Bernoulli(mean − 1)` five-stars.
 *
 * The shape is assumed — only the mean is published — and it barely matters:
 * `r = q · E[N] − O(q²)`, so any shape with this mean agrees for the small `q` this is for.
 */
export function perRunSuccess(perDrop: number, fiveStarPerRun: number): number {
  const extra = fiveStarPerRun - 1;
  return 1 - (1 - perDrop) * (1 - extra * perDrop);
}

/** Claims until the first success at probability `r`, at quantile `p`: `⌈ln(1−p) / ln(1−r)⌉`. */
export function claimsAtQuantile(r: number, p: number): number {
  if (r >= 1) return 1;
  return Math.max(1, Math.ceil(Math.log(1 - p) / Math.log(1 - r)));
}

/** The whole estimate for one slot, from its per-slot beat probability. */
export function resinToUpgrade(
  pBeatInSlot: number,
  factor: number,
  model: ClaimModel,
): ResinEstimate {
  const perDrop = factor * model.slotShare * pBeatInSlot;
  if (!(perDrop > 0)) {
    return {
      perDrop: 0, perRun: 0, unreachable: true,
      mean: null, p25: null, median: null, p75: null, p90: null,
    };
  }
  const r = perRunSuccess(perDrop, model.fiveStarPerRun);
  const resin = (p: number): number => claimsAtQuantile(r, p) * model.resinPerRun;
  return {
    perDrop,
    perRun: r,
    unreachable: false,
    mean: model.resinPerRun / r,
    p25: resin(0.25),
    median: resin(0.5),
    p75: resin(0.75),
    p90: resin(0.9),
  };
}
