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

import { parseSample, replayHit, resolveConversions } from '../src/app/sim/recipe.ts';
import { evaluateHit, NO_STATS } from '../src/app/sim/recipe-eval.ts';

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
  { config: 'rotation_gated.txt', calc: 'rotation_gated_calc.json', minHits: 200, stale: [] },
  {
    config: 'noelle_redhorn.txt',
    calc: 'noelle_redhorn_calc.json',
    minHits: 80,
    // Redhorn puts DEF into flat damage; Noelle's burst puts DEF into flat ATK. Both are
    // computed at calibration from stats a candidate is about to change, so both go stale.
    // Asserted here because detection that never fires on real data is not detection.
    stale: ['flatDamage', 'flatAtk'],
  },
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
  // The element and attack tag come from the paired `damage` event, not from `calc` — which
  // publishes `ele` as gcsim's internal enum (19, 14). If the pairing silently produced
  // nothing, every hit would carry an empty element and G.4 would match no bonus to anything.
  const unlabelled = fixture.hits.filter((h) => h.element === '' || h.attackTag < 0);
  if (unlabelled.length > 0) {
    console.error(
      `${c.calc}: ${unlabelled.length} of ${fixture.hits.length} hits have no element or ` +
        `attack tag. The calc/damage pairing produced nothing usable.`,
    );
    process.exit(1);
  }
  const stale = fixture.meta.staleConversions.map((c) => c.term).sort();
  const expected = [...c.stale].sort();
  if (JSON.stringify(stale) !== JSON.stringify(expected)) {
    console.error(
      `${c.calc}: stale-conversion detection expected [${expected}] but found [${stale}].\n` +
        `A recipe that does not know what is baked into it cannot warn a caller about it.`,
    );
    process.exit(1);
  }

  const elements = [...new Set(fixture.hits.map((h) => h.element))].sort();
  console.log(
    `${c.calc}: replayed ${fixture.hits.length} hits, worst rel err ${worst.toExponential(3)}` +
      `, elements [${elements.join(', ')}]` +
      (stale.length > 0 ? `, stale [${stale.join(', ')}]` : ', no stale conversions'),
  );
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


// ── The gate that decides whether any of this is worth having ────────────────────────────
//
// The checks above prove **transcription**: a recipe replays the run it came from. That is
// necessary and it is not the point — a recipe that only reproduces its own calibration is a
// very expensive identity function.
//
// This proves **prediction**. Take the calibration captured at *zero artifact stats*, apply
// the stats a different run actually used, and check the result against that run's own
// numbers. gcsim is the oracle; the recipe is the claim.
//
// Scope, stated: this predicts across **substats**, not across set combinations. A different
// artifact set changes the buffs baked into the calibration, so it needs its own — which is
// why calibration is keyed by set combination in DESIGN §3.
{
  const zero = parseSample(readFileSync(join(FIXTURES, 'rotation_gated_nostats_calc.json'), 'utf8'));
  const real = parseSample(readFileSync(join(FIXTURES, 'rotation_gated_calc.json'), 'utf8'));

  // Exactly what `rotation_gated.txt` adds and `rotation_gated_nostats.txt` omits.
  const candidate = { ...NO_STATS, atkPercent: 0.464, critDmg: 0.62 };

  if (zero.hits.length !== real.hits.length) {
    console.error(
      `the zero-stat and with-stats calibrations disagree on hit count ` +
        `(${zero.hits.length} vs ${real.hits.length}). Adding stats must not change the ` +
        `rotation's structure — if it did, a recipe is not reusable across candidates at all.`,
    );
    process.exit(1);
  }

  let worst = 0;
  let worstAbil = '';
  for (let i = 0; i < zero.hits.length; i++) {
    const predicted = evaluateHit(zero.hits[i], candidate);
    const actual = real.hits[i].gcsimAverageDamage;
    const rel = Math.abs(predicted - actual) / Math.max(Math.abs(actual), 1e-12);
    if (rel > worst) {
      worst = rel;
      worstAbil = zero.hits[i].abil;
    }
  }
  if (!(worst <= TOLERANCE)) {
    console.error(
      `the recipe mispredicts a run it was not calibrated on.\n` +
        `  worst relative error ${worst.toExponential(3)} on "${worstAbil}"\n` +
        `  tolerance ${TOLERANCE.toExponential(0)}\n` +
        `Transcription passing while this fails means the *evaluator* is wrong, not the parser.`,
    );
    process.exit(1);
  }
  console.log(
    `recipe predicts an uncalibrated run: ${zero.hits.length} hits, ` +
      `worst rel err ${worst.toExponential(3)}`,
  );
}


