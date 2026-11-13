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
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Worker } from 'node:worker_threads';

import { configError, run } from '../src/app/sim/gcsim.ts';
import { GcsimTimeoutError } from '../src/app/sim/gcsim-runner.ts';
import { WorkerGcsimRunner } from '../src/app/sim/gcsim-worker-runner.ts';

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

// ── The worker path ─────────────────────────────────────────────────────────────────────────
//
// The app no longer calls `run()` on the page: it sends the job to `gcsim.worker.ts` through
// `WorkerGcsimRunner`, which owns the deadline. Everything above proves the runner; this proves
// the **shipped worker module and the shipped deadline logic** reach the same number, and that
// a simulation which can never finish is killed and the worker replaced.
//
// Node worker threads stand in for Web Workers (`gcsim-node-worker.mjs` says what it shims).
// `Worker.terminate()` is V8's `TerminateExecution` in both, which is the property that
// matters: it interrupts a thread spinning inside wasm, where no JavaScript check can run.

const BASE = pathToFileURL(join(FRONTEND, 'gcsim') + '/').href;
const exited = [];

function nodeWorker() {
  const thread = new Worker(new URL('./gcsim-node-worker.mjs', import.meta.url));
  const like = {
    onmessage: null,
    onerror: null,
    postMessage: (message) => thread.postMessage(message),
    terminate: () => void thread.terminate(),
  };
  const record = { exited: false };
  exited.push(record);
  thread.on('message', (data) => like.onmessage?.({ data }));
  thread.on('error', (error) => like.onerror?.({ message: error.message, preventDefault() {} }));
  thread.on('exit', () => { record.exited = true; });
  return like;
}

const fail = (message) => {
  console.error(message);
  process.exit(1);
};

// 1. The real deadline formula, a real job: the worker must agree with the oracle.
const viaWorker = new WorkerGcsimRunner({ createWorker: nodeWorker, base: BASE });
const workerSeen = [];
const workerRun = await viaWorker.run(config, 3, (done, total) => workerSeen.push([done, total]));
if (workerRun.totalDamage !== EXPECTED_TOTAL) {
  fail(
    `the worker path disagrees with the oracle.\n  expected ${EXPECTED_TOTAL}\n` +
      `  got      ${workerRun.totalDamage}`,
  );
}
if (workerSeen.length !== 3 || workerSeen.at(-1)[0] !== 3) {
  fail(`progress did not cross the worker boundary: ${JSON.stringify(workerSeen)}`);
}
if ((await viaWorker.validate(config)) !== null) fail('the worker reports a valid config as rejected.');
if ((await viaWorker.validate('ayaka char lvl=nonsense;')) === null) {
  fail('the worker reports an invalid config as accepted.');
}
viaWorker.dispose();

// 2. The planted hang. Ayaka alone starts with a full burst and nothing in the rotation can
// refill it, so the second, **ungated** `burst` can never become ready — the deadlock
// `/root/CLAUDE.md` §gcsim describes. At v2.47.2 it grew to ~2.4 GB and died; from v2.50.0
// (gcsim `e4fe22e5b`) it spins forever at flat memory. The gated twin is the control: same
// config, `if .ayaka.burst.ready`, and it must finish — otherwise this gate would pass on a
// config that is broken for some other reason.
const hang = (gated) => [
  'options iteration=1;',
  'ayaka char lvl=90/90 cons=0 talent=9,9,9;',
  'ayaka add weapon="dullblade" lvl=90/90 refine=1;',
  'target lvl=90 resist=0.1 pos=0,1 hp=999999999;',
  'active ayaka;',
  'ayaka burst;',
  gated ? 'if .ayaka.burst.ready { ayaka burst; }' : 'ayaka burst;',
].join('\n');

const PLANTED_DEADLINE_MS = 3_000;
const guarded = new WorkerGcsimRunner({
  createWorker: nodeWorker,
  base: BASE,
  deadline: () => PLANTED_DEADLINE_MS,
});

const control = await guarded.run(hang(true), 1);
if (control.totalDamage === null) fail('the gated control config produced no damage.');
const before = exited.length;

const started = performance.now();
let caught = null;
try {
  await guarded.run(hang(false), 1);
} catch (error) {
  caught = error;
}
const tookMs = performance.now() - started;
if (!(caught instanceof GcsimTimeoutError)) {
  fail(
    `the planted hang did not time out: ${caught === null ? 'it finished' : caught}.\n` +
      `If it finished, gcsim no longer deadlocks on an ungated unfundable burst — re-read ` +
      `gcsim-runner.ts before trusting the deadline's rationale.`,
  );
}
// The worker that hung must actually be gone, not merely abandoned while it spins a core.
await new Promise((resolve) => setTimeout(resolve, 500));
const hungWorker = exited[before - 1];
if (!hungWorker?.exited) fail('the hung worker was not terminated; it is still spinning.');

// 3. After the kill, the same runner must work — on a fresh worker.
const recovered = await guarded.run(config, 1);
if (recovered.totalDamage !== EXPECTED_TOTAL) {
  fail(`the runner did not recover after a timeout: got ${recovered.totalDamage}`);
}
if (exited.length !== before + 1) {
  fail(`expected exactly one replacement worker, saw ${exited.length - before}`);
}
guarded.dispose();

console.log(
  `the worker path agrees with the oracle (${workerRun.totalDamage}); the planted hang was ` +
    `killed after ${(tookMs / 1000).toFixed(1)} s (deadline ${PLANTED_DEADLINE_MS / 1000} s) and ` +
    `a fresh worker ran the next job.`,
);
// Worker threads already terminated; nothing keeps the loop alive except the main module's own
// parked Go program, which never exits.
process.exit(0);
