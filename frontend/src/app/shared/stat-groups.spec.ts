import { describe, expect, it } from 'vitest';

import { groupStats, isPercent, type StatAccount } from './stat-groups';

/**
 * §12 — the details pane's stat table, grouped and totalled the way a build is read.
 */

const account = (quantity: string, parts: [string, number, string][]): StatAccount => ({
  quantity,
  parts: parts.map(([q, value, source]) => ({ quantity: q, value, source })),
  sum_of_parts: parts.reduce((sum, [, value]) => sum + value, 0),
  sources: parts.map(([, , source]) => source),
});

describe('isPercent', () => {
  it.each(['crit_rate', 'crit_dmg', 'energy_recharge', 'atk_pct', 'cryo_dmg_bonus'])(
    '%s is a fraction shown as a percentage', (quantity) => {
      expect(isPercent(quantity)).toBe(true);
    },
  );

  it.each(['atk', 'base_atk', 'flat_atk', 'elemental_mastery'])(
    '%s is an absolute number', (quantity) => {
      expect(isPercent(quantity)).toBe(false);
    },
  );
});

describe('groupStats', () => {
  it('shows the resolved total, which is never the sum of the rows', () => {
    // `base * (1 + pct) + flat` is not addition: 1000 base, +50%, +311 flat is 1811, and the
    // parts add to 1311.5. The group must show the server's number, not the arithmetic one.
    const accounts = [
      account('base_atk', [['base_atk', 1000, 'character']]),
      account('atk_pct', [['atk_pct', 0.5, 'artifact']]),
      account('flat_atk', [['flat_atk', 311, 'artifact']]),
    ];

    const [atk] = groupStats(accounts, { atk: 1811 });

    expect(atk.label).toBe('Effective ATK');
    expect(atk.total).toBe(1811);
    expect(atk.total).not.toBe(accounts.reduce((s, a) => s + a.sum_of_parts, 0));
  });

  it('lists every contribution as its own row', () => {
    // The owner's ask: a stat fed by three sources shows three rows, not one row with the
    // sources joined into a sentence.
    const accounts = [account('crit_rate', [
      ['crit_rate', 0.05, 'character'],
      ['crit_rate', 0.311, 'artifact'],
      ['crit_rate', 0.2, 'weapon'],
    ])];

    const [crit] = groupStats(accounts, { crit_rate: 0.561 });

    expect(crit.label).toBe('CRIT Rate');
    expect(crit.rows.map((r) => r.source)).toEqual(['character', 'artifact', 'weapon']);
    expect(crit.percent).toBe(true);
    expect(crit.rows.every((r) => r.percent)).toBe(true);
  });

  it('gives each element its own damage bonus group', () => {
    // A build carrying two bonuses has two different numbers, and one "Damage bonus" row
    // would have to pick one of them.
    const groups = groupStats(
      [account('cryo_dmg_bonus', [['cryo_dmg_bonus', 0.466, 'artifact']])],
      { cryo_dmg_bonus: 0.466 },
    );

    expect(groups.map((g) => g.label)).toEqual(['Cryo DMG Bonus']);
    expect(groups[0].total).toBe(0.466);
  });

  it('shows a group with no published total rather than computing one', () => {
    // A server that predates `totals` must degrade to the rows, not to an invented headline.
    const [atk] = groupStats([account('base_atk', [['base_atk', 1000, 'character']])], {});

    expect(atk.total).toBeNull();
    expect(atk.rows).toHaveLength(1);
  });

  it('drops nothing it does not recognise', () => {
    const groups = groupStats([account('mystery_stat', [['mystery_stat', 7, 'somewhere']])], {});

    expect(groups.map((g) => g.label)).toEqual(['Other']);
    expect(groups[0].rows[0].value).toBe(7);
  });

  it('omits a stat this build has nothing to say about', () => {
    // A talent scaling off ATK records no HP quantities. An empty "Effective HP" row would
    // present a question the page cannot answer as an answer it can.
    const groups = groupStats([account('base_atk', [['base_atk', 1000, 'character']])], {});

    expect(groups.map((g) => g.label)).not.toContain('Effective HP');
  });
});
