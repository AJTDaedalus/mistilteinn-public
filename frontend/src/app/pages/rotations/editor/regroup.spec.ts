import { describe, expect, it } from 'vitest';

import { regroup } from './regroup';
import type { RotationStep } from '../rotations.service';

function step(action: string, group = '', groupRepeat = 1): RotationStep {
  return {
    character: '10000002', action, repeat: 1, note: '',
    group, group_repeat: groupRepeat, group_condition: '',
  } as RotationStep;
}

const groups = (steps: RotationStep[]) => steps.map((s) => s.group);

describe('regroup', () => {
  it('leaves a contiguous group alone', () => {
    const steps = [step('skill', 'g', 3), step('burst', 'g', 3), step('attack')];

    expect(groups(regroup(steps))).toEqual(['g', 'g', '']);
  });

  it('leaves an ungrouped rotation alone', () => {
    // Every rotation authored before groups existed passes through untouched.
    const steps = [step('skill'), step('burst'), step('attack')];

    expect(regroup(steps)).toEqual(steps);
  });

  it('releases the second run of a split group, keeping the first', () => {
    // The API refuses a group in two places: gathering scattered members would reorder the
    // user's rotation, and repeating them where they stand would put the chunk somewhere
    // nobody wrote it. Keeping the *first* run is the half that did not move.
    const steps = [step('skill', 'g', 2), step('attack'), step('burst', 'g', 2)];

    expect(groups(regroup(steps))).toEqual(['g', '', '']);
  });

  it('resets the repeat on what it releases', () => {
    // A released step carrying `group_repeat: 2, group_condition: ''` is a number nothing reads — and the schema
    // refuses one on an ungrouped step, so leaving it would fail the next save.
    const steps = [step('skill', 'g', 2), step('attack'), step('burst', 'g', 2)];

    expect(regroup(steps)[2].group_repeat).toBe(1);
  });

  it('keeps two different groups that are each contiguous', () => {
    const steps = [
      step('skill', 'g1', 2), step('burst', 'g1', 2),
      step('attack', 'g2', 3), step('charge', 'g2', 3),
    ];

    expect(groups(regroup(steps))).toEqual(['g1', 'g1', 'g2', 'g2']);
  });

  it('releases a group split by another group rather than by a bare step', () => {
    const steps = [
      step('skill', 'g1', 2), step('attack', 'g2', 2), step('burst', 'g1', 2),
    ];

    expect(groups(regroup(steps))).toEqual(['g1', 'g2', '']);
  });

  it('releases every later run, not only the second', () => {
    const steps = [
      step('a', 'g', 2), step('b'), step('c', 'g', 2), step('d'), step('e', 'g', 2),
    ];

    expect(groups(regroup(steps))).toEqual(['g', '', '', '', '']);
  });

  it('does not mutate what it was given', () => {
    // The editor holds `steps()` as a signal and compares snapshots to detect unsaved edits;
    // a repair that mutated in place would change the stored copy too and the rotation would
    // stop looking dirty.
    const steps = [step('skill', 'g', 2), step('attack'), step('burst', 'g', 2)];
    const before = JSON.stringify(steps);

    regroup(steps);

    expect(JSON.stringify(steps)).toBe(before);
  });
});
