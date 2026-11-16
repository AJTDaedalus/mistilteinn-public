// Math-fallback P1 — the synthetic recipe against the GO-cited fixtures.
//
// `backend/tests/unit/test_go_formula_fixtures.py` works each figure by hand from Genshin
// Optimizer's formula (the comparator for the formula estimate, `docs/DECISIONS.md` §38) with
// this repo's own numbers, and checks that the committed file matches what the Python
// resolver gives for the set and resonance buffs. This script holds the **browser's**
// application of those buffs to the same figures: `formula-recipe.ts` synthesises the recipe,
// `recipe-eval.ts` scores the fixture's artifacts against it, and the total must equal
// `expected` — the figure with gcsim's 2.78 EM coefficient, which this repo follows. GO's own
// 25/9 figure is reported beside it, never asserted.
//
// A Node script rather than a vitest spec for the reason `verify-kernel.mjs` gives: it reads a
// fixture from disk, and Angular's test builder targets the browser.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  energyAt, fieldMultiplier, flatSourceAt, particlesPerRotation, particleValue, raidenA4Multiplier,
  requiredEnergyRecharge,
} from '../src/app/sim/formula-energy.ts';
import { synthesizeRecipe } from '../src/app/sim/formula-recipe.ts';
import { cappedAmount } from '../src/app/sim/recipe.ts';
import { evaluateRecipe } from '../src/app/sim/recipe-eval.ts';
import { candidateStatsFrom } from '../src/app/sim/recipe-search.ts';

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), '..');
const FIXTURE = join(FRONTEND, '..', 'backend', 'tests', 'fixtures', 'formula', 'go_fixtures.json');

/** f32 kernel terms (`damage.ts`) against Python's f64 hand-worked figure: `CROSSVAL_gcsim.md`. */
const TOLERANCE = 1e-6;

const data = JSON.parse(readFileSync(FIXTURE, 'utf8'));
if (!Array.isArray(data.fixtures) || data.fixtures.length < 3) {
  console.error(`expected at least 3 fixtures, found ${data.fixtures?.length ?? 0}`);
  process.exit(1);
}

function score(f, sources) {
  const rows = f.rows.map((r) => ({
    id: r.id,
    label: r.label,
    move: r.move,
    // The talent row, for a row-scoped kit buff (Nahida's burst bonus on Tri-Karma).
    hit: r.hit ?? null,
    count: r.count,
    conditionals: r.conditionals,
    // A reaction row and an additive talent row (math-fallback P3).
    reaction: r.reaction ?? null,
    additive: r.additive ?? null,
    // A weapon proc row (owner approval 2026-11-14, DECISIONS §45).
    proc: r.proc ?? null,
    context: {
      reactionLevelMultiplier: data.reaction_level_multiplier,
      base: f.base,
      hit: {
        multiplier: r.multiplier,
        scalingStat: r.scaling_stat,
        // A mixed-stat row (`ATK + EM`) is one hit with several terms (P0, task 1).
        extraTerms: r.extra_terms ?? [],
        flatDamage: 0,
        baseDamageBonus: 0,
        amplifying: r.amplifying,
        reactionBonus: 0,
      },
      target: {
        level: data.target.level,
        resistance: data.target.resistance,
        defReduction: data.target.def_reduction,
        defIgnore: data.target.def_ignore,
      },
      characterLevel: data.character_level,
      // A row may name its own channel (a Physical normal attack beside a Pyro burst).
      dmgBonusQuantity: `${r.channel ?? f.channel}_dmg_bonus`,
    },
  }));
  const team = {
    element: f.team.element, weaponType: f.team.weapon_type, memberElements: f.team.member_elements,
  };
  // A kit's talent-level raise (DECISIONS §42): the subject's rows at the raised levels.
  const recipe = synthesizeRecipe(
    rows, sources, team, f.conditionals, [], undefined, f.raised_talents ?? [],
  );
  if (recipe.meta.formula?.kind !== 'formula-estimate') throw new Error('no provenance marker');
  // The GO fixtures state their energy assumption explicitly: none. GO has no energy model, so
  // no fixture may carry one — and the estimate's default mode (Wait, owner 2026-11-15) cannot
  // move a figure that has no energy model to apply it to.
  if (recipe.meta.formulaEnergy !== undefined) {
    throw new Error(`${f.name} carries an energy model; the GO fixtures are scored without one`);
  }
  return evaluateRecipe(recipe, candidateStatsFrom([f.artifacts, ...f.set_pools]));
}

