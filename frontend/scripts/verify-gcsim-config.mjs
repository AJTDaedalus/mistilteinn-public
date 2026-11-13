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

import { flushResult } from '../src/app/sim/gcsim.ts';

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
// The question used to be whether the config *looped*. It no longer loops: a rotation runs
// exactly as long as its author wrote it, so the property checked here is that the emitted
// config performs the authored number of cycles. `rotation_once` is the control — the same
// rotation at `group_repeat` 1. Without it this would be a gate that has only ever seen
// passing input, which is not a gate.
//
// **Skills are counted, not bursts.** The compiler gates bursts, so a starved rotation skips
// one and the count would be measuring energy rather than length.

function runSim(cfg) {
  globalThis.initializeAggregator(cfg);
  globalThis.initializeWorker(cfg);
  globalThis.aggregate(globalThis.simulate());
  // Read through the app's own reader: `flush()`'s shape changed at gcsim v2.50.0, and a
  // second hand-rolled reading here is how one copy ends up right and the other wrong.
  return flushResult(globalThis.flush());
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

const pair = ['rotation_repeated', 'rotation_once'];
if (!pair.every((n) => files.includes(`${n}.txt`))) {
  console.error(
    `the rotation pair is missing from ${CASES}. Both are required: the repeated config is ` +
      `what the compiler emits for a rotation authored with cycles, and the single-cycle one ` +
      `is the control that proves this check can fail. Regenerate with: ` +
      `cd backend && python -m scripts.gcsim.emit_sample_configs`,
  );
  process.exit(1);
}

// **The authored count comes from the manifest, not from the config.** Counting the cycles in
// the emitted file and comparing that to what gcsim ran compares the artefact against itself:
// it passes for any number the compiler emits, and deleting a cycle from the fixture was not
// caught. The generator writes what the rotation was *authored* with; that is the only anchor
// outside the thing under test.
const MANIFEST = join(CASES, 'rotation_cycles.json');
if (!existsSync(MANIFEST)) {
  console.error(
    `${MANIFEST} is missing. It carries the authored cycle count, without which this check ` +
      `can only compare the emitted config to itself. Regenerate with: ` +
      `cd backend && python -m scripts.gcsim.emit_sample_configs`,
  );
  process.exit(1);
}
const authoredCycles = JSON.parse(readFileSync(MANIFEST, 'utf8'));

const measured = {};
const sources = {};
for (const name of pair) {
  sources[name] = readFileSync(join(CASES, `${name}.txt`), 'utf8');
  const out = runSim(sources[name]);
  measured[name] = actionCounts(out);
  console.log(`  ${name}: ${JSON.stringify(measured[name])}`);
}

// The emitter's three decisions, pinned structurally. Each was a real defect: a loop made the
// rotation's length irrelevant, a pinned duration truncated it, and gating every action turned
// a cooldown wait into a silent skip.
for (const name of pair) {
  const text = sources[name];
  const structural = [
    ['while 1', text.includes('while 1'), 'a loop makes the rotation own length irrelevant'],
    ['duration=', text.includes('duration='), 'a pinned clock truncates the rotation'],
    ['.skill.ready', text.includes('.skill.ready'), 'gating a cooldown turns waiting into skipping'],
  ];
  for (const [needle, present, why] of structural) {
    if (present) {
      console.error(`${name} contains \`${needle}\`: ${why}.`);
      process.exit(1);
    }
  }
  if (!text.includes('.burst.ready')) {
    console.error(
      `${name} has no burst gate. Energy is the one readiness condition a rotation cannot ` +
        `satisfy on its own, and an ungated burst hangs gcsim outright rather than failing.`,
    );
    process.exit(1);
  }
}

// Skills are ungated, so gcsim performs every one the rotation asks for. That makes the skill
// count the rotation's length, measured rather than asserted.
const expected = authoredCycles;

// The emitted config must also *write* what the rotation was authored with. This is the half
// that catches a compiler dropping or duplicating a cycle, and it is separate from the half
// that catches gcsim not performing what was written.
for (const name of pair) {
  const written = sources[name].split('\n').filter((l) => l.includes(' skill;')).length;
  if (written !== expected[name]) {
    console.error(
      `${name} was authored with ${expected[name]} cycle(s) but the emitted config writes ` +
        `${written}. The compiler is not emitting the rotation the user wrote.`,
    );
    process.exit(1);
  }
}

if (expected.rotation_once !== 1 || expected.rotation_repeated < 2) {
  console.error(
    `the pair no longer differs: the control writes ${expected.rotation_once} skill(s) and ` +
      `the repeated case ${expected.rotation_repeated}. The control must be one cycle and ` +
      `the other must be several, or this check cannot fail. Fix the generator, not this.`,
  );
  process.exit(1);
}

for (const name of pair) {
  const ran = measured[name].skill ?? 0;
  if (Math.abs(ran - expected[name]) > 0.001) {
    console.error(
      `${name} was authored with ${expected[name]} skill cast(s) and gcsim performed ${ran}. ` +
        `A rotation runs as written, to completion: a mismatch means the emitted config is ` +
        `answering a different question from the one the user wrote.`,
    );
    process.exit(1);
  }
}

console.log(
  `rotation cycles: ${expected.rotation_repeated} authored and performed, control ` +
    `${expected.rotation_once} — the rotation own length is what gcsim runs`,
);
