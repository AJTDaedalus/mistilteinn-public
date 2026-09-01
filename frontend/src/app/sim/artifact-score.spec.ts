import { describe, expect, it } from 'vitest';

import type { Recipe, RecipeHit } from './recipe';
import { type StatPool, scoreArtifact, scoreForSlot } from './artifact-score';

/**
 * Scoring one artifact against one build, over its rotation.
 *
 * `DESIGN_artifact_ranking.md` Task 3 — the smallest thing that proves the engine choice. The
 * engine is the recipe evaluator by owner ruling (`DECISIONS.md` §22), not a weights table and
 * not the single-hit chain.
 */

const hit = (over: Partial<RecipeHit> = {}): RecipeHit => ({
  mine: true,
  abil: 'x', attackTag: 1, element: 'cryo', talent: 2, scaling: 'atk', flatDamage: 0,
  calibratedScaling: 1000, bonusDmg: 0, critRate: 0, critDmg: 0,
  conversions: {},
  calibratedBase: { atk: 1000, hp: 10000, def: 800 },
  calibratedPercent: { atk: 0, hp: 0, def: 0 },
  calibratedFlat: { atk: 0, hp: 0, def: 0 },
  defMultiplier: 0.5, resMultiplier: 0.9, ampMultiplier: 1, gcsimAverageDamage: 900, ...over,
});

const recipe = (hits: RecipeHit[] = [hit()]): Recipe => ({
  hits,
  seed: '1',
  meta: { seed: '1', staleConversions: [], unstable: [], calibratedSetIds: [], minimumEnergyRecharge: null },
});

const pool = (over: Record<string, number> = {}): StatPool => ({ ...over });

/** Five slots, all contributing nothing, so a candidate's effect is the whole difference. */
const bare = (): StatPool[] => [pool(), pool(), pool(), pool(), pool()];

describe('scoreArtifact', () => {
  it('reports the build as it stands, the build with the piece, and the difference', () => {
    const found = scoreArtifact(recipe(), bare(), pool({ atk_pct: 0.5 }), 2);

    expect(found.delta).toBeCloseTo(found.damage - found.current, 9);
    expect(found.damage).toBeGreaterThan(found.current);
  });

  it('gives a worse piece a negative delta', () => {
    // **The number a player is actually asking for.** A score says how good a piece is; a
    // signed delta says whether to keep it, which is what the Fribbels audit identifies as
    // the difference between a sortable list and a decidable one.
    const equipped = bare();
    equipped[2] = pool({ atk_pct: 0.5 });

    const found = scoreArtifact(recipe(), equipped, pool({ atk_pct: 0.1 }), 2);

    expect(found.delta).toBeLessThan(0);
  });

  it('gives an identical piece a delta of zero', () => {
    const equipped = bare();
    equipped[3] = pool({ crit_rate: 0.2 });

    const found = scoreArtifact(recipe(), equipped, pool({ crit_rate: 0.2 }), 3);

    expect(found.delta).toBeCloseTo(0, 9);
  });

  it('replaces the named slot and leaves the others wearing what they had', () => {
    // Slot 0 keeps its ATK% when slot 4 is the one being scored, so the candidate's effect is
    // measured *on top of* the rest of the build rather than instead of it.
    const equipped = bare();
    equipped[0] = pool({ atk_pct: 1 });

    const found = scoreArtifact(recipe(), equipped, pool({ atk_pct: 1 }), 4);

    expect(found.current).toBeGreaterThan(0);
    expect(found.damage).toBeGreaterThan(found.current);
  });

  it('does not mutate the caller’s equipped array', () => {
    // **A splice here would leave the build wearing the last piece scored**, and every later
    // score would be measured against it — an inventory sweep would drift piece by piece with
    // nothing reporting a problem.
    const equipped = bare();
    const before = JSON.stringify(equipped);

    scoreArtifact(recipe(), equipped, pool({ atk_pct: 9 }), 1);

    expect(JSON.stringify(equipped)).toBe(before);
  });

  it('refuses a slot the build does not have', () => {
    // A number about nothing, rather than an exception, is the failure mode this repo names
    // most often.
    expect(() => scoreArtifact(recipe(), bare(), pool(), 5)).toThrow(RangeError);
    expect(() => scoreArtifact(recipe(), bare(), pool(), -1)).toThrow(RangeError);
  });
});

