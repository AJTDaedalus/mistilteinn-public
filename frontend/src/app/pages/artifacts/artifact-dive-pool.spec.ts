import { describe, expect, it } from 'vitest';

import { DIVE_PER_SLOT, trimForDive } from './artifact-ranking.service';
import type { Candidate } from '../../sim/search';
import type { Recipe } from '../../sim/recipe';

/**
 * **The pinned search has to be able to reproduce the build it is measured against.**
 *
 * `trimForDive` keeps the best `DIVE_PER_SLOT` pieces per slot, and kept the pinned piece
 * unconditionally on the argument that dropping it "would produce a search that silently
 * answered a different question". The same argument was never applied to the pieces the build
 * is already wearing — so in a slot where two dozen pieces each beat the equipped one, the
 * equipped one fell out of the pool and the search could no longer construct the status quo.
 *
 * The visible symptom, driven on the owner's own data: a sands whose card read `max +2.9%`
 * reported a best build of **+1.1%** — a re-optimisation with strictly more freedom than a
 * single swap coming out *behind* one, which is incoherent rather than merely pessimistic.
 * It read **+3.1%** after.
 */

/**
 * A recipe with no hits, so every candidate scores the same.
 *
 * That is the point: `Array.prototype.sort` is stable, so an all-equal ranking keeps array
 * order and the last piece is the one the budget drops. The exemption is then the only thing
 * that can put it back, which is exactly the behaviour under test — a recipe that actually
 * scored would let a piece survive on merit and pass this vacuously.
 */
const FLAT: Recipe = {
  hits: [],
  meta: {
    seed: '1', staleConversions: [], characters: [], unstable: [],
    calibratedSetIds: [], minimumEnergyRecharge: null,
  },
} as unknown as Recipe;

/** `equip_bracer` because `SLOTS` is the kernel's closed set — `trimForDive` drops an
 *  unrecognised slot name, and a made-up one would return an empty pool that passes anything. */
function pool(count: number): Candidate[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `p${i}`,
    slot: 'equip_bracer' as const,
    setId: 0,
    stats: { flat_atk: 1 },
  }));
}

describe('trimForDive', () => {
  const candidates = pool(DIVE_PER_SLOT + 16);
  const dropped = candidates[candidates.length - 1];
  const kept0 = candidates[0];

  it('keeps a worn piece the budget would otherwise drop', () => {
    const kept = trimForDive(
      candidates, kept0.id, FLAT, [kept0.stats], new Set([dropped.id]),
    );

    expect(kept.some((c) => c.id === dropped.id)).toBe(true);
  });

  it('drops that same piece when it is not worn — the exemption is doing the work', () => {
    // Guards the guard. Without this, the assertion above would pass for a `trimForDive` that
    // simply never trimmed, and the bug it exists to catch would be invisible again.
    const kept = trimForDive(candidates, kept0.id, FLAT, [kept0.stats], new Set());

    expect(kept.some((c) => c.id === dropped.id)).toBe(false);
    expect(kept.length).toBe(DIVE_PER_SLOT);
  });

  it('keeps the pinned piece too, and does not double it when it already fits', () => {
    const kept = trimForDive(
      candidates, dropped.id, FLAT, [kept0.stats], new Set([kept0.id]),
    );

    expect(kept.filter((c) => c.id === dropped.id)).toHaveLength(1);
    expect(kept.filter((c) => c.id === kept0.id)).toHaveLength(1);
  });
});
