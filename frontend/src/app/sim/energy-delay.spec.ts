import { describe, expect, it } from 'vitest';

import {
  energyCost, energyCostMessage, energyDelays, energyDelayMessage, subjectIsShort,
} from './energy-delay';

/**
 * The numbers here are the owner's real run: identical action counts to gcsim's own database
 * page, 191.7 s against 124.6 s, and the entire 67-second difference is Furina waiting.
 */
const RAW = {
  statistics: {
    failed_actions: [
      { insufficient_energy: { mean: 0 } },
      { insufficient_energy: { mean: 67.1 } },
      { insufficient_energy: { mean: 0.4 } },
      { insufficient_energy: { mean: 12.5 } },
    ],
  },
};
const ORDER = ['skirk', 'furina', 'citlali', 'escoffier'];

describe('energyDelays', () => {
  it('reads gcsim seconds per character, worst first', () => {
    expect(energyDelays(RAW, ORDER)).toEqual([
      { character: 'furina', seconds: 67.1 },
      { character: 'escoffier', seconds: 12.5 },
    ]);
  });

  it('drops a delay under the floor', () => {
    // 0.4 s is where a frame boundary fell, not "insufficient energy". Warning about it
    // teaches a reader to ignore the warning.
    expect(energyDelays(RAW, ORDER).map((d) => d.character)).not.toContain('citlali');
  });

  it('is positional against gcsim\'s own character order', () => {
    // `failed_actions` is indexed by gcsim's key order, so a caller passing names in another
    // order would blame the wrong character — silently, and plausibly.
    const swapped = energyDelays(RAW, ['furina', 'skirk', 'citlali', 'escoffier']);
    expect(swapped[0].character).toBe('skirk');
  });

  it('says nothing when nobody waits', () => {
    const quiet = { statistics: { failed_actions: [{ insufficient_energy: { mean: 0 } }] } };
    expect(energyDelays(quiet, ['skirk'])).toEqual([]);
    expect(energyDelayMessage([])).toBeNull();
  });

  it('survives a run that carries no failure block', () => {
    expect(energyDelays({ statistics: {} }, ORDER)).toEqual([]);
    expect(energyDelays(null, ORDER)).toEqual([]);
  });
});

describe('energyDelayMessage', () => {
  it('reads as a sentence for one character', () => {
    expect(energyDelayMessage([{ character: 'Furina', seconds: 67.1 }]))
      .toBe('Energy insufficient to burst on time for Furina: 67.1 second delay.');
  });

  it('gives each character its own figure', () => {
    // A combined total would hide which character to actually fix.
    expect(energyDelayMessage([
      { character: 'Furina', seconds: 67.1 },
      { character: 'Escoffier', seconds: 12.5 },
    ])).toBe('Energy insufficient to burst on time for Furina (67.1s), Escoffier (12.5s).');
  });
});


