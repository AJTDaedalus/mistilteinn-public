import type { components } from '../../api/api.types';

type ContributionSchema = components['schemas']['ContributionSchema'];

export type SourceCategory =
  | 'agent'
  | 'wengine'
  | 'disc_set'
  | 'base'
  | 'discs'
  | 'external';

export interface GroupedRow {
  contribution: ContributionSchema;
  ownerSuffix: string | null;
}

export const CATEGORY_ORDER: SourceCategory[] = [
  'agent',
  'wengine',
  'disc_set',
  'discs',
  'base',
  'external',
];

/**
 * Groups and sorts contributions for the buff drawer.
 *
 * Ordering: agent → wengine → disc_set → discs → base → external.
 * Within each group, rows are sorted by descending |value|.
 * ownerSuffix is null when the owner is absent or equals the active agent.
 * Contributions with an unknown/missing source_category fall into "external".
 */
export function groupContributions(
  contribs: ContributionSchema[],
  activeAgentName: string,
): Record<SourceCategory, GroupedRow[]> {
  const groups: Record<SourceCategory, GroupedRow[]> = {
    agent: [],
    wengine: [],
    disc_set: [],
    base: [],
    discs: [],
    external: [],
  };

  for (const contrib of contribs) {
    const rawCat = contrib.source_category ?? null;
    const category: SourceCategory =
      rawCat && (CATEGORY_ORDER as string[]).includes(rawCat)
        ? (rawCat as SourceCategory)
        : 'external';

    const owner = contrib.owner_agent_name ?? null;
    const ownerSuffix =
      owner && owner !== activeAgentName ? owner : null;

    groups[category].push({ contribution: contrib, ownerSuffix });
  }

  for (const cat of CATEGORY_ORDER) {
    groups[cat].sort((a, b) => Math.abs(b.contribution.value) - Math.abs(a.contribution.value));
  }

  return groups;
}