const failures = [];
let worst = 0;
for (const f of data.fixtures) {
  const got = score(f, f.sources);
  const rel = Math.abs(got - f.expected) / Math.abs(f.expected);
  worst = Math.max(worst, rel);
  const vsGo = Math.abs(got - f.go_value) / Math.abs(f.go_value);
  console.log(
    `${f.name}: ${got.toFixed(4)} (expected ${f.expected.toFixed(4)}, rel ${rel.toExponential(2)}; `
      + `GO ${f.go_value.toFixed(4)}, rel ${vsGo.toExponential(2)} — ${f.divergence})`,
  );
  if (rel > TOLERANCE) failures.push(f.name);

  // Guard the guard: without its buffs the same fixture must miss, or it proves nothing.
  if (f.sources.length > 0) {
    const bare = score(f, []);
    if (Math.abs(bare - f.expected) / f.expected < 1e-3) {
      failures.push(`${f.name} (passes with no buffs at all)`);
    }
  }

  // Task 11, fourth batch — a row-scoped kit buff (Nahida's burst bonus on Tri-Karma) must
  // depend on the row naming its talent row: unnamed, it is skipped and the figure must miss.
  if (f.rows.some((r) => r.hit)) {
    const unnamed = score({ ...f, rows: f.rows.map(({ hit: _hit, ...r }) => r) }, f.sources);
    if (Math.abs(unnamed - f.expected) / f.expected <= TOLERANCE) {
      failures.push(`${f.name} (passes with its row-scoped buff unscoped)`);
    }
  }

  // A kit's talent-level raise (DECISIONS §42) — **the raised rows dropped** must miss: the
  // row's own multiplier is the unraised one, so a figure that passes without them is not
  // checking the raise at all.
  if (f.raised_talents !== undefined) {
    if (!f.sources.some((s) => s.bonus.effects.some((e) => e.stat === 'talent_level'))) {
      failures.push(`${f.name} (carries raised rows but no talent-level raise)`);
    }
    const unraised = score({ ...f, raised_talents: [] }, f.sources);
    if (Math.abs(unraised - f.expected) / f.expected <= TOLERANCE) {
      failures.push(`${f.name} (passes with its talent-level raise unread)`);
    }
  }

  // Math-fallback P2, task 10 — **a planted wrong kit buff must fail.** Every kit effect 1 %
  // off, and the classic self-buff mistake (the subject's own EM frozen at his zero-artifact
  // value instead of moving with the candidate), each have to leave the tolerance.
  // A weapon passive (P3, task 12) is planted exactly as a kit is: same vocabulary, same
  // resolution in the wielder's context, same per-candidate conversions on the subject's own.
  const isKit = (s) => s.id.startsWith('kit:') || s.id.startsWith('weapon:');
  const kits = f.sources.filter(isKit);
  if (kits.length > 0) {
    const planted = (mutate) => f.sources.map((s) => (isKit(s)
      ? { ...s, bonus: { ...s.bonus, effects: s.bonus.effects.map(mutate) } }
      : s));
    // The cap too, or a figure past its cap would not notice (DECISIONS §40).
    const off = score(f, planted((e) => ({
      ...e, value: e.value * 1.01, ...(e.cap != null ? { cap: e.cap * 1.01 } : {}),
    })));
    if (f.kit_must_not_reach) {
      // The kit is there to prove it does **not** reach these rows (a DMG% on a reaction
      // row, P3): moving every one of its values must change nothing.
      if (Math.abs(off - got) / got > TOLERANCE) {
        failures.push(`${f.name} (a kit buff that must not reach the rows moved the figure)`);
      }
    } else if (Math.abs(off - f.expected) / f.expected <= TOLERANCE) {
      failures.push(`${f.name} (a kit buff 1% off still passes)`);
    }
    // Task 11 and the capped conversions (DECISIONS §40) — **the classic self-buff mistake**:
    // a conversion of the subject's own stat frozen at the zero-artifact build instead of moving
    // with the candidate. Kazuha's EM, Valeriy's/Kachina's/Zhongli's flat damage, Noelle's ATK
    // from DEF, and the capped ones: Hu Tao's ATK from HP, Clorinde's A1, Nahida's, Furina's,
    // Alhaitham's and Tighnari's A4. Each frozen conversion must leave the tolerance — **where it
    // reaches the fixture's row at all**: Xianyun's plunge-scoped A4 rides on her own kit beside
    // a skill row it never touches, and freezing a term that is not there proves nothing.
    const frozenAs = {
      dmg_bonus_from_em: ['dmg_bonus', 'em'], dmg_bonus_from_hp: ['dmg_bonus', 'hp'],
      crit_rate_from_em: ['crit_rate', 'em'],
      crit_rate_from_hp: ['crit_rate', 'hp'], crit_dmg_from_hp: ['crit_dmg', 'hp'],
      flat_damage_from_atk: ['flat_damage', 'atk'], flat_damage_from_hp: ['flat_damage', 'hp'],
      flat_damage_from_def: ['flat_damage', 'def'], flat_damage_from_em: ['flat_damage', 'em'],
      flat_atk_from_def: ['flat_atk', 'def'], flat_atk_from_hp: ['flat_atk', 'hp'],
      // The wielder conversions (owner approval 2026-11-14, DECISIONS §45).
      atk_pct_from_er: ['atk_pct', 'er'], em_from_hp: ['elemental_mastery', 'hp'],
      flat_atk_from_em: ['flat_atk', 'em'], dmg_bonus_from_def: ['dmg_bonus', 'def'],
    };
    const zero = (stat) => {
      if (stat === 'em') return f.base.elemental_mastery;
      if (stat === 'er') return f.base.energy_recharge;
      return f.base[`base_${stat}`] * (1 + f.base[`${stat}_pct`]) + f.base[`flat_${stat}`];
    };
    const passes = (got) => Math.abs(got - f.expected) / f.expected <= TOLERANCE;
    const converting = (e) => e.stat in frozenAs;
    if (kits.some((s) => s.bonus.effects.some(converting))) {
      const without = score(f, planted((e) => (converting(e) ? { ...e, value: 0 } : e)));
      if (!passes(without)) {
        const frozen = score(f, planted((e) => {
          if (!converting(e)) return e;
          const [stat, from] = frozenAs[e.stat];
          // The capped amount at the zero-artifact stat, as a constant. Under a `per` the cap
          // binds the stacked total, which a constant per stack cannot say: frozen uncapped.
          const counted = e.per ? e.value * zero(from)
            : cappedAmount(e.value, zero(from), e.threshold ?? undefined, e.cap ?? undefined);
          const { cap: _cap, threshold: _threshold, ...rest } = e;
          return { ...rest, stat, value: counted };
        }));
        if (passes(frozen)) failures.push(`${f.name} (a frozen self conversion still passes)`);
      }
    }

    // The capped conversions (DECISIONS §40) — **the cap ignored** must fail on a fixture whose
    // build is past it, and must change nothing on one below it: the fixture states which, so
    // a "past the cap" figure that never reaches the cap is caught as mislabelled too.
    if (f.cap_state !== undefined) {
      const capped = (e) => converting(e) && e.cap != null;
      if (!kits.some((s) => s.bonus.effects.some(capped))) {
        failures.push(`${f.name} (states a cap but carries no capped conversion)`);
      }
      const uncapped = score(f, planted((e) => (capped(e) ? { ...e, cap: null } : e)));
      if (f.cap_state === 'past' && passes(uncapped)) {
        failures.push(`${f.name} (past its cap, and ignoring the cap still passes)`);
      }
      if (f.cap_state === 'below' && !passes(uncapped)) {
        failures.push(`${f.name} (stated below its cap, but the cap binds)`);
      }
    }
  }
}

