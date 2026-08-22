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
const CASE = join(REPO, 'backend', 'tests', 'fixtures', 'crossval', 'ayaka_normal_1.txt');

/** What the committed fixture, the native binary and the WASI probe all report. */
const EXPECTED_DPS = 21.706079870465302;

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
const out = JSON.parse(globalThis.flush());
const actual = out?.stats?.dps?.mean;

if (actual !== EXPECTED_DPS) {
  console.error(
    `gcsim's browser build disagrees with the oracle.\n` +
      `  expected ${EXPECTED_DPS}\n` +
      `  got      ${actual}\n` +
      `This is a blocker, not a rounding note: the crossval fixture, the native binary and ` +
      `the WASI probe all report the expected value, so a fourth answer means the browser ` +
      `build is not the simulator this project verified.`,
  );
  process.exit(1);
}

console.log(`gcsim browser build agrees with the oracle: ${actual}`);
