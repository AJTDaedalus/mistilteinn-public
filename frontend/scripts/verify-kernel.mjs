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

import {
  additiveFlat, computeDamage, critMultiplier, defMultiplier, lunarDamage, resMultiplier,
  resolveStat, transformativeDamage,
} from '../src/app/sim/damage.ts';

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), '..');
const CASES = join(FRONTEND, '..', 'backend', 'tests', 'fixtures', 'kernel', 'cases.json');

/** `docs/CROSSVAL_gcsim.md`, and `backend/tests/unit/test_f32_tolerance.py`. */
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
function extraTerms(c) {
  return c.hit.extra_terms ?? [];
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

// ── Reactions (math-fallback P3) ─────────────────────────────────────────────────────────
//
// The same gate for `damage.ts`'s reaction terms: `reaction_cases.json`, written by
// `backend/scripts/kernel/generate_reaction_cases.py` from `reactions.py`, which
// `tests/crossval/test_reaction_crossval.py` pins to gcsim. Transformative and Lunar cases call
// their functions directly; an additive case is a whole talent hit through `computeDamage`, so
// the flat term's place in the chain is held, not just its value.
const REACTIONS = join(
  FRONTEND, '..', 'backend', 'tests', 'fixtures', 'kernel', 'reaction_cases.json',
);

function additiveInputs(c, additive) {
  return {
    hit: {
      multiplier: c.hit.multiplier, scalingStat: c.hit.scaling_stat,
      flatDamage: c.hit.flat_damage, baseDamageBonus: c.hit.base_damage_bonus,
      amplifying: null, reactionBonus: c.hit.reaction_bonus, additive,
    },
    reactionLevelMultiplier: c.level_base,
    scalingValue: c.scaling_value,
    dmgBonus: c.dmg_bonus,
    critRate: c.crit_rate,
    critDmg: c.crit_dmg,
    elementalMastery: c.elemental_mastery,
    characterLevel: c.character_level,
    target: {
      level: c.enemy_level, resistance: c.resistance, defReduction: c.def_reduction,
      defIgnore: c.def_ignore,
    },
  };
}

function runReaction(c) {
  switch (c.kind) {
    case 'transformative':
      return transformativeDamage({
        reaction: c.reaction, levelBase: c.level_base, elementalMastery: c.elemental_mastery,
        resistance: c.resistance, reactionBonus: c.reaction_bonus, critRate: c.crit_rate,
        critDmg: c.crit_dmg,
      });
    case 'lunar':
      return lunarDamage({
        reaction: c.reaction, levelBase: c.level_base, elementalMastery: c.elemental_mastery,
        resistance: c.resistance, critRate: c.crit_rate, critDmg: c.crit_dmg,
        reactionBonus: c.reaction_bonus, baseDmgBonus: c.base_dmg_bonus,
      });
    case 'additive':
      return computeDamage(additiveInputs(c, c.reaction));
    default:
      throw new Error(`unknown reaction case kind ${c.kind}`);
  }
}

const reactionCases = JSON.parse(readFileSync(REACTIONS, 'utf8')).cases;
if (!Array.isArray(reactionCases) || reactionCases.length < 900) {
  console.error(`expected at least 900 reaction cases, found ${reactionCases?.length ?? 0}`);
  process.exit(1);
}
const reactionFailures = [];
let reactionWorst = 0;
for (const c of reactionCases) {
  const got = runReaction(c);
  const rel = c.expected === 0 ? Math.abs(got) : Math.abs(got - c.expected) / Math.abs(c.expected);
  if (rel > reactionWorst) reactionWorst = rel;
  if (rel > TOLERANCE) reactionFailures.push({ id: c.id, got, want: c.expected, rel });
}

// A planted error must fail: the additive flat placed **outside** the DMG bonus is the ordering
// mistake a reimplementation makes, and the gate has to be able to see it.
const planted = reactionCases.find((c) => c.kind === 'additive' && c.dmg_bonus > 0.2);
const plantedInputs = additiveInputs(planted, null);
const outside = computeDamage(plantedInputs)
  + additiveFlat(planted.reaction, planted.level_base, planted.elemental_mastery,
    planted.hit.reaction_bonus)
  * defMultiplier(planted.character_level, planted.enemy_level, planted.def_reduction,
    planted.def_ignore)
  * resMultiplier(planted.resistance) * critMultiplier(planted.crit_rate, planted.crit_dmg);
if (Math.abs(outside - planted.expected) / planted.expected <= TOLERANCE) {
  console.error('an additive flat outside the DMG bonus still matches: the gate cannot see it');
  process.exit(1);
}

if (reactionFailures.length > 0) {
  reactionFailures.sort((a, b) => b.rel - a.rel);
  console.error(`${reactionFailures.length}/${reactionCases.length} reaction cases diverge:`);
  for (const r of reactionFailures.slice(0, 5)) {
    console.error(`  ${r.id}: got ${r.got} want ${r.want} (rel ${r.rel.toExponential(3)})`);
  }
  process.exit(1);
}
console.log(
  `reaction terms match the Python chain on all ${reactionCases.length} cases ` +
    `(worst ${reactionWorst.toExponential(3)}, tolerance ${TOLERANCE.toExponential(0)})`,
);
if (reactionWorst > TOLERANCE / 2) {
  console.error(`worst reaction case ${reactionWorst.toExponential(3)} is past half the tolerance`);
  process.exit(1);
}
