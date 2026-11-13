// C.5 — the WGSL backend against the same 2,000 cases as the CPU one.
//
// **OQ-S4 answered here**: this repo's rule is that a check which cannot run is not a pass,
// and CI runners have no GPU. They do not have a Vulkan driver either — that was the first
// answer's mistake, generalised from a dev box that happened to have Mesa installed. CI now
// installs `mesa-vulkan-drivers` (lavapipe), and Dawn picks up the software adapter, so the
// GPU path is genuinely exercised rather than exempted.
// Software adapters are slow, which does not matter: this gate checks that the shader
// computes the right numbers, not that it computes them quickly.
//
// If no adapter can be had at all, this **fails** rather than skipping. A skip here would be
// the third damage chain shipping unverified.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { create } from '@kmamal/gpu';

import { CASE_STRIDE, FIELD, createGpuKernel } from '../src/app/sim/gpu.ts';
import { AMPLIFYING_MULTIPLIER, computeDamage, resolveStat } from '../src/app/sim/damage.ts';

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), '..');
const CASES = join(FRONTEND, '..', 'backend', 'tests', 'fixtures', 'kernel', 'cases.json');
const SHADER = join(FRONTEND, 'src', 'app', 'sim', 'damage.wgsl');

/** `docs/CROSSVAL_gcsim.md`. The same number the CPU backend is held to. */
const TOLERANCE = 1e-6;

const SCALING = {
  atk: ['base_atk', 'atk_pct', 'flat_atk'],
  hp: ['base_hp', 'hp_pct', 'flat_hp'],
  def: ['base_def', 'def_pct', 'flat_def'],
};

function statValue(c, stat) {
  if (stat === 'elemental_mastery') return c.stats.elemental_mastery;
  const [base, pct, flat] = SCALING[stat];
  return resolveStat(c.stats[base], c.stats[pct], c.stats[flat]);
}

function scalingValue(c) {
  return statValue(c, c.hit.scaling_stat);
}

// A mixed-stat hit (math-fallback P0) carries `extra_terms`; the pre-P0 cases omit the key.
// The WGSL case holds one, which is the most any catalogue row carries.
function extraTerms(c) {
  const terms = c.hit.extra_terms ?? [];
  if (terms.length > 1) {
    console.error(`${c.id} has ${terms.length} extra terms; the WGSL case struct holds one`);
    process.exit(1);
  }
  return terms;
}

const { cases } = JSON.parse(readFileSync(CASES, 'utf8'));
if (!Array.isArray(cases) || cases.length < 1000) {
  console.error(`expected at least 1000 cases, found ${cases?.length ?? 0}`);
  process.exit(1);
}

const gpu = create([]);
const adapter = await gpu.requestAdapter();
if (!adapter) {
  console.error(
    'no WebGPU adapter, so the GPU backend is unverified — this fails rather than skipping.\n' +
      'On a machine without a GPU this usually means no Vulkan ICD is installed: Dawn reports\n' +
      '`vkCreateInstance: Found no drivers!` even though libvulkan is present. Install a\n' +
      'software driver:\n' +
      '    sudo apt-get install -y mesa-vulkan-drivers   # provides lavapipe (lvp_icd.json)\n' +
      'CI does exactly this; see the workflow step above `kernel:verify-gpu`.',
  );
  process.exit(1);
}
const info = adapter.info ?? {};
console.log(`adapter: ${info.description || 'unknown'}`);
const device = await adapter.requestDevice();

const kernel = createGpuKernel(device, readFileSync(SHADER, 'utf8'), () => device.tick?.());

