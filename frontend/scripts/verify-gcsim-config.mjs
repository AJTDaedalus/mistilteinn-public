// B.3 — a config this repo emits must be one gcsim accepts.
//
// String assertions in `test_gcsim_config.py` pin the decisions; this pins that the result
// is a *real* config, by handing it to gcsim's own `validateConfig`. Nothing else is an
// authority on that — a config that parses in our head and not in gcsim's is worth nothing,
// and would surface as a runtime error in a Web Worker rather than as a failing test.
//
// The backend writes fixtures to `frontend/gcsim/emitted/` (gitignored); this reads them.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), '..');
const CASES = join(FRONTEND, 'gcsim', 'emitted');

if (!existsSync(CASES)) {
  console.error(
    `no emitted configs at ${CASES}. Generate them first:\n` +
      `  cd backend && python -m scripts.gcsim.emit_sample_configs`,
  );
  process.exit(1);
}

const files = readdirSync(CASES).filter((f) => f.endsWith('.txt'));
if (files.length === 0) {
  console.error(`${CASES} is empty — a validator with nothing to validate is not a gate`);
  process.exit(1);
}

await import(join(FRONTEND, 'gcsim', 'wasm_exec.js'));
const go = new globalThis.Go();
const { instance } = await WebAssembly.instantiate(
  readFileSync(join(FRONTEND, 'gcsim', 'gcsim.wasm')), go.importObject,
);
void go.run(instance);
await new Promise((resolve) => setTimeout(resolve, 50));

let failed = 0;
for (const file of files) {
  const cfg = readFileSync(join(CASES, file), 'utf8');
  const result = globalThis.validateConfig(cfg);
  if (typeof result === 'string' && result.includes('"error"')) {
    console.error(`REJECTED ${file}: ${result.slice(0, 300)}`);
    failed += 1;
    continue;
  }
  const parsed = JSON.parse(result);
  const keys = (parsed.characters ?? []).map((c) => c?.base?.key ?? c?.base?.name);
  console.log(`ok ${file} -> ${JSON.stringify(keys)}`);
}

if (failed > 0) {
  console.error(`${failed} of ${files.length} emitted configs were rejected by gcsim`);
  process.exit(1);
}
console.log(`gcsim accepted all ${files.length} emitted configs`);
