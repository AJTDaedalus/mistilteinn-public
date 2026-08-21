import type { DiscRead } from '../builds/discs.service';

const RARITY_ORDER: Record<string, number> = { S: 3, A: 2, B: 1 };

export interface FilterInventoryOptions {
  minRarity: 'S' | 'A' | 'B';
  minLevel: number;
  mainStatBySlot: Partial<Record<4 | 5 | 6, string[]>>;
}

export interface FilterInventoryResult {
  discIds: string[];
  warnings: string[];
}

/**
 * Filters a disc inventory by rarity, level, and per-slot main stat, then
 * returns the passing disc IDs.  Discs that pass rarity+level but would be
 * fully excluded by a main-stat filter trigger a per-slot fallback (all
 * rarity/level-passing discs for that slot are kept) and a warning string.
 */
export function filterInventory(
  discs: DiscRead[],
  opts: FilterInventoryOptions,
): FilterInventoryResult {
  const { minRarity, minLevel, mainStatBySlot } = opts;
  const minRarityOrder = RARITY_ORDER[minRarity] ?? 3;

  // Step 1: basic rarity + level gate
  const passing = discs.filter(
    (d) => (RARITY_ORDER[d.rarity] ?? 0) >= minRarityOrder && d.level >= minLevel,
  );

  const warnings: string[] = [];
  const includedIds = new Set<string>();

  // Group passing discs by slot for per-slot main filtering
  const bySlot = new Map<number, DiscRead[]>();
  for (const d of passing) {
    const slot = typeof d.slot === 'number' ? d.slot : Number(d.slot);
    if (!bySlot.has(slot)) bySlot.set(slot, []);
    bySlot.get(slot)!.push(d);
  }

  for (const [slot, slotDiscs] of bySlot) {
    const mainFilter = mainStatBySlot[slot as 4 | 5 | 6];
    if (!mainFilter || mainFilter.length === 0) {
      // No main-stat filter for this slot — include all
      for (const d of slotDiscs) includedIds.add(d.id);
    } else {
      const filtered = slotDiscs.filter((d) => mainFilter.includes(d.main_stat_type));
      if (filtered.length === 0) {
        warnings.push(`Slot ${slot} main filter matched no discs; using all`);
        for (const d of slotDiscs) includedIds.add(d.id);
      } else {
        for (const d of filtered) includedIds.add(d.id);
      }
    }
  }

  return { discIds: Array.from(includedIds), warnings };
}
