// B.2 — gcsim's **browser** build must agree with the committed oracle.
//
// Chunk S proved the simulation core runs under WASI, hosted from Python. This is a
// different build: `GOOS=js GOARCH=wasm` against `syscall/js`, driven through upstream's own
// JS bindings — what a Web Worker actually loads. The whole client-side architecture rests
// on it producing the same numbers, so it is asserted rather than assumed.
//
// Run as its own CI step rather than as a vitest spec: it needs the real Node WebAssembly
// host and Go's JS runtime, not Angular's test environment, and a gate is easier to trust
// when nothing else shares its harness. Same reasoning as the backend's `-m perf` lane.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = join(HERE, '..');
const REPO = join(FRONTEND, '..');

const WASM = join(FRONTEND, 'gcsim', 'gcsim.wasm');
// The **no-crit** variant, deliberately. gcsim rolls crit, so re-running the plain case is
// not deterministic — this check passed five CI runs and then returned 40.894 against an
// expected 21.706, a ratio of exactly `1 + Ayaka's crit DMG`. It had rolled a crit, and a
// gate that fails 5% of the time is worse than no gate: it trains people to re-run CI.
// Forcing crit to zero makes the run reproducible. See the fixtures' PROVENANCE.md.
const CASE = join(REPO, 'backend', 'tests', 'fixtures', 'crossval', 'ayaka_normal_1_nocrit.txt');

/**
 * Total damage for the no-crit case — the same figure `ayaka_normal_1.json` recorded, since
 * that roll did not crit either. Compared as a total rather than DPS because the total is
 * what the fixture states; the DPS is that divided by the 5-second duration.
 */
const EXPECTED_TOTAL = 108.53039935232651;

await import(join(FRONTEND, 'gcsim', 'wasm_exec.js'));   // assigns globalThis.Go

const go = new globalThis.Go();
const { instance } = await WebAssembly.instantiate(readFileSync(WASM), go.importObject);
void go.run(instance);
await new Promise((resolve) => setTimeout(resolve, 50));

const cfg = readFileSync(CASE, 'utf8');
const invalid = globalThis.validateConfig(cfg);
if (typeof invalid === 'string' && invalid.includes('"error"')) {
  console.error('gcsim rejected the committed config:', invalid);
  process.exit(1);
}

globalThis.initializeAggregator(cfg);
globalThis.initializeWorker(cfg);
globalThis.aggregate(globalThis.simulate());
// **The raw contract, read by hand on purpose** — this gate is about the wasm, not the app's
// reader of it (that is `verify-gcsim-runner.mjs`). From gcsim v2.50.0 `flush()` returns an
// object, `{result: "<SimulationResult JSON>", hash}`, and the statistics sit under
// `statistics`; up to v2.47.2 it returned a string `{"stats": …}`. A string here therefore
// means either an older wasm or a failure, and both are worth stopping on.
const flushed = globalThis.flush();
if (typeof flushed === 'string' || typeof flushed?.result !== 'string') {
  console.error('flush() did not return the v2.50.0 {result, hash} envelope:', flushed);
  process.exit(1);
}
const actual = JSON.parse(flushed.result)?.statistics?.total_damage?.mean;

if (actual !== EXPECTED_TOTAL) {
  console.error(
    `gcsim's browser build disagrees with the oracle.\n` +
      `  expected ${EXPECTED_TOTAL}\n` +
      `  got      ${actual}\n` +
      `This is a blocker, not a rounding note: the crossval fixture, the native binary and ` +
      `the WASI probe all report the expected value, so a fourth answer means the browser ` +
      `build is not the simulator this project verified.`,
  );
  process.exit(1);
}

console.log(`gcsim browser build agrees with the oracle: ${actual}`);
