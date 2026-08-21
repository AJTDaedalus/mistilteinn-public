import { describe, expect, it } from 'vitest';
import { filterInventory } from './filter-inventory';
import type { DiscRead } from '../builds/discs.service';

function disc(
  id: string,
  slot: number,
  rarity: string,
  level: number,
  main_stat_type: string,
): DiscRead {
  return {
    id,
    disc_set_id: 'set1',
    slot: slot as DiscRead['slot'],
    rarity: rarity as DiscRead['rarity'],
    level,
    main_stat_type: main_stat_type as DiscRead['main_stat_type'],
    main_stat_value: 1000,
    substats: [],
    build_id: null,
    build_slot: null,
  };
}

const MIXED_INVENTORY: DiscRead[] = [
  // Slot 1
  disc('s1-s', 1, 'S', 15, 'hp'),
  disc('s1-a', 1, 'A', 12, 'hp'),
  disc('s1-b', 1, 'B', 9, 'hp'),
  // Slot 4 — different mains
  disc('s4-cr-s', 4, 'S', 15, 'crit_rate'),
  disc('s4-cd-s', 4, 'S', 12, 'crit_dmg'),  // S but level < 15
  disc('s4-cr-a', 4, 'A', 15, 'crit_rate'),
  // Slot 5
  disc('s5-phy-s', 5, 'S', 15, 'physical_dmg'),
  disc('s5-atk-s', 5, 'S', 15, 'atk_pct'),
  // Slot 6
  disc('s6-hp-s', 6, 'S', 15, 'hp_pct'),
];

describe('filterInventory', () => {
  describe('C7 — rarity + level', () => {
    it('default S+15 keeps only S-rarity lv15 discs', () => {
      const { discIds, warnings } = filterInventory(MIXED_INVENTORY, {
        minRarity: 'S',
        minLevel: 15,
        mainStatBySlot: {},
      });
      // S+15 discs: s1-s, s4-cr-s, s5-phy-s, s5-atk-s, s6-hp-s
      // s4-cd-s is S but level 12 — excluded
      // s4-cr-a is A level 15 — excluded
      expect(discIds.sort()).toEqual(['s1-s', 's4-cr-s', 's5-atk-s', 's5-phy-s', 's6-hp-s'].sort());
      expect(warnings).toHaveLength(0);
    });

    it('A+12 includes S+A discs at level ≥12', () => {
      const { discIds } = filterInventory(MIXED_INVENTORY, {
        minRarity: 'A',
        minLevel: 12,
        mainStatBySlot: {},
      });
      // Excludes B-rarity and level < 12
      expect(discIds).not.toContain('s1-b');
      expect(discIds).toContain('s1-a');
      expect(discIds).toContain('s1-s');
    });
  });

  describe('C7b — main stat slot filter', () => {
    it('filters slot 4 to crit_rate only', () => {
      const { discIds } = filterInventory(MIXED_INVENTORY, {
        minRarity: 'S',
        minLevel: 15,
        mainStatBySlot: { 4: ['crit_rate'] },
      });
      expect(discIds).toContain('s4-cr-s');
      expect(discIds).not.toContain('s4-cd-s'); // S but level 12 — already rarity-filtered too
    });

    it('slot filter does not affect other slots', () => {
      const { discIds } = filterInventory(MIXED_INVENTORY, {
        minRarity: 'S',
        minLevel: 15,
        mainStatBySlot: { 4: ['crit_rate'] },
      });
      // Slot 5 and 6 should still have their S+15 discs
      expect(discIds).toContain('s5-phy-s');
      expect(discIds).toContain('s6-hp-s');
    });
  });

  describe('C7c — empty-slot fallback', () => {
    it('falls back and warns when main filter produces zero candidates', () => {
      // Slot 6 has only hp_pct disc; filter for atk_pct → zero → fallback
      const { discIds, warnings } = filterInventory(MIXED_INVENTORY, {
        minRarity: 'S',
        minLevel: 15,
        mainStatBySlot: { 6: ['atk_pct'] },
      });
      // Fallback: include all S+15 slot-6 discs
      expect(discIds).toContain('s6-hp-s');
      expect(warnings).toHaveLength(1);
      expect(warnings[0]).toContain('Slot 6');
      expect(warnings[0]).toContain('using all');
    });

    it('no warning when filter matches at least one disc', () => {
      const { warnings } = filterInventory(MIXED_INVENTORY, {
        minRarity: 'S',
        minLevel: 15,
        mainStatBySlot: { 5: ['physical_dmg'] },
      });
      expect(warnings).toHaveLength(0);
    });
  });
});
