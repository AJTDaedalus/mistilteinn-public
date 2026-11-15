/**
 * Energy Recharge in the formula estimate: a closed-form energy model (math-fallback P3, task
 * 14; `docs/DESIGN_team_math_fallback.md` §2.10).
 *
 * The estimate had no energy model, so ER was worth nothing to it — the behaviour
 * `DESIGN_energy_in_the_optimizer.md` was written to end on the gcsim path. This prices it from
 * particle data, the way KeqingMains' energy methodology and gcsim's own substat optimizer do:
 *
 * - **A particle's value** is 3 for the receiver's own element, 2 for a clear one, 1 for any
 *   other — gcsim `pkg/core/player/character/energy.go:61-71` at the pin, and KQM's Energy
 *   library page (*"Same Element 3.0 · Clear 2.0 · Different Element 1.0"*).
 * - **Off field** a receiver gains `1 − 0.1 × party size` of it: 0.6 in a party of four
 *   (`energy.go:58-60`; KQM: *"In a party of 4, a unit off-field gains 60% … for parties of 3,
 *   70%; for parties of 2, 80%"*).
 * - **ER multiplies particles and nothing else** (`energy.go:72-77`, `amt * er * p.Num`); flat
 *   energy is added as-is (`AddEnergy`, `energy.go:35-43`; KQM: flat energy *"is not affected by
 *   Energy Recharge"*).
 * - **The requirement** is gcsim's own: `max((cost − flat) / raw particle energy, 1)`
 *   (`pkg/optimization/optstats/energy_stats.go:85`), the ER at which one rotation's particles
 *   pay for one burst.
 *
 * Verified against gcsim's own energy events (`backend/tests/fixtures/formula/energy/`,
 * `npm run formula:verify`): a native sample of the owner's National team at the pin, where
 * Xiangling's steady rotation banks exactly the energy this module computes.
 *
 * ## What the score does with it — three modes, and the fork is the owner's
 *
 * `off` leaves the score as it was (ER worth nothing) and only reports the requirement. `skip`
 * and `wait` are the two models CLAUDE.md records for the gcsim path (owner, 2026-09-02:
 * *"Build waiting as an option"*):
 *
 * - **skip**: a burst the energy cannot fund is not cast, so over many rotations the burst rows
 *   land `min(1, energy / cost)` as often — the long-run fraction, since energy carries between
 *   rotations. Like gcsim's skipping, it is blind to what a burst does beyond its own hits.
 * - **wait**: the team holds the rotation until the drip funds the burst, so the whole sequence
 *   takes `L + wait` seconds instead of `L` and every row is scaled by `L / (L + wait)`. It needs
 *   the drip, as gcsim's waiting model does.
 *
 * Both are monotone in ER, so the search's bound stays admissible.
 */

/** Which energy model prices ER in a formula recipe. */
export type EnergyMode = 'off' | 'skip' | 'wait';

/** One particle source over one rotation, as the subject receives it. */
export interface EnergySource {
  key: string;
  label: string;
  /** The particle's element, lower case; `null` is a clear particle (the drip). */
  element: string | null;
  /** Particles per rotation: per cast × casts, or a rate × seconds. */
  particles: number;
  /** The share of these particles the subject catches on field, 0..1. */
  onFieldShare: number;
  citation: string;
}

/** Everything the closed form reads, for one recipe. */
export interface FormulaEnergy {
  mode: EnergyMode;
  /** The subject's burst energy cost (game data). */
  cost: number;
  /** The subject's element, lower case. */
  element: string;
  /** Party size, which sets the off-field multiplier. */
  partyCount: number;
  /** The rotation's length in seconds: the waiting model's time base. */
  rotationSeconds: number;
  /** Energy per rotation that ER does not multiply (a kit's or weapon's flat refund). */
  flatEnergy: number;
  /** Every particle source over one rotation, the drip included when it is on. */
  sources: EnergySource[];
  /** The drip as a rate (clear particles a second) and the subject's on-field share; null: off. */
  drip: { particlesPerSecond: number; onFieldShare: number } | null;
  /** The subject's total Energy Recharge before artifacts, as a fraction (1.0 is 100 %). */
  baseEnergyRecharge: number;
}

/** gcsim `energy.go:61-71`: own element 3, clear 2, any other 1 (KQM's Energy page agrees). */
export const PARTICLE_VALUE = { same: 3, clear: 2, different: 1 } as const;

/** A particle's value to a receiver of `receiver`'s element. */
export function particleValue(receiver: string, particle: string | null): number {
  if (particle === null) return PARTICLE_VALUE.clear;
  return particle === receiver ? PARTICLE_VALUE.same : PARTICLE_VALUE.different;
}

/** gcsim `energy.go:58-60`: `1 − 0.1 × party size` off field (0.6 in four), 1 on field. */
export function offFieldMultiplier(partyCount: number): number {
  return 1 - 0.1 * partyCount;
}

/** The field multiplier for a source caught on field `share` of the time. */
export function fieldMultiplier(onFieldShare: number, partyCount: number): number {
  const share = Math.min(1, Math.max(0, onFieldShare));
  return share + (1 - share) * offFieldMultiplier(partyCount);
}

/** Raw particle energy over a rotation at ER 1: Σ particles × value × field. */
export function rawParticleEnergy(model: FormulaEnergy): number {
  let raw = 0;
  for (const source of model.sources) {
    raw += source.particles * particleValue(model.element, source.element)
      * fieldMultiplier(source.onFieldShare, model.partyCount);
  }
  return raw;
}

