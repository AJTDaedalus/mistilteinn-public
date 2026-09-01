import { describe, expect, it } from 'vitest';

import { energyDelays, energyDelayMessage } from './energy-delay';

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
