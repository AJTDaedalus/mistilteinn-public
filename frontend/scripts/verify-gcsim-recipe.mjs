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
// Still not covered: crit rate above 100 %. Amplifying reactions were too, until the
// `xiangling_vape` pair (2026-11-13). Named in `PROVENANCE.md` rather than left for someone to
// discover from a surviving mutation.
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
  {
    // The first **multi-character** fixture, from a rotation the owner actually runs: Skirk,
    // Furina, Yelan and Escoffier, with `+params`, a `for` loop, `energy every` and a custom
    // target. `PROVENANCE.md` named multi-character as untested, and the two solo fixtures
    // could not have caught a swap, an off-field hit, or three elements in one rotation.
    config: 'skirk_team.txt',
    calc: 'skirk_team_calc.json',
    minHits: 200,
    // **Empty, and that is the fix rather than a regression.** This expected `['flatDamage']`
    // until hits carried an owner. Every flat-bearing hit in this fixture belongs to
    // `char_index` 1 or 2 — Furina and Yelan — and the calibrated character's 74 landed hits
    // carry none. Those terms are the teammates' *equipped stats*, which the config states
    // outright (`furina add stats atk=311 … hp=6035 …`), not conversions: nothing in a search
    // moves them and no probe can identify them.
    //
    // The discrimination is the point, and `noelle_redhorn` above is the control: solo, every
    // hit `char_index` 0, and her DEF-to-ATK conversions are **still reported**. A change that
    // simply silenced the warning would have silenced hers too.
    stale: [],
  },
  {
    // The first **amplifying** fixture: Xiangling vaporizing off Xingqiu and Yelan, with
    // Bennett. Ten of Xiangling's 27 landed hits vaporize (Pyro onto Hydro, ×1.5), and her
    // teammates' Hydro onto her Pyro gives the ×2 side. Replaying it is what checks that an
    // amplified hit's `gcsimAverageDamage` is gcsim's *post*-reaction average — `avg_crit_dmg`
    // is written before amplification (`pkg/enemy/damage.go:164`), so reading it made every
    // vaporize hit disagree with its own replay by exactly the multiplier.
    config: 'xiangling_vape.txt',
    calc: 'xiangling_vape_calc.json',
    minHits: 80,
    // Bennett's burst lands in Xiangling's flat ATK at zero artifact stats. It is computed
    // from *Bennett's* base ATK, so no probe of hers can resolve it — reported, as it should be.
    stale: ['flatAtk'],
  },
  {
    // The same rotation at +250 artifact EM — the run the EM gate below predicts.
    config: 'xiangling_vape_em.txt',
    calc: 'xiangling_vape_em_calc.json',
    minHits: 80,
    stale: ['flatAtk'],
  },
  // **EM folded into flat damage** (2026-11-13): a calibration, its probe and a +300 EM run
  // for each of two characters. Sethos is the clean case — his EM enters only `FlatDmg`
  // (`internal/characters/sethos/{aimed,attack}.go`) — and Nahida the real one, whose
  // Tri-Karma carries an EM-driven A4 and whose bloom team adds transformative hits.
  // Every flat term is reported at parse time: nothing has been resolved yet.
  { config: 'sethos.txt', calc: 'sethos_calc.json', minHits: 60, stale: ['flatDamage'] },
  {
    config: 'sethos_probe.txt', calc: 'sethos_probe_calc.json', minHits: 60,
    stale: ['flatDamage'],
  },
  { config: 'sethos_em.txt', calc: 'sethos_em_calc.json', minHits: 60, stale: ['flatDamage'] },
  { config: 'nahida.txt', calc: 'nahida_calc.json', minHits: 80, stale: ['flatDamage'] },
  {
    config: 'nahida_probe.txt', calc: 'nahida_probe_calc.json', minHits: 80,
    stale: ['flatDamage'],
  },
  { config: 'nahida_em.txt', calc: 'nahida_em_calc.json', minHits: 80, stale: ['flatDamage'] },
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
  // `''` is our own sentinel for a pairing that produced nothing. `'none'` is gcsim's name
  // for the empty element since `61f578730` renamed it (it stringified as `''` before), so
  // after the 2026-09-19 re-pin the same failure arrives spelled differently — and a check
  // looking only for `''` would have passed a fixture where every hit was unlabelled.
  const UNLABELLED = new Set(['', 'none']);
  const unlabelled = fixture.hits.filter((h) => UNLABELLED.has(h.element) || h.attackTag < 0);
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