for (const f of data.fixtures) {
  // GO's non-stacking buffs (DECISIONS §45): with the names stripped every source applies, and
  // a fixture stating a contested family must then miss — or it is not checking the rule.
  if (f.non_stack !== undefined) {
    const stripped = f.sources.map((s) => ({
      ...s, bonus: { ...s.bonus, effects: s.bonus.effects.map(({ non_stack: _n, ...e }) => e) },
    }));
    const both = score(f, stripped);
    if (Math.abs(both - f.expected) / f.expected <= TOLERANCE) {
      failures.push(`${f.name} (passes with every non-stacking buff applied)`);
    }
    // **The stronger applies** (owner ruling 2026-11-15, DECISIONS §46), and GO's key order is
    // only its tie-break: reversing the keys must change nothing on a fixture with no tie …
    const ranks = f.sources.map((s) => s.stack_rank).filter(Boolean).sort();
    const swapped = new Map(ranks.map((r, i) => [r, ranks[ranks.length - 1 - i]]));
    const reversed = f.sources.map((s) => (s.stack_rank
      ? { ...s, stack_rank: swapped.get(s.stack_rank) } : s));
    const flipped = score(f, reversed);
    if (f.non_stack_rule === 'stronger'
      && Math.abs(flipped - f.expected) / f.expected > TOLERANCE) {
      failures.push(`${f.name} (the key order moved a figure the stronger buff decides)`);
    }
    // … and GO's own rule — only the wielder whose key sorts first writes the family — must
    // miss, or the fixture is not showing the ruling at all.
    const first = ranks[0];
    const goRule = f.sources.map((s) => (s.stack_rank && s.stack_rank !== first
      ? { ...s, bonus: { ...s.bonus, effects: s.bonus.effects.filter(
        (e) => e.non_stack !== f.non_stack) } }
      : s));
    const asGo = score(f, goRule);
    if (Math.abs(asGo - f.expected) / f.expected <= TOLERANCE) {
      failures.push(`${f.name} (passes under GO's key-order rule too)`);
    }
  }
  // A proc row (DECISIONS §45): the proc's multiplier 1% off must miss.
  if (f.rows.some((r) => r.proc)) {
    const off = f.sources.map((s) => (s.procs
      ? { ...s, procs: s.procs.map((p) => ({ ...p, multiplier: p.multiplier * 1.01 })) } : s));
    const got = score(f, off);
    if (Math.abs(got - f.expected) / f.expected <= TOLERANCE) {
      failures.push(`${f.name} (a proc 1% off still passes)`);
    }
  }
}

