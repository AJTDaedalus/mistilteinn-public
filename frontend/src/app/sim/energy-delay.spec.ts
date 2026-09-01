import { describe, expect, it } from 'vitest';

import {
  energyCost, energyCostMessage, energyDelays, energyDelayMessage,
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
});