// ── Elemental Mastery, predicted across two artifact-EM builds ─────────────────────────────
//
// The defect fixed on 2026-11-13 (owner: "Fix it"): a gcsim recipe froze the amplifying
// multiplier at the calibration's EM, so **artifact EM was worth exactly nothing** to a
// vaporize or melt build. `parseSample` now carries each hit's snapshot `em` and its reaction,
// and `evaluateHit` recomputes the multiplier through `damage.ts:amplifyingMultiplier` — the
// function the single-hit kernel uses.
//
// The claim checked here is the one a search acts on: **the recipe's predicted gain from
// artifact EM equals the gain gcsim measures**, calibrated at zero artifact EM and predicting
// a run at +250. Measured at the fix: gcsim +23,461.20, predicted +23,461.20 (1.1e-7 relative),
// where the frozen multiplier predicted −0.0017.
//
// **The tolerance is 1e-6, not the 1e-12 above, and that is argued rather than loosened.**
// The amplifying term goes through `damage.ts`, which rounds to f32 at every step so the CPU
// and GPU backends agree (`docs/CROSSVAL_gcsim.md` measures that at 3.51e-07 worst case and
// sets the kernel's tolerance at 1e-6 from it). Everything else in a hit is still f64.
{
  const zero = parseSample(readFileSync(join(FIXTURES, 'xiangling_vape_calc.json'), 'utf8'));
  const more = parseSample(readFileSync(join(FIXTURES, 'xiangling_vape_em_calc.json'), 'utf8'));
  const candidate = { ...NO_STATS, elementalMastery: 250 }; // what `_em.txt` adds
  const EM_TOLERANCE = 1e-6;

  if (zero.hits.length !== more.hits.length) {
    console.error(
      `the zero-EM and +EM calibrations disagree on hit count ` +
        `(${zero.hits.length} vs ${more.hits.length}); EM must not move the rotation.`,
    );
    process.exit(1);
  }
  // Counted off gcsim's own multiplier, not off `amplifying`: a parser that stopped naming the
  // reaction must fail the *price* check below, not disappear into this precondition.
  const amplified = zero.hits.filter((h) => h.mine && h.ampMultiplier !== 1).length;
  if (amplified === 0) {
    // A gate on EM over a recipe with nothing amplifying would pass with the defect present.
    console.error('the vaporize fixture has no amplifying hit of the calibrated character.');
    process.exit(1);
  }

  let measured = 0;
  let predicted = 0;
  let worst = 0;
  let worstAbil = '';
  for (let i = 0; i < zero.hits.length; i++) {
    const before = evaluateHit(zero.hits[i], NO_STATS);
    const after = evaluateHit(zero.hits[i], candidate);
    const actual = more.hits[i].gcsimAverageDamage;
    measured += actual - zero.hits[i].gcsimAverageDamage;
    predicted += after - before;
    const rel = Math.abs(after - actual) / Math.max(Math.abs(actual), 1e-12);
    if (rel > worst) {
      worst = rel;
      worstAbil = zero.hits[i].abil;
    }
  }
  const deltaErr = Math.abs(predicted - measured) / Math.abs(measured);
  if (!(measured > 0) || !(deltaErr <= EM_TOLERANCE) || !(worst <= EM_TOLERANCE)) {
    console.error(
      `the recipe mis-prices artifact EM against gcsim.\n` +
        `  gcsim's gain ${measured.toFixed(2)}, predicted ${predicted.toFixed(2)} ` +
        `(rel err ${deltaErr.toExponential(3)})\n` +
        `  worst hit ${worst.toExponential(3)} on "${worstAbil}", tolerance ` +
        `${EM_TOLERANCE.toExponential(0)}`,
    );
    process.exit(1);
  }
  console.log(
    `artifact EM priced as gcsim prices it: ${amplified} vaporize hits, gain ` +
      `${measured.toFixed(2)} measured vs ${predicted.toFixed(2)} predicted ` +
      `(${deltaErr.toExponential(3)}), worst hit ${worst.toExponential(3)}`,
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


// ── Elemental Mastery folded into flat damage ──────────────────────────────────────────────
//
// The gap DECISIONS §39 left open. gcsim writes the EM part of a hit such as Sethos's
// Shadowpiercing Shot or Nahida's Tri-Karma as `FlatDmg = em × k`. With EM outside the probe
// that term did not move, so `resolveConversions` filed it **constant**: artifact EM was
// worth nothing to it and no warning said so. The probe now moves EM by +100, and the term
// resolves to `from: 'em'` like a Redhorn DEF term resolves to `from: 'def'`.
//
// **Sethos is the price check.** His EM enters nothing but `FlatDmg`, so the recipe's whole
// predicted gain from +300 artifact EM must equal gcsim's measured gain. Everything is f64 —
// no amplifying term — so the tolerance is the 1e-12 transcription budget, not the EM gate's
// f32 one.
{
  const baseline = parseSample(readFileSync(join(FIXTURES, 'sethos_calc.json'), 'utf8'));
  const probe = parseSample(readFileSync(join(FIXTURES, 'sethos_probe_calc.json'), 'utf8'));
  const more = parseSample(readFileSync(join(FIXTURES, 'sethos_em_calc.json'), 'utf8'));
  const candidate = { ...NO_STATS, elementalMastery: 300 }; // what `sethos_em.txt` adds

  const gain = () => {
    let measured = 0;
    let predicted = 0;
    let worst = 0;
    let worstAbil = '';
    for (let i = 0; i < baseline.hits.length; i++) {
      const h = baseline.hits[i];
      const after = evaluateHit(h, candidate);
      const actual = more.hits[i].gcsimAverageDamage;
      measured += actual - h.gcsimAverageDamage;
      predicted += after - evaluateHit(h, NO_STATS);
      const rel = Math.abs(after - actual) / Math.max(Math.abs(actual), 1e-12);
      if (rel > worst) {
        worst = rel;
        worstAbil = h.abil;
      }
    }
    return { measured, predicted, worst, worstAbil };
  };

  if (baseline.hits.length !== more.hits.length || baseline.hits.length !== probe.hits.length) {
    console.error('the Sethos triple disagrees on hit count; EM must not move the rotation.');
    process.exit(1);
  }
  // Before resolution the flat term is frozen, so the recipe predicts no gain at all — the
  // defect, measured rather than asserted. If this ever reads non-zero the case has stopped
  // demonstrating anything.
  const frozen = gain();
  const { resolved, unresolved } = resolveConversions(baseline, probe);
  const priced = gain();
  const fromEm = baseline.hits.filter((h) => h.mine && h.conversions.flatDamage?.from === 'em');
  const deltaErr = Math.abs(priced.predicted - priced.measured) / Math.abs(priced.measured);

  if (frozen.predicted !== 0 || fromEm.length === 0 || unresolved !== 0
    || baseline.meta.staleConversions.length !== 0) {
    console.error(
      `the probe did not resolve Sethos's EM-in-flat terms.\n` +
        `  frozen gain ${frozen.predicted.toFixed(2)} (expected 0), resolved ${resolved}, ` +
        `unresolved ${unresolved}, from EM ${fromEm.length}, stale ` +
        `[${baseline.meta.staleConversions.map((c) => c.term)}]`,
    );
    process.exit(1);
  }
  if (!(priced.measured > 0) || !(deltaErr <= TOLERANCE) || !(priced.worst <= TOLERANCE)) {
    console.error(
      `the recipe mis-prices EM folded into flat damage against gcsim.\n` +
        `  gcsim's gain ${priced.measured.toFixed(2)}, predicted ${priced.predicted.toFixed(2)} ` +
        `(rel err ${deltaErr.toExponential(3)})\n` +
        `  worst hit ${priced.worst.toExponential(3)} on "${priced.worstAbil}", tolerance ` +
        `${TOLERANCE.toExponential(0)}`,
    );
    process.exit(1);
  }
  console.log(
    `EM in flat damage priced as gcsim prices it: ${fromEm.length} Sethos hits resolved to EM, ` +
      `gain ${priced.measured.toFixed(2)} measured vs ${priced.predicted.toFixed(2)} predicted ` +
      `(${deltaErr.toExponential(3)}; frozen predicted ${frozen.predicted.toFixed(2)}), ` +
      `worst hit ${priced.worst.toExponential(3)}`,
  );
}

// **Nahida is the honesty check.** Her Tri-Karma's flat term resolves to EM exactly — checked
// here against gcsim's own `flat_dmg` at +300 EM — but two more things move with her EM and
// neither is priced: her A4 turns EM above 200 into Tri-Karma DMG% and CRIT Rate (capped, so a
// two-point slope would be a guess past the cap), and her bloom hits' damage is gcsim's
// transformative EM curve. Both must be **reported**, not silently frozen — the old probe
// filed every one of these thirteen terms `constant` and the stale list was empty.
{
  const baseline = parseSample(readFileSync(join(FIXTURES, 'nahida_calc.json'), 'utf8'));
  const probe = parseSample(readFileSync(join(FIXTURES, 'nahida_probe_calc.json'), 'utf8'));
  const more = parseSample(readFileSync(join(FIXTURES, 'nahida_em_calc.json'), 'utf8'));
  const EM = 300; // what `nahida_em.txt` adds
  resolveConversions(baseline, probe);

  const triKarma = baseline.hits
    .map((h, i) => ({ h, i }))
    .filter(({ h }) => h.mine && h.abil.startsWith('Tri-Karma'));
  let worst = 0;
  for (const { h, i } of triKarma) {
    const conversion = h.conversions.flatDamage;
    if (conversion?.from !== 'em') {
      console.error(`Tri-Karma hit ${i} did not resolve to EM: ${JSON.stringify(conversion)}`);
      process.exit(1);
    }
    const predicted = conversion.perUnit * (h.calibratedEm + EM);
    const actual = more.hits[i].flatDamage;
    worst = Math.max(worst, Math.abs(predicted - actual) / actual);
  }
  if (triKarma.length === 0 || !(worst <= TOLERANCE)) {
    console.error(
      `Tri-Karma's EM-in-flat term does not follow gcsim: ${triKarma.length} hits, ` +
        `worst ${worst.toExponential(3)}`,
    );
    process.exit(1);
  }

  const stale = baseline.meta.staleConversions.map((c) => c.term).sort();
  const staleFlat = baseline.hits.filter(
    (h) => h.mine && h.flatDamage !== 0 && h.conversions.flatDamage === undefined,
  );
  if (JSON.stringify(stale) !== JSON.stringify(['bonusDmg', 'critRate', 'flatDamage'])
    || staleFlat.some((h) => h.abil.startsWith('Tri-Karma'))
    || !staleFlat.every((h) => h.abil.startsWith('bloom'))) {
    console.error(
      `Nahida's unpriced EM effects are not reported as they should be.\n` +
        `  stale [${stale}], unresolved flat on [${[...new Set(staleFlat.map((h) => h.abil))]}]\n` +
        `A recipe that resolves the part it can and goes quiet about the rest is worse than ` +
        `one that warned about all of it.`,
    );
    process.exit(1);
  }

  // How much of gcsim's measured gain the recipe now prices — reported, not gated, because the
  // remainder is exactly what the stale list above names.
  let measured = 0;
  let predicted = 0;
  const candidate = { ...NO_STATS, elementalMastery: EM };
  for (let i = 0; i < baseline.hits.length; i++) {
    measured += more.hits[i].gcsimAverageDamage - baseline.hits[i].gcsimAverageDamage;
    predicted += evaluateHit(baseline.hits[i], candidate) - evaluateHit(baseline.hits[i], NO_STATS);
  }
  console.log(
    `Nahida: ${triKarma.length} Tri-Karma flat terms follow gcsim (worst ` +
      `${worst.toExponential(3)}); still reported [${stale.join(', ')}] — the recipe prices ` +
      `${predicted.toFixed(2)} of gcsim's ${measured.toFixed(2)} gain from +${EM} EM ` +
      `(${((predicted / measured) * 100).toFixed(1)} %), where the old probe priced 0`,
  );
}