// ── Energy (math-fallback P3, task 14) ────────────────────────────────────────────────────
//
// GO has no energy model (ER is a user-set floor there), so the oracle is gcsim's own energy
// events: a native sample of the owner's National team at the pin
// (`backend/tests/fixtures/formula/energy/PROVENANCE.md`). Every particle event must be what
// `formula-energy.ts` says one is worth, and Xiangling's steady rotation — built from the
// particle table, not from the log — must bank exactly what her fourth drain reads.
const ENERGY = join(FRONTEND, '..', 'backend', 'tests', 'fixtures', 'formula', 'energy',
  'national_energy_sample.json');
const TABLE = join(FRONTEND, '..', 'backend', 'app', 'data', 'formula', 'energy', 'particles.json');
const sample = JSON.parse(readFileSync(ENERGY, 'utf8'));
const table = JSON.parse(readFileSync(TABLE, 'utf8')).characters;
let energyChecked = 0;
for (const e of sample.particles) {
  const ele = e.ele === 'none' ? null : e.ele;
  const got = e.count * particleValue(sample.elements[e.receiver], ele)
    * fieldMultiplier(e.is_active ? 1 : 0, e.party_count) * e.er;
  if (Math.abs(got - e.amt) > 1e-9 * e.amt) {
    failures.push(`energy event ${e.frame}/${e.receiver} (${got} against gcsim's ${e.amt})`);
  }
  energyChecked += 1;
}
const drains = sample.drains.filter((d) => d.character === 'xiangling');
const er = sample.particles.find((e) => e.receiver === 'xiangling').er;
const national = (overrides = {}) => ({
  mode: 'off', cost: 80, element: 'pyro', partyCount: 4, rotationSeconds: 20, flatEnergy: 0,
  drip: null, baseEnergyRecharge: er,
  sources: [
    // The config holds Bennett's skill at level 1: 3 (skill.go:242), not the tap's 2.25.
    { key: 'b', label: 'Bennett', element: 'pyro', particles: 3, onFieldShare: 0, citation: '' },
    // Guoba: the table's 4, two of them caught on field in this rotation (PROVENANCE.md).
    { key: 'g', label: 'Guoba', element: 'pyro', particles: table.Xiangling.sources[0].particles,
      onFieldShare: 0.5, citation: '' },
    { key: 'x', label: 'Xingqiu', element: 'hydro', particles: table.Xingqiu.sources[0].particles,
      onFieldShare: 0, citation: '' },
    { key: 'y', label: 'Yelan', element: 'hydro', particles: table.Yelan.sources[0].particles,
      onFieldShare: 0, citation: '' },
  ],
  ...overrides,
});
const banked = energyAt(national(), er);
if (Math.abs(banked - drains[3].pre_drain) > 1e-9) {
  failures.push(`energy: the closed form banks ${banked}, gcsim's drain reads ${drains[3].pre_drain}`);
}
// gcsim's requirement for that rotation (energy_stats.go:85) is the module's.
if (Math.abs(requiredEnergyRecharge(national()) - 80 / (drains[3].pre_drain / er)) > 1e-12) {
  failures.push('energy: the requirement is not gcsim\'s (cost − flat) / raw');
}
// Plants: each rule broken on its own must miss the drain.
const plants = {
  'every particle caught on field': national({
    sources: national().sources.map((s) => ({ ...s, onFieldShare: 1 })) }),
  'an off-element particle worth a same-element one': national({ element: 'hydro' }),
  'Guoba all off field': national({
    sources: national().sources.map((s) => (s.key === 'g' ? { ...s, onFieldShare: 0 } : s)) }),
};
for (const [name, model] of Object.entries(plants)) {
  if (Math.abs(energyAt(model, er) - drains[3].pre_drain) <= 1e-6) {
    failures.push(`energy plant "${name}" still matches gcsim`);
  }
}

