import { describe, it, expect } from 'vitest';
import { groupContributions } from './group-contributions';
import type { components } from '../../api/api.types';

type ContributionSchema = components['schemas']['ContributionSchema'];

function contrib(
  overrides: Partial<ContributionSchema> & { value: number },
): ContributionSchema {
  return {
    source: 'Test Source',
    source_category: null,
    source_kind: null,
    owner_agent_name: null,
    description: null,
    ...overrides,
  };
}

describe('groupContributions', () => {
  it('places contributions into the correct category bucket', () => {
    const contribs: ContributionSchema[] = [
      contrib({ value: 100, source: 'Core F', source_category: 'agent' }),
      contrib({ value: 200, source: 'Deep Sea', source_category: 'wengine' }),
      contrib({ value: 150, source: 'Polar 4pc', source_category: 'disc_set' }),
      contrib({ value: 80, source: 'Base ATK', source_category: 'base' }),
      contrib({ value: 60, source: 'ATK% main', source_category: 'discs' }),
      contrib({ value: 40, source: 'Food buff', source_category: 'external' }),
    ];

    const result = groupContributions(contribs, 'Ellen Joe');

    expect(result.agent).toHaveLength(1);
    expect(result.wengine).toHaveLength(1);
    expect(result.disc_set).toHaveLength(1);
    expect(result.base).toHaveLength(1);
    expect(result.discs).toHaveLength(1);
    expect(result.external).toHaveLength(1);
  });

  it('unknown/null source_category falls into external', () => {
    const contribs = [
      contrib({ value: 50, source: 'Mystery buff', source_category: null }),
      contrib({ value: 30, source: 'Bad cat', source_category: 'unknown_cat' }),
    ];

    const result = groupContributions(contribs, 'Ellen Joe');
    expect(result.external).toHaveLength(2);
  });

  it('sorts rows within a group by descending |value|', () => {
    const contribs: ContributionSchema[] = [
      contrib({ value: 50, source: 'Small', source_category: 'agent' }),
      contrib({ value: 300, source: 'Large', source_category: 'agent' }),
      contrib({ value: 150, source: 'Mid', source_category: 'agent' }),
    ];

    const result = groupContributions(contribs, 'Ellen Joe');
    const values = result.agent.map((r) => r.contribution.value);
    expect(values).toEqual([300, 150, 50]);
  });

  it('sorts by descending |value| when values are negative', () => {
    const contribs: ContributionSchema[] = [
      contrib({ value: -50, source: 'Small neg', source_category: 'agent' }),
      contrib({ value: -300, source: 'Large neg', source_category: 'agent' }),
    ];

    const result = groupContributions(contribs, 'Ellen Joe');
    const values = result.agent.map((r) => r.contribution.value);
    expect(values).toEqual([-300, -50]);
  });

  // ── Owner suffix elision ───────────────────────────────────────────────────

  it('ownerSuffix is null when owner equals activeAgentName', () => {
    const contribs = [
      contrib({
        value: 100,
        source: 'Core F',
        source_category: 'agent',
        owner_agent_name: 'Ellen Joe',
      }),
    ];

    const result = groupContributions(contribs, 'Ellen Joe');
    expect(result.agent[0].ownerSuffix).toBeNull();
  });

  it('ownerSuffix is the owner name when owner differs from activeAgentName', () => {
    const contribs = [
      contrib({
        value: 100,
        source: 'Cunning Hares',
        source_category: 'agent',
        owner_agent_name: 'Nicole Demara',
      }),
    ];

    const result = groupContributions(contribs, 'Ellen Joe');
    expect(result.agent[0].ownerSuffix).toBe('Nicole Demara');
  });

  it('ownerSuffix is null when owner_agent_name is null', () => {
    const contribs = [
      contrib({
        value: 100,
        source: 'Discs ATK%',
        source_category: 'discs',
        owner_agent_name: null,
      }),
    ];

    const result = groupContributions(contribs, 'Ellen Joe');
    expect(result.discs[0].ownerSuffix).toBeNull();
  });

  // ── Multiple contributions, mixed categories ───────────────────────────────

  it('distributes multiple contributions across categories correctly', () => {
    const contribs: ContributionSchema[] = [
      contrib({ value: 200, source: 'A1', source_category: 'agent', owner_agent_name: 'Ellen Joe' }),
      contrib({ value: 100, source: 'A2', source_category: 'agent', owner_agent_name: 'Nicole Demara' }),
      contrib({ value: 250, source: 'W1', source_category: 'wengine', owner_agent_name: 'Ellen Joe' }),
      contrib({ value: 75, source: 'D1', source_category: 'discs' }),
    ];

    const result = groupContributions(contribs, 'Ellen Joe');
    expect(result.agent).toHaveLength(2);
    expect(result.wengine).toHaveLength(1);
    expect(result.discs).toHaveLength(1);
    // Agent sorted by |value| descending
    expect(result.agent[0].contribution.source).toBe('A1');
    expect(result.agent[1].contribution.source).toBe('A2');
    // Nicole gets ownerSuffix; Ellen does not
    expect(result.agent[0].ownerSuffix).toBeNull();
    expect(result.agent[1].ownerSuffix).toBe('Nicole Demara');
  });

  it('empty contribution list returns all groups as empty arrays', () => {
    const result = groupContributions([], 'Ellen Joe');
    for (const cat of ['agent', 'wengine', 'disc_set', 'base', 'discs', 'external'] as const) {
      expect(result[cat]).toHaveLength(0);
    }
  });
});
