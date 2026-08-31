/**
 * Why a gated rotation goes unstable, measured rather than argued.
 *
 *     npm run probe:energy
 *
 * `BACKLOG_optimize.md` §8 proposed a mechanism and named the experiment that would settle it:
 * a rotation is unstable because its burst is **energy-marginal**. The compiler gates every
 * action on `.ready` (`DESIGN_rotation.md` §3.4, deliberately, so a rotation never deadlocks),
 * gcsim's particle generation carries RNG, so a burst that is borderline fires on some
 * iterations and not others. Its instance count then varies and `stabilityFrom` marks the
 * rotation unstable — **by construction**, not by accident.
 *
 * Run against the committed `rotation_gated.txt` (Ayaka, 90 s, burst gated on `.ready`) at 40
 * iterations per point, this is what came back:
 *
 *       ER      burst mean    burst sd   verdict
 *        0%        2.0250     0.1581     UNSTABLE
 *       10%        2.2250     0.4229     UNSTABLE
 *       20%        2.9000     0.3038     UNSTABLE
 *       30%        3.0000     0.0000     stable
 *       45%        3.0000     0.0000     stable
 *       60%        3.0000     0.0000     stable
 *      100%        3.0000     0.0000     stable
 *
 * **Confirmed, with a sharp boundary.** Below 30 % ER the burst count varies; at and above it
 * the rotation performs identically every iteration. The hypothesis predicted exactly this
 * shape — stable above the threshold, unstable below — and the alternative it had to beat
 * ("unstable at every ER, so the cause is elsewhere") is ruled out.
 *
 * It is not a CI gate: it takes minutes and it measures gcsim's behaviour, not this repo's.
 * It is here so the claim can be re-derived rather than believed.
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { run } from '../src/app/sim/gcsim.ts';

/** A copy of `instancesFrom`; the service itself carries Angular decorators node cannot load. */
function instancesFrom(raw, characters) {
  const perCharacter = raw?.stats?.character_actions;
  if (!Array.isArray(perCharacter)) return {};
  const out = {};
  perCharacter.forEach((entry, index) => {
    const who = characters[index] ?? `character ${index + 1}`;
    for (const [action, stat] of Object.entries(entry?.sources ?? {})) {
      if (typeof stat?.mean === 'number' && typeof stat?.sd === 'number') {
        out[`${who} ${action}`] = { mean: stat.mean, sd: stat.sd };
      }
    }
  });
  return out;
}

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), '..');
const CONFIG = join(FRONTEND, '..', 'backend', 'tests', 'fixtures', 'gcsim_sample',
  'rotation_gated.txt');
const WASM = join(FRONTEND, 'gcsim', 'gcsim.wasm');
const ITERATIONS = 40;

if (!existsSync(WASM)) {
  console.error('gcsim wasm missing — run `npm run gcsim:build`.');
  process.exit(2);
}

await import(join(FRONTEND, 'gcsim', 'wasm_exec.js'));
const go = new globalThis.Go();
const { instance } = await WebAssembly.instantiate(readFileSync(WASM), go.importObject);
void go.run(instance);
await new Promise((r) => setTimeout(r, 50));

const base = readFileSync(CONFIG, 'utf8');

/** The same config with an ER value spliced into the stats line. */
function withEnergyRecharge(text, er) {
  return text.replace(
    /(kamisatoayaka add stats [^;]*)/,
    (m) => `${m} er=${er.toFixed(3)}`,
  );
}

console.log(`config: rotation_gated.txt (Ayaka, gated burst, 90s), ${ITERATIONS} iterations\n`);
console.log('  ER      burst mean    burst sd   verdict');
console.log('  ------  ------------  ---------  -----------------------------');

for (const er of [0, 0.10, 0.20, 0.30, 0.45, 0.60, 1.00]) {
  const config = withEnergyRecharge(base, er);
  let result;
  try {
    result = run(globalThis, config, ITERATIONS);
  } catch (err) {
    console.log(`  ${(er * 100).toFixed(0).padStart(4)}%  FAILED: ${err.message}`);
    continue;
  }
  const instances = instancesFrom(result.raw, ['kamisatoayaka']);
  const burst = Object.entries(instances).find(([k]) => k.endsWith(' burst'))?.[1];
  if (!burst) { console.log(`  ${(er * 100).toFixed(0).padStart(4)}%  no burst rows`); continue; }
  const verdict = burst.sd === 0 ? 'stable' : 'UNSTABLE — count varies';
  console.log(
    `  ${(er * 100).toFixed(0).padStart(4)}%  ${burst.mean.toFixed(4).padStart(12)}` +
    `  ${burst.sd.toFixed(4).padStart(9)}  ${verdict}`,
  );
}