// ── Summons, Favonius and flat refunds (TASKS 14 follow-ups, DECISIONS §48) ───────────────
//
// A second native sample at the pin: Raiden (a Favonius Lance R3), Fischl, Kokomi, Zhongli.
// Every particle event — the Favonius proc's clear particles included — must be what the
// module says, and every Raiden restoration must be `flatSourceAt` with her A4: the row's 2.4
// (burst level 9 in our catalogue) × (1 + 0.006 × whole percent of her ER above 100 %),
// to every member, never times the receiver's ER.
const SUMMON = JSON.parse(readFileSync(join(FRONTEND, '..', 'backend', 'tests', 'fixtures',
  'formula', 'energy', 'summon_energy_sample.json'), 'utf8'));
let summonChecked = 0;
let favoniusChecked = 0;
for (const e of SUMMON.particles) {
  const ele = e.ele === 'none' ? null : e.ele;
  const got = e.count * particleValue(SUMMON.elements[e.receiver], ele)
    * fieldMultiplier(e.is_active ? 1 : 0, e.party_count) * e.er;
  if (Math.abs(got - e.amt) > 1e-9 * e.amt) {
    failures.push(`summon energy event ${e.frame}/${e.receiver}/${e.source} (${got} against ${e.amt})`);
  }
  if (e.source.startsWith('favonius-')) {
    favoniusChecked += 1;
    if (e.count !== 3 || ele !== null) failures.push(`a Favonius drop is not 3 clear: ${e.frame}`);
  }
  summonChecked += 1;
}
const raidenEr = SUMMON.particles.find((e) => e.receiver === 'raidenshogun').er;
const restoration = { key: 'r', label: 'Musou Isshin', energy: 2.4, scaling: 'raiden_a4', citation: '' };
const refunds = SUMMON.flat.filter((e) => e.source === 'raiden-burst');
for (const e of refunds) {
  const got = flatSourceAt(restoration, raidenEr);
  if (Math.abs(got - e.amt) > 1e-12) {
    failures.push(`Raiden's restoration ${e.frame}/${e.receiver}: ${got} against gcsim's ${e.amt}`);
  }
}
// Plants: the A4 read as a continuous 0.6 % per percent, or times the receiver's ER, must miss.
const continuous = 2.4 * (1 + 0.6 * (raidenEr - 1));
if (Math.abs(continuous - refunds[0].amt) <= 1e-9) failures.push('Raiden plant: continuous A4 still matches');
if (Math.abs(2.4 * raidenA4Multiplier(raidenEr) * raidenEr - refunds[0].amt) <= 1e-9) {
  failures.push("Raiden plant: a refund times the receiver's ER still matches");
}
if (refunds.length !== 5 * 4 * 4 || favoniusChecked === 0) { // 5 a burst, 4 bursts, 4 members
  failures.push(`summon sample: ${refunds.length} restorations, ${favoniusChecked} Favonius events`);
}

