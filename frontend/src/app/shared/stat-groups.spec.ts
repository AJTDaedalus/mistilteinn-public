import { describe, expect, it } from 'vitest';

import { groupStats, isPercent, quantityLabel, type StatAccount } from './stat-groups';

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
    expect(crit.rows.map((r) => r.from)).toEqual(['character', 'artifact', 'weapon']);
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


describe('row labels and provenance', () => {
  it('names the quantity as a reader knows it', () => {
    expect(quantityLabel('atk_pct')).toBe('ATK%');
    expect(quantityLabel('crit_dmg')).toBe('CRIT DMG');
  });

  it('prettifies a quantity it has no name for rather than showing the key', () => {
    // So a quantity added upstream reads acceptably instead of as `shield_strength`, and
    // nothing has to be kept in step for the table to stay legible.
    expect(quantityLabel('shield_strength')).toBe('Shield Strength');
    expect(quantityLabel('cryo_dmg_bonus')).toBe('Cryo DMG Bonus');
  });

  it('renders a slot key in a note as the name a player uses', () => {
    // `equip_bracer substat` beside `Base ATK` and `ATK%` is the same raw-key ugliness those
    // labels fix, one field over. The server writes the key because the note is also a join
    // key; the substitution happens here rather than by rewording it upstream.
    const account: StatAccount = {
      quantity: 'atk_pct',
      parts: [{ quantity: 'atk_pct', value: 0.047, source: 'artifact', note: 'equip_bracer substat' }],
      sum_of_parts: 0.047,
      sources: ['artifact'],
    };

    const [atk] = groupStats([account], { atk: 1897 }, { equip_bracer: 'Flower' });

    expect(atk.rows[0].from).toBe('Flower substat');
  });

  it('leaves the note alone when no slot vocabulary was passed', () => {
    const account: StatAccount = {
      quantity: 'atk_pct',
      parts: [{ quantity: 'atk_pct', value: 0.047, source: 'artifact', note: 'equip_bracer substat' }],
      sum_of_parts: 0.047,
      sources: ['artifact'],
    };

    expect(groupStats([account], {})[0].rows[0].from).toBe('equip_bracer substat');
  });

  it('prefers the contribution note over its category', () => {
    // **Four artifacts all labelled "artifact" read as one row repeated.** The note says which
    // piece and whether it is a main stat or a substat; the source says only "artifact".
    const account: StatAccount = {
      quantity: 'atk_pct',
      parts: [
        { quantity: 'atk_pct', value: 0.308, source: 'artifact', note: 'equip_ring main stat +12' },
        { quantity: 'atk_pct', value: 0.087, source: 'artifact' },
      ],
      sum_of_parts: 0.395,
      sources: ['artifact', 'artifact'],
    };

    const [atk] = groupStats([account], { atk: 1897 });

    expect(atk.rows[0].from).toBe('equip_ring main stat +12');
    // Falls back rather than rendering blank when a contribution carries no note.
    expect(atk.rows[1].from).toBe('artifact');
  });
});
