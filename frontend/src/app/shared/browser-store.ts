/**
 * The browser's key/value store, behind one guarded accessor.
 *
 * This lives here rather than beside its first caller because a *second* caller was about to
 * copy it. `recipe-cache.ts` owned both the interface and the try/catch, and the optimize
 * page needed the same two things to remember the user's last selection — which is how
 * `.muted`/`.hint`/`.error` ended up hand-written in nine stylesheets: a pattern nothing
 * owned, so every surface decided separately.
 */

/** Where something is kept. An interface, not `Storage`, so a test needs no browser. */
export interface WebStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  readonly length: number;
  key(index: number): string | null;
}

/** The browser's, or `null` where there is none (SSR, a locked-down browser). */
export function browserStore(): WebStorage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    // Accessing it can *throw* where site data is blocked, not merely return null.
    return null;
  }
}
