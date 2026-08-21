import { describe, expect, it } from 'vitest';
import { composeFrames } from './frame-composer';

describe('composeFrames', () => {
  describe('shape: 4+2', () => {
    it('pool size 1 → no frames (need ≥2 sets)', () => {
      expect(composeFrames([1], ['4+2'])).toHaveLength(0);
    });

    it('pool size 2 → 2 frames: {A:4,B:2} and {B:4,A:2}', () => {
      const frames = composeFrames([1, 2], ['4+2']);
      expect(frames).toHaveLength(2);
      const keys = frames.map((f) => JSON.stringify(f.counts)).sort();
      expect(keys).toContain(JSON.stringify({ 1: 4, 2: 2 }));
      expect(keys).toContain(JSON.stringify({ 2: 4, 1: 2 }));
    });

    it('pool size 3 → 6 frames', () => {
      const frames = composeFrames([1, 2, 3], ['4+2']);
      expect(frames).toHaveLength(6);
    });

    it('all frames sum to 6', () => {
      for (const f of composeFrames([1, 2, 3], ['4+2'])) {
        const total = Object.values(f.counts).reduce((a, b) => a + b, 0);
        expect(total).toBe(6);
      }
    });
  });

  describe('shape: 2+2+2', () => {
    it('pool size 1 → no frames (need ≥3 sets)', () => {
      expect(composeFrames([1], ['2+2+2'])).toHaveLength(0);
    });

    it('pool size 2 → no frames (need ≥3 sets)', () => {
      expect(composeFrames([1, 2], ['2+2+2'])).toHaveLength(0);
    });

    it('pool size 3 → 1 frame: {A:2,B:2,C:2}', () => {
      const frames = composeFrames([1, 2, 3], ['2+2+2']);
      expect(frames).toHaveLength(1);
      expect(frames[0].counts).toEqual({ 1: 2, 2: 2, 3: 2 });
    });

    it('pool size 4 → 4 frames (C(4,3))', () => {
      const frames = composeFrames([1, 2, 3, 4], ['2+2+2']);
      expect(frames).toHaveLength(4);
    });
  });

  describe('shape: 4_only', () => {
    it('pool size 1 with allSetIds = [1,2] → frames with A:4 + 2 wildcard slots', () => {
      const frames = composeFrames([1], ['4_only'], [1, 2]);
      // All frames should have set 1 with count 4.
      for (const f of frames) {
        expect(f.counts[1]).toBeGreaterThanOrEqual(4);
      }
    });

    it('all frames sum to 6', () => {
      for (const f of composeFrames([1, 2], ['4_only'], [1, 2, 3])) {
        const total = Object.values(f.counts).reduce((a, b) => a + b, 0);
        expect(total).toBe(6);
      }
    });
  });

  describe('shape: 2+2', () => {
    it('pool size 1 → no frames (need ≥2 sets)', () => {
      expect(composeFrames([1], ['2+2'], [1, 2, 3])).toHaveLength(0);
    });

    it('all frames sum to 6', () => {
      for (const f of composeFrames([1, 2], ['2+2'], [1, 2, 3])) {
        const total = Object.values(f.counts).reduce((a, b) => a + b, 0);
        expect(total).toBe(6);
      }
    });
  });

  describe('combined shapes', () => {
    it('4+2 + 2+2+2 on pool [1,2,3] → 6 + 1 = 7 frames (no overlap)', () => {
      const frames = composeFrames([1, 2, 3], ['4+2', '2+2+2']);
      expect(frames).toHaveLength(7);
    });

    it('returns empty when pool is empty', () => {
      expect(composeFrames([], ['4+2', '2+2+2'])).toHaveLength(0);
    });

    it('returns empty when shapes is empty', () => {
      expect(composeFrames([1, 2], [])).toHaveLength(0);
    });
  });
});
