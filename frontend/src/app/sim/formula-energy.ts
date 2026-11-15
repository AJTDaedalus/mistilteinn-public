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
 * ## What the score does with it — three modes, Wait the default (owner, 2026-11-15)
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
 *
 * **Wait is the default** (owner, 2026-11-15, `DECISIONS.md` §48): the estimate prices the
 * sequence a player performs, and a player waits for the burst rather than dropping it.
 *
 * ## Flat energy (follow-ups, §48)
 *
 * A kit's refund (gcsim `AddEnergy`: Raiden's burst to every member, Sara's A4, Jean's and
 * Venti's) is **flat**: ER never multiplies it. Two of them scale with **their giver's** ER
 * instead — Sara's is `1.2 × ER` (`sara/asc.go:32`) and Raiden's restoration is
 * `× (1 + 0.006 × ⌊(ER − 1) × 100⌋)` (`raiden/asc.go:42`, her A4). When the giver is the
 * optimized character that ER is the candidate's, so the refund moves with it; for a
 * teammate it is their build's, a constant here. Both are non-decreasing, so the bound holds.
 *
 * ## Refinements (owner rulings 2026-11-15, `DECISIONS.md` §49)
 *
 * - **Electro resonance** is one more particle source (`formula-estimate.service.ts`): one
 *   Electro particle a qualifying reaction, at most one every 5 s (gcsim `setup.go:185`).
 * - **An on-field subject** catches every off-field generator's particles on field by default.
 * - **The subject's own Favonius** is `subjectFavonius`, priced from each candidate's crit rate:
 *   `energyFactors` takes the candidate's artifact crit beside its ER. Energy is non-decreasing
 *   in both, so the search's bound — every remaining slot's most of each live quantity — still
 *   dominates. A requirement is reported at the build's crit; `energyVaries` asks at the base.
 * - **Yae's totems** share one particle ICD: `particlesPerRotation` does not multiply a
 *   `shared_icd` source by casts.
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

/**
 * How a flat refund scales with the optimized character's own total ER: `none` (a constant —
 * a teammate's, its giver's ER already applied), `per_er` (× ER, Sara's A4) or `raiden_a4`
 * (× 1 + 0.006 × whole percent above 100 %, Raiden's burst).
 */
export type FlatScaling = 'none' | 'per_er' | 'raiden_a4';

/** One flat-energy source over one rotation, as the subject receives it. */
export interface FlatSource {
  key: string;
  label: string;
  /** Energy per rotation before `scaling` is applied. */
  energy: number;
  scaling: FlatScaling;
  citation: string;
}

/** gcsim `raiden/asc.go:42-43`: `excess := int(er * 100)`, `× 0.006` — whole percents only. */
export function raidenA4Multiplier(totalEnergyRecharge: number): number {
  return 1 + 0.006 * Math.floor(Math.max(totalEnergyRecharge - 1, 0) * 100);
}

/** A flat source's energy at a total ER. */
export function flatSourceAt(source: FlatSource, totalEnergyRecharge: number): number {
  switch (source.scaling) {
    case 'none': return source.energy;
    case 'per_er': return source.energy * totalEnergyRecharge;
    case 'raiden_a4': return source.energy * raidenA4Multiplier(totalEnergyRecharge);
  }
}

/**
 * The optimized character's own Favonius weapon, priced per candidate (owner ruling
 * 2026-11-15, `DECISIONS.md` §49): its procs read the candidate's crit rate, so they are not a
 * fixed source.
 *
 * gcsim `favonius.go:38-59`: a crit by the wielder while active procs with the refinement's
 * chance, then a cooldown, and drops 3 clear particles. Procs per rotation are
 * `min(rotation ÷ cooldown, hits × crit rate × chance)` — non-decreasing in crit rate, so a
 * candidate with more crit banks at least as much energy and the search's bound, which
 * completes a partial build with every remaining slot's most crit, still dominates.
 */
export interface SubjectFavonius {
  key: string;
  label: string;
  /** The subject's crit-eligible hits on field per rotation. */
  hits: number;
  chance: number;
  cooldownSeconds: number;
  particles: number;
  /** The share of its particles the subject catches on field, 0..1. */
  onFieldShare: number;
  citation: string;
  /**
   * The subject's crit rate before artifacts (character, weapon, kit crit buffs on the first
   * row: `formula-recipe.ts:subjectCritRate`); a candidate's artifact crit is added to it.
   * Crit converted from another stat (EM, HP) is not included.
   */
  baseCritRate: number;
  /** The build's current crit rate (pass 1): where the requirement is reported. */
  buildCritRate: number;
}

