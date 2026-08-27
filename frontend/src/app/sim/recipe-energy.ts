/**
 * The minimum Energy Recharge a recipe needs, and whether a build clears it.
 *
 * `docs/RESEARCH_recipe_risks.md` §3. A recipe is calibrated at one ER; a build with less
 * cannot burst when the rotation says to burst, so **it is not performing that rotation**.
 *
 * The repo has already ruled on what to do about that — `docs/DECISIONS.md` (2026-08-25),
 * *rotations are authored, never optimized*. Scoring such a build against a degraded variant
 * would be the optimizer **silently substituting a rotation nobody wrote**. So it is flagged,
 * with the ER it has and the ER it needs, and the user adds ER or changes the rotation.
 *
 * **A number, not a dimension.** An earlier design keyed recipes by ER plateau and multiplied
 * the calibration budget; this replaces that with one threshold per recipe.
 */

/** One point of an ER sweep: what the rotation did at that Energy Recharge. */
export interface EnergyObservation {
  /** Artifact-borne ER, as a fraction — `0.30` is +30 %. */
  energyRecharge: number;
  /** Mean instances of the burst across the sweep's iterations. */
  burstInstances: number;
  /** Spread of that count. **Non-zero means the rotation is not the same every iteration.** */
  standardDeviation: number;
}

/**
 * The lowest ER at which the rotation executes exactly as the calibration did.
 *
 * Two conditions, and the second is the one that is easy to forget: the burst count must
 * **match the calibration's**, and its spread must be **zero**. A count that averages the
 * right value while varying between iterations is a rotation that sometimes performs and
 * sometimes does not — `RESEARCH_damage_recipe.md` measured exactly that at the transition,
 * where the burst fires 2 or 3 times depending on the seed.
 *
 * Returns `null` when no observation qualifies, which means the sweep did not reach far
 * enough — **not** that the rotation has no requirement. A caller must not read a missing
 * threshold as "no threshold".
 */
export function minimumEnergyRecharge(
  sweep: readonly EnergyObservation[],
  calibratedBurstInstances: number,
  tolerance = 1e-9,
): number | null {
  const qualifying = sweep
    .filter(
      (point) =>
        point.standardDeviation <= tolerance
        && Math.abs(point.burstInstances - calibratedBurstInstances) <= tolerance,
    )
    .map((point) => point.energyRecharge);
  return qualifying.length > 0 ? Math.min(...qualifying) : null;
}

/** Why a build cannot perform a rotation, in the terms a user can act on. */
export interface EnergyShortfall {
  /** The build's own artifact-borne ER. */
  has: number;
  /** What the recipe needs. */
  needs: number;
  /** The gap, so a caller can say "17 % more Energy Recharge" rather than two numbers. */
  shortfall: number;
}

/**
 * Whether this build can perform the rotation, and by how much it falls short if not.
 *
 * `null` means it clears the threshold. **A recipe with no known minimum returns `null` too**,
 * and that is deliberate: an unmeasured threshold is not a passed one, but blocking every
 * build on a measurement that was never taken would be worse. The caller that skipped the
 * measurement is the one that has to say so.
 */
export function energyShortfall(
  buildEnergyRecharge: number,
  minimum: number | null,
): EnergyShortfall | null {
  if (minimum === null || buildEnergyRecharge >= minimum) return null;
  return {
    has: buildEnergyRecharge,
    needs: minimum,
    shortfall: minimum - buildEnergyRecharge,
  };
}
