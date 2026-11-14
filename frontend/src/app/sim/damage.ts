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

/**
 * One further `multiplier x stat` part of a hit. `damage.py:ScalingTerm`.
 *
 * Nahida's Tri-Karma Purification is `ATK x a + EM x b` in **one** instance of damage. gcsim
 * writes the second part as `FlatDmg` (`nahida/skill.go:219-220`), so it enters the base
 * where flat damage does: after `baseDamageBonus`, before the DMG bonus.
 */
export interface ScalingTerm {
  stat: ScalingStat;
  multiplier: number;
}

export interface Hit {
  multiplier: number;
  scalingStat: ScalingStat;
  flatDamage: number;
  baseDamageBonus: number;
  amplifying: Amplifying | null;
  /** The amplifying reaction's bonus, or the additive one's: a hit triggers at most one. */
  reactionBonus: number;
  /** A mixed-stat hit's further terms. Absent or empty for every single-stat hit. */
  extraTerms?: readonly ScalingTerm[];
  /**
   * The additive reaction this hit triggers, if any (math-fallback P3): flat damage added to
   * the base before the DMG bonus. `damage.py:Hit.additive`, gcsim `catalyze.go:24,43`. Needs
   * `DamageInputs.reactionLevelMultiplier`.
   */
  additive?: Additive | null;
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
 * `backend/app/formula/genshin/stats.py`, cited to gcsim `stats.go:49-51`.
 */
export function resolveStat(base: number, percent: number, flat: number): number {
  return f(f(base * f(1 + percent)) + flat);
}

export interface DamageInputs {
  hit: Hit;
  /**
   * The reaction level multiplier at `characterLevel` (`ElementCoeffExcelConfigData.
   * playerElementLevelCo`), as the server sends it. Read only by an additive hit.
   */
  reactionLevelMultiplier?: number;
  scalingValue: number;
  /** The resolved stat for each of `hit.extraTerms`, in order. One per term. */
  extraScalingValues?: readonly number[];
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
  const terms = hit.extraTerms ?? [];
  const values = inputs.extraScalingValues ?? [];
  if (values.length !== terms.length) {
    // `damage.py:compute_damage` refuses the same thing: pairing them short drops a term's
    // damage and still returns a number.
    throw new Error(
      `the hit has ${terms.length} extra scaling term(s) and ${values.length} value(s) ` +
        `were resolved for them`,
    );
  }

  // Each extra term is `f(multiplier * stat)`, summed in f32 — the order the WGSL computes in.
  let extra = 0;
  terms.forEach((term, i) => {
    extra = f(extra + f(f(term.multiplier) * f(values[i])));
  });

