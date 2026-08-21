import { describe, it, expect } from 'vitest';
import { groupBuffRoster } from './buff-roster-group';
import type { components } from '../../api/api.types';

type BuffRosterEntrySchema = components['schemas']['BuffRosterEntrySchema'];

function entry(
  overrides: Partial<BuffRosterEntrySchema> & { value_bp: number },
): BuffRosterEntrySchema {
  return {
    source_label: 'Test Source',
    source_category: null,
    source_kind: null,
    owner_agent_name: null,
    stat: 'dmg_bonus',
    zone: 'boost',
    magnitude_display: '+0.00%',
    condition: null,
    is_modeled: true,
    notes: null,
    ...overrides,
  };
}

describe('groupBuffRoster', () => {
  it('places entries into the correct category bucket', () => {
    const entries: BuffRosterEntrySchema[] = [
      entry({ value_bp: 100, source_label: 'Core F', source_category: 'agent' }),
      entry({ value_bp: 200, source_label: 'Deep Sea', source_category: 'wengine' }),
      entry({ value_bp: 150, source_label: 'Polar 4pc', source_category: 'disc_set' }),
      entry({ value_bp: 80, source_label: 'Base ATK', source_category: 'base' }),
      entry({ value_bp: 60, source_label: 'ATK% main', source_category: 'discs' }),
      entry({ value_bp: 40, source_label: 'Food buff', source_category: 'external' }),
    ];

    const result = groupBuffRoster(entries);

    expect(result.agent).toHaveLength(1);
    expect(result.wengine).toHaveLength(1);
    expect(result.disc_set).toHaveLength(1);
    expect(result.base).toHaveLength(1);
    expect(result.discs).toHaveLength(1);
    expect(result.external).toHaveLength(1);
  });

  it('unknown/null source_category falls into external', () => {
    const entries = [
      entry({ value_bp: 50, source_label: 'Mystery buff', source_category: null }),
      entry({ value_bp: 30, source_label: 'Bad cat', source_category: 'unknown_cat' }),
    ];

    const result = groupBuffRoster(entries);
    expect(result.external).toHaveLength(2);
  });

  it('sorts rows within a group by descending |value_bp|', () => {
    const entries: BuffRosterEntrySchema[] = [
      entry({ value_bp: 50, source_label: 'Small', source_category: 'agent' }),
      entry({ value_bp: 300, source_label: 'Large', source_category: 'agent' }),
      entry({ value_bp: 150, source_label: 'Mid', source_category: 'agent' }),
    ];

    const result = groupBuffRoster(entries);
    expect(result.agent.map((e) => e.value_bp)).toEqual([300, 150, 50]);
  });

  it('is_modeled=false entries (active but 0-contributing) are kept, not dropped', () => {
    const entries = [
      entry({ value_bp: 0, source_label: 'Unbaked scaling stat', is_modeled: false }),
    ];
    const result = groupBuffRoster(entries);
    expect(result.external).toHaveLength(1);
    expect(result.external[0].is_modeled).toBe(false);
  });

  it('empty roster returns all groups as empty arrays', () => {
    const result = groupBuffRoster([]);
    for (const cat of ['agent', 'wengine', 'disc_set', 'base', 'discs', 'external'] as const) {
      expect(result[cat]).toHaveLength(0);
    }
  });
});
