import { describe, expect, it } from 'vitest';

import { instancesFrom } from './recipe-optimize.service';

/**
 * Reading per-character action counts out of gcsim's aggregate.
 *
 * **This is what makes the stability warning real.** `stabilityFrom({})` returns
 * `stable: true`, so until an aggregate was run the optimize page rendered a caveat — *"the
 * rotation did not run the same way every iteration"* — that nothing could ever produce. It
 * fires on the owner's actual rotation.
 *
 * The payloads here are transcribed from driving the committed `gcsim/gcsim.wasm`, not
 * invented: the top-level key is `stats` (the native CLI writes `statistics`), and
 * `character_actions` is a **positional list with no names in it**.
 */
describe('instancesFrom', () => {
  const aggregate = (characters: { sources: Record<string, unknown> }[]) => ({
    stats: { character_actions: characters },
  });

  it('names each character from the order the config declared them', () => {
    // The whole reason `/calibrate` publishes `characters`. Two members both have a `skill`,
    // and a positional list cannot say whose is whose.
    const raw = aggregate([
      { sources: { skill: { mean: 4, sd: 0 } } },
      { sources: { skill: { mean: 2, sd: 0.5 } } },
    ]);

    expect(instancesFrom(raw, ['nahida', 'furina'])).toEqual({
      'nahida skill': { mean: 4, sd: 0 },
      'furina skill': { mean: 2, sd: 0.5 },
    });
  });

  it('does not collapse two characters who share an action', () => {
    // Collapsing them would attribute one character's instability to the other — a warning
    // naming the wrong person, which is worse than no warning.
    const raw = aggregate([
      { sources: { burst: { mean: 1, sd: 0 } } },
      { sources: { burst: { mean: 1, sd: 0.4 } } },
    ]);

    expect(Object.keys(instancesFrom(raw, ['kuki', 'kazuha']))).toHaveLength(2);
  });

  it('falls back to a position when the order is short', () => {
    // A number is a poor label and an honest one. Inventing a name would be worse, and
    // dropping the entry would hide instability rather than mislabel it.
    const raw = aggregate([{ sources: { attack: { mean: 8, sd: 0 } } }]);

    expect(instancesFrom(raw, [])).toEqual({ 'character 1 attack': { mean: 8, sd: 0 } });
  });

  it('reads `stats`, which is what the browser build writes', () => {
    // The native CLI writes `statistics`; the wasm writes `stats` and nothing else at the top
    // level. Reading the wrong one returns {} — and {} reports every rotation as stable.
    const native = { statistics: { character_actions: [{ sources: { skill: { mean: 1, sd: 1 } } }] } };

    expect(instancesFrom(native, ['nahida'])).toEqual({});
  });

  it('skips an entry whose numbers are not numbers', () => {
    // Submissions cross a trust boundary and the aggregate is gcsim's, but a shape change
    // upstream should degrade to "unmeasured", never to a crash mid-search.
    const raw = aggregate([{ sources: { skill: { mean: 'four', sd: 0 } } }]);

    expect(instancesFrom(raw, ['nahida'])).toEqual({});
  });

  it('returns nothing rather than throwing on a payload with no aggregate', () => {
    expect(instancesFrom({}, ['nahida'])).toEqual({});
    expect(instancesFrom(null, ['nahida'])).toEqual({});
    expect(instancesFrom({ stats: { character_actions: 'no' } }, [])).toEqual({});
  });
});
