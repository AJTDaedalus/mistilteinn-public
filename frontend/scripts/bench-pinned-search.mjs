/**
 * What a **pinned** recipe search costs, against the free search it constrains.
 *
 *     node --import ./scripts/ts-resolve.mjs scripts/bench-pinned-search.mjs [inventory.json]
 *
 * `docs/TASKS_artifact_ranking.md` A.10, `docs/DESIGN_artifact_ranking.md` OQ-A9.
 *
 * ## Why this exists rather than an inference
 *
 * `DESIGN_artifact_ranking.md` §7 records a cost that was **inferred and wrong by a factor of
 * thirty** — ~14 s guessed for 59 candidates from a native all-cores figure, against 7.7 minutes
 * measured on the committed browser build. `bench-search.mjs` states the rule this file obeys:
 * *"a borrowed timing is a fabricated measurement."* The free search's cost is not the pinned
 * search's cost, and the difference is the whole question, so it is measured.
 *
 * ## What pinning actually changes
 *
 * One slot's bucket becomes a single candidate, so the Cartesian product loses that slot's
 * factor entirely — the walk is the product of the *other four*. That is the arithmetic; whether
 * it lands inside an interactive budget over a real 2,370-piece inventory is what this measures.
 *
 * **Node, not a browser**, for the reason `bench-search.mjs` gives: the hot loop has no WASM, no
 * DOM and one small allocation per combination, so both run the same V8 arithmetic. That is an
 * argument rather than a proof, which is why the figure is reported as an order of magnitude
 * rather than pasted into a constant.
 */

import { readFileSync } from 'node:fs';

import { SLOTS, bucketBySlot, paretoFilter } from '../src/app/sim/search.ts';
import { liveQuantitiesFor, searchRecipe } from '../src/app/sim/recipe-search.ts';

/** One hit, the ordinary ATK-scaling case, repeated to a realistic rotation length. */
const hit = () => ({
  mine: true,
  owner: 0,
  abil: 'x', attackTag: 1, element: 'hydro', talent: 2, scaling: 'atk', flatDamage: 0,
  calibratedScaling: 1000, bonusDmg: 0, critRate: 0.05, critDmg: 0.5,
  conversions: {},
  calibratedBase: { atk: 1000, hp: 20000, def: 800 },
  calibratedPercent: { atk: 0, hp: 0, def: 0 },
  calibratedFlat: { atk: 0, hp: 0, def: 0 },
  defMultiplier: 0.5, resMultiplier: 0.9, ampMultiplier: 1, gcsimAverageDamage: 900,
});

/**
 * 245 hits — the size of a real decomposed rotation.
 *
 * `RESEARCH_gcsim_calibration.md` §2 measures the owner's own rotation at that length, and
 * `RESEARCH_recipe_cost.md` uses the same figure. A shorter recipe would understate the cost by
 * the ratio of the lengths and there would be nothing on the page to say so.
 */
const HITS = 245;
const recipe = {
  hits: Array.from({ length: HITS }, hit),
  seed: '1',
  meta: {
    seed: '1', staleConversions: [], characters: [], unstable: [],
    calibratedSetIds: [], minimumEnergyRecharge: null,
  },
};
const recipes = { byFourPieceSet: new Map(), noFourPiece: recipe };

const QUANTITIES = ['flat_atk', 'atk_pct', 'crit_rate', 'crit_dmg', 'hydro_dmg_bonus'];

/** `n` pieces per slot, spread so the Pareto layer keeps most of them. */
function synthetic(n) {
  const out = [];
  for (const [slotIndex, slot] of SLOTS.entries()) {
    for (let i = 0; i < n; i += 1) {
      const stats = {};
      for (const [q, quantity] of QUANTITIES.entries()) {
        // Coprime strides, so few pieces dominate each other and the Pareto layer keeps a
        // realistic bucket. A tighter spread left five per slot and made the walk trivial.
        stats[quantity] = ((i * 17 + q * 41 + slotIndex * 7) % 97) / 100;
      }
      // **Sets are spread across five ids, not left uniform.** The first draft gave every
      // piece `setId: 0`, so every combination formed a 4-piece of set 0 — a state the recipe
      // map has no entry for — and the walk evaluated **nothing**. It reported a time, and the
      // time was of an empty loop. `evaluated` is printed below for exactly that reason.
      out.push({ id: `${slot}-${i}`, slot, setId: i % 5, stats });
    }
  }
  return out;
}

function fromInventory(path) {
  const raw = JSON.parse(readFileSync(path, 'utf8'));
  return raw.artifacts
    .filter((a) => SLOTS.includes(a.slot))
    .map((a) => ({ id: a.id, slot: a.slot, setId: a.set_id ?? 0, stats: a.stats }));
}

function capped(candidates, perSlot) {
  const bySlot = new Map();
  for (const c of candidates) {
    const bucket = bySlot.get(c.slot) ?? [];
    if (bucket.length < perSlot) bucket.push(c);
    bySlot.set(c.slot, bucket);
  }
  return [...bySlot.values()].flat();
}

function time(run) {
  run();                                    // warm V8, or the first run pays for the JIT
  const started = process.hrtime.bigint();
  const result = run();
  return { seconds: Number(process.hrtime.bigint() - started) / 1e9, result };
}

const path = process.argv[2];
const all = path ? fromInventory(path) : synthetic(400);
const live = liveQuantitiesFor(recipe);
const kept = paretoFilter(bucketBySlot(all), live).kept;

console.log('inventory     :', path ?? 'synthetic', `(${all.length} pieces)`);
console.log('recipe        :', HITS, 'hits');
console.log('after Pareto  :', SLOTS.map((s) => kept.get(s)?.length ?? 0).join(' × '));
console.log(
  'free space    :',
  SLOTS.reduce((n, s) => n * (kept.get(s)?.length ?? 0), 1).toLocaleString(), 'combinations',
);
console.log();

if (!kept.size || SLOTS.some((s) => (kept.get(s)?.length ?? 0) === 0)) {
  console.error('a slot came back empty after the Pareto filter; nothing to measure');
  process.exit(2);
}

const CAPS = process.argv.includes('--full') ? [Infinity] : [20, 24, 28];
for (const perSlot of CAPS) {
  const subset = Number.isFinite(perSlot) ? capped(all, perSlot) : all;
  const pin = subset.find((c) => c.slot === SLOTS[0]);

  const free = time(() => searchRecipe(subset, { recipes, topN: 1 }));
  const pinned = time(() => searchRecipe(subset, { recipes, topN: 1, pinned: pin }));

  if (free.result.evaluated === 0) {
    // **The failure the first run of this script hit.** A walk that evaluates nothing still
    // returns a time, and that time is of an empty loop.
    console.error(`${perSlot} per slot: the free search evaluated 0 combinations — no state to`
      + ' walk. Check the set ids against the recipe map.');
    process.exit(2);
  }
  console.log(
    `${Number.isFinite(perSlot) ? String(perSlot).padStart(2) : 'all'} per slot  :`
    + ` free ${free.result.evaluated.toLocaleString()} combos in ${free.seconds.toFixed(3)}s`
    + ` | pinned ${pinned.result.evaluated.toLocaleString()} in ${pinned.seconds.toFixed(3)}s`
    + ` | ${(free.seconds / Math.max(pinned.seconds, 1e-9)).toFixed(1)}x cheaper`,
  );
}

console.log(
  '\nA pinned search drops one slot from the Cartesian product, so it costs about'
  + '\nthe free search divided by that slot\'s bucket size. Report the measured ratio in'
  + '\ndocs/RESEARCH_pinned_search_cost.md rather than the arithmetic.',
);
