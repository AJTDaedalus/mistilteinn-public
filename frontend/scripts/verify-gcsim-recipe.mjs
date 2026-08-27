// G.2/G.3 — the recipe parser against the real gcsim run it claims to transcribe.
//
// Two assertions, and the second is the one that matters:
//
//   1. Replaying every hit of the committed fixture reproduces gcsim's own `avg_crit_dmg`.
//      That proves the decomposition in `RESEARCH_gcsim_calibration.md` §2 is transcribed
//      correctly rather than approximately.
//   2. Regenerating the sample from the committed config and seed reproduces the fixture.
//      Without this the fixture silently becomes the oracle the moment the pin moves —
//      which is exactly how fairy shipped a stale golden fixture that sat green for months.
//
// A standalone Node script rather than a vitest spec, for the reason `verify-kernel.mjs`
// gives: it reads fixtures from disk, and Angular's test builder targets the browser where
// `node:fs` does not exist.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { parseSample, replayHit } from '../src/app/sim/recipe.ts';

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), '..');
const FIXTURES = join(FRONTEND, '..', 'backend', 'tests', 'fixtures', 'gcsim_sample');
const WASM = join(FRONTEND, 'gcsim', 'gcsim.wasm');
const SEED = '12345';

// Two calibrations, because one is not enough to exercise the parser. The Ayaka rotation is
// entirely ATK-scaling with no flat damage and no amplification, so a gate built on it alone
// cannot catch a mis-transcribed `flat_dmg` or `use_def` — the mutation survives while the
// numbers still match. Noelle + Redhorn Stonethresher covers both, and Redhorn is the weapon
// this whole plan exists to stop the optimizer getting wrong.
//
// Still not covered by either: crit rate above 100 %, and amplifying reactions. Named in
// `PROVENANCE.md` rather than left for someone to discover from a surviving mutation.
const CASES = [
  { config: 'rotation_gated.txt', calc: 'rotation_gated_calc.json', minHits: 200 },
  { config: 'noelle_redhorn.txt', calc: 'noelle_redhorn_calc.json', minHits: 80 },
];

// The decomposition is exact in float64, so this is a float-noise budget, not a tolerance for
// disagreement. `RESEARCH_gcsim_calibration.md` §2 measured the worst relation at 1.986e-16.
const TOLERANCE = 1e-12;

for (const c of CASES) {
  const fixture = parseSample(readFileSync(join(FIXTURES, c.calc), 'utf8'));
  if (fixture.hits.length < c.minHits) {
    console.error(`${c.calc}: expected ${c.minHits}+ hits, got ${fixture.hits.length}`);
    process.exit(1);
  }
  let worst = 0;
  for (const hit of fixture.hits) {
    const rel = Math.abs(replayHit(hit) - hit.gcsimAverageDamage) /
      Math.max(Math.abs(hit.gcsimAverageDamage), 1e-12);
    worst = Math.max(worst, rel);
  }
  if (!(worst <= TOLERANCE)) {
    console.error(
      `${c.calc}: replaying the recipe disagrees with gcsim's own numbers.\n` +
        `  worst relative error ${worst.toExponential(3)} over ${fixture.hits.length} hits\n` +
        `  tolerance ${TOLERANCE.toExponential(0)}\n` +
        `This is a transcription error, not a modelling one: every term is published.`,
    );
    process.exit(1);
  }
  console.log(`${c.calc}: replayed ${fixture.hits.length} hits, worst rel err ${worst.toExponential(3)}`);
}

if (!existsSync(WASM)) {
  // Loud, not skipped. A skipped check BLOCKS — it means *could not check*.
  console.error(
    `gcsim's browser build is missing at ${WASM}, so the fixture cannot be regenerated.\n` +
      `Run \`npm run gcsim:build\`. This gate cannot vouch for the fixture without it.`,
  );
  process.exit(2);
}

await import(join(FRONTEND, 'gcsim', 'wasm_exec.js'));
const go = new globalThis.Go();
const { instance } = await WebAssembly.instantiate(readFileSync(WASM), go.importObject);
void go.run(instance);
await new Promise((resolve) => setTimeout(resolve, 50));

for (const c of CASES) {
  const config = readFileSync(join(FIXTURES, c.config), 'utf8');
  const committed = parseSample(readFileSync(join(FIXTURES, c.calc), 'utf8'));
  const regenerated = parseSample(globalThis.sample(config, SEED));

  if (regenerated.hits.length !== committed.hits.length) {
    console.error(
      `${c.calc} is stale: ${committed.hits.length} hits committed, ` +
        `${regenerated.hits.length} regenerated at the pin from the same config and seed.`,
    );
    process.exit(1);
  }
  let worstDrift = 0;
  for (let i = 0; i < committed.hits.length; i++) {
    const a = committed.hits[i];
    const b = regenerated.hits[i];
    if (a.abil !== b.abil) {
      console.error(`${c.calc} hit ${i}: committed "${a.abil}" but regenerated "${b.abil}"`);
      process.exit(1);
    }
    worstDrift = Math.max(
      worstDrift,
      Math.abs(a.gcsimAverageDamage - b.gcsimAverageDamage) /
        Math.max(Math.abs(b.gcsimAverageDamage), 1e-12),
    );
  }
  if (!(worstDrift <= TOLERANCE)) {
    console.error(
      `${c.calc} no longer matches the pin: worst drift ${worstDrift.toExponential(3)}. ` +
        `Re-capture it, and say in the PR what moved.`,
    );
    process.exit(1);
  }
  console.log(`${c.calc}: matches the pin, worst drift ${worstDrift.toExponential(3)}`);
}
