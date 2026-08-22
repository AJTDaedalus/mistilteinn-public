// Let the Node gates import app sources the way the app writes them.
//
// The kernel's own imports are extensionless (`from './damage'`) because that is what the
// Angular build requires: `allowImportingTsExtensions` needs `noEmit`, and the build emits,
// so `.ts` specifiers in source break `npm run build`.
//
// Node's ESM resolver has no extension inference, so this hook appends `.ts` when a bare
// relative specifier does not resolve. It is confined to the gates in `scripts/` — app code
// is never loaded through it, and nothing about the shipped bundle changes.
import { register } from 'node:module';
import { pathToFileURL } from 'node:url';

register('./ts-resolve-hook.mjs', pathToFileURL(import.meta.filename));