/** A subject Favonius's procs per rotation at a total crit rate. */
export function favoniusProcsAt(
  fav: Pick<SubjectFavonius, 'hits' | 'chance' | 'cooldownSeconds'>,
  rotationSeconds: number, totalCritRate: number,
): number {
  const crit = Math.min(1, Math.max(0, totalCritRate));
  return Math.min(rotationSeconds / fav.cooldownSeconds, fav.hits * crit * fav.chance);
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
  /** Energy per rotation the user entered, that ER does not multiply. */
  flatEnergy: number;
  /** The kits' flat refunds over one rotation (absent: none). */
  flatSources?: FlatSource[];
  /** Every particle source over one rotation, the drip included when it is on. */
  sources: EnergySource[];
  /** The drip as a rate (clear particles a second) and the subject's on-field share; null: off. */
  drip: { particlesPerSecond: number; onFieldShare: number } | null;
  /** The subject's total Energy Recharge before artifacts, as a fraction (1.0 is 100 %). */
  baseEnergyRecharge: number;
  /** The optimized character's own Favonius, priced from each candidate's crit (absent: none). */
  subjectFavonius?: SubjectFavonius;
}

/** The crit rate a model is reported at when none is given: the build's own. */
function reportedCrit(model: FormulaEnergy, totalCritRate: number | undefined): number {
  return totalCritRate ?? model.subjectFavonius?.buildCritRate ?? 0;
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

/**
 * Raw particle energy over a rotation at ER 1: Σ particles × value × field — and the subject's
 * own Favonius at a total crit rate (the build's when none is given).
 */
export function rawParticleEnergy(model: FormulaEnergy, totalCritRate?: number): number {
  let raw = 0;
  for (const source of model.sources) {
    raw += source.particles * particleValue(model.element, source.element)
      * fieldMultiplier(source.onFieldShare, model.partyCount);
  }
  const fav = model.subjectFavonius;
  if (fav) {
    raw += favoniusProcsAt(fav, model.rotationSeconds, reportedCrit(model, totalCritRate))
      * fav.particles * PARTICLE_VALUE.clear * fieldMultiplier(fav.onFieldShare, model.partyCount);
  }
  return raw;
}

/** Flat energy over one rotation at a total ER: the user's plus every refund. */
export function flatEnergyAt(model: FormulaEnergy, totalEnergyRecharge: number): number {
  let flat = model.flatEnergy;
  for (const source of model.flatSources ?? []) flat += flatSourceAt(source, totalEnergyRecharge);
  return flat;
}

/**
 * Energy banked over one rotation at a total ER (and crit rate, for a subject's Favonius):
 * `ER × raw + flat` (gcsim `energy.go:77`).
 */
export function energyAt(
  model: FormulaEnergy, totalEnergyRecharge: number, totalCritRate?: number,
): number {
  return totalEnergyRecharge * rawParticleEnergy(model, totalCritRate)
    + flatEnergyAt(model, totalEnergyRecharge);
}

/** The highest ER the requirement is searched to (10 000 %): beyond it, "no ER answers". */
const ER_CEILING = 100;

/**
 * The total ER at which one rotation funds one burst — gcsim's own
 * `max((cost − flat) / raw, 1.0)` (`energy_stats.go:85`) — at a total crit rate (the build's
 * when none is given; it moves only a subject's own Favonius).
 *
 * `null` when no particle is counted and flat energy falls short: no ER answers it, and that is
 * not the same as "no requirement".
 */
export function requiredEnergyRecharge(
  model: FormulaEnergy, totalCritRate?: number,
): number | null {
  const crit = reportedCrit(model, totalCritRate);
  const raw = rawParticleEnergy(model, crit);
  if (!(model.flatSources ?? []).some((s) => s.scaling !== 'none')) {
    const flat = flatEnergyAt(model, 1);
    if (raw <= 0) return flat >= model.cost ? 1 : null;
    return Math.max((model.cost - flat) / raw, 1);
  }
  // A refund that scales with the subject's own ER: energy is still non-decreasing in ER, so
  // the requirement is the least ER whose energy reaches the cost, found by bisection.
  if (energyAt(model, 1, crit) >= model.cost) return 1;
  if (energyAt(model, ER_CEILING, crit) < model.cost) return null;
  let low = 1;
  let high = ER_CEILING;
  for (let i = 0; i < 200 && high - low > 1e-12; i += 1) {
    const mid = (low + high) / 2;
    if (energyAt(model, mid, crit) >= model.cost) high = mid;
    else low = mid;
  }
  return high;
}

/** The artifact ER the requirement asks for beyond this recipe's own: 0 when already met. */
export function artifactEnergyRequirement(
  model: FormulaEnergy, totalCritRate?: number,
): number | null {
  const total = requiredEnergyRecharge(model, totalCritRate);
  return total === null ? null : Math.max(0, total - model.baseEnergyRecharge);
}

/** Bursts a rotation funds, long run: `min(1, energy / cost)`. */
export function burstFraction(
  model: FormulaEnergy, totalEnergyRecharge: number, totalCritRate?: number,
): number {
  if (model.cost <= 0) return 1;
  return Math.min(1, energyAt(model, totalEnergyRecharge, totalCritRate) / model.cost);
}

/**
 * Seconds the team waits for the drip to fund what the rotation's particles did not.
 *
 * The drip is the only energy during a wait (the team stands still), caught on field its share
 * of the time. **Refused without a drip**: gcsim with no drip waits forever (CLAUDE.md, *"gcsim
 * has no watchdog"*), and so would this.
 */
export function waitSeconds(
  model: FormulaEnergy, totalEnergyRecharge: number, totalCritRate?: number,
): number {
  const deficit = model.cost - energyAt(model, totalEnergyRecharge, totalCritRate);
  if (deficit <= 0) return 0;
  if (model.drip === null || model.drip.particlesPerSecond <= 0) {
    throw new Error('the waiting model needs the energy drip: without it the wait never ends');
  }
  const perSecond = model.drip.particlesPerSecond * PARTICLE_VALUE.clear
    * fieldMultiplier(model.drip.onFieldShare, model.partyCount) * totalEnergyRecharge;
  return deficit / perSecond;
}

/**
 * What a candidate's artifact ER (and artifact crit, for a subject's Favonius) does to a formula
 * recipe: a factor on burst rows (`skip`) and a factor on the whole score (`wait`). Both 1 under
 * `off`, and both non-decreasing in ER and in crit — so the search's bound, which completes a
 * partial build with the most of every live quantity, still dominates.
 */
export function energyFactors(
  model: FormulaEnergy, artifactEnergyRecharge: number, artifactCritRate = 0,
): { burst: number; all: number } {
  const er = model.baseEnergyRecharge + artifactEnergyRecharge;
  const crit = (model.subjectFavonius?.baseCritRate ?? 0) + artifactCritRate;
  switch (model.mode) {
    case 'off': return { burst: 1, all: 1 };
    case 'skip': return { burst: burstFraction(model, er, crit), all: 1 };
    case 'wait': {
      const length = model.rotationSeconds;
      return { burst: 1, all: length / (length + waitSeconds(model, er, crit)) };
    }
  }
}

/**
 * Whether artifact ER can move this recipe's score at all: a priced mode, and a requirement the
 * recipe's own ER does not already meet **at the lowest crit a candidate can have** — the base,
 * no artifact crit — since a subject's Favonius banks less with less crit. The search makes ER
 * live exactly when this holds.
 */
export function energyVaries(model: FormulaEnergy | undefined): boolean {
  if (!model || model.mode === 'off') return false;
  const need = artifactEnergyRequirement(model, model.subjectFavonius?.baseCritRate);
  return need === null || need > 0;
}

/**
 * Particles a source drops in one rotation, from the server's per-cast or per-second form.
 *
 * A `shared_icd` source (Yae's totems, gcsim `yaemiko/skill.go:43`) holds its particle ICD on
 * the character, so totems standing together drop no more than one does: casts switch it on
 * (any cast at all) but do not multiply it.
 */
export function particlesPerRotation(
  source: { per: 'cast' | 'second'; particles: number; interval?: number | null;
    max_seconds?: number | null; shared_icd?: boolean | null },
  casts: number,
  rotationSeconds: number,
): number {
  const times = source.shared_icd ? Math.min(casts, 1) : casts;
  if (source.per === 'cast') return source.particles * times;
  const seconds = Math.min(rotationSeconds, source.max_seconds ?? Infinity) * times;
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
        + `rotation at 100% ER, ${flatEnergyAt(model, 1).toFixed(2)} flat).`,
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
  const fav = model.subjectFavonius;
  if (fav) {
    const procs = favoniusProcsAt(fav, model.rotationSeconds, fav.buildCritRate);
    out.push(`Energy source: ${fav.label} — procs priced from each candidate's crit rate: `
      + `min(${model.rotationSeconds}s ÷ ${fav.cooldownSeconds}s, ${fav.hits.toFixed(1)} hits × `
      + `crit × ${fav.chance}); ${procs.toFixed(2)} a rotation at the build's `
      + `${(fav.buildCritRate * 100).toFixed(1)}% crit, ${fav.particles} clear particles each, `
      + `${Math.round(fav.onFieldShare * 100)}% caught on field (${fav.citation}).`);
  }
  for (const s of model.flatSources ?? []) {
    const scaled = s.scaling === 'none' ? ''
      : s.scaling === 'per_er' ? ' × the optimized character\'s ER'
        : ' × (1 + 0.006 per whole 1% of the optimized character\'s ER above 100%)';
    out.push(`Flat energy: ${s.label} — ${s.energy.toFixed(2)} a rotation${scaled}, `
      + `not multiplied by ER (${s.citation}).`);
  }
  return out;
}