// ── Refinements (owner rulings 2026-11-15, DECISIONS §49) ──────────────────────────────────
//
// Electro resonance: every `electro-res` event in two native samples is one Electro particle
// valued like any other, never closer than the table's cooldown; #393's 72.58 to Raiden is the
// closed form at 3 procs a rotation and her 8-of-12 on-field share. Yae: her totems drop one
// every `interval`, one totem or three (the shared ICD), and the per-second form counts a totem
// set within one particle of gcsim's 8.
const RES = JSON.parse(readFileSync(join(FRONTEND, '..', 'backend', 'tests', 'fixtures',
  'formula', 'energy', 'electro_res_sample.json'), 'utf8'));
const YAE = JSON.parse(readFileSync(join(FRONTEND, '..', 'backend', 'tests', 'fixtures',
  'formula', 'energy', 'yae_energy_sample.json'), 'utf8'));
const highVoltage = JSON.parse(readFileSync(TABLE, 'utf8')).resonances.electro;
let resonanceChecked = 0;
for (const sample of [SUMMON, RES]) {
  const events = sample.particles.filter((e) => e.source === 'electro-res');
  for (const e of events) {
    const got = highVoltage.particles * particleValue(sample.elements[e.receiver], highVoltage.element)
      * fieldMultiplier(e.is_active ? 1 : 0, e.party_count) * e.er;
    if (e.count !== highVoltage.particles || Math.abs(got - e.amt) > 1e-9 * e.amt) {
      failures.push(`resonance event ${e.frame}/${e.receiver} (${got} against ${e.amt})`);
    }
    resonanceChecked += 1;
  }
  const frames = [...new Set(events.map((e) => e.frame))].sort((a, b) => a - b);
  for (let i = 1; i < frames.length; i += 1) {
    if (frames[i] - frames[i - 1] < highVoltage.cooldown_seconds * 60) {
      failures.push(`resonance procs ${frames[i - 1]} and ${frames[i]} inside the cooldown`);
    }
  }
}
const raidenRes = SUMMON.particles.filter((e) => e.source === 'electro-res'
  && e.receiver === 'raidenshogun');
