import { describe, expect, it } from 'vitest';

import {
  type SetRecommendation,
  type WeaponGuide,
  type WeaponRecommendation,
  listedFirst,
  marked,
  setsByNanokaId,
  statAdvice,
  weaponCard,
  weaponsById,
} from './kqm';

function weapon(over: Partial<WeaponRecommendation> = {}): WeaponRecommendation {
  return {
    position: 1, weapon_id: 'row-homa', weapon_nanoka_id: 13501,
    weapon_name: 'Staff of Homa', note: 'Uncontested BiS.', playstyle: '', relative_dps: '',
    ...over,
  };
}

function set(over: Partial<SetRecommendation> = {}): SetRecommendation {
  return {
    position: 1, kind: 'set', as_written: '4pc Crimson Witch of Flames (1 Stack)',
    note: '100%', set_id: 'row-cw', set_nanoka_id: 15006, set_name: 'Crimson Witch of Flames',
    pieces: '4pc', playstyle: '', relative_dps: '',
    ...over,
  };
}

function guide(over: Partial<WeaponGuide> = {}): WeaponGuide {
  return {
    character: 'Hu Tao', url: 'https://keqingmains.com/hutao/', retrieved_at: '2026-09-02',
    weapons: [], sets: [], ...over,
  };
}

describe('weaponsById', () => {
  it('drops a row this pin cannot link rather than keying it by null', () => {
    // The endpoint publishes the row with its citation intact and `weapon_id: null` when the
    // seeded patch has no such weapon. There is nothing to mark, and `null` as a map key would
    // collide every unresolved row onto one entry.
    const listed = weaponsById(guide({
      weapons: [weapon(), weapon({ position: 2, weapon_id: null, weapon_nanoka_id: 99999 })],
    }));

    expect([...listed.keys()]).toEqual(['row-homa']);
  });

  it('is empty for a character nobody captured', () => {
    // **Null is not an empty guide**, and the pages rely on that: a card marked *not
    // recommended* because nobody captured the character is a claim about KQM nobody made.
    expect(weaponsById(null).size).toBe(0);
  });
});

describe('setsByNanokaId', () => {
  it('keys on the game id, which is what the set catalogue is already keyed by', () => {
    const listed = setsByNanokaId(guide({ sets: [set()] }));

    expect(listed.get(15006)?.set_name).toBe('Crimson Witch of Flames');
  });

  it('keeps the best position when a guide lists one set under several playstyles', () => {
    // Zhongli's guide carries 32 set rows across five playstyles, so a set appears several
    // times with several positions. A card shows one, and KQM's order is the recommendation.
    const listed = setsByNanokaId(guide({
      sets: [
        set({ position: 4, playstyle: 'Burst Support' }),
        set({ position: 2, playstyle: 'Main DPS' }),
      ],
    }));

    expect(listed.get(15006)?.position).toBe(2);
    expect(listed.get(15006)?.playstyle).toBe('Main DPS');
  });

  it('never turns a stat description into a set', () => {
    // `2pc HP% / ER` names every set granting HP%, not a set. Resolving it would invent a name
    // KQM did not write, which is the curated-data failure this repo must not import.
    const listed = setsByNanokaId(guide({
      sets: [set({ kind: 'stat', as_written: '2pc HP% / ER', set_id: null, set_nanoka_id: null,
                   set_name: null })],
    }));

    expect(listed.size).toBe(0);
  });
});

describe('statAdvice', () => {
  it('returns the stat rows and only those, as KQM wrote them', () => {
    const stat = set({ kind: 'stat', as_written: '2pc HP% / ER', set_nanoka_id: null,
                       set_name: null });

    expect(statAdvice(guide({ sets: [set(), stat] })).map((e) => e.as_written))
      .toEqual(['2pc HP% / ER']);
  });
});

describe('marked', () => {
  it('says position and never rank', () => {
    // KQM's table carries an order and no rank numbers. "#1" is where it appears; calling it a
    // rank would put a word in the source's mouth.
    const card = marked({ value: 'x', label: 'Staff of Homa', detail: '5★' }, weapon());

    expect(card.detail).toBe('KQM #1 · 5★');
    expect(card.detail).not.toContain('rank');
  });

  it('carries KQM sentence verbatim, and the card own explanation with it', () => {
    // A set card's tooltip is its 4-piece bonus. Dropping it to make room for the citation
    // would trade one true thing for another.
    const card = marked(
      { value: 'x', label: 'Crimson Witch', tooltip: 'Bonus from Pyro DMG' }, set(),
    );

    expect(card.tooltip).toBe('100%\n\nBonus from Pyro DMG');
  });

  it('leaves an unlisted card its own tooltip and marks it false rather than absent', () => {
    const card = marked({ value: 'x', label: 'Set', tooltip: 'Bonus from ER' }, undefined);

    expect(card.tooltip).toBe('Bonus from ER');
    expect(card.recommended).toBe(false);
    expect(card.tags).toEqual({ kqm: '' });
  });
});

describe('weaponCard', () => {
  const summary = {
    id: 'row-homa', name: 'Staff of Homa', icon: 'UI_EquipIcon_Pole_Homa',
    stars: 5, sub_stat_display: 'CRIT DMG',
  };

  it('gives the substat line up to KQM comparison when there is one', () => {
    // Four segments is what a card's second line holds. The substat is on the weapon's own
    // page; KQM's position and percentage are why this card is at the top of the list.
    expect(weaponCard(summary, weapon({ relative_dps: '114.2%', playstyle: 'Burst' })).detail)
      .toBe('KQM #1 · 114.2% · Burst · 5★');
  });

  it('keeps the substat when KQM says nothing', () => {
    expect(weaponCard(summary, undefined).detail).toBe('5★ · CRIT DMG');
  });
});

describe('listedFirst', () => {
  it('puts listed cards in KQM order and leaves the rest where they were', () => {
    // A weapon KQM did not list is not thereby *bad* — it is unlisted, which is why the rest
    // keep their order rather than being pushed into a "not recommended" bucket.
    const order = listedFirst(
      [{ id: 'c' }, { id: 'a' }, { id: 'b' }],
      (card) => ({ a: 1, b: 2 } as Record<string, number>)[card.id],
    );

    expect(order.map((card) => card.id)).toEqual(['a', 'b', 'c']);
  });
});
