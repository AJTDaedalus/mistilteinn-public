import { describe, expect, it } from 'vitest';

import { defaultEnemyId, filterEnemiesByTab } from './enemy-tabs';

const TRASH = { id: 'e-trash', rarity: 1 };
const ELITE = { id: 'e-elite', rarity: 2 };
const NAMED = { id: 'e-named', rarity: 3 };
const BOSS_A = { id: 'e-boss-a', rarity: 4 };
const BOSS_B = { id: 'e-boss-b', rarity: 4 };

const ALL = [TRASH, ELITE, NAMED, BOSS_A, BOSS_B];

describe('filterEnemiesByTab', () => {
  it('"bosses" keeps only rarity 4 profiles', () => {
    expect(filterEnemiesByTab(ALL, 'bosses')).toEqual([BOSS_A, BOSS_B]);
  });

  it('"all" returns every profile unfiltered', () => {
    expect(filterEnemiesByTab(ALL, 'all')).toEqual(ALL);
  });

  it('returns an empty array rather than throwing when no boss profiles exist', () => {
    expect(filterEnemiesByTab([TRASH, ELITE], 'bosses')).toEqual([]);
  });
});

describe('defaultEnemyId', () => {
  it('picks the first boss profile under the default tab', () => {
    expect(defaultEnemyId(ALL, 'bosses')).toBe('e-boss-a');
  });

  it('picks the first profile overall under the "all" tab', () => {
    expect(defaultEnemyId(ALL, 'all')).toBe('e-trash');
  });

  it('falls back to the first enemy overall when the bosses tab is empty', () => {
    expect(defaultEnemyId([TRASH, ELITE], 'bosses')).toBe('e-trash');
  });

  it('returns null when there are no enemies at all', () => {
    expect(defaultEnemyId([], 'bosses')).toBeNull();
  });
});
