/**
 * Where this site's source code is, and under what licence — the offer AGPL §13 requires.
 *
 * **Why the site has to say this at all.** Mistilteinn is AGPL-3.0-or-later, and from the
 * gcsim v2.50.0 re-pin (2026-11-13) it also serves gcsim, which is AGPLv3, to every browser.
 * §13 obliges a program that users interact with over a network to *offer* those users its
 * Corresponding Source, prominently. A link in a README nobody visiting the site reads does
 * not do that; one in the shell footer, on every page and before sign-in, does.
 * `docs/DECISIONS.md` §37.
 *
 * One constant, so the footer and `/about` cannot point at two different places.
 */
export const SOURCE_CODE = {
  url: 'https://github.com/AJTDaedalus/mistilteinn-public',
  licence: 'AGPL-3.0-or-later',
  label: 'Source code (AGPL-3.0)',
} as const;

/** gcsim's repository. The exact commit served is read from `gcsim/BUILT_FROM` at run time. */
export const GCSIM_REPOSITORY = 'https://github.com/genshinsim/gcsim';

/**
 * The browsable source of gcsim at `commit`, or the repository itself when the commit is not
 * a full SHA.
 *
 * **Read from the served artifact, never restated.** `gcsim/BUILT_FROM` is written by the same
 * build that produced the `gcsim.wasm` beside it, so it names the commit of the binary this
 * visitor actually downloaded — which is what "Corresponding Source" means. A constant here
 * would be a second copy of the pin in `docs/CROSSVAL_gcsim.md`, and it would go stale at the
 * next re-pin with nothing to notice it.
 */
export function gcsimSourceUrl(commit: string | null): string {
  return commit !== null && /^[0-9a-f]{40}$/.test(commit)
    ? `${GCSIM_REPOSITORY}/tree/${commit}`
    : GCSIM_REPOSITORY;
}
