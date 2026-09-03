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
  /**
   * Team DPS at this rung.
   *
   * **The burst count is not what ER buys.** Measured on the owner's team: Furina's damage is
   * **98.3 % `AttackTagElementalArt`** and only **1.5 %** burst — the Salon Members are skill
   * damage, and her burst matters because it *buffs the team*, not because it hits. Scaling
   * burst-tagged hits was therefore nearly a no-op on the character that motivated the
   * feature.
   *
   * DPS at each rung captures the whole effect — buff uptime, cast frequency, damage — without
   * attributing any of it to a hit tag.
   */
  dps?: number;
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


/**
 * The burst count a candidate's own Energy Recharge buys.
 *
 * **A step function, because bursts are integers.** Between two rungs of the ladder the count
 * is whatever the lower rung measured — you do not get four fifths of a burst for being four
 * fifths of the way to affording it. Below the ladder's floor the floor's own count stands;
 * above its ceiling, the ceiling's.
 *
 * This is measured, not modelled: every point is a gcsim run at that ER on the same config.
 * The alternative — fitting a curve to "how much damage is ER worth" — is the thing
 * `DESIGN_energy_in_the_optimizer.md` rejected, because gcsim's own optimizer does not do it
 * either.
 */
export function burstsAt(
  sweep: readonly EnergyObservation[],
  energyRecharge: number,
): number | null {
  if (!sweep.length) return null;
  const ordered = [...sweep].sort((a, b) => a.energyRecharge - b.energyRecharge);
  let best = ordered[0];
  for (const point of ordered) {
    if (point.energyRecharge <= energyRecharge) best = point;
    else break;
  }
  return best.burstInstances;
}


/**
 * Team DPS at the ER a candidate can pay for, read off the same ladder.
 *
 * A step function for the same reason `burstsAt` is: each rung is a gcsim run, and between two
 * of them the honest answer is the lower one's.
 *
 * **All of the below was measured under the *skipping* model, and the waiting model has not
 * been re-measured.** Owner's ruling of 2026-09-02 makes waiting an option
 * (`DESIGN_waiting_for_energy.md`, OQ-E2), and under it the rotation's **duration moves with
 * ER** — 151.5 s at the owner's real gear down to 102.1 s at 1.6 — so DPS climbs for two
 * reasons at once where here it climbs for one. The running maximum rests on monotonicity over
 * the ladder's range; that argument was established for a constant duration and does not
 * automatically carry. **Re-measure before trusting a waiting-model ladder.**
 *
 * ## The running maximum, and the claim that does *not* justify it
 *
 * **"More ER cannot buy less" is false, and was measured false.** That was this function's
 * first stated reason and it does not survive contact with gcsim. Native run on the owner's
 * team, 100 iterations, fixed 90-second duration:
 *
 * | artifact ER | 0.3 | 0.6 | 1.0 | 1.5 | 2.0 | 3.0 | 5.0 |
 * |---|---|---|---|---|---|---|---|
 * | team DPS | 154,106 | 157,499 | 157,359 | 157,471 | **139,387** | 141,487 | 141,812 |
 * | Furina bursts | 2 | 2.74 | 3 | 3 | 3 | **5** | 5 |
 * | Skirk bursts | 3 | 3 | 3 | 3 | 3 | **2** | 2 |
 *
 * An 11.5 % collapse at 2.0, and at 3.0 Furina's two extra bursts cost Skirk one of his. A
 * `while 1` rotation runs for a fixed duration, so a cast that becomes affordable **consumes
 * time another character was using**. Energy is not a free parameter of a fixed sequence.
 *
 * The narrower claim is the true one, and it is what this rests on: **over the range the
 * ladder measures — `ENERGY_LADDER` stops at 1.0, and no build reaches even that without an ER
 * sands, an ER weapon and rolls — the curve is monotone**, and the reversals inside it are
 * 0.12 % and 0.14 %, which is the noise of a 60-iteration mean. So this reads the best rung at
 * or below `energyRecharge` rather than the last one, and it is safe *because the ladder's top
 * rung is inside the region where the effect is monotone* — not because monotonicity is a law.
 *
 * **If `ENERGY_LADDER` is ever extended past ~1.5, this becomes wrong** and the running max
 * would hand a candidate a peak it cannot actually reach. That is the tripwire on this
 * function, and it is stated here rather than left to be rediscovered.
 *
 * That is not a hypothetical. Measured on the owner's Furina, 2026-09-01, at
 * `ENERGY_LADDER_RUNS = 20`:
 *
 * | artifact ER | 0.20 | 0.30 | 0.45 | 0.60 | 0.80 | 1.00 |
 * |---|---|---|---|---|---|---|
 * | team DPS | 142,380 | 152,589 | 157,761 | **154,314** | 158,306 | **156,188** |
 * | bursts | 2 | 2 | 2.8 | **2.5** | 3 | 3 |
 *
 * More ER, *fewer bursts*, twice — and at these rungs that **is** noise, unlike the real
 * displacement above. The whole signal above 0.30 is +3.7 % and this dip is 2.2 % of it, so
 * without the running max a candidate landing on the 0.60 rung was scored 2.2 % worse than one
 * on 0.45 for no reason but which side of a coin flip its gcsim run fell. At 60 iterations the
 * same ladder reverses by 0.12 %.
 *
 * The running max invents no measurement: every value it returns was measured, at an ER the
 * candidate can actually pay for.
 */
export function dpsAt(
  sweep: readonly EnergyObservation[],
  energyRecharge: number,
): number | null {
  let best: number | null = null;
  for (const point of sweep) {
    if (typeof point.dps !== 'number') continue;
    if (point.energyRecharge > energyRecharge) continue;
    if (best === null || point.dps > best) best = point.dps;
  }
  if (best !== null) return best;
  // Below every rung: the lowest measured one is the closest honest answer, and returning null
  // would silently disable ER weighting for exactly the builds most short of it.
  const measured = sweep.filter((p) => typeof p.dps === 'number');
  if (!measured.length) return null;
  return measured.reduce((lo, p) => (p.energyRecharge < lo.energyRecharge ? p : lo)).dps ?? null;
}
