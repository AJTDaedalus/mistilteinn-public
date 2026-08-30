/**
 * What one gcsim `sample()` run says about who was on field, and when.
 *
 * T.8. `DESIGN_rotation_builder_gui.md` §1: a *measured* timeline is one `sample()` call away
 * — 2.3 s for a real four-character config, with no browser penalty
 * (`RESEARCH_calibration_cost.md`). This is the pure half of that: JSON in, intervals out, no
 * wasm and no DOM, so the derivation can be tested against a committed trace.
 *
 * ## `sample()` does not return `stats.Result`
 *
 * The obvious expectation is wrong and cost a wrong assumption in the design draft. gcsim's
 * `stats.Result` carries `ActiveCharacters []ActiveCharacterInterval` — exactly this, ready
 * made. **`sample()` returns something else**: `{config, initial_character, character_details,
 * target_details, seed, logs}`, where `logs` is a flat event list. There is no
 * `active_characters` array to read.
 *
 * So the intervals are **derived** from `char_index` transitions across the log's
 * `event: "action"` entries, and that derivation is ours to own — which is why it is a
 * function with tests rather than a field access.
 */

/** One `event: "action"` entry of a sample log. Every other event shape is ignored. */
interface ActionEvent {
  event?: string;
  frame?: number;
  char_index?: number;
  logs?: { action?: string };
}

/** What a sample run returns, as far as this module reads it. */
export interface SampleResult {
  character_details?: { name?: string }[];
  logs?: ActionEvent[];
}

/** A stretch of frames during which one character acted. */
export interface OnFieldInterval {
  /** Index into the team, as gcsim ordered it. */
  character: number;
  /** gcsim's key for that character, or `''` when the result did not name them. */
  key: string;
  /** Frame of the first action in this stretch. */
  start: number;
  /** Frame of the last action in this stretch. */
  end: number;
  /** How many actions were executed in it. */
  actions: number;
}

/**
 * The on-field intervals of one sample run.
 *
 * **A new interval starts when `char_index` changes**, which is the definition of a swap in a
 * log that records no swap of its own for an implicit one. gcsim *does* log explicit `swap`
 * actions — 15 of them in the committed four-character trace — but reading those alone would
 * miss the first stretch and any swap the evaluator inserted, so the transition is the signal
 * and the explicit swap is redundant with it.
 *
 * Returns `[]` for a run with no actions rather than throwing: a rotation whose every gate was
 * closed is a real answer, and it is exactly the answer the measured timeline exists to make
 * visible.
 */
export function onFieldIntervals(result: SampleResult): OnFieldInterval[] {
  const names = (result.character_details ?? []).map((c) => c.name ?? '');
  const intervals: OnFieldInterval[] = [];
  for (const event of result.logs ?? []) {
    if (event.event !== 'action' || !event.logs?.action) continue;
    const character = event.char_index ?? -1;
    const frame = event.frame ?? 0;
    const last = intervals[intervals.length - 1];
    if (last && last.character === character) {
      last.end = frame;
      last.actions += 1;
      continue;
    }
    intervals.push({
      character,
      key: names[character] ?? '',
      start: frame,
      end: frame,
      actions: 1,
    });
  }
  return intervals;
}

/**
 * How many times the whole rotation came round, as far as the intervals can tell.
 *
 * The count of times the **first** character's stretch begins again. A rotation that ran once
 * in ninety seconds reports 1, which is `DESIGN_rotation.md` §1's first silent failure made
 * visible without anyone reading a config.
 */
export function cycles(intervals: OnFieldInterval[]): number {
  if (intervals.length === 0) return 0;
  const first = intervals[0].character;
  return intervals.filter((i) => i.character === first).length;
}
