import { describe, expect, it } from 'vitest';

import { isFilterableMainStat, sortMainStats } from './stat-order';

/**
 * The order main stats are offered in.
 *
 * Owner audit: *"Elemental damage all together and alphabetical, stat% together, EM and ER in
 * between."* Shared between the inventory filter and the optimizer's per-slot constraint, so a
 * user meets the same order twice.
 */

const stat = (key: string, display: string) => ({ key, display });

describe('sortMainStats', () => {
  it('puts elemental damage first, alphabetically by display', () => {
    // **By display, not by key.** `FIGHT_PROP_ELEC_ADD_HURT` sorts before
    // `FIGHT_PROP_FIRE_ADD_HURT`, but "Electro" and "Pyro" do not — and the user reads the
    // display.
    const found = sortMainStats([
      stat('FIGHT_PROP_FIRE_ADD_HURT', 'Pyro DMG Bonus'),
      stat('FIGHT_PROP_ELEC_ADD_HURT', 'Electro DMG Bonus'),
      stat('FIGHT_PROP_ICE_ADD_HURT', 'Cryo DMG Bonus'),
    ]);

    expect(found.map((s) => s.display)).toEqual([
      'Cryo DMG Bonus', 'Electro DMG Bonus', 'Pyro DMG Bonus',
    ]);
  });

  it('puts EM and ER between the damage bonuses and the percentages', () => {
    // The one thing that is *not* alphabetical across groups — Elemental Mastery sits there
    // because that is where a player looks for it, not because "E" falls there.
    const found = sortMainStats([
      stat('FIGHT_PROP_ATTACK_PERCENT', 'ATK%'),
      stat('FIGHT_PROP_ELEMENT_MASTERY', 'Elemental Mastery'),
      stat('FIGHT_PROP_FIRE_ADD_HURT', 'Pyro DMG Bonus'),
      stat('FIGHT_PROP_CHARGE_EFFICIENCY', 'Energy Recharge'),
    ]);

    expect(found.map((s) => s.display)).toEqual([
      'Pyro DMG Bonus', 'Elemental Mastery', 'Energy Recharge', 'ATK%',
    ]);
  });

  it('keeps the percentages together', () => {
    const found = sortMainStats([
      stat('FIGHT_PROP_HP_PERCENT', 'HP%'),
      stat('FIGHT_PROP_CRITICAL', 'CRIT Rate'),
      stat('FIGHT_PROP_ATTACK_PERCENT', 'ATK%'),
      stat('FIGHT_PROP_DEFENSE_PERCENT', 'DEF%'),
    ]);
    const keys = found.map((s) => s.key);

    // The three `_PERCENT` stats are contiguous; CRIT is neither a percentage key nor a
    // damage bonus, so it lands after them rather than between them.
    expect(keys.slice(0, 3).every((k) => k.endsWith('_PERCENT'))).toBe(true);
    expect(keys[3]).toBe('FIGHT_PROP_CRITICAL');
  });

  it('does not mutate the caller’s array', () => {
    const given = [stat('FIGHT_PROP_ATTACK_PERCENT', 'ATK%'), stat('FIGHT_PROP_HP_PERCENT', 'HP%')];
    const before = given.map((s) => s.key);

    sortMainStats(given);

    expect(given.map((s) => s.key)).toEqual(before);
  });
});

describe('isFilterableMainStat', () => {
  it('drops the flat stats', () => {
    // A flower is always flat HP and a plume always flat ATK, so offering them as a *choice*
    // is offering the only option there is.
    expect(isFilterableMainStat('FIGHT_PROP_HP')).toBe(false);
    expect(isFilterableMainStat('FIGHT_PROP_ATTACK')).toBe(false);
  });

  it('keeps their percentage forms, which are real choices', () => {
    // **The distinction that matters.** `FIGHT_PROP_HP` is a flower's only main stat;
    // `FIGHT_PROP_HP_PERCENT` is one of five a sands can roll.
    expect(isFilterableMainStat('FIGHT_PROP_HP_PERCENT')).toBe(true);
    expect(isFilterableMainStat('FIGHT_PROP_ATTACK_PERCENT')).toBe(true);
  });

  it('keeps everything else', () => {
    expect(isFilterableMainStat('FIGHT_PROP_CRITICAL')).toBe(true);
    expect(isFilterableMainStat('FIGHT_PROP_FIRE_ADD_HURT')).toBe(true);
  });
});