describe('scoreForSlot', () => {
  it('agrees with scoring each piece one at a time', () => {
    // The batch computes the build's own damage once; the single does it per call. They must
    // not diverge, because the batch is what an inventory sweep will use.
    const equipped = bare();
    equipped[1] = pool({ crit_dmg: 0.3 });
    const candidates = [
      { id: 'a', stats: pool({ atk_pct: 0.2 }) },
      { id: 'b', stats: pool({ crit_dmg: 0.9 }) },
      { id: 'c', stats: pool({}) },
    ];

    const batch = scoreForSlot(recipe(), equipped, candidates, 1);

    for (const { id, score } of batch) {
      const one = scoreArtifact(
        recipe(), equipped, candidates.find((c) => c.id === id)!.stats, 1,
      );
      expect(score.damage).toBeCloseTo(one.damage, 9);
      expect(score.delta).toBeCloseTo(one.delta, 9);
    }
  });

  it('reports the same current damage for every candidate', () => {
    // It is the build's own number and does not depend on what is being scored against it.
    const found = scoreForSlot(recipe(), bare(), [
      { id: 'a', stats: pool({ atk_pct: 1 }) },
      { id: 'b', stats: pool({ atk_pct: 2 }) },
    ], 0);

    expect(found[0].score.current).toBe(found[1].score.current);
  });

  it('scores an empty candidate list without touching the build', () => {
    expect(scoreForSlot(recipe(), bare(), [], 0)).toEqual([]);
  });
});

describe('scoreForSlot across two calibrated states', () => {
  /**
   * §10 — a swap that drops a build below four of its set lands in a *different* calibrated
   * state, and scoring it under the old recipe credits a bonus it would no longer have.
   */
  /**
   * The same rotation without the 4-piece bonus, modelled as the bonus actually is: a
   * `bonusDmg` term the evaluator reads (`recipe-eval.ts` — `base * (1 + bonus) * …`).
   *
   * The first version of this helper varied `calibratedScaling`, which the evaluator does not
   * read at all — so both recipes produced identical damage and two of these tests asserted
   * `1350 < 1350`. A stub that changes nothing tests nothing.
   */
  const withBonus = () => recipe([hit({ bonusDmg: 0.5 })]);
  const weaker = () => recipe([hit({ bonusDmg: 0 })]);

  it('evaluates the swapped build on the recipe the caller names for it', () => {
    const found = scoreForSlot(
      withBonus(), bare(),
      [{ id: 'keeps', stats: pool({ atk_pct: 0.5 }) },
       { id: 'breaks', stats: pool({ atk_pct: 0.5 }) }],
      0,
      (id) => (id === 'breaks' ? weaker() : withBonus()),
    );
    const [keeps, breaks] = found;

    // Identical stats, so the *only* difference is which state the build ends up in.
    expect(breaks.score.damage).toBeLessThan(keeps.score.damage);
  });

  it('measures against the build as it stands, bonus included', () => {
    // `current` stays on the original recipe for every candidate: the build really does have
    // the bonus today, and that is what a swap is being compared to. Recomputing `current` on
    // the weaker recipe would compare two builds that neither exist.
    const found = scoreForSlot(
      withBonus(), bare(), [{ id: 'breaks', stats: pool({ atk_pct: 0.5 }) }], 0,
      () => weaker(),
    );

    expect(found[0].score.current).toBeCloseTo(
      scoreForSlot(withBonus(), bare(), [{ id: 'x', stats: pool() }], 0)[0].score.current, 9,
    );
  });

  it('can turn an apparent upgrade into the loss it really is', () => {
    // The defect in one assertion. Under the four-piece recipe this piece is a clear gain;
    // once the swap is scored in the state it actually produces, it is not — which is what
    // "an off-set piece has to justify its existence" means arithmetically.
    const flattering = scoreForSlot(
      withBonus(), bare(), [{ id: 'p', stats: pool({ atk_pct: 0.2 }) }], 0,
    )[0];
    const honest = scoreForSlot(
      withBonus(), bare(), [{ id: 'p', stats: pool({ atk_pct: 0.2 }) }], 0, () => weaker(),
    )[0];

    expect(flattering.score.delta).toBeGreaterThan(0);
    expect(honest.score.delta).toBeLessThan(0);
  });

  it('falls back to the one recipe when the caller names none', () => {
    const withHook = scoreForSlot(
      recipe(), bare(), [{ id: 'p', stats: pool({ atk_pct: 0.2 }) }], 0, () => recipe(),
    );
    const without = scoreForSlot(
      recipe(), bare(), [{ id: 'p', stats: pool({ atk_pct: 0.2 }) }], 0,
    );

    expect(withHook[0].score.delta).toBeCloseTo(without[0].score.delta, 9);
  });
});
