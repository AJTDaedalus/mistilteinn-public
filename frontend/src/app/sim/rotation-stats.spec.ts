import { describe, expect, it } from 'vitest';

import {
  charactersInConfig, displayNames, gcsimKeyOf, parseRotationStats, toPrecision,
} from './rotation-stats';

/** A trimmed copy of a real run: the owner's team on their own rotation. */
const RAW = {
  statistics: {
    iterations: 200,
    dps: { min: 180298.7, max: 208796.5, mean: 192580.5, sd: 5732.0, q1: 188614, q2: 192871, q3: 196375 },
    eps: { mean: 12.92, sd: 0.05, min: 12.77, max: 13.08 },
    duration: { mean: 191.7, sd: 0.4, min: 190.1, max: 193.2 },
    character_dps: [
      { mean: 140000, sd: 4000, min: 130000, max: 150000 },
      { mean: 25338.6, sd: 1346.1, min: 21853.1, max: 28986.4 },
    ],
    field_time: [
      { mean: 74.0, sd: 2.0, min: 70, max: 78 },
      { mean: 85.6, sd: 3.8, min: 75.1, max: 94.8 },
    ],
    end_stats: [
      { ending_energy: { mean: 12.0, sd: 1.0, min: 10, max: 14 } },
      { ending_energy: { mean: 31.99, sd: 1.64, min: 28.2, max: 35.5 } },
    ],
    failed_actions: [
      { insufficient_energy: { mean: 0 } },
      { insufficient_energy: { mean: 67.1 } },
    ],
    character_actions: [
      { sources: { attack: { mean: 151, sd: 0, min: 151, max: 151 } } },
      { sources: { burst: { mean: 7, sd: 0, min: 7, max: 7 } } },
    ],
    dps_by_element: [
      { elements: { cryo: { mean: 120000, sd: 3000, min: 0, max: 0 } } },
      { elements: { hydro: { mean: 20000, sd: 900, min: 0, max: 0 }, physical: { mean: 5338, sd: 400, min: 0, max: 0 } } },
    ],
    source_dps: [
      { sources: { 'Normal (Skill) 0': { mean: 40000, sd: 900, min: 0, max: 0 } } },
      { sources: { 'Let the People Rejoice': { mean: 430, sd: 82, min: 239, max: 638 } } },
    ],
    source_reactions: [{ sources: { freeze: { mean: 60.2, sd: 1.9, min: 55, max: 65 } } }],
    target_aura_uptime: [{ sources: { cryo: { mean: 47.8, sd: 0.9, min: 45.5, max: 50.6 } } }],
  },
};
const NAMES = ['Skirk', 'Furina'];

describe('parseRotationStats', () => {
  it('reads the headline spreads, not just their means', () => {
    // gcsim reports a distribution; a page that prints only the mean claims a precision the
    // run does not have.
    const stats = parseRotationStats(RAW, NAMES);
    expect(stats.iterations).toBe(200);
    expect(stats.dps?.mean).toBeCloseTo(192580.5);
    expect(stats.dps?.sd).toBeCloseTo(5732);
    expect(stats.dps?.q1).toBeCloseTo(188614);
    expect(stats.duration?.mean).toBeCloseTo(191.7);
  });

  it('pairs every per-character array positionally against gcsim order', () => {
    const [skirk, furina] = parseRotationStats(RAW, NAMES).characters;
    expect(skirk.name).toBe('Skirk');
    expect(skirk.insufficientEnergy).toBe(0);
    expect(furina.name).toBe('Furina');
    expect(furina.insufficientEnergy).toBeCloseTo(67.1);
    expect(furina.fieldTime?.mean).toBeCloseTo(85.6);
    expect(furina.endingEnergy?.mean).toBeCloseTo(31.99);
  });

  it('sorts sources and elements by contribution', () => {
    const furina = parseRotationStats(RAW, NAMES).characters[1];
    expect(furina.byElement.map((e) => e.name)).toEqual(['hydro', 'physical']);
    expect(furina.bySource[0].name).toBe('Let the People Rejoice');
  });

  it('keeps reactions and aura uptime, which are per target rather than per character', () => {
    const stats = parseRotationStats(RAW, NAMES);
    expect(stats.reactions[0].name).toBe('freeze');
    expect(stats.auraUptime[0].name).toBe('cryo');
  });

  it('reads the browser wasm shape as well as the native one', () => {
    // `flush()` returns `{stats}`; the native `-out` JSON returns `{statistics}`. Reading only
    // one gives a page of blanks and "over 0 iterations" — an empty result that looks like a
    // finished one.
    const browserShape = { stats: RAW.statistics };
    expect(parseRotationStats(browserShape, NAMES).dps?.mean).toBeCloseTo(192580.5);
    expect(parseRotationStats(browserShape, NAMES).iterations).toBe(200);
  });

  it('survives a run with no statistics at all', () => {
    expect(parseRotationStats(null, NAMES).characters).toHaveLength(2);
    expect(parseRotationStats({}, []).dps).toBeNull();
  });
});

