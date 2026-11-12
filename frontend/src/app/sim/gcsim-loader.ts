/**
 * Loading gcsim's browser build, once, on demand.
 *
 * W.6. **Lazy is not an optimisation here.** The artifact is 41 MB (~7 MB gzipped) and
 * `RESEARCH_gcsim_embed.md` §6 keeps gcsim out of the optimizer's inner loop — so a page that
 * paid for this on load would be charging every user of the artifact search for a simulator
 * that search is forbidden to use.
 *
 * The wasm is **gitignored and produced by `npm run gcsim:build`** (`frontend/gcsim/
 * PROVENANCE.md`), served from `/gcsim/` by an `angular.json` assets entry. A deployment that
 * has not run the build serves 404s here, the same failure the catalogue icons have when
 * `scripts.download_icons` has not run — and the reason `load()` reports a reason rather than throwing an
 * opaque instantiation error.
 */

import type { GcsimModule } from './gcsim';

/** gcsim's exports land on `globalThis`; this is the window with them attached. */
type GcsimGlobal = typeof globalThis & GcsimModule & { Go?: new () => GoRuntime };

interface GoRuntime {
  importObject: WebAssembly.Imports;
  run(instance: WebAssembly.Instance): Promise<void>;
}

/** Where the assets entry puts them. Relative, so a sub-path deployment still resolves. */
const WASM_URL = 'gcsim/gcsim.wasm';
const EXEC_URL = 'gcsim/wasm_exec.js';

let loading: Promise<GcsimModule> | null = null;

/**
 * The gcsim module, loading it on first use.
 *
 * **Memoised on the promise, not on the result.** Two comparisons started before the first
 * finishes would otherwise each instantiate a 41 MB module — and W.4 measured peak worker RSS
 * near 1 GB per instance, so a duplicate is not merely wasteful.
 *
 * A failed load clears the memo, because a 404 during a deploy should not poison the page for
 * its lifetime.
 */
export function loadGcsim(): Promise<GcsimModule> {
  loading ??= instantiate().catch((error: unknown) => {
    loading = null;
    throw error;
  });
  return loading;
}

/** Test seam: forget any loaded module. Not for production use. */
export function resetGcsimForTesting(): void {
  loading = null;
}

async function instantiate(): Promise<GcsimModule> {
  const scope = globalThis as GcsimGlobal;
  if (scope.Go === undefined) await loadScript(EXEC_URL);
  if (scope.Go === undefined) {
    throw new Error(
      `${EXEC_URL} loaded but did not define Go. The gcsim build is incomplete — run ` +
        `\`npm run gcsim:build\`.`,
    );
  }

  const response = await fetch(WASM_URL);
  if (!response.ok) {
    // Named rather than left as a WebAssembly parse error, because the overwhelmingly likely
    // cause is a deployment where `npm run gcsim:build` never ran.
    throw new Error(
      `gcsim's browser build is not being served (${response.status} for ${WASM_URL}). ` +
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

function loadScript(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = url;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`could not load ${url}`));
    document.head.appendChild(script);
  });
}