const resonanceModel = (procs, onFieldShare) => ({
  mode: 'off', cost: 90, element: 'electro', partyCount: 4, rotationSeconds: 25, flatEnergy: 0,
  drip: null, baseEnergyRecharge: 1,
  sources: [{ key: 'resonance:electro', label: 'High Voltage', element: 'electro',
    particles: procs * highVoltage.particles, onFieldShare, citation: '' }],
});
const resTotal = raidenRes.reduce((s, e) => s + e.amt, 0);
const resEr = raidenRes[0].er;
if (Math.abs(4 * energyAt(resonanceModel(3, 8 / 12), resEr) - resTotal) > 1e-9) {
  failures.push(`resonance: 4 rotations bank ${4 * energyAt(resonanceModel(3, 8 / 12), resEr)}, gcsim ${resTotal}`);
}
// Plants: every proc off field, or the cooldown ceiling (5 a rotation), must miss the sample.
for (const [name, model] of [['all off field', resonanceModel(3, 0)],
  ['the ceiling', resonanceModel(25 / highVoltage.cooldown_seconds, 8 / 12)]]) {
  if (Math.abs(4 * energyAt(model, resEr) - resTotal) <= 1e-6) {
    failures.push(`resonance plant "${name}" still matches gcsim`);
  }
}
const [totems] = table['Yae Miko'].sources;
const yaeOwn = YAE.particles.filter((e) => e.receiver === 'yaemiko').map((e) => e.frame);
const secondCast = YAE.casts.filter((c) => c.character === 'yaemiko')[1].frame;
for (const set of [yaeOwn.filter((f) => f < secondCast), yaeOwn.filter((f) => f > secondCast)]) {
  for (let i = 1; i < set.length; i += 1) {
    if (Math.abs(set[i] - set[i - 1] - totems.interval * 60) > 1e-3) {
      failures.push(`Yae: particles ${set[i - 1]} and ${set[i]} are not one interval apart`);
    }
  }
  if (set.length !== 8) failures.push(`Yae: ${set.length} particles for a totem set, not 8`);
}
const perSet = (casts) => particlesPerRotation(totems, casts, 1500 / 60);
if (Math.abs(perSet(3) - perSet(1)) > 1e-12 || Math.abs(perSet(3) - 8) >= 1) {
  failures.push(`Yae: the per-second form counts ${perSet(1)} and ${perSet(3)} against gcsim's 8`);
}
// Plant: totems multiplied by casts (no shared ICD) must miss gcsim's three-totem count.
if (Math.abs(particlesPerRotation({ ...totems, shared_icd: false }, 3, 25) - 8) < 1) {
  failures.push('Yae plant: an unshared ICD still matches gcsim');
}
for (const e of YAE.particles) {
  const got = e.count * particleValue(YAE.elements[e.receiver], e.ele)
    * fieldMultiplier(e.is_active ? 1 : 0, e.party_count) * e.er;
  if (Math.abs(got - e.amt) > 1e-9 * e.amt) failures.push(`Yae event ${e.frame}/${e.receiver}`);
}

// ── Small calls (owner rulings 2026-11-15, DECISIONS §50) ──────────────────────────────────
//
// Electro resonance's default is the samples' rate (`default_procs_per_second`): at a 25 s
// rotation it is #393's 3 procs, so the closed form at that default reproduces Raiden's 72.58.
// The drip: every `drop` particle in a native sample with the drip on is a clear particle
// valued at the active member's full share. Venti's absorbed 15 and the counted constellation
// refunds: gcsim's flat energy per receiver is the table's amount × count × triggers.
if (Math.abs(4 * energyAt(resonanceModel(highVoltage.default_procs_per_second * 25, 8 / 12), resEr)
  - resTotal) > 1e-9) {
  failures.push(`resonance default rate: ${highVoltage.default_procs_per_second} a second does not give gcsim's 3 procs`);
}
const fixture = (name) => JSON.parse(readFileSync(join(FRONTEND, '..', 'backend', 'tests',
  'fixtures', 'formula', 'energy', name), 'utf8'));
const VENTI = fixture('venti_cons_energy_sample.json');
const KLEE = fixture('klee_cons_energy_sample.json');
const fullTable = JSON.parse(readFileSync(TABLE, 'utf8'));
const drops = VENTI.particles.filter((e) => e.source === 'drop');
for (const e of drops) {
  const got = particleValue(VENTI.elements[e.receiver], null)
    * fieldMultiplier(e.is_active ? 1 : 0, e.party_count) * e.er;
  if (Math.abs(got - e.amt) > 1e-9 * e.amt) failures.push(`drip event ${e.frame}/${e.receiver}`);
}
const burstsOf = (sample, who) => sample.casts.filter(
  (c) => c.character === who && c.action === 'burst').length;
