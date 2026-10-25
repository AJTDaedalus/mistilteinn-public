import { describe, expect, it } from 'vitest';

import { lineOutcomes } from './artifact-distribution';
import { freshDropCells, rollBudgets } from './fresh-drop';
import { CIRCLET, FLOWER, WEIGHTS } from './upgrade-fixtures';

/** `docs/TASKS_upgrade_estimator.md` Task 4 — the fresh-drop prior. */
describe('freshDropCells', () => {
  it('sums to 1 over a slot, to 1e-12', () => {
    for (const table of [FLOWER, CIRCLET]) {
      const total = freshDropCells(table, WEIGHTS).reduce((a, c) => a + c.p, 0);
      expect(Math.abs(total - 1)).toBeLessThan(1e-12);
    }
  });

  it('never puts the main stat among the substats', () => {
    for (const cell of freshDropCells(CIRCLET, WEIGHTS)) {
      expect(cell.subs).not.toContain(cell.main);
      expect(new Set(cell.subs).size).toBe(4);
    }
  });

  it('has C(9,4) = 126 sets when the main is a substat type, C(10,4) = 210 when it is not', () => {
    const cells = freshDropCells(CIRCLET, WEIGHTS);
    expect(cells.filter((c) => c.main === 'crit_dmg')).toHaveLength(126);
    expect(cells.filter((c) => c.main === 'healing_bonus')).toHaveLength(210);
  });

  it('agrees with lineOutcomes, the recursive port of GO substatProb, cell by cell', () => {
    const pool = Object.fromEntries(Object.entries(WEIGHTS).filter(([q]) => q !== 'crit_dmg'));
    const bySet = new Map<string, number>();
    for (const o of lineOutcomes(pool, 4)) {
      const key = [...o.added].sort().join('|');
      bySet.set(key, (bySet.get(key) ?? 0) + o.p);
    }
    const cells = freshDropCells({ crit_dmg: 1 }, WEIGHTS);
    expect(cells).toHaveLength(bySet.size);
    for (const cell of cells) expect(cell.p).toBeCloseTo(bySet.get(cell.subs.join('|'))!, 14);
  });

  it('gives equal weights equal sets: 1 / C(n, 4)', () => {
    const flat = Object.fromEntries(Object.keys(WEIGHTS).map((q) => [q, 1]));
    for (const cell of freshDropCells({ healing_bonus: 1 }, flat)) {
      expect(cell.p).toBeCloseTo(1 / 210, 14);
    }
  });

  it('matches one cell worked by hand', () => {
    // Flower (main flat HP, out of the pool): the pool is 6+6+4·5+3+3 = 38. The set
    // {flat_atk, flat_def, crit_rate, crit_dmg} — weights 6, 6, 3, 3 — summed over its 24 draw
    // orders, each order the product of w_i / (remaining pool) — computed independently here.
    const w = [6, 6, 3, 3];
    let p = 0;
    const permute = (left: number[], pool: number, acc: number): void => {
      if (!left.length) { p += acc; return; }
      left.forEach((x, i) => permute([...left.slice(0, i), ...left.slice(i + 1)], pool - x, acc * (x / pool)));
    };
    permute(w, 38, 1);
    const cell = freshDropCells(FLOWER, WEIGHTS)
      .find((c) => c.subs.join() === ['crit_dmg', 'crit_rate', 'flat_atk', 'flat_def'].join())!;
    expect(cell.p).toBeCloseTo(p, 14);
  });

  it("reproduces the wiki's worked example of the fourth line", () => {
    // W-DIST (RESEARCH §4.2): a plume holding ATK%, ER and CRIT Rate draws CRIT DMG at 3/27.
    // In set terms: P(set = those three + CD) / P(set contains those three) is NOT 3/27 —
    // the three could have come in any order with CD among them — so the check is on the
    // pool arithmetic itself: plume pool 38, minus 4 + 4 + 3, leaves 27.
    const pool = Object.values(WEIGHTS).reduce((a, b) => a + b, 0) - WEIGHTS['flat_atk'];
    expect(pool).toBe(38);
    expect(pool - WEIGHTS['atk_pct'] - WEIGHTS['energy_recharge'] - WEIGHTS['crit_rate']).toBe(27);
    const cells = freshDropCells({ flat_atk: 1 }, WEIGHTS);
    expect(cells.every((c) => !c.subs.includes('flat_atk'))).toBe(true);
  });
});

describe('rollBudgets', () => {
  it('is 4 upgrades 80% of the time and 5 upgrades 20% of the time', () => {
    expect(rollBudgets(0.2)).toEqual([{ upgrades: 4, p: 0.8 }, { upgrades: 5, p: 0.2 }]);
  });

  it('refuses a share that is not one', () => {
    expect(() => rollBudgets(0)).toThrow(RangeError);
    expect(() => rollBudgets(1)).toThrow(RangeError);
  });
});