// ── Conversions, measured from a probe rather than transcribed ──────────────────────────────
//
// `Redhorn Stonethresher` converts DEF into flat damage. Frozen at calibration, that term does
// not move when a candidate's DEF does — and for this build it is **83 % of the damage**.
//
// A probe calibration at a perturbed DEF identifies the source and the coefficient from
// gcsim's own numbers. `TASKS_passive_port.md` planned to transcribe them from Go; this needs
// no coefficient, no per-weapon record, and catches character kits a weapon list would miss.
{
  const baseline = parseSample(readFileSync(join(FIXTURES, 'noelle_redhorn_calc.json'), 'utf8'));
  const probe = parseSample(readFileSync(join(FIXTURES, 'noelle_redhorn_probe_calc.json'), 'utf8'));
  const target = parseSample(readFileSync(join(FIXTURES, 'noelle_redhorn_target_calc.json'), 'utf8'));
  const candidate = { ...NO_STATS, defPercent: 0.9, critDmg: 0.4 };

  // Noelle's burst **snapshots** DEF at cast, so its flat-ATK term moves by a factor no
  // hit-time stat ratio equals. A two-point probe cannot resolve that, and the recipe says so
  // rather than guessing — these hits are excluded here and remain reported as stale.
  const hitTime = baseline.hits
    .map((h, i) => ({ h, i }))
    .filter(({ h }) => h.calibratedFlat.atk === 0);

  const worstOver = () => hitTime.reduce((worst, { h, i }) => {
    const actual = target.hits[i].gcsimAverageDamage;
    return Math.max(worst, Math.abs(evaluateHit(h, candidate) - actual) / Math.max(actual, 1e-12));
  }, 0);

  const before = worstOver();
  const { resolved, unresolved } = resolveConversions(baseline, probe);
  const after = worstOver();

  if (resolved === 0) {
    console.error('the probe resolved no conversions at all — detection that never fires.');
    process.exit(1);
  }
  if (!(before > 0.01)) {
    console.error(
      `the frozen recipe was already accurate to ${(before * 100).toFixed(2)}% on these hits, ` +
        `so this case cannot show a probe fixing anything. Pick a target further from the ` +
        `calibration.`,
    );
    process.exit(1);
  }
  if (!(after <= TOLERANCE)) {
    console.error(
      `resolving conversions did not make the prediction exact.\n` +
        `  before ${(before * 100).toFixed(2)}%   after ${after.toExponential(3)}\n` +
        `  resolved ${resolved}, unresolved ${unresolved}`,
    );
    process.exit(1);
  }
  const stale = baseline.meta.staleConversions.map((c) => c.term);
  if (!stale.includes('flatAtk')) {
    console.error(
      `the snapshotted flat-ATK conversion should still be reported stale, but stale is ` +
        `[${stale}]. A recipe that stops warning about something it did not fix is worse ` +
        `than one that never warned.`,
    );
    process.exit(1);
  }
  console.log(
    `probe resolved ${resolved} conversions (${unresolved} unresolved): ` +
      `hit-time prediction ${(before * 100).toFixed(2)}% → ${after.toExponential(3)}, ` +
      `still stale [${stale.join(', ')}]`,
  );
}
