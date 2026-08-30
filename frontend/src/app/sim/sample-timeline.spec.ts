import { describe, expect, it } from 'vitest';

import { cycles, onFieldIntervals, type SampleResult } from './sample-timeline';

/** An `event: "action"` log entry, the only shape this module reads. */
function act(charIndex: number, frame: number, action = 'attack') {
  return { event: 'action', frame, char_index: charIndex, logs: { action } };
}

describe('onFieldIntervals', () => {
  it('starts a new interval when the acting character changes', () => {
    const result: SampleResult = {
      character_details: [{ name: 'nahida' }, { name: 'xingqiu' }],
      logs: [act(0, 1), act(0, 20), act(1, 60), act(0, 90)],
    };

    expect(onFieldIntervals(result)).toEqual([
      { character: 0, key: 'nahida', start: 1, end: 20, actions: 2 },
      { character: 1, key: 'xingqiu', start: 60, end: 60, actions: 1 },
      { character: 0, key: 'nahida', start: 90, end: 90, actions: 1 },
    ]);
  });

  it('ignores every event that is not an action', () => {
    // A 90-second solo rotation logs 3,124 entries and 157 of them are actions. Reading the
    // rest as though they were would put damage ticks and status changes on the timeline.
    const result: SampleResult = {
      character_details: [{ name: 'nahida' }],
      logs: [
        { event: 'status', frame: 0, char_index: 0 },
        { event: 'damage', frame: 5, char_index: 0 },
        act(0, 10),
        { event: 'energy', frame: 12, char_index: 0 },
      ],
    };

    expect(onFieldIntervals(result)).toHaveLength(1);
    expect(onFieldIntervals(result)[0].actions).toBe(1);
  });

  it('ignores an action event with no action name', () => {
    const result: SampleResult = {
      character_details: [{ name: 'nahida' }],
      logs: [{ event: 'action', frame: 3, char_index: 0, logs: {} }],
    };

    expect(onFieldIntervals(result)).toEqual([]);
  });

  it('reproduces the shape of the committed four-character trace', () => {
    // `DESIGN_rotation_builder_gui.md` §1 records the real run:
    //   f1-117 nicole, f160-245 chevreuse, f280-345 durin, f459-924 clorinde
    // Not the whole 163-event log — the first four stretches, which is what fixes the
    // derivation's behaviour at a swap.
    const result: SampleResult = {
      character_details: [
        { name: 'clorinde' }, { name: 'chevreuse' }, { name: 'nicole' }, { name: 'durin' },
      ],
      logs: [
        act(2, 1), act(2, 117),
        act(1, 160), act(1, 200), act(1, 220), act(1, 245),
        act(3, 280), act(3, 300), act(3, 320), act(3, 345),
        act(0, 459), act(0, 924),
      ],
    };

    expect(onFieldIntervals(result).map((i) => [i.key, i.start, i.end, i.actions])).toEqual([
      ['nicole', 1, 117, 2],
      ['chevreuse', 160, 245, 4],
      ['durin', 280, 345, 4],
      ['clorinde', 459, 924, 2],
    ]);
  });

  it('is empty for a run in which nothing executed', () => {
    // Not an error. A rotation whose every gate stayed closed is a real answer, and it is
    // precisely the answer the measured timeline exists to make visible.
    expect(onFieldIntervals({ character_details: [{ name: 'nahida' }], logs: [] })).toEqual([]);
  });

  it('survives a result with no logs and no team at all', () => {
    expect(onFieldIntervals({})).toEqual([]);
  });

  it('names a character the result did not describe with an empty key', () => {
    // Absent beats plausible: a made-up name on a tile is worse than a blank one.
    const found = onFieldIntervals({ logs: [act(7, 1)] });

    expect(found[0].key).toBe('');
    expect(found[0].character).toBe(7);
  });
});

describe('cycles', () => {
  it('counts how many times the opener comes round', () => {
    const intervals = onFieldIntervals({
      character_details: [{ name: 'a' }, { name: 'b' }],
      logs: [act(0, 1), act(1, 50), act(0, 100), act(1, 150), act(0, 200)],
    });

    expect(cycles(intervals)).toBe(3);
  });

  it('reports one for a rotation that ran once in ninety seconds', () => {
    // `DESIGN_rotation.md` §1's first silent failure, visible without reading a config.
    const intervals = onFieldIntervals({
      character_details: [{ name: 'a' }, { name: 'b' }],
      logs: [act(0, 1), act(1, 50)],
    });

    expect(cycles(intervals)).toBe(1);
  });

  it('is zero when nothing ran', () => {
    expect(cycles([])).toBe(0);
  });
});
