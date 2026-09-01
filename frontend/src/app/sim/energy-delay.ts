/**
 * How long each character stood unable to act for want of energy.
 *
 * **gcsim measures this itself, in seconds, per character.** `pkg/agg/failures/failures.go`
 * sums the frames of every `insufficient_energy` failure interval and divides by 60:
 *
 * ```go
 * case action.InsufficientEnergy.String():
 *     energy += float64(fail.End-fail.Start) / 60
 * ```
 *
 * So this reads a number rather than inventing one — which matters, because the obvious
 * alternative (counting failed attempts and guessing a frame cost) produces a plausible figure
 * that is wrong by whatever the guess was.
 *
 * ## Why it is worth surfacing
 *
 * Measured on the owner's team against the same rotation gcsim's own database page publishes:
 * identical action counts on both runs — 189 attacks, 18 bursts, 6 charges, 53 dashes, 24
 * skills, 24 swaps — but **191.7 s against 124.6 s**. The whole 67-second difference is
 * Furina, who reports `insufficient_energy = 67.1` where the published build reports **0**.
 *
 * Same actions, same order, 54 % longer, and the only visible cause was a duration nobody was
 * looking at. A player reads that as "my better build is worse".
 */

/** One character's wait, in seconds. */
export interface EnergyDelay {
  character: string;
  seconds: number;
}

/** gcsim's per-character failure block; every field is a descriptive-stats object. */
interface FailedActions {
  insufficient_energy?: { mean?: number } | number;
}

function meanOf(value: FailedActions['insufficient_energy']): number {
  if (typeof value === 'number') return value;
  return value?.mean ?? 0;
}

/**
 * Read the per-character energy delay out of an aggregate run.
 *
 * `characters` is gcsim's own key order, which `failed_actions` is indexed by — the pairing is
 * positional in gcsim's output, so a caller must pass the order `character_order` returned
 * rather than any list of names it happens to hold.
 *
 * Anything below `floor` is dropped. A rotation that waits a tenth of a second is not
 * "insufficient energy"; it is a rounding artefact of where a frame boundary fell, and warning
 * about it would teach a reader to ignore the warning.
 */
export function energyDelays(
  raw: unknown,
  characters: readonly string[],
  floor = 1,
): EnergyDelay[] {
  const stats = (raw as { statistics?: { failed_actions?: FailedActions[] } } | null)?.statistics;
  const failed = stats?.failed_actions;
  if (!Array.isArray(failed)) return [];

  const out: EnergyDelay[] = [];
  for (let i = 0; i < failed.length; i++) {
    const seconds = meanOf(failed[i]?.insufficient_energy);
    if (seconds >= floor) {
      out.push({ character: characters[i] ?? `character ${i + 1}`, seconds });
    }
  }
  return out.sort((a, b) => b.seconds - a.seconds);
}

/**
 * The sentence both Optimize and Calculate show, or `null` when nobody is waiting.
 *
 * The owner's wording, kept: *"Energy insufficient to burst on time for <characters>: x second
 * delay"*. One name reads as a sentence; several carry their own figure, because a combined
 * total would hide which character to actually fix.
 */
export function energyDelayMessage(delays: readonly EnergyDelay[]): string | null {
  if (!delays.length) return null;
  if (delays.length === 1) {
    const [only] = delays;
    return `Energy insufficient to burst on time for ${only.character}: `
      + `${only.seconds.toFixed(1)} second delay.`;
  }
  const named = delays
    .map((d) => `${d.character} (${d.seconds.toFixed(1)}s)`)
    .join(', ');
  return `Energy insufficient to burst on time for ${named}.`;
}