const gotFlat = (sample, source, receiver) => sample.flat
  .filter((f) => f.source === source && f.receiver === receiver).reduce((s, f) => s + f.amt, 0);
const flatChecks = [];
const absorbedRefund = fullTable.characters.Venti.refunds.find((r) => r.recipients === 'absorbed');
const carried = new Set(Object.entries(VENTI.elements).filter(([w]) => w !== 'venti').map(([, e]) => e));
const absorbed = absorbedRefund.absorbs.find((e) => carried.has(e));
for (const [who, element] of Object.entries(VENTI.elements)) {
  if (who === 'venti') continue;
  const expected = element === absorbed
    ? flatSourceAt({ energy: absorbedRefund.amount * absorbedRefund.count * burstsOf(VENTI, 'venti'),
      scaling: 'none' }, 1) : 0;
  flatChecks.push([`venti-a4 → ${who}`, expected, gotFlat(VENTI, 'venti-a4', who)]);
}
const cons = (name) => fullTable.constellation_refunds[name].refunds.find((r) => r.basis === 'kit');
for (const [sample, who, name, source] of [[VENTI, 'kaeya', 'Kaeya', 'kaeya-c6'],
  [VENTI, 'thoma', 'Thoma', 'thoma-c4'], [KLEE, 'diona', 'Diona', 'diona-c1']]) {
  const r = cons(name);
  flatChecks.push([source, r.amount * r.count * burstsOf(sample, who), gotFlat(sample, source, who)]);
}
const klee = cons('Klee');
for (const who of Object.keys(KLEE.elements)) {
  const expected = who === 'klee' ? 0 : klee.amount * klee.count * burstsOf(KLEE, 'klee');
  flatChecks.push([`klee-c6 → ${who}`, expected, gotFlat(KLEE, 'klee-c6', who)]);
}
for (const [what, expected, got] of flatChecks) {
  if (Math.abs(expected - got) > 1e-9) failures.push(`${what}: table ${expected}, gcsim ${got}`);
}
// Plants: Venti absorbing Kaeya's Cryo, or Klee's C6 reaching Klee too, must miss gcsim.
if (gotFlat(VENTI, 'venti-a4', 'kaeya') === absorbedRefund.amount * burstsOf(VENTI, 'venti')) {
  failures.push('Venti plant: a Cryo absorption still matches gcsim');
}
if (gotFlat(KLEE, 'klee-c6', 'klee') === klee.amount * klee.count * burstsOf(KLEE, 'klee')) {
  failures.push('Klee plant: a refund to Klee herself still matches gcsim');
}

if (failures.length > 0) {
  console.error(`formula recipe diverges from the GO-cited figures: ${failures.join(', ')}`);
  process.exit(1);
}
console.log(
  `formula recipe matches all ${data.fixtures.length} GO-cited fixtures `
    + `(worst ${worst.toExponential(3)}, tolerance ${TOLERANCE.toExponential(0)})`,
);
console.log(
  `energy model matches gcsim's ${energyChecked} particle events and Xiangling's drain `
    + `(${banked.toFixed(5)} banked; 3 plants miss)`,
);
console.log(
  `summons, Favonius and refunds match gcsim's ${summonChecked} particle events `
    + `(${favoniusChecked} Favonius) and ${refunds.length} Raiden restorations (2 plants miss)`,
);
console.log(
  `Electro resonance matches gcsim's ${resonanceChecked} events and Raiden's ${resTotal.toFixed(4)} `
    + `(2 plants miss); Yae's totems one per ${(totems.interval * 60).toFixed(0)} frames, `
    + `${YAE.particles.length} events (1 plant misses)`,
);
console.log(
  `small calls: the resonance's default rate gives gcsim's 3 procs; ${drops.length} drip events `
    + `exact; ${flatChecks.length} flat totals (Venti absorbing ${absorbed}, Kaeya, Thoma, Diona, `
    + 'Klee) equal the table (2 plants miss)',
);
