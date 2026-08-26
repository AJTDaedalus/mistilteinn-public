// W.1 — the app's gcsim runner, against the real browser build.
//
// `scripts/verify-gcsim-wasm.mjs` proves the *wasm* agrees with the oracle. This proves the
// **runner the app actually calls** agrees with it, driving `src/app/sim/gcsim.ts` rather
// than re-hand-rolling the `initializeAggregator` → `simulate` → `flush` sequence beside it.
//
// That distinction is the whole point. A gate that re-implements the thing it checks can pass
// while the shipped path is broken — two copies, and the duplicate is the one that works.
//
// A standalone Node script rather than a vitest spec, for the reason `verify-kernel.mjs`
// gives: it reads a fixture from disk, and Angular's test builder targets the browser where
// `node:fs` does not exist. Node 24 strips types, so this imports the source directly and no
// build artifact can go stale between the code and its gate.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { configError, run } from '../src/app/sim/gcsim.ts';

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), '..');
const WASM = join(FRONTEND, 'gcsim', 'gcsim.wasm');
const CASE = join(
  FRONTEND, '..', 'backend', 'tests', 'fixtures', 'crossval', 'ayaka_normal_1_nocrit.txt',
);

// The same anchor `verify-gcsim-wasm.mjs` uses, and the same one `tests/crossval` pins the
// Python chain to. One number, checked from three directions.
const EXPECTED_TOTAL = 108.53039935232651;

if (!existsSync(WASM)) {
  // Loud, not skipped. A skipped check BLOCKS — it means *could not check*, never *checked
  // and clean*. CI builds the wasm before this runs (`npm run gcsim:build`); locally you
  // have not.
  console.error(
    `gcsim's browser build is missing at ${WASM}.\n` +
      `Run \`npm run gcsim:build\` — this gate cannot vouch for anything without it.`,
  );
  process.exit(2);
}

await import(join(FRONTEND, 'gcsim', 'wasm_exec.js')); // assigns globalThis.Go
const go = new globalThis.Go();
const { instance } = await WebAssembly.instantiate(readFileSync(WASM), go.importObject);
void go.run(instance);
await new Promise((resolve) => setTimeout(resolve, 50));

const config = readFileSync(CASE, 'utf8');

// The runner's own contract, checked before the number: a valid config must not read as an
// error. This is the assertion that would have caught treating `validateConfig`'s success
// return as a failure, which is the mistake that made all four sample configs look invalid.
if (configError(globalThis.validateConfig(config)) !== null) {
  console.error('configError() reports a valid config as rejected.');
  process.exit(1);
}

const seen = [];
const result = run(globalThis, config, 1, (done, total) => seen.push([done, total]));

if (result.totalDamage !== EXPECTED_TOTAL) {
  console.error(
    `the app's gcsim runner disagrees with the oracle.\n` +
      `  expected ${EXPECTED_TOTAL}\n  got      ${result.totalDamage}\n` +
      `The wasm gate passing while this fails means the runner is wrong, not the simulator.`,
  );
  process.exit(1);
}

// `iteration=1` is in the config text, and the runner must ignore it in favour of its own
// count — the misreading that made a benchmark show no cost for more work.
if (seen.length !== 1 || seen[0][0] !== 1 || seen[0][1] !== 1) {
  console.error(`progress did not report exactly one iteration: ${JSON.stringify(seen)}`);
  process.exit(1);
}

// The loop is the runner's actual job, and one iteration cannot show it working. This run
// asks for three against the same deterministic fixture: the mean must not move, and progress
// must report three times. Without it the gate passes on a runner that simulates once and
// calls it a hundred — which is exactly the misreading of `iteration=N` this module documents.
const many = [];
const thrice = run(globalThis, config, 3, (done, total) => many.push([done, total]));

if (thrice.totalDamage !== EXPECTED_TOTAL) {
  console.error(
    `three iterations of a deterministic fixture moved the mean.\n` +
      `  expected ${EXPECTED_TOTAL}\n  got      ${thrice.totalDamage}`,
  );
  process.exit(1);
}
if (many.length !== 3 || many.at(-1)[0] !== 3) {
  console.error(`progress did not report three iterations: ${JSON.stringify(many)}`);
  process.exit(1);
}

console.log(`the app's gcsim runner agrees with the oracle: ${result.totalDamage}`);