  let additive = 0;
  if (hit.additive) {
    if (hit.amplifying !== null) {
      throw new Error('a hit triggers an amplifying or an additive reaction, not both');
    }
    if (inputs.reactionLevelMultiplier === undefined) {
      throw new Error(`an ${hit.additive} hit needs the reaction level multiplier`);
    }
    additive = additiveFlat(
      hit.additive, inputs.reactionLevelMultiplier, inputs.elementalMastery, hit.reactionBonus,
    );
  }
  let value = f(
    f(f(f(f(f(hit.multiplier) * f(inputs.scalingValue)) * f(1 + hit.baseDamageBonus)) + extra) +
      hit.flatDamage) + additive,
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

// ── Reactions (math-fallback P3, task 13) ──────────────────────────────────────────────────
//
// The mirror of `backend/app/formula/genshin/reactions.py`, bound to it by
// `backend/tests/fixtures/kernel/reaction_cases.json` (`npm run kernel:verify`), and through it
// to gcsim (`tests/crossval/test_reaction_crossval.py`). The level multiplier is not here: the
// server sends it (`/search-context`'s `reaction_level_multiplier`) from the committed game
// table, so there is one copy of it.

/** `reactions.py:TRANSFORMATIVE_EM_*`: `16·EM/(2000+EM)`, gcsim `reaction.go:38`. */
const TRANSFORMATIVE_EM = [16, 2000] as const;
/** `reactions.py:ADDITIVE_EM_*`: `5·EM/(1200+EM)`, gcsim `reaction.go:42`. */
const ADDITIVE_EM = [5, 1200] as const;
/** `reactions.py:LUNAR_EM_*`: `6·EM/(2000+EM)`, gcsim `reaction.go:30`. */
const LUNAR_EM = [6, 2000] as const;

/** `reactions.py:TRANSFORMATIVE`: multiplier, damage element (`null`: the swirled one), crit. */
export const TRANSFORMATIVE = {
  overloaded: { multiplier: 2.75, element: 'pyro', crittable: false },
  electro_charged: { multiplier: 2.0, element: 'electro', crittable: false },
  superconduct: { multiplier: 1.5, element: 'cryo', crittable: false },
  swirl: { multiplier: 0.6, element: null, crittable: true },
  shattered: { multiplier: 3.0, element: 'physical', crittable: false },
  burning: { multiplier: 0.25, element: 'pyro', crittable: true },
  bloom: { multiplier: 2.0, element: 'dendro', crittable: true },
  hyperbloom: { multiplier: 3.0, element: 'dendro', crittable: true },
  burgeon: { multiplier: 3.0, element: 'dendro', crittable: true },
} as const;

export type Transformative = keyof typeof TRANSFORMATIVE;

/** `reactions.py:SWIRL_ELEMENTS`. */
export const SWIRL_ELEMENTS = ['pyro', 'hydro', 'electro', 'cryo'] as const;

/** `reactions.py:ADDITIVE`: multiplier and the element of the hit that triggers it. */
export const ADDITIVE = {
  spread: { multiplier: 1.25, element: 'dendro' },
  aggravate: { multiplier: 1.15, element: 'electro' },
} as const;

export type Additive = keyof typeof ADDITIVE;

/** `reactions.py:LUNAR`: multiplier and damage element. */
export const LUNAR = {
  lunar_charged: { multiplier: 3.0, element: 'electro' },
  lunar_crystallize: { multiplier: 1.6, element: 'geo' },
} as const;

export type Lunar = keyof typeof LUNAR;

function emBonus([numerator, denominator]: readonly [number, number], em: number): number {
  if (em < 0) throw new Error(`elemental mastery cannot be negative; got ${em}`);
  return f(f(numerator * em) / f(denominator + em));
}

/** `reactions.py:transformative_element`: whose RES a transformative reaction meets. */
export function transformativeElement(reaction: Transformative, swirled?: string | null): string {
  const element = TRANSFORMATIVE[reaction].element;
  if (element !== null) {
    if (swirled) throw new Error(`${reaction} carries ${element}; only a swirl takes a swirled element`);
    return element;
  }
  if (!swirled || !(SWIRL_ELEMENTS as readonly string[]).includes(swirled)) {
    throw new Error(`a swirl carries one of ${SWIRL_ELEMENTS.join('/')}; got ${swirled}`);
  }
  return swirled;
}

/**
 * The transformative multiplier before RES and crit:
 * `multiplier × levelBase × (1 + 16·EM/(2000+EM) + reactionBonus)`.
 */
export function transformativeBase(
  reaction: Transformative, levelBase: number, elementalMastery: number, reactionBonus = 0,
): number {
  const bracket = f(f(1 + emBonus(TRANSFORMATIVE_EM, elementalMastery)) + reactionBonus);
  return f(f(TRANSFORMATIVE[reaction].multiplier * f(levelBase)) * bracket);
}

/**
 * One transformative reaction's expected damage (`reactions.py:transformative_damage`). DEF is
 * ignored (gcsim `IgnoreDefPercent: 1`); the CRIT is the **reaction's own**, refused on a
 * reaction that cannot crit.
 */
export function transformativeDamage(inputs: {
  reaction: Transformative;
  levelBase: number;
  elementalMastery: number;
  resistance: number;
  reactionBonus?: number;
  critRate?: number;
  critDmg?: number;
}): number {
  const critRate = inputs.critRate ?? 0;
  const critDmg = inputs.critDmg ?? 0;
  if (!TRANSFORMATIVE[inputs.reaction].crittable && (critRate || critDmg)) {
    throw new Error(`${inputs.reaction} cannot crit`);
  }
  const base = transformativeBase(
    inputs.reaction, inputs.levelBase, inputs.elementalMastery, inputs.reactionBonus ?? 0,
  );
  return f(f(base * resMultiplier(inputs.resistance)) * critMultiplier(critRate, critDmg));
}

/** The flat damage an additive reaction adds to its hit. `reactions.py:additive_flat`. */
export function additiveFlat(
  reaction: Additive, levelBase: number, elementalMastery: number, reactionBonus = 0,
): number {
  const bracket = f(f(1 + emBonus(ADDITIVE_EM, elementalMastery)) + reactionBonus);
  return f(f(ADDITIVE[reaction].multiplier * f(levelBase)) * bracket);
}

/**
 * The Lunar multiplier before RES and crit:
 * `multiplier × levelBase × (1 + 6·EM/(2000+EM) + reactionBonus) × (1 + baseDmgBonus)`.
 */
export function lunarBase(
  reaction: Lunar, levelBase: number, elementalMastery: number, reactionBonus = 0,
  baseDmgBonus = 0,
): number {
  const bracket = f(f(1 + emBonus(LUNAR_EM, elementalMastery)) + reactionBonus);
  return f(f(f(LUNAR[reaction].multiplier * f(levelBase)) * bracket) * f(1 + baseDmgBonus));
}

/** One character's Lunar contribution with their own CRIT. `reactions.py:lunar_damage`. */
export function lunarDamage(inputs: {
  reaction: Lunar;
  levelBase: number;
  elementalMastery: number;
  resistance: number;
  critRate: number;
  critDmg: number;
  reactionBonus?: number;
  baseDmgBonus?: number;
}): number {
  const base = lunarBase(
    inputs.reaction, inputs.levelBase, inputs.elementalMastery, inputs.reactionBonus ?? 0,
    inputs.baseDmgBonus ?? 0,
  );
  return f(f(base * resMultiplier(inputs.resistance)) * critMultiplier(inputs.critRate, inputs.critDmg));
}