describe('toPrecision', () => {
  it('rounds the estimate to what its spread supports', () => {
    // 192,580.52 ± 5,732.01 is eight digits of precision on four digits of knowledge.
    expect(toPrecision(192580.52, 5732.01)).toEqual({ value: 192600, uncertainty: 5700 });
  });

  it('keeps small numbers readable', () => {
    expect(toPrecision(12.92, 0.05)).toEqual({ value: 12.92, uncertainty: 0.05 });
  });

  it('leaves an exact quantity exact', () => {
    // An action count that never varies is not uncertain, and rounding it would invent doubt.
    expect(toPrecision(151, 0)).toEqual({ value: 151, uncertainty: 0 });
  });
});


describe('charactersInConfig', () => {
  const CONFIG = [
    'options iteration=100 duration=90;',
    '',
    'skirk char lvl=90/90 cons=2 talent=1,10,10;',
    'skirk add weapon="azurelight" lvl=90/90 refine=1;',
    'furina char lvl=90/90 cons=2 talent=1,10,10;',
    'citlali char lvl=90/90 cons=0 talent=1,10,6;',
    'escoffier char lvl=90/90 cons=0 talent=1,10,10;',
    'target lvl=100 resist=0.1;',
  ].join('\n');

  it('reads the order gcsim will index by', () => {
    // **Not the roster order.** `/rotations/options` returns its own; using it named Citlali
    // for Furina's missed bursts — a plausible sentence about the wrong character.
    expect(charactersInConfig(CONFIG)).toEqual(['skirk', 'furina', 'citlali', 'escoffier']);
  });

  it('counts a character once, however many lines they have', () => {
    expect(charactersInConfig(CONFIG).filter((k) => k === 'skirk')).toHaveLength(1);
  });

  it('ignores lines that are not character declarations', () => {
    expect(charactersInConfig(CONFIG)).not.toContain('options');
    expect(charactersInConfig(CONFIG)).not.toContain('target');
  });
});

describe('displayNames', () => {
  it('matches gcsim keys back to readable names', () => {
    expect(displayNames(['kaedeharakazuha', 'skirk'], ['Skirk', 'Kaedehara Kazuha']))
      .toEqual(['Kaedehara Kazuha', 'Skirk']);
  });

  it('keeps an unmatched key rather than borrowing a neighbour', () => {
    // A wrong name reads as right; a raw key reads as a gap, which is the honest failure.
    expect(displayNames(['nobody'], ['Skirk'])).toEqual(['nobody']);
  });

  it('normalises the way gcsim does', () => {
    expect(gcsimKeyOf('Kamisato Ayaka')).toBe('kamisatoayaka');
    expect(gcsimKeyOf("Sangonomiya Kokomi")).toBe('sangonomiyakokomi');
  });
});

describe('parseRotationStats, per-target rows', () => {
  /**
   * gcsim reports reactions once **per enemy**, and these were concatenated into one flat
   * list — so a three-target run rendered `bloom` three times with three different numbers and
   * no column accounting for it. Audit finding 14. It reads as the simulator contradicting
   * itself rather than as three separate targets.
   */
  it('names the target when a reaction is reported for more than one', () => {
    const stats = parseRotationStats({
      statistics: {
        iterations: 10,
        source_reactions: [
          { sources: { bloom: { mean: 1, sd: 0, min: 1, max: 1 } } },
          { sources: { bloom: { mean: 2.6, sd: 0.5, min: 2, max: 3 } } },
          { sources: { bloom: { mean: 2, sd: 0, min: 2, max: 2 } } },
        ],
      },
    }, ['Nahida']);

    expect(stats.reactions.map((r) => r.name)).toEqual([
      'bloom · target 1', 'bloom · target 2', 'bloom · target 3',
    ]);
  });

  it('says nothing about targets when there is only one', () => {
    // The ordinary case. A `· target 1` suffix on its own would be noise claiming a
    // distinction that does not exist.
    const stats = parseRotationStats({
      statistics: {
        iterations: 10,
        source_reactions: [{ sources: { bloom: { mean: 2, sd: 0, min: 2, max: 2 } } }],
      },
    }, ['Nahida']);

    expect(stats.reactions.map((r) => r.name)).toEqual(['bloom']);
  });

  it('keeps every row rather than collapsing duplicates', () => {
    // The values differ per target, so dropping one would be losing a measurement — and
    // `track reaction.name` in the template needs them distinct to render all three at all.
    const stats = parseRotationStats({
      statistics: {
        iterations: 10,
        source_reactions: [
          { sources: { bloom: { mean: 1, sd: 0, min: 1, max: 1 } } },
          { sources: { bloom: { mean: 2.6, sd: 0.5, min: 2, max: 3 } } },
        ],
      },
    }, ['Nahida']);

    expect(stats.reactions.map((r) => r.spread.mean)).toEqual([1, 2.6]);
    expect(new Set(stats.reactions.map((r) => r.name)).size).toBe(2);
  });

  it('labels aura uptime per target too', () => {
    const stats = parseRotationStats({
      statistics: {
        iterations: 10,
        target_aura_uptime: [
          { sources: { dendro: { mean: 80, sd: 1, min: 79, max: 81 } } },
          { sources: { dendro: { mean: 60, sd: 1, min: 59, max: 61 } } },
        ],
      },
    }, ['Nahida']);

    expect(stats.auraUptime.map((a) => a.name)).toEqual([
      'dendro · target 1', 'dendro · target 2',
    ]);
  });
});