/** Energy banked over one rotation at a total ER: `ER × raw + flat` (gcsim `energy.go:77`). */
export function energyAt(model: FormulaEnergy, totalEnergyRecharge: number): number {
  return totalEnergyRecharge * rawParticleEnergy(model) + model.flatEnergy;
}

/**
 * The total ER at which one rotation funds one burst — gcsim's own
 * `max((cost − flat) / raw, 1.0)` (`energy_stats.go:85`).
 *
 * `null` when no particle is counted and flat energy falls short: no ER answers it, and that is
 * not the same as "no requirement".
 */
export function requiredEnergyRecharge(model: FormulaEnergy): number | null {
  const raw = rawParticleEnergy(model);
  if (raw <= 0) return model.flatEnergy >= model.cost ? 1 : null;
  return Math.max((model.cost - model.flatEnergy) / raw, 1);
}

/** The artifact ER the requirement asks for beyond this recipe's own: 0 when already met. */
export function artifactEnergyRequirement(model: FormulaEnergy): number | null {
  const total = requiredEnergyRecharge(model);
  return total === null ? null : Math.max(0, total - model.baseEnergyRecharge);
}

/** Bursts a rotation funds, long run: `min(1, energy / cost)`. */
export function burstFraction(model: FormulaEnergy, totalEnergyRecharge: number): number {
  if (model.cost <= 0) return 1;
  return Math.min(1, energyAt(model, totalEnergyRecharge) / model.cost);
}

/**
 * Seconds the team waits for the drip to fund what the rotation's particles did not.
 *
 * The drip is the only energy during a wait (the team stands still), caught on field its share
 * of the time. **Refused without a drip**: gcsim with no drip waits forever (CLAUDE.md, *"gcsim
 * has no watchdog"*), and so would this.
 */
export function waitSeconds(model: FormulaEnergy, totalEnergyRecharge: number): number {
  const deficit = model.cost - energyAt(model, totalEnergyRecharge);
  if (deficit <= 0) return 0;
  if (model.drip === null || model.drip.particlesPerSecond <= 0) {
    throw new Error('the waiting model needs the energy drip: without it the wait never ends');
  }
  const perSecond = model.drip.particlesPerSecond * PARTICLE_VALUE.clear
    * fieldMultiplier(model.drip.onFieldShare, model.partyCount) * totalEnergyRecharge;
  return deficit / perSecond;
}

/**
 * What a candidate's artifact ER does to a formula recipe: a factor on burst rows (`skip`) and a
 * factor on the whole score (`wait`). Both 1 under `off`, and both non-decreasing in ER.
 */
export function energyFactors(
  model: FormulaEnergy, artifactEnergyRecharge: number,
): { burst: number; all: number } {
  const er = model.baseEnergyRecharge + artifactEnergyRecharge;
  switch (model.mode) {
    case 'off': return { burst: 1, all: 1 };
    case 'skip': return { burst: burstFraction(model, er), all: 1 };
    case 'wait': {
      const length = model.rotationSeconds;
      return { burst: 1, all: length / (length + waitSeconds(model, er)) };
    }
  }
}

/**
 * Whether artifact ER can move this recipe's score at all: a priced mode, and a requirement the
 * recipe's own ER does not already meet. The search makes ER live exactly when this holds.
 */
export function energyVaries(model: FormulaEnergy | undefined): boolean {
  if (!model || model.mode === 'off') return false;
  const need = artifactEnergyRequirement(model);
  return need === null || need > 0;
}

/** Particles a source drops in one rotation, from the server's per-cast or per-second form. */
export function particlesPerRotation(
  source: { per: 'cast' | 'second'; particles: number; interval?: number | null;
    max_seconds?: number | null },
  casts: number,
  rotationSeconds: number,
): number {
  if (source.per === 'cast') return source.particles * casts;
  const seconds = Math.min(rotationSeconds, source.max_seconds ?? Infinity) * casts;
  return source.particles * seconds / (source.interval ?? Infinity);
}

/** The panel's sentence for a model: the requirement, the mode and what it assumes. */
export function energyAssumptions(model: FormulaEnergy, subject: string): string[] {
  const total = requiredEnergyRecharge(model);
  const out = [
    total === null
      ? `${subject}'s burst (${model.cost} energy): no particle counted, so no ER requirement can be computed.`
      : `${subject} needs ${(total * 100).toFixed(1)}% Energy Recharge to burst every rotation `
        + `(${model.cost} energy; ${rawParticleEnergy(model).toFixed(2)} particle energy per `
        + `rotation at 100% ER, ${model.flatEnergy} flat).`,
  ];
  if (model.mode === 'off') out.push('Energy: reported only — ER does not change the score.');
  if (model.mode === 'skip') {
    out.push('Energy: skip — a burst the energy cannot fund is skipped, so burst rows land '
      + 'min(1, energy ÷ cost) as often. What the burst does beyond its own hits is not priced.');
  }
  if (model.mode === 'wait') {
    out.push(`Energy: wait — the team holds a ${model.rotationSeconds}s rotation until the drip `
      + 'funds the burst; every row is scaled by rotation ÷ (rotation + wait).');
  }
  for (const s of model.sources) {
    out.push(`Energy source: ${s.label} — ${s.particles.toFixed(2)} particles a rotation, `
      + `${Math.round(s.onFieldShare * 100)}% caught on field (${s.citation}).`);
  }
  return out;
}