// One flat buffer for every case: the batch interface is the point, and dispatching 2,000
// single-case jobs would test a shape nothing will use.
const packed = new Float32Array(cases.length * CASE_STRIDE);
cases.forEach((c, i) => {
  const at = i * CASE_STRIDE;
  packed[at + FIELD.multiplier] = c.hit.multiplier;
  packed[at + FIELD.scalingValue] = scalingValue(c);
  packed[at + FIELD.dmgBonus] = c.dmg_bonus.value;
  packed[at + FIELD.critRate] = c.stats.crit_rate;
  packed[at + FIELD.critDmg] = c.stats.crit_dmg;
  packed[at + FIELD.elementalMastery] = c.stats.elemental_mastery;
  packed[at + FIELD.characterLevel] = c.character_level;
  packed[at + FIELD.enemyLevel] = c.enemy.level;
  packed[at + FIELD.resistance] = c.enemy.resistance;
  packed[at + FIELD.defReduction] = c.enemy.def_reduction;
  packed[at + FIELD.defIgnore] = c.enemy.def_ignore;
  packed[at + FIELD.flatDamage] = c.hit.flat_damage;
  packed[at + FIELD.baseDamageBonus] = c.hit.base_damage_bonus;
  packed[at + FIELD.amplifyingMultiplier] = c.hit.amplifying
    ? AMPLIFYING_MULTIPLIER[c.hit.amplifying]
    : 0;
  packed[at + FIELD.reactionBonus] = c.hit.reaction_bonus;
  const [extra] = extraTerms(c);
  packed[at + FIELD.extraMultiplier] = extra ? extra.multiplier : 0;
  packed[at + FIELD.extraScalingValue] = extra ? statValue(c, extra.stat) : 0;
});

const got = await kernel.computeDamageBatch(packed);

const failures = [];
let worst = 0;
cases.forEach((c, i) => {
  const want = c.expected.expected;
  const rel = want === 0 ? Math.abs(got[i]) : Math.abs(got[i] - want) / Math.abs(want);
  if (rel > worst) worst = rel;
  if (rel > TOLERANCE) failures.push({ id: c.id, got: got[i], want, rel });
});

if (failures.length > 0) {
  failures.sort((a, b) => b.rel - a.rel);
  console.error(`${failures.length}/${cases.length} cases diverge past ${TOLERANCE}:`);
  for (const f of failures.slice(0, 5)) {
    console.error(`  ${f.id}: got ${f.got} want ${f.want} (rel ${f.rel.toExponential(3)})`);
  }
  process.exit(1);
}

console.log(
  `GPU kernel matches the Python chain on all ${cases.length} cases ` +
    `(worst ${worst.toExponential(3)}, tolerance ${TOLERANCE.toExponential(0)})`,
);

// The property a *user* actually feels: switching backends must not change their build's
// number by more than the tolerance. Both agreeing with Python does not imply agreeing with
// each other — their errors can lean opposite ways, and this divergence is larger than
// either's from the chain.
let backendWorst = 0;
let identical = 0;
cases.forEach((c, i) => {
  const cpu = computeDamage({
    hit: {
      multiplier: c.hit.multiplier,
      scalingStat: c.hit.scaling_stat,
      flatDamage: c.hit.flat_damage,
      baseDamageBonus: c.hit.base_damage_bonus,
      amplifying: c.hit.amplifying,
      reactionBonus: c.hit.reaction_bonus,
      extraTerms: extraTerms(c),
    },
    scalingValue: scalingValue(c),
    extraScalingValues: extraTerms(c).map((t) => statValue(c, t.stat)),
    dmgBonus: c.dmg_bonus.value,
    critRate: c.stats.crit_rate,
    critDmg: c.stats.crit_dmg,
    elementalMastery: c.stats.elemental_mastery,
    characterLevel: c.character_level,
    target: {
      level: c.enemy.level,
      resistance: c.enemy.resistance,
      defReduction: c.enemy.def_reduction,
      defIgnore: c.enemy.def_ignore,
    },
  });
  if (cpu === got[i]) identical += 1;
  const rel = cpu === 0 ? Math.abs(got[i]) : Math.abs(cpu - got[i]) / Math.abs(cpu);
  if (rel > backendWorst) backendWorst = rel;
});

if (backendWorst > TOLERANCE) {
  console.error(
    `the CPU and GPU backends diverge by ${backendWorst.toExponential(3)}, past ${TOLERANCE}. ` +
      `A user switching backends would see their build's number change by more than the ` +
      `tolerance allows — which is the one thing Math.fround in damage.ts exists to prevent.`,
  );
  process.exit(1);
}

console.log(
  `CPU and GPU agree: ${identical}/${cases.length} bit-identical, ` +
    `worst ${backendWorst.toExponential(3)}`,
);
process.exit(0);
