/**
 * Every `var(--token)` the app uses must be a token the palette defines.
 *
 *     npm run check:tokens
 *
 * **This exists because a design pass shipped four tokens that do not exist and nothing said
 * so.** The rotation timeline's tap/hold badge was drawn `background: var(--accent); color:
 * var(--surface)` — there is no `--accent`, so the background resolved to nothing and dark
 * text sat on a dark tile. The DOM had the badge, a unit test asserted its text, the build was
 * clean, and on screen there was nothing at all. It was found by taking a screenshot.
 *
 * The same sweep found `--space-5` in three other stylesheets, one of them already written as
 * `var(--space-5, var(--space-4))` — so somebody had noticed once and fixed only their own.
 *
 * CSS custom properties fail **silently by design**: an undefined one makes the whole
 * declaration invalid at compute time and the element keeps whatever it had. That is the shape
 * `FINDINGS_frontend_validation.md` already recorded — the two colours the app uses to say
 * *something is wrong* were the only ones not in the palette, because every page decided
 * separately.
 *
 * It cannot tell whether a colour is *right*. It can tell whether it exists, which is the half
 * a machine can check.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '..', 'src');
const PALETTE = join(SRC, 'styles', '_tokens.scss');

/** `--foo: value;` — a definition, wherever it is written. */
const DEFINITION = /^[ \t]*(--[a-z0-9-]+)[ \t]*:/gm;
/** `var(--foo)` and `var(--foo, fallback)`. */
const USE = /var\(\s*(--[a-z0-9-]+)/g;

/**
 * Built at runtime from a checked list (`ElementChip`, and the timeline's run colours), so a
 * template string reaches this sweep as a bare prefix and there is nothing static to verify.
 */
const RUNTIME_BUILT = new Set([
  '--element-',
  // Set by an Angular style binding — `[style.--element]="…"` — which no sweep of stylesheet
  // text can see as a definition, though it is one.
  '--element',
]);

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.(scss|ts|html)$/.test(entry) && !/\.spec\.ts$/.test(entry)) out.push(path);
  }
  return out;
}

const found = (pattern, text) =>
  new Set([...text.matchAll(new RegExp(pattern))].map((m) => m[1]));

/**
 * Strip comments before scanning.
 *
 * A token named in prose is not a token used, and this check flagged one that was: a comment
 * documenting the historical `var(--accent)` bug — the whole reason this script exists — was
 * reported as a live undefined token. A checker that punishes writing down the defect it
 * guards against teaches people to stop writing it down.
 *
 * Block comments only, and that is deliberate. `//` in a `.ts` or `.html` file can appear
 * inside a string or a URL, and stripping to end-of-line there would silently delete real
 * code from the scan — which fails the other way, by hiding a token that *is* used.
 */
const withoutComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, ' ');

const palette = found(DEFINITION, readFileSync(PALETTE, 'utf8'));
if (palette.size === 0) {
  console.error(`no tokens parsed from ${PALETTE}; this check would pass vacuously`);
  process.exit(2);
}

const missing = new Map();
let scanned = 0;
for (const file of walk(SRC)) {
  const text = withoutComments(readFileSync(file, 'utf8'));
  scanned += 1;
  // A file may define its own. `--element` is set inline by a component and read by its own
  // stylesheet: a local variable, not a palette entry.
  const local = found(DEFINITION, text);
  for (const token of found(USE, text)) {
    if (palette.has(token) || local.has(token) || RUNTIME_BUILT.has(token)) continue;
    missing.set(token, [...(missing.get(token) ?? []), relative(SRC, file)]);
  }
}

if (missing.size === 0) {
  console.log(`${palette.size} tokens defined; ${scanned} files use only those.`);
  process.exit(0);
}

console.error('These tokens are used but never defined, so every declaration using them does');
console.error('nothing and the element silently keeps what it had:\n');
for (const [token, files] of [...missing].sort()) {
  console.error(`  ${token}`);
  for (const file of [...new Set(files)]) console.error(`      src/${file}`);
}
process.exit(1);
