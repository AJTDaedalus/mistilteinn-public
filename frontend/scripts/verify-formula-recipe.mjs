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
    context: {
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
  const recipe = synthesizeRecipe(rows, sources, team, f.conditionals);
  if (recipe.meta.formula?.kind !== 'formula-estimate') throw new Error('no provenance marker');
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

  // Math-fallback P2, task 10 — **a planted wrong kit buff must fail.** Every kit effect 1 %
  // off, and the classic self-buff mistake (the subject's own EM frozen at his zero-artifact
  // value instead of moving with the candidate), each have to leave the tolerance.
  const kits = f.sources.filter((s) => s.id.startsWith('kit:'));
  if (kits.length > 0) {
    const planted = (mutate) => f.sources.map((s) => (s.id.startsWith('kit:')
      ? { ...s, bonus: { ...s.bonus, effects: s.bonus.effects.map(mutate) } }
      : s));
    // The cap too, or a figure past its cap would not notice (DECISIONS §40).
    const off = score(f, planted((e) => ({
      ...e, value: e.value * 1.01, ...(e.cap != null ? { cap: e.cap * 1.01 } : {}),
    })));
    if (Math.abs(off - f.expected) / f.expected <= TOLERANCE) {
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
      flat_damage_from_atk: ['flat_damage', 'atk'], flat_damage_from_hp: ['flat_damage', 'hp'],
      flat_damage_from_def: ['flat_damage', 'def'], flat_damage_from_em: ['flat_damage', 'em'],
      flat_atk_from_def: ['flat_atk', 'def'], flat_atk_from_hp: ['flat_atk', 'hp'],
    };
    const zero = (stat) => (stat === 'em' ? f.base.elemental_mastery
      : f.base[`base_${stat}`] * (1 + f.base[`${stat}_pct`]) + f.base[`flat_${stat}`]);
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

if (failures.length > 0) {
  console.error(`formula recipe diverges from the GO-cited figures: ${failures.join(', ')}`);
  process.exit(1);
}
console.log(
  `formula recipe matches all ${data.fixtures.length} GO-cited fixtures `
    + `(worst ${worst.toExponential(3)}, tolerance ${TOLERANCE.toExponential(0)})`,
);
