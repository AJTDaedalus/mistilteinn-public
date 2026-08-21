import { describe, expect, it } from 'vitest';
import { deriveFrames, emptySetFilterState } from './optimizer-set-filter';

// The dialog-based component requires HTMLDialogElement.showModal() which is
// not available in jsdom. Component integration is covered by E2E tests.
// These unit tests cover the pure frame-derivation logic.

describe('deriveFrames', () => {
  it('returns empty array when both lists are empty', () => {
    expect(deriveFrames([], [])).toHaveLength(0);
  });

  it('4pc only (no 2pc) → no frames (backend requires sum=6)', () => {
    expect(deriveFrames([100], [])).toHaveLength(0);
  });

  it('4pc + different 2pc → {s4: 4, s2: 2}', () => {
    const frames = deriveFrames([100], [101]);
    expect(frames).toHaveLength(1);
    expect(frames[0].counts).toEqual({ 100: 4, 101: 2 });
  });

  it('same set in 4pc and 2pc → {s: 6}', () => {
    const frames = deriveFrames([100], [100]);
    expect(frames).toHaveLength(1);
    expect(frames[0].counts).toEqual({ 100: 6 });
  });

  it('two 4pc candidates × one 2pc → two frames', () => {
    const frames = deriveFrames([100, 101], [102]);
    expect(frames).toHaveLength(2);
  });

  it('deduplicates symmetric pairs', () => {
    // [100,101] × [100,101] → {100:6}, {100:4,101:2}, {101:4,100:2}, {101:6}
    const frames = deriveFrames([100, 101], [100, 101]);
    expect(frames).toHaveLength(4);
  });

  it('2pc-only (no 4pc selected) → empty', () => {
    expect(deriveFrames([], [100])).toHaveLength(0);
  });
});

describe('emptySetFilterState', () => {
  it('returns zeroed state', () => {
    const s = emptySetFilterState();
    expect(s.fourPieceSets).toHaveLength(0);
    expect(s.twoPieceSets).toHaveLength(0);
    expect(s.frames).toHaveLength(0);
  });
});
