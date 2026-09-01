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


/* ── Missed bursts: the same problem, as a gated rotation shows it ───────────
 *
 * **`insufficient_energy` cannot fire for a rotation this app compiled.** The compiler gates
 * every step on `.ready`, so gcsim never *attempts* a burst it cannot pay for — it skips it,
 * and records no failure. Measured on the owner's own team: the ungated community config
 * reports 67.1 s for Furina; the identical gear on our compiled rotation reports **0 for all
 * four**, while Furina casts 2 bursts where free energy casts 5.
 *
 * So a warning built only on seconds is correct when it fires and silent exactly where this
 * app's own rotations fail. The counterfactual gcsim's optimizer uses covers both: run once
 * with `ignore_burst_energy=true` and compare.
 */

/** One character's shortfall, however the rotation expresses it. */
export interface EnergyShortfallReport {
  character: string;
  /** Seconds spent unable to act. Non-zero only for ungated rotations. */
  seconds: number;
  /** Bursts cast with real energy, and with energy free. */
  bursts: { real: number; free: number };
}

/** What energy is costing the team, measured against the free-energy run. */
export interface EnergyCost {
  characters: EnergyShortfallReport[];
  /** Fraction of DPS lost to energy — `(free - real) / real`. */
  dpsCost: number;
}

function burstsOf(raw: unknown, index: number): number {
  const wrapper = raw as { statistics?: { character_actions?: unknown[] };
    stats?: { character_actions?: unknown[] } } | null;
  const stats = wrapper?.statistics ?? wrapper?.stats;
  const sources = (stats?.character_actions?.[index] as { sources?: Record<string, { mean?: number }> })
    ?.sources;
  return sources?.['burst']?.mean ?? 0;
}

function dpsOf(raw: unknown): number {
  const wrapper = raw as { statistics?: { dps?: { mean?: number } };
    stats?: { dps?: { mean?: number } } } | null;
  return (wrapper?.statistics ?? wrapper?.stats)?.dps?.mean ?? 0;
}

/**
 * Compare a real run against the same rotation with energy free.
 *
 * `floor` drops a character short by less than a fifth of a burst — that is where a frame
 * boundary fell across iterations, not a build that cannot pay for its burst.
 */
export function energyCost(real: unknown, free: unknown, characters: readonly string[],
  floor = 0.2): EnergyCost {
  const out: EnergyShortfallReport[] = [];
  const delays = energyDelays(real, characters, 1);
  const bySeconds = new Map(delays.map((d) => [d.character, d.seconds]));

  for (let i = 0; i < characters.length; i++) {
    const name = characters[i] ?? `character ${i + 1}`;
    const bursts = { real: burstsOf(real, i), free: burstsOf(free, i) };
    const seconds = bySeconds.get(name) ?? 0;
    if (bursts.free - bursts.real >= floor || seconds >= 1) {
      out.push({ character: name, seconds, bursts });
    }
  }

  const realDps = dpsOf(real);
  return {
    characters: out.sort((a, b) => (b.bursts.free - b.bursts.real) - (a.bursts.free - a.bursts.real)),
    dpsCost: realDps ? (dpsOf(free) - realDps) / realDps : 0,
  };
}

/**
 * The owner's sentence, told the way this rotation actually fails.
 *
 * Seconds when the rotation waits; missed bursts when it skips. Both, when both happen. The
 * DPS cost is the number that answers *"is more Energy Recharge worth it"*, so it closes the
 * line rather than sitting in a separate caveat.
 */
export function energyCostMessage(cost: EnergyCost): string | null {
  if (!cost.characters.length) return null;
  const named = cost.characters.map((c) => {
    const missed = c.bursts.free - c.bursts.real;
    if (missed >= 0.2) {
      return `${c.character} (${c.bursts.real.toFixed(0)} of ${c.bursts.free.toFixed(0)} bursts)`;
    }
    return `${c.character} (${c.seconds.toFixed(1)}s)`;
  }).join(', ');
  const toll = cost.dpsCost > 0.001 ? ` — costing ${(cost.dpsCost * 100).toFixed(1)}% DPS.` : '.';
  return `Energy insufficient to burst on time for ${named}${toll}`;
}


/**
 * Whether *this* character is the one short of energy.
 *
 * **ER is strictly per-character.** A starved Furina is a real problem and says nothing about
 * what an Energy Recharge sands would do for Skirk — his burst count is governed by his own
 * ER and nobody else's. So the ladder that measures "what would more ER buy" runs only when
 * the character being optimized is the one falling short; triggering it because a *teammate*
 * is starved would spend six gcsim runs to measure a curve that is flat.
 *
 * The teammate's shortfall is not lost — it is what the warning names. It simply is not a
 * reason to weigh ER on somebody else's artifacts.
 */
export function subjectIsShort(cost: EnergyCost | null, subject: string): boolean {
  if (!cost || !subject) return false;
  return cost.characters.some(
    (c) => c.character === subject && c.bursts.free > c.bursts.real,
  );
}
