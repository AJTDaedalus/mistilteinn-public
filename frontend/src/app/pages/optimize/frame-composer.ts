import type { SetFrameSchema } from './optimizer.service';

export type FrameShape = '4+2' | '2+2+2' | '4_only' | '2+2';

/**
 * Compose concrete SetFrameSchema[] from a set pool + shape list.
 *
 * @param setIds    Hakushin IDs of the sets the user is willing to use.
 * @param shapes    Which distribution shapes to include.
 * @param allSetIds Full inventory set IDs used to fan out wildcard slots
 *                  for '4_only' and '2+2' (DESIGN §5.3 Option A).
 */
export function composeFrames(
  setIds: number[],
  shapes: FrameShape[],
  allSetIds: number[] = [],
): SetFrameSchema[] {
  if (setIds.length === 0 || shapes.length === 0) return [];

  const frames: SetFrameSchema[] = [];

  for (const shape of shapes) {
    switch (shape) {
      case '4+2':
        frames.push(...compose4Plus2(setIds));
        break;
      case '2+2+2':
        frames.push(...compose2Plus2Plus2(setIds));
        break;
      case '4_only':
        frames.push(...compose4Only(setIds, allSetIds));
        break;
      case '2+2':
        frames.push(...compose2Plus2(setIds, allSetIds));
        break;
    }
  }

  return dedupe(frames);
}

/** {A:4, B:2} for every ordered pair (A, B) where A ≠ B. */
function compose4Plus2(setIds: number[]): SetFrameSchema[] {
  const frames: SetFrameSchema[] = [];
  for (const a of setIds) {
    for (const b of setIds) {
      if (a !== b) {
        frames.push({ counts: { [a]: 4, [b]: 2 } });
      }
    }
  }
  return frames;
}

/** {A:2, B:2, C:2} for every distinct unordered triple. */
function compose2Plus2Plus2(setIds: number[]): SetFrameSchema[] {
  if (setIds.length < 3) return [];
  const frames: SetFrameSchema[] = [];
  for (let i = 0; i < setIds.length; i++) {
    for (let j = i + 1; j < setIds.length; j++) {
      for (let k = j + 1; k < setIds.length; k++) {
        frames.push({ counts: { [setIds[i]]: 2, [setIds[j]]: 2, [setIds[k]]: 2 } });
      }
    }
  }
  return frames;
}

/**
 * {A:4, W:1, X:1} for every A in setIds, for every unordered pair (W, X)
 * from allSetIds (fan-out wildcard). If allSetIds is empty, uses setIds itself.
 */
function compose4Only(setIds: number[], allSetIds: number[]): SetFrameSchema[] {
  const wildcards = allSetIds.length > 0 ? allSetIds : setIds;
  const frames: SetFrameSchema[] = [];
  for (const a of setIds) {
    for (let i = 0; i < wildcards.length; i++) {
      for (let j = i; j < wildcards.length; j++) {
        const w1 = wildcards[i];
        const w2 = wildcards[j];
        const counts: Record<number, number> = { [a]: 4 };
        // Remaining 2 slots: w1 and w2 (may be same set as a or each other).
        incrementCount(counts, w1);
        incrementCount(counts, w2);
        if (sum(counts) === 6) frames.push({ counts });
      }
    }
  }
  return frames;
}

/**
 * {A:2, B:2, W:1, X:1} for every unordered pair (A, B) in setIds,
 * fan-out the remaining 2 slots over allSetIds.
 */
function compose2Plus2(setIds: number[], allSetIds: number[]): SetFrameSchema[] {
  if (setIds.length < 2) return [];
  const wildcards = allSetIds.length > 0 ? allSetIds : setIds;
  const frames: SetFrameSchema[] = [];
  for (let i = 0; i < setIds.length; i++) {
    for (let j = i + 1; j < setIds.length; j++) {
      const a = setIds[i];
      const b = setIds[j];
      for (let k = 0; k < wildcards.length; k++) {
        for (let l = k; l < wildcards.length; l++) {
          const counts: Record<number, number> = { [a]: 2, [b]: 2 };
          incrementCount(counts, wildcards[k]);
          incrementCount(counts, wildcards[l]);
          if (sum(counts) === 6) frames.push({ counts });
        }
      }
    }
  }
  return frames;
}

function incrementCount(counts: Record<number, number>, id: number) {
  counts[id] = (counts[id] ?? 0) + 1;
}

function sum(counts: Record<number, number>): number {
  return Object.values(counts).reduce((a, b) => a + b, 0);
}

function dedupe(frames: SetFrameSchema[]): SetFrameSchema[] {
  const seen = new Set<string>();
  return frames.filter((f) => {
    const key = JSON.stringify(Object.entries(f.counts).sort(([a], [b]) => Number(a) - Number(b)));
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
