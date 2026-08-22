// C.3 — the browser kernel against the differential harness.
//
// DESIGN §6 accepts a second damage chain only if a gate binds it to the first. This is that
// gate: 2,000 generated cases sweeping the input surface, each carrying the Python chain's
// answer, and the chain is pinned to gcsim at 1.3e-8 by `backend/tests/crossval`.
//
// A standalone Node script rather than a vitest spec, for the same reason the gcsim verifiers
// are: it reads a fixture from disk, and Angular's test builder targets the browser where
// `node:fs` does not exist. Node 24 strips types, so this imports the kernel source directly
// and there is no build artifact to go stale between the code and its gate.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { computeDamage, resolveStat } from '../src/app/sim/damage.ts';

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), '..');
const CASES = join(FRONTEND, '..', 'backend', 'tests', 'fixtures', 'kernel', 'cases.json');

/** `docs/CROSSVAL_gcsim.md`, and `backend/tests/unit/test_f32_tolerance.py`. */
const TOLERANCE = 1e-6;

const SCALING = {
  atk: ['base_atk', 'atk_pct', 'flat_atk'],
  hp: ['base_hp', 'hp_pct', 'flat_hp'],
  def: ['base_def', 'def_pct', 'flat_def'],
};

function scalingValue(c) {
  if (c.hit.scaling_stat === 'elemental_mastery') return c.stats.elemental_mastery;
  const [base, pct, flat] = SCALING[c.hit.scaling_stat];
  return resolveStat(c.stats[base], c.stats[pct], c.stats[flat]);
}

function run(c) {
  return computeDamage({
    hit: {
      multiplier: c.hit.multiplier,
      scalingStat: c.hit.scaling_stat,
      flatDamage: c.hit.flat_damage,
      baseDamageBonus: c.hit.base_damage_bonus,
      amplifying: c.hit.amplifying,
      reactionBonus: c.hit.reaction_bonus,
    },
    scalingValue: scalingValue(c),
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
}

const { cases } = JSON.parse(readFileSync(CASES, 'utf8'));

// A differential gate with no cases passes trivially — the one way this could go green while
// proving nothing. Same guard the gcsim config verifier has, for the same reason.
if (!Array.isArray(cases) || cases.length < 1000) {
  console.error(`expected at least 1000 cases, found ${cases?.length ?? 0}`);
  process.exit(1);
}

const failures = [];
let worst = 0;
for (const c of cases) {
  const want = c.expected.expected;
  const got = run(c);
  const rel = want === 0 ? Math.abs(got) : Math.abs(got - want) / Math.abs(want);
  if (rel > worst) worst = rel;
  if (rel > TOLERANCE) failures.push({ id: c.id, got, want, rel });
}

if (failures.length > 0) {
  // Worst-first, not first-found: one failure is a typo, a hundred sharing a shape is a
  // formula, and only the aggregate shows which.
  failures.sort((a, b) => b.rel - a.rel);
  console.error(`${failures.length}/${cases.length} cases diverge past ${TOLERANCE}:`);
  for (const f of failures.slice(0, 5)) {
    console.error(`  ${f.id}: got ${f.got} want ${f.want} (rel ${f.rel.toExponential(3)})`);
  }
  process.exit(1);
}

console.log(
  `kernel matches the Python chain on all ${cases.length} cases ` +
    `(worst ${worst.toExponential(3)}, tolerance ${TOLERANCE.toExponential(0)})`,
);

// The tolerance should be generous, not load-bearing. If the worst case ever creeps up to it,
// the next rounding change anywhere breaks the gate — and the temptation is to widen it.
if (worst > TOLERANCE / 2) {
  console.error(
    `worst case ${worst.toExponential(3)} is more than half the tolerance. Re-derive it from ` +
      `the measurement (docs/CROSSVAL_gcsim.md) rather than widening it.`,
  );
  process.exit(1);
}
