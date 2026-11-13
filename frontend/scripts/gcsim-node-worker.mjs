// The app's gcsim worker, `src/app/sim/gcsim.worker.ts`, run in a Node worker thread.
//
// Used by `verify-gcsim-runner.mjs` to drive the **shipped worker module** against the real
// wasm — not a copy of it. Node's worker threads are not Web Workers, so this supplies the
// three things the module touches that differ: `postMessage` and `addEventListener('message')`
// (over `parentPort`), and `fetch` of a `file:` URL, which Node's fetch refuses. Everything the
// worker does with them — loading `wasm_exec.js` by dynamic import, instantiating the wasm,
// driving `run()` — is the app's own code.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { parentPort } from 'node:worker_threads';

globalThis.postMessage = (message) => parentPort.postMessage(message);
globalThis.addEventListener = (type, listener) => {
  if (type === 'message') parentPort.on('message', (data) => listener({ data }));
};

const networkFetch = globalThis.fetch;
globalThis.fetch = async (input) => {
  const url = String(input);
  if (!url.startsWith('file:')) return networkFetch(input);
  return new Response(readFileSync(fileURLToPath(url)), {
    headers: { 'content-type': 'application/wasm' },
  });
};

await import('../src/app/sim/gcsim.worker.ts');