describe('energyCost — the counterfactual', () => {
  /**
   * The owner's real numbers. Their compiled rotation reports `insufficient_energy = 0` for
   * every character, because the compiler gates each step on `.ready` and gcsim never attempts
   * a burst it cannot pay for. The shortfall is visible only as bursts not cast.
   */
  const real = {
    stats: {
      dps: { mean: 173979 },
      character_actions: [
        { sources: { burst: { mean: 3 } } },
        { sources: { burst: { mean: 2 } } },
        { sources: { burst: { mean: 0 } } },
        { sources: { burst: { mean: 3 } } },
      ],
      failed_actions: [{}, {}, {}, {}],
    },
  };
  const free = {
    stats: {
      dps: { mean: 186167 },
      character_actions: [
        { sources: { burst: { mean: 4 } } },
        { sources: { burst: { mean: 5 } } },
        { sources: { burst: { mean: 0 } } },
        { sources: { burst: { mean: 4 } } },
      ],
    },
  };
  const party = ['Skirk', 'Furina', 'Citlali', 'Escoffier'];

  it('finds the shortfall a gated rotation hides', () => {
    const cost = energyCost(real, free, party);
    expect(cost.characters.map((c) => c.character)).toEqual(['Furina', 'Skirk', 'Escoffier']);
    expect(cost.characters[0].bursts).toEqual({ real: 2, free: 5 });
  });

  it('prices it, because that is the question being asked', () => {
    expect(energyCost(real, free, party).dpsCost).toBeCloseTo(0.07, 2);
  });

  it('leaves a character who loses nothing out of it', () => {
    // Citlali never bursts in this rotation; she is not short of energy, she simply has none
    // to spend, and naming her would teach a reader to ignore the line.
    expect(energyCost(real, free, party).characters.map((c) => c.character))
      .not.toContain('Citlali');
  });

  it('says nothing when energy costs nothing', () => {
    expect(energyCostMessage(energyCost(real, real, party))).toBeNull();
  });

  it('reads as the owner wrote it, with the toll', () => {
    expect(energyCostMessage(energyCost(real, free, party))).toBe(
      'Energy insufficient to burst on time for Furina (2 of 5 bursts), '
      + 'Skirk (3 of 4 bursts), Escoffier (3 of 4 bursts) — costing 7.0% DPS.',
    );
  });

  /**
   * Owner, 2026-08-31: *"Skirk has no burst energy cost, she has a unique burst effect.
   * Something is very wrong there."*
   *
   * Her burst spends Serpent's Subtlety, so it cannot be short of energy — and yet her count
   * moves between the two runs above, because the counterfactual changes the whole team's
   * timing. That is the false positive: a real difference, attributed to the wrong cause.
   */
  const costs = [null, 60, 60, 60];

  it('never reports a character whose burst costs no energy', () => {
    expect(energyCost(real, free, party, costs).characters.map((c) => c.character))
      .toEqual(['Furina', 'Escoffier']);
  });

  it('still names the teammates who are genuinely short', () => {
    expect(energyCostMessage(energyCost(real, free, party, costs))).toBe(
      'Energy insufficient to burst on time for Furina (2 of 5 bursts), '
      + 'Escoffier (3 of 4 bursts) — costing 7.0% DPS.',
    );
  });

  it('filters nothing when the costs are unknown', () => {
    // An empty list is "the caller has not said", which is different from "none of them cost
    // energy" — guessing the second from the first would silently empty the warning.
    expect(energyCost(real, free, party, []).characters).toHaveLength(3);
  });

  /**
   * Optimize's two runs are calibration probes: the subject wears an ER value and a set bonus
   * and nothing else, so a missed burst costs far more of that build's DPS than of a real one.
   * The ratio read 47.9% on Optimize where Calculate, on the same team and rotation with the
   * actual artifacts equipped, measured 6.9%.
   */
  it('omits the toll for a run that was not wearing real gear', () => {
    expect(energyCostMessage(energyCost(real, free, party, costs), false)).toBe(
      'Energy insufficient to burst on time for Furina (2 of 5 bursts), '
      + 'Escoffier (3 of 4 bursts).',
    );
  });
});

describe('subjectIsShort — ER is per character', () => {
  const cost = {
    characters: [
      { character: 'Furina', seconds: 0, bursts: { real: 2, free: 5 } },
    ],
    dpsCost: 0.07,
  };

  it('is true when the optimized character is the starved one', () => {
    expect(subjectIsShort(cost, 'Furina')).toBe(true);
  });

  it("is false when it is a teammate who is starved", () => {
    // The owner's question: *"If Furina is starved and Skirk isn't, does it trigger ER
    // optimization for Skirk? Even though that does nothing?"* It must not — Skirk's burst
    // count is governed by his own ER, so the ladder would spend six gcsim runs measuring a
    // curve that is flat. Her shortfall is still named by the warning.
    expect(subjectIsShort(cost, 'Skirk')).toBe(false);
  });

  it('is false before anything has been measured', () => {
    expect(subjectIsShort(null, 'Furina')).toBe(false);
  });

  it('is false for a character short by nothing', () => {
    const even = { characters: [{ character: 'Skirk', seconds: 0, bursts: { real: 4, free: 4 } }], dpsCost: 0 };
    expect(subjectIsShort(even, 'Skirk')).toBe(false);
  });
});
