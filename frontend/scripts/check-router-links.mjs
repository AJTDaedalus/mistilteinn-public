/**
 * A `routerLink` in a template belongs to a component that imports `RouterLink`.
 *
 *     npm run check:router-links
 *
 * **Why this is a script and not a spec.** Angular does not error on an unknown *static*
 * attribute. A standalone component whose `imports` omits `RouterLink` still compiles, still
 * lints, and still renders `<a routerLink="/inventory">Import a GOOD export</a>` — as an
 * anchor with **no `href`**: not clickable, not focusable, no navigation, and no message
 * anywhere. That shipped on `/weapons-inventory`, on the one line an empty inventory shows.
 *
 * The directive is the whole difference between a link and a word, so the check is: every
 * template that writes `routerLink` (or `routerLinkActive`) must sit beside a component that
 * imports the directive that makes it mean something.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
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

/** `routerLink` as an attribute — plain, bound, or with a `routerLinkActive` beside it. */
const USES_LINK = /\[?routerLink(?:Active)?\]?\s*=/;

/**
 * What a component's `imports: [...]` array names.
 *
 * `RouterModule` and `RouterLinkWithHref` both bring the directive in, so either satisfies
 * this — the question is whether the template's attribute resolves, not which symbol did it.
 */
const SATISFIES = /\b(RouterLink|RouterLinkActive|RouterLinkWithHref|RouterModule)\b/;

const offenders = [];
const checked = [];

for (const template of files.filter((f) => f.endsWith('.html'))) {
  const markup = readFileSync(template, 'utf8');
  if (!USES_LINK.test(markup)) continue;

  // The component beside it, by Angular's own `templateUrl` convention: `foo.html` is
  // rendered by `foo.ts`. A template with no such neighbour is reported rather than skipped.
  const component = template.replace(/\.html$/, '.ts');
  if (!files.includes(component)) {
    offenders.push(`${relative(SRC, template)}  uses routerLink and has no component beside it`);
    continue;
  }

  const source = readFileSync(component, 'utf8');
  const imports = /imports\s*:\s*\[([^\]]*)\]/s.exec(source);
  checked.push(relative(SRC, template));
  if (!imports || !SATISFIES.test(imports[1])) {
    offenders.push(
      `${relative(SRC, component)}  renders routerLink and does not import RouterLink`,
    );
  }
}

// **A check that cannot fail is not a check.** If the template scan stops finding links, the
// loop above holds trivially — so the count is asserted before the result is trusted.
if (checked.length < 3) {
  console.error(
    `only ${checked.length} template(s) using routerLink were found — the scan is broken, `
    + 'not the tree. Nothing was checked.',
  );
  process.exit(2);
}

if (offenders.length) {
  console.error(
    'a routerLink renders as a plain attribute here: the anchor gets no href, so it is not '
    + 'clickable, not focusable, and navigates nowhere. Angular does not error on an unknown '
    + 'static attribute, which is why this compiles.\n',
  );
  for (const line of offenders) console.error(`  ${line}`);
  process.exit(1);
}

console.log(`${checked.length} templates use routerLink; every one imports the directive.`);
