import type { components } from '../../api/api.types';
import { CATEGORY_ORDER, type SourceCategory } from './group-contributions';

type BuffRosterEntrySchema = components['schemas']['BuffRosterEntrySchema'];

/**
 * Groups and sorts buff_roster entries for the active-buff panel
 * (DESIGN_explainability.md §2.3). Same category ordering/fallback rules as
 * `groupContributions` -- unknown/missing source_category falls into
 * "external"; entries within a group sort by descending |value_bp|.
 * `is_modeled=false` entries are kept (shown with a "not yet modeled" tag),
 * never dropped.
 */
export function groupBuffRoster(
  entries: BuffRosterEntrySchema[],
): Record<SourceCategory, BuffRosterEntrySchema[]> {
  const groups: Record<SourceCategory, BuffRosterEntrySchema[]> = {
    agent: [],
    wengine: [],
    disc_set: [],
    base: [],
    discs: [],
    external: [],
  };

  for (const entry of entries) {
    const rawCat = entry.source_category ?? null;
    const category: SourceCategory =
      rawCat && (CATEGORY_ORDER as string[]).includes(rawCat)
        ? (rawCat as SourceCategory)
        : 'external';
    groups[category].push(entry);
  }

  for (const cat of CATEGORY_ORDER) {
    groups[cat].sort((a, b) => Math.abs(b.value_bp) - Math.abs(a.value_bp));
  }

  return groups;
}
