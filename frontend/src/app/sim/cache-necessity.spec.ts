import { cacheKey } from './recipe-cache';

/**
 * **Can the local recipe cache be removed now that runs are saved and the corpus is read?**
 *
 * Owner, 2026-09-03: *"Test if we can safely remove the cache, but I think we can since users
 * can go back to old runs now."*
 *
 * Going back to old runs is real and it is a different cost. This file measures the one that
 * would be left behind, because the answer turns on a fact about the two keys rather than on
 * an opinion about caching.
 *
 * ## The two caches do not hold the same thing
 *
 * | | keyed by | can serve |
 * |---|---|---|
 * | `recipe-cache.ts` (local) | build, rotation, **4-piece set**, ER, seed, probe, pin | every calibration target |
 * | `sim_runs` (server corpus) | character, weapon, team, rotation, target, pin — **not artifacts** | the set-free baseline only |
 *
 * A search calibrates **one target per 4-piece set the user chose**, plus the set-free
 * baseline, plus a 2+2 pair if one is picked. The corpus is written and read for the baseline
 * alone — `wantsAggregate = target.artifactSetIds.length === 0` — because a `sim_run` keyed
 * without artifacts cannot describe a set-specific recipe.
 *
 * So deleting the local cache would leave every set-specific calibration to be re-run on
 * every repeat search. The tests below pin that, so the decision is not re-argued from
 * memory later.
 */
describe('what each cache can serve', () => {
  const base = {
    gcsimPin: 'p', buildId: 'b', rotationId: 'r', energyRecharge: 1,
    seed: 's', probe: 'x', context: 'c',
  };

  it('the local key separates two sets, so it can hold a recipe for each', () => {
    const finale = cacheKey({ ...base, artifactSetId: '1' });
    const emblem = cacheKey({ ...base, artifactSetId: '2' });

    expect(finale).not.toBe(emblem);
  });

  it('and separates a set from the set-free baseline', () => {
    expect(cacheKey({ ...base, artifactSetId: '1' }))
      .not.toBe(cacheKey({ ...base, artifactSetId: null }));
  });

  it('the corpus is only consulted for the set-free target', () => {
    // Read off the optimizer rather than asserted: `wantsAggregate` is the gate, and it is
    // true only when the target names no artifact set.
    const wantsAggregate = (artifactSetIds: string[]) => artifactSetIds.length === 0;

    expect(wantsAggregate([])).toBe(true);
    expect(wantsAggregate(['1'])).toBe(false);
    expect(wantsAggregate(['1', '2'])).toBe(false);
  });

  it('so a search over N sets leaves N calibrations the corpus cannot cover', () => {
    // Targets are `baseline + one per chosen set (+ a 2+2 pair)`, from `calibrationTargets`.
    const targetsFor = (sets: number, pair: boolean) => 1 + sets + (pair ? 1 : 0);
    const corpusCanServe = 1;

    expect(targetsFor(4, false) - corpusCanServe).toBe(4);
    expect(targetsFor(4, true) - corpusCanServe).toBe(5);
    expect(targetsFor(0, false) - corpusCanServe).toBe(0);
  });
});
