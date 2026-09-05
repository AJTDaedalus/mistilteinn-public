/**
 * A `<dialog>` this app styles must still be able to close.
 *
 *     npm run check:dialogs
 *
 * **Why this is a script and not a spec.** The UA stylesheet hides a dialog with
 * `dialog:not([open]) { display: none }`. That is an ordinary declaration in the user-agent
 * origin, so **any** author rule setting `display` on the same element beats it, and the
 * dialog then stays laid out in the page after `close()` — with its `open` attribute correctly
 * absent and nothing else on screen to say so.
 *
 * It shipped: `.editor-dialog { display: grid }` inside `@media (min-width: 88rem)` left the
 * rotation editor rendered under the rotation list on every viewport wider than 1408px. Two
 * Discord reports came out of that one declaration — *"Rotation Edit screen is still visible
 * on the page after closing it"* (#290), and *"`Show/Hide gcsim config` seems to do nothing
 * other than flip itself"* (#284), which was a click on the phantom copy, whose team had never
 * been chosen because it had never been opened.
 *
 * **No test in this repo could have caught it.** jsdom has no `HTMLDialogElement`, which is
 * why every spec here calls `showModal?.()` and gets `undefined` — so a component test cannot
 * tell an open dialog from a closed one, and 1030 of them passed through this. The check that
 * works reads the stylesheet, and reading files is what a script does and what the Angular
 * compiler refuses to typecheck. `check-css-tokens.mjs` is here for the same reason.
 *
 * The rule: a rule whose selector resolves to the bare dialog element may not set `display`.
 * Qualify it with `[open]`, or with a state (`:hover`) a closed dialog cannot be in.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { basename, dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '..', 'src');

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

const files = walk(SRC);

/**
 * Class names a template puts on a `<dialog>`.
 *
 * Read off the markup rather than listed here, so a dialog written tomorrow is covered on the
 * day it is written and not on the day somebody remembers this file.
 */
const dialogClasses = new Set();
for (const file of files.filter((f) => f.endsWith('.html'))) {
  for (const tag of readFileSync(file, 'utf8').matchAll(/<dialog\b[^>]*>/g)) {
    const attr = /class="([^"]*)"/.exec(tag[0]);
    for (const name of attr?.[1].split(/\s+/).filter(Boolean) ?? []) dialogClasses.add(name);
  }
}

/** `.editor` matches `.editor`, and not `.editor-dialog` or `.editor__head`. */
const namesClass = (selector, klass) => new RegExp(`\\.${klass}(?![\\w-])`).test(selector);

/**
 * The compounds a selector list actually styles — its **subjects**.
 *
 * `.rank .field` styles `.field`, not `.rank`: a descendant of a hidden dialog is hidden along
 * with it, and reading the whole string would flag every such rule.
 */
const subjects = (selector) => selector
  .split(',')
  .map((one) => one.trim().split(/[\s>+~]+/).filter(Boolean).pop() ?? '')
  .filter(Boolean);

const isDialog = (selector) => subjects(selector)
  .some((one) => [...dialogClasses].some((klass) => namesClass(one, klass)));

/**
 * Every `display` declaration, with the selector chain it sits under.
 *
 * A brace walk rather than a parser: the question is only "which selectors is this nested
 * inside", and a dependency for that would be a dependency to keep.
 */
function displayRules(scss) {
  const found = [];
  const stack = [];
  let pending = '';
  // Block comments are blanked **line by line**. Collapsing them shifts every line number
  // after a multi-line comment, which is a check that points at the wrong rule.
  const blanked = scss.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ' '));
  blanked.split('\n').forEach((raw, index) => {
    const line = raw.replace(/\/\/.*$/, '');
    for (const part of line.split(/([{}])/)) {
      if (part === '{') { stack.push(pending.trim()); pending = ''; continue; }
      if (part === '}') { stack.pop(); pending = ''; continue; }
      if (/^\s*display\s*:/.test(part)) {
        found.push({ selector: [...stack], line: index + 1, text: part.trim() });
      }
      pending += part;
    }
  });
  return found;
}

const stylesheets = files.filter((f) => f.endsWith('.scss'));
const offenders = stylesheets.flatMap((file) => displayRules(readFileSync(file, 'utf8'))
  .filter(({ selector }) => {
    // `@media` and other at-rules are containers, not selectors — the class they hold is what
    // matters, and #290 lived inside one. They are dropped **before** the chain is built, not
    // after: `@media (min-width: 88rem)` contains a colon, and reading it as part of the
    // selector made the state guard below swallow the one rule this file exists to catch.
    // Found by planting the bug back and watching the check pass.
    const parts = selector.filter((s) => !s.startsWith('@'));
    if (!parts.length) return false;
    const base = parts[parts.length - 1];
    // `&.wide { display: grid }` nested inside the dialog's own rule is still the dialog.
    const nestedOntoItself = subjects(base).some((one) => one.startsWith('&') && !one.includes(':'))
      && parts.slice(0, -1).some(isDialog);
    if (!isDialog(base) && !nestedOntoItself) return false;
    const chain = parts.join(' ');
    // Qualified so a closed dialog cannot match it: `[open]`, or a state it cannot be in.
    return !chain.includes('[open]') && !chain.includes(':');
  })
  .map(({ line, text }) => `${relative(SRC, file)}:${line}  ${text}`));

// **A check that cannot fail is not a check.** If the markup scan stops finding dialogs, every
// assertion below holds trivially — so the count is asserted before the result is trusted.
if (dialogClasses.size < 3) {
  console.error(
    `only ${dialogClasses.size} dialog class(es) found in the templates — the scan is broken, `
    + 'not the tree. Nothing was checked.',
  );
  process.exit(2);
}

if (offenders.length) {
  console.error(
    'a closed <dialog> would stay on the page: `display` is set on the element itself, which '
    + "beats the UA's `dialog:not([open]) { display: none }`.\n"
    + 'Qualify the selector with `[open]`.\n',
  );
  for (const line of offenders) console.error(`  ${line}`);
  process.exit(1);
}

console.log(
  `${dialogClasses.size} dialog classes across ${stylesheets.length} stylesheets; `
  + 'none is given a display it cannot lose.',
);
