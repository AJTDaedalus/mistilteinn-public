// The damage chain as a compute shader — the GPU half of the browser kernel.
//
// A **third** implementation of the same arithmetic (Python chain → TypeScript kernel → this),
// which DESIGN §1 A6 tolerates only because one gate binds all three: the 2,000 generated
// cases in `backend/tests/fixtures/kernel/cases.json`, matched to 1e-6.
//
// Every formula is cited to the TypeScript line that owns it, and through that to
// `backend/app/formula/genshin/damage.py` and to gcsim. Do not change one alone.
//
// WGSL has no f64, which is not a limitation here — it is the reason the tolerance is 1e-6
// rather than the f64 chain's 1e-7. `docs/CROSSVAL_gcsim.md` measures and argues it.

// One case, flat: 17 fields padded to 20 floats. It was 16 (15 and a pad, for 64-byte
// boundaries) until a hit could carry a second scaling term — `gpu.ts:CASE_STRIDE` says why
// the alignment was given up rather than doubling the stride to 32.
struct Case {
  multiplier: f32,
  scaling_value: f32,
  dmg_bonus: f32,
  crit_rate: f32,
  crit_dmg: f32,
  elemental_mastery: f32,
  character_level: f32,
  enemy_level: f32,
  resistance: f32,
  def_reduction: f32,
  def_ignore: f32,
  flat_damage: f32,
  base_damage_bonus: f32,
  // 0 means "no reaction". Passed as the reaction's own multiplier (2.0 melt, 1.5 reverse)
  // rather than an enum: the host already knows which reaction it is, and a branch per
  // reaction inside the shader would buy nothing.
  amplifying_multiplier: f32,
  reaction_bonus: f32,
  // A mixed-stat hit's second `multiplier x stat` term (`damage.ts:ScalingTerm`, math-fallback
  // P0) — Nahida's Tri-Karma is `ATK x a + EM x b`. Both 0 for a single-stat hit.
  extra_multiplier: f32,
  extra_scaling_value: f32,
  _padding0: f32,
  _padding1: f32,
  _padding2: f32,
}

@group(0) @binding(0) var<storage, read> cases: array<Case>;
@group(0) @binding(1) var<storage, read_write> results: array<f32>;

const MAX_DEF_REDUCTION: f32 = 0.9;
const MAX_DEF_IGNORE: f32 = 1.0;
const RES_DIMINISHING_THRESHOLD: f32 = 0.75;
const AMPLIFYING_EM_NUMERATOR: f32 = 2.78;
const AMPLIFYING_EM_DENOMINATOR: f32 = 1400.0;

/// `damage.ts:defMultiplier`. Reduction and ignore multiply separately — adding them
/// overstates a build that has both.
fn def_multiplier(char_level: f32, enemy_level: f32, reduction: f32, ignore: f32) -> f32 {
  let r = min(reduction, MAX_DEF_REDUCTION);
  let i = min(ignore, MAX_DEF_IGNORE);
  let attacker = char_level + 100.0;
  let defender = (enemy_level + 100.0) * (1.0 - r) * (1.0 - i);
  return attacker / (attacker + defender);
}

/// `damage.ts:resMultiplier`. Exactly 0.75 takes the diminishing branch — the documented
/// divergence from gcsim, whose `>` sends it to the negative branch instead.
fn res_multiplier(resistance: f32) -> f32 {
  if (resistance < 0.0) { return 1.0 - resistance / 2.0; }
  if (resistance < RES_DIMINISHING_THRESHOLD) { return 1.0 - resistance; }
  return 1.0 / (4.0 * resistance + 1.0);
}

/// `damage.ts:critMultiplier`. Crit rate clamps to [0, 1], as gcsim does.
fn crit_multiplier(crit_rate: f32, crit_dmg: f32) -> f32 {
  return 1.0 + clamp(crit_rate, 0.0, 1.0) * crit_dmg;
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
  let index = id.x;
  if (index >= arrayLength(&cases)) { return; }
  let c = cases[index];

  // The order is the chain's: base_damage_bonus multiplies the scaled stat *before* flat
  // damage is added, and the DMG bonus applies after. A second scaling term enters where
  // gcsim puts it, as flat damage — after base_damage_bonus.
  let extra = c.extra_multiplier * c.extra_scaling_value;
  var value = c.multiplier * c.scaling_value * (1.0 + c.base_damage_bonus) + extra + c.flat_damage;
  value = value * (1.0 + c.dmg_bonus);
  value = value * def_multiplier(c.character_level, c.enemy_level, c.def_reduction, c.def_ignore);
  value = value * res_multiplier(c.resistance);

  if (c.amplifying_multiplier > 0.0) {
    let em_bonus = (AMPLIFYING_EM_NUMERATOR * c.elemental_mastery)
      / (AMPLIFYING_EM_DENOMINATOR + c.elemental_mastery);
    value = value * c.amplifying_multiplier * (1.0 + em_bonus + c.reaction_bonus);
  }

  results[index] = value * crit_multiplier(c.crit_rate, c.crit_dmg);
}
