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

// ── R.3: acceptance is not evidence ─────────────────────────────────────────
//
// Everything above proves gcsim can *parse* what we emit. It cannot tell whether the
// rotation actually happens, and that distinction is the whole reason this section exists:
// building D.2's ER sweep, two different mistakes each produced a config gcsim accepted
// happily and which ran the rotation **exactly once** over ninety seconds. The DPS figure
// looked entirely ordinary.
//
// So the compiled rotation is *run*, and its action counts are read back.
//
// `rotation_ungated` is the control — the same rotation without the loop and gates the
// compiler adds. It must run once. Without it this would be a gate that has only ever seen
// passing input, which is not a gate.

function runSim(cfg) {
  globalThis.initializeAggregator(cfg);
  globalThis.initializeWorker(cfg);
  globalThis.aggregate(globalThis.simulate());
  return JSON.parse(globalThis.flush());
}

/** How many times each action was used, summed over every character. */
function actionCounts(out) {
  const counts = {};
  for (const entry of out?.stats?.character_actions ?? []) {
    for (const [action, stat] of Object.entries(entry?.sources ?? {})) {
      counts[action] = (counts[action] ?? 0) + (stat?.mean ?? 0);
    }
  }
  return counts;
}

const pair = ['rotation_gated', 'rotation_ungated'];
if (!pair.every((n) => files.includes(`${n}.txt`))) {
  console.error(
    `the rotation pair is missing from ${CASES}. Both are required: the gated config is ` +
      `what the compiler emits, and the ungated one is the control that proves this check ` +
      `can fail. Regenerate with: cd backend && python -m scripts.gcsim.emit_sample_configs`,
  );
  process.exit(1);
}

const measured = {};
for (const name of pair) {
  const out = runSim(readFileSync(join(CASES, `${name}.txt`), 'utf8'));
  measured[name] = actionCounts(out);
  console.log(`  ${name}: ${JSON.stringify(measured[name])}`);
}

// The rotation has one burst per cycle, so burst count *is* the cycle count.
const gatedCycles = measured.rotation_gated.burst ?? 0;
const ungatedCycles = measured.rotation_ungated.burst ?? 0;

if (ungatedCycles > 1.5) {
  console.error(
    `the ungated control ran ${ungatedCycles} cycles. It is supposed to run once — that is ` +
      `the failure this check exists to catch. If gcsim's behaviour changed, this check is ` +
      `now measuring nothing and needs rewriting rather than relaxing.`,
  );
  process.exit(1);
}

if (gatedCycles < 2) {
  console.error(
    `the compiled rotation ran ${gatedCycles} cycle(s) over the configured duration. A ` +
      `rotation is a cycle: it should repeat until the clock runs out. Running once is ` +
      `exactly the D.2 failure — a plausible number for a question nobody asked.`,
  );
  process.exit(1);
}

console.log(
  `rotation cycles: gated ${gatedCycles}, ungated control ${ungatedCycles} — ` +
    `the loop and the gates are doing work gcsim can see`,
);
