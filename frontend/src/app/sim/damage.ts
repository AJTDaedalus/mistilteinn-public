/**
 * The damage chain, in the browser.
 *
 * A **second implementation** of `backend/app/formula/genshin/damage.py` — which DESIGN §1
 * A6's "one mechanic, one implementation" rule normally forbids, and which
 * `DESIGN_client_optimizer.md` §6 accepts only because a gate binds the two: 2,000 generated
 * cases in `backend/tests/fixtures/kernel/cases.json`, matched to `1e-6`.
 *
 * Every formula here is cited to the Python line that owns it, and through it to gcsim. Do
 * not "simplify" one without changing both — a divergence here is a number that disagrees
 * with the project's own crossval oracle.
 *
 * ## Everything is `Math.fround`
 *
 * The GPU backend will be WGSL, which has **no f64**. If this backend computed in JavaScript's
 * native f64 it would be *more* accurate — and then the two backends would disagree, and a
 * user switching between them would see their build's number change for no reason they could
 * act on.
 *
 * So this rounds to f32 at every step, matching what the GPU must do. The cost is deliberate:
 * `docs/CROSSVAL_gcsim.md` measures it at 3.51e-07 worst case and argues the `1e-6` tolerance
 * from it.
 */

/** Round to f32, the precision the GPU backend is limited to. */
const f = Math.fround;

/** `damage.py:MAX_DEF_REDUCTION` — gcsim `damage.go:81-84`. */
const MAX_DEF_REDUCTION = 0.9;
/** `damage.py:MAX_DEF_IGNORE`. */
const MAX_DEF_IGNORE = 1.0;
/** Above this, resistance follows the diminishing branch. `damage.py:RES_DIMINISHING_THRESHOLD`. */
const RES_DIMINISHING_THRESHOLD = 0.75;
/** `2.78 * em / (1400 + em)`. `damage.py:AMPLIFYING_EM_*`, gcsim `damage.go:113`. */
const AMPLIFYING_EM_NUMERATOR = 2.78;
const AMPLIFYING_EM_DENOMINATOR = 1400.0;

/** What a talent's multiplier scales off. Mirrors `damage.py:ScalingStat`. */
export type ScalingStat = 'atk' | 'hp' | 'def' | 'elemental_mastery';

/** The amplifying reactions and their base multipliers. `damage.py:Amplifying`. */
export const AMPLIFYING_MULTIPLIER = {
  melt: 2.0,
  reverse_melt: 1.5,
  vaporize: 2.0,
  reverse_vaporize: 1.5,
} as const;

export type Amplifying = keyof typeof AMPLIFYING_MULTIPLIER;

export interface Hit {
  multiplier: number;
  scalingStat: ScalingStat;
  flatDamage: number;
  baseDamageBonus: number;
  amplifying: Amplifying | null;
  reactionBonus: number;
}

export interface Target {
  level: number;
  resistance: number;
  defReduction: number;
  defIgnore: number;
}

/**
 * The DEF term. `damage.py:def_multiplier`, gcsim `damage.go:81-84`.
 *
 * Reduction and ignore are **different mechanics multiplied separately**, not one pool.
 * Adding them overstates a build that has both — a mistake worth 2.27e-04 relative, which is
 * 226x the tolerance, so the gate catches it.
 */
export function defMultiplier(
  characterLevel: number,
  enemyLevel: number,
  defReduction = 0,
  defIgnore = 0,
): number {
  const reduction = Math.min(defReduction, MAX_DEF_REDUCTION);
  const ignore = Math.min(defIgnore, MAX_DEF_IGNORE);
  const attacker = f(characterLevel + 100);
  const defender = f(f(f(enemyLevel + 100) * f(1 - reduction)) * f(1 - ignore));
  return f(attacker / f(attacker + defender));
}

/**
 * The RES term. `damage.py:res_multiplier`.
 *
 * **Exactly 0.75 takes the diminishing branch here**, where gcsim's `else if res > 0.75`
 * falls through to the negative-RES branch and returns 0.625 against this one's 0.25. That
 * is a deliberate, documented divergence — see `docs/CROSSVAL_gcsim.md`. Copying gcsim's
 * `>` would be a 1.5 relative difference, which is 1,500,000x the tolerance.
 */
export function resMultiplier(resistance: number): number {
  if (resistance < 0) return f(1 - f(resistance / 2));
  if (resistance < RES_DIMINISHING_THRESHOLD) return f(1 - resistance);
  return f(1 / f(f(4 * resistance) + 1));
}

/** The amplifying term. `damage.py:amplifying_multiplier`, gcsim `damage.go:113`. */
export function amplifyingMultiplier(
  reaction: Amplifying,
  elementalMastery: number,
  reactionBonus = 0,
): number {
  const emBonus = f(
    f(AMPLIFYING_EM_NUMERATOR * elementalMastery) / f(AMPLIFYING_EM_DENOMINATOR + elementalMastery),
  );
  return f(AMPLIFYING_MULTIPLIER[reaction] * f(f(1 + emBonus) + reactionBonus));
}

/**
 * The **expected** crit multiplier: `1 + clamp(rate) * dmg`. `damage.py:crit_multiplier`.
 *
 * Crit rate clamps to [0, 1] as gcsim does at `damage.go:66-71`. A kernel that forgets the
 * clamp is wrong *only* above 100% — invisible on ordinary builds, and worth 2.06e-04 there,
 * which is 206x the tolerance.
 */
export function critMultiplier(critRate: number, critDmg: number): number {
  return f(1 + f(Math.min(Math.max(critRate, 0), 1) * critDmg));
}

/**
 * `base * (1 + pct) + flat` — the single-stage stat formula.
 * `backend/app/formula/genshin/stats.py`, cited to gcsim `stats.go:44-46`.
 */
export function resolveStat(base: number, percent: number, flat: number): number {
  return f(f(base * f(1 + percent)) + flat);
}

export interface DamageInputs {
  hit: Hit;
  scalingValue: number;
  dmgBonus: number;
  critRate: number;
  critDmg: number;
  elementalMastery: number;
  characterLevel: number;
  target: Target;
}

/**
 * One hit's expected damage.
 *
 * The order is the chain's, and the order matters: `baseDamageBonus` multiplies the scaled
 * stat *before* flat damage is added, and the DMG bonus applies *after*. Swapping those is
 * the sort of thing a reimplementation gets subtly wrong and the case sweep is built to
 * catch.
 */
export function computeDamage(inputs: DamageInputs): number {
  const { hit, target } = inputs;

  let value = f(
    f(f(f(hit.multiplier) * f(inputs.scalingValue)) * f(1 + hit.baseDamageBonus)) +
      hit.flatDamage,
  );
  value = f(value * f(1 + inputs.dmgBonus));
  value = f(
    value * defMultiplier(inputs.characterLevel, target.level, target.defReduction, target.defIgnore),
  );
  value = f(value * resMultiplier(target.resistance));
  if (hit.amplifying !== null) {
    value = f(value * amplifyingMultiplier(hit.amplifying, inputs.elementalMastery, hit.reactionBonus));
  }
  return f(value * critMultiplier(inputs.critRate, inputs.critDmg));
}
