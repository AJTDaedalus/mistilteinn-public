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
    count: r.count,
    conditionals: r.conditionals,
    context: {
      base: f.base,
      hit: {
        multiplier: r.multiplier,
        scalingStat: r.scaling_stat,
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
      dmgBonusQuantity: `${f.channel}_dmg_bonus`,
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
}

if (failures.length > 0) {
  console.error(`formula recipe diverges from the GO-cited figures: ${failures.join(', ')}`);
  process.exit(1);
}
console.log(
  `formula recipe matches all ${data.fixtures.length} GO-cited fixtures `
    + `(worst ${worst.toExponential(3)}, tolerance ${TOLERANCE.toExponential(0)})`,
);
