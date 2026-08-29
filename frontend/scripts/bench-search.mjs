/**
 * Time one scored combination of the browser search.
 *
 *     node --import ./scripts/ts-resolve.mjs scripts/bench-search.mjs [inventory.json]
 *
 * **Why this exists.** `sim/search.ts` walks the full Cartesian product of five buckets, and
 * `SECONDS_PER_COMBINATION` there is the number that decides how large a K the budget layer
 * may keep. `backend/app/services/artifact_prefilter.py` states the rule this file obeys:
 * *"The ZZZ pipeline's equivalent constant was a fit against a different hot loop and was
 * deliberately not ported. A borrowed timing is a fabricated measurement."* The server's
 * 5.5e-4 s is a different evaluator in a different language, so it is not this number either.
 *
 * **Not wired into CI.** A timing measurement is not a pass/fail gate — a slow machine would
 * fail it for being slow. It is here so the constant can be re-derived rather than trusted.
 *
 * **Node, not a browser**, and the difference matters enough to name: `bench-sample-browser.mjs`
 * exists because `sample()` was suspected of a browser penalty. This hot loop has no WASM, no
 * DOM and no allocation per combination beyond one small object, so both run the same V8
 * arithmetic — but that is an argument, and the constant carries a safety factor rather than
 * resting on it. See the constant's own comment in `sim/search.ts`.
 *
 * With no argument it builds a synthetic inventory. Pass a `GET /api/v1/artifacts/inventory`
 * payload to measure against a real one.
 */

import { readFileSync } from 'node:fs';

import { SLOTS, bucketBySlot, liveQuantities, paretoFilter, search } from '../src/app/sim/search.ts';

/** A hit that reads ATK, crit and one element — the ordinary case a user searches. */
const CONTEXT = {
  base: { base_atk: 1000, base_hp: 20000, base_def: 800, crit_rate: 0.05, crit_dmg: 0.5 },
  hit: {
    multiplier: 2, scalingStat: 'atk', flatDamage: 0, baseDamageBonus: 0,
    amplifying: null, reactionBonus: 0,
  },
  target: { level: 90, resistance: 0.1, defReduction: 0, defIgnore: 0 },
  characterLevel: 90,
  dmgBonusQuantity: 'hydro_dmg_bonus',
  setBonuses: [],
  topN: 10,
};

const QUANTITIES = ['flat_atk', 'atk_pct', 'crit_rate', 'crit_dmg', 'hydro_dmg_bonus'];

/** `n` pieces per slot, varied enough that the Pareto layer keeps most of them. */
function synthetic(n) {
  const out = [];
  for (const [slotIndex, slot] of SLOTS.entries()) {
    for (let i = 0; i < n; i += 1) {
      const stats = {};
      for (const [q, quantity] of QUANTITIES.entries()) {
        // A spread of values with no piece dominating another on every axis, which is what
        // a real inventory looks like to the lossless layer.
        stats[quantity] = ((i * 7 + q * 13 + slotIndex * 3) % 29) / 100;
      }
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

/** Trim each bucket so the exhaustive walk finishes in seconds rather than hours. */
function capped(candidates, perSlot) {
  const bySlot = new Map();
  for (const c of candidates) {
    const bucket = bySlot.get(c.slot) ?? [];
    if (bucket.length < perSlot) bucket.push(c);
    bySlot.set(c.slot, bucket);
  }
  return [...bySlot.values()].flat();
}

const path = process.argv[2];
const all = path ? fromInventory(path) : synthetic(400);

const kept = paretoFilter(bucketBySlot(all), liveQuantities(CONTEXT)).kept;
console.log('inventory        :', path ?? 'synthetic', `(${all.length} pieces)`);
console.log('after Pareto     :', SLOTS.map((s) => kept.get(s)?.length ?? 0).join(' × '));

// Two sizes, like `bench_optimizer.py`: one measurement could be an artefact of a bucket
// shape, and the constant is only credible if the per-combination cost is flat across them.
for (const perSlot of [14, 20]) {
  const subset = capped(all, perSlot);
  // Warm V8's JIT before the measurement, or the first run pays for compiling the hot loop.
  search(subset, { ...CONTEXT, topN: 10 });
  const started = process.hrtime.bigint();
  const result = search(subset, { ...CONTEXT, topN: 10 });
  const seconds = Number(process.hrtime.bigint() - started) / 1e9;
  console.log(
    `${perSlot} per slot   : ${result.evaluated.toLocaleString()} combinations`
    + ` in ${seconds.toFixed(3)}s`
    + ` → ${(seconds / result.evaluated).toExponential(3)} s/combination`,
  );
}

console.log(
  '\nPaste the higher figure into SECONDS_PER_COMBINATION in src/app/sim/search.ts,'
  + '\nwith the date and both runs, the way artifact_prefilter.py records its own.',
);
