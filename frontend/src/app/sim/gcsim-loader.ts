/**
 * Loading gcsim's browser build — **inside the gcsim worker**, never on the page.
 *
 * W.6. **Lazy is not an optimisation here.** The artifact is 41 MB (~7 MB gzipped) and
 * `RESEARCH_gcsim_embed.md` §6 keeps gcsim out of the optimizer's inner loop — so a page that
 * paid for this on load would be charging every user of the artifact search for a simulator
 * that search is forbidden to use. The worker is created on the first job and loads this then.
 *
 * The wasm is **gitignored and produced by `npm run gcsim:build`** (`frontend/gcsim/
 * PROVENANCE.md`), served from `/gcsim/` by an `angular.json` assets entry. A deployment that
 * has not run the build serves 404s here, the same failure the catalogue icons have when
 * `scripts.download_icons` has not run — and the reason this reports a reason rather than
 * throwing an opaque instantiation error.
 *
 * **One instance per worker, and one worker at a time.** W.4 measured peak RSS near 1 GB per
 * instance, so the page never holds two: `gcsim-worker-runner.ts` creates the worker once and
 * replaces it only after terminating the old one on a deadline.
 */

import type { GcsimModule } from './gcsim';

/** gcsim's exports land on `globalThis`; this is the scope with them attached. */
type GcsimGlobal = typeof globalThis & GcsimModule & { Go?: new () => GoRuntime };

interface GoRuntime {
  importObject: WebAssembly.Imports;
  run(instance: WebAssembly.Instance): Promise<void>;
}

/**
 * Instantiate gcsim in the current (worker) scope.
 *
 * `base` is the absolute URL of the `gcsim/` directory, resolved **by the page** against its
 * own `document.baseURI` and handed over — a worker's relative URLs resolve against the worker
 * chunk instead, which only happens to be the same directory today.
 *
 * **`wasm_exec.js` is a classic script, loaded here by dynamic `import()`.** Angular bundles a
 * worker as an ES module, and a module worker has no `importScripts`. Go's shim is an IIFE
 * that assigns `globalThis.Go` and declares nothing at top level, so it evaluates identically
 * as a module — which `scripts/verify-gcsim-runner.mjs` has always relied on in Node. It is
 * same-origin, so `script-src 'self'` in `nginx.prod.conf` already covers it, and the worker
 * chunk is served under the server-level CSP that carries `'wasm-unsafe-eval'`.
 */
export async function instantiateGcsim(base: string): Promise<GcsimModule> {
  const scope = globalThis as GcsimGlobal;
  const execUrl = new URL('wasm_exec.js', base).href;
  const wasmUrl = new URL('gcsim.wasm', base).href;

  if (scope.Go === undefined) {
    try {
      await import(/* @vite-ignore */ execUrl);
    } catch {
      throw new Error(`could not load ${execUrl}. The gcsim build is incomplete — run ` +
        `\`npm run gcsim:build\`.`);
    }
  }
  if (scope.Go === undefined) {
    throw new Error(
      `${execUrl} loaded but did not define Go. The gcsim build is incomplete — run ` +
        `\`npm run gcsim:build\`.`,
    );
  }

  const response = await fetch(wasmUrl);
  if (!response.ok) {
    // Named rather than left as a WebAssembly parse error, because the overwhelmingly likely
    // cause is a deployment where `npm run gcsim:build` never ran.
    throw new Error(
      `gcsim's browser build is not being served (${response.status} for ${wasmUrl}). ` +
        `It is gitignored; run \`npm run gcsim:build\`.`,
    );
  }

  const go = new scope.Go();
  const { instance } = await WebAssembly.instantiateStreaming(response, go.importObject);
  // `go.run` resolves only when the Go program exits, which it never does — gcsim's wasm
  // entry parks and waits for calls. Awaiting it would hang forever.
  void go.run(instance);
  await new Promise((resolve) => setTimeout(resolve, 50));
  return scope;
}
