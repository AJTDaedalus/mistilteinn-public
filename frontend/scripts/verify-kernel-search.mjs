// C.4 — the browser search must pick the same build as the Python optimizer.
//
// C.3's gate pins the kernel's *arithmetic*. This pins its **search**: same inventory, same
// context, same winner. The fixtures come from `artifact_optimizer.optimize`, which is the
// implementation G.1 and G.3 verified.
//
// On near-ties: the Python optimizer computes in f64 and the kernel in f32, diverging by up
// to 3.4e-07, so two builds closer than that could swap places. That is the tolerance doing
// what C.2 argued, not a bug — so the comparison accepts a different winner *only* when the
// two damages agree within tolerance. The fixtures are also checked to have no near-ties, so
// a regeneration that introduces one is visible rather than silently exercising the escape.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { search } from '../src/app/sim/search.ts';

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), '..');
const CASES = join(FRONTEND, '..', 'backend', 'tests', 'fixtures', 'kernel', 'search_cases.json');

/** `docs/CROSSVAL_gcsim.md`. */
const TOLERANCE = 1e-6;

const { cases } = JSON.parse(readFileSync(CASES, 'utf8'));
if (!Array.isArray(cases) || cases.length < 10) {
  console.error(`expected at least 10 search cases, found ${cases?.length ?? 0}`);
  process.exit(1);
}

const failures = [];
let tieAccepted = 0;
let worstDamageRel = 0;

for (const c of cases) {
  const result = search(
    c.inventory.map((p) => ({ id: p.id, slot: p.slot, setId: p.set_id, stats: p.stats })),
    {
      base: c.base,
      hit: {
        multiplier: c.hit.multiplier,
        scalingStat: c.hit.scaling_stat,
        flatDamage: 0,
        baseDamageBonus: 0,
        amplifying: c.hit.amplifying,
        reactionBonus: 0,
      },
      target: {
        level: c.target.level,
        resistance: c.target.resistance,
        defReduction: c.target.def_reduction,
        defIgnore: c.target.def_ignore,
      },
      characterLevel: 90,
      dmgBonusQuantity: `${c.hit.channel}_dmg_bonus`,
      setBonuses: c.set_bonuses.map((b) => ({
        setId: b.set_id,
        piecesRequired: b.pieces_required,
        stats: b.stats,
      })),
      topN: 3,
    },
  );

  const want = c.expected;
  const got = result.builds[0];
  const rel = Math.abs(got.damage - want.winner_damage) / Math.abs(want.winner_damage);
  if (rel > worstDamageRel) worstDamageRel = rel;

  const sameWinner =
    JSON.stringify([...got.artifactIds].sort()) === JSON.stringify([...want.winner_ids].sort());

  if (!sameWinner) {
    if (rel <= TOLERANCE) {
      // A genuine tie inside the tolerance — see the header.
      tieAccepted += 1;
    } else {
      failures.push({ id: c.id, got: got.artifactIds, want: want.winner_ids, rel });
    }
  } else if (rel > TOLERANCE) {
    failures.push({ id: c.id, got: got.damage, want: want.winner_damage, rel });
  }

  // The lossless layer must remove the same pieces: it is arithmetic, not a heuristic, so
  // the two implementations agreeing on *how much* it removed is a real check on both.
  if (result.paretoRemoved !== want.pareto_removed) {
    failures.push({
      id: c.id,
      got: `pareto removed ${result.paretoRemoved}`,
      want: `${want.pareto_removed}`,
      rel: 0,
    });
  }
  if (!result.isExact) {
    failures.push({ id: c.id, got: 'isExact false', want: 'true', rel: 0 });
  }
}

if (failures.length > 0) {
  console.error(`${failures.length}/${cases.length} search cases diverge:`);
  for (const f of failures.slice(0, 5)) {
    console.error(`  ${f.id}: got ${JSON.stringify(f.got)} want ${JSON.stringify(f.want)}` +
      (f.rel ? ` (rel ${f.rel.toExponential(3)})` : ''));
  }
  process.exit(1);
}

if (tieAccepted > 0) {
  // Not a failure, but it means the fixtures now contain builds separated by less than the
  // tolerance — which makes the winner comparison weaker than it looks.
  console.error(
    `${tieAccepted} case(s) matched only via the near-tie escape. Regenerate the fixtures ` +
      `with better-separated builds, or the winner check is not really checking a winner.`,
  );
  process.exit(1);
}

console.log(
  `kernel search matches the Python optimizer on all ${cases.length} cases ` +
    `(worst damage divergence ${worstDamageRel.toExponential(3)}, no ties needed)`,
);
