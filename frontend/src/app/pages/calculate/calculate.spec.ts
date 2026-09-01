import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { CalculatePage } from './calculate';
import { BuildsService } from '../builds/builds.service';
import { GCSIM_LOADER } from '../optimize/recipe-optimize.service';
import { RotationsService } from '../rotations/rotations.service';

/**
 * **Calculate runs the team's real config through gcsim and reads what it reports.**
 *
 * It used to calibrate a recipe per character — the optimizer's machinery, which exists so a
 * search can score thousands of candidates cheaply. One team and one rotation is one run, and
 * running it removes the approximation rather than improving it.
 *
 * Parsing gcsim's object is `rotation-stats.spec.ts`; this covers what the page decides.
 */

const REPORT = {
  characters: [
    { name: 'Skirk', dps: { mean: 120000, sd: 0, min: 0, max: 0 }, insufficientEnergy: 0,
      bySource: [{ name: 'Normal (Skill) 0', spread: { mean: 90, sd: 0, min: 0, max: 0 } },
                 { name: 'Normal 0', spread: { mean: 10, sd: 0, min: 0, max: 0 } }],
      byElement: [], actions: [], fieldTime: null, endingEnergy: null },
    { name: 'Furina', dps: { mean: 30000, sd: 0, min: 0, max: 0 }, insufficientEnergy: 67.1,
      bySource: [], byElement: [], actions: [], fieldTime: null, endingEnergy: null },
  ],
};

function page() {
  TestBed.configureTestingModule({
    providers: [
      { provide: RotationsService, useValue: {} },
      { provide: BuildsService, useValue: {} },
      { provide: GCSIM_LOADER, useValue: vi.fn() },
    ],
  });
  return TestBed.runInInjectionContext(
    () => new CalculatePage(),
  ) as unknown as Record<string, never>;
}

describe('CalculatePage headline', () => {
  it('rounds the estimate to what its spread supports', () => {
    // 192,580.52 ± 5,732.01 is eight digits of precision on four of knowledge.
    const p = page();
    (p['stats'] as unknown as { set: (v: unknown) => void }).set({
      iterations: 200,
      dps: { mean: 192580.52, sd: 5732.01, min: 0, max: 0 },
      duration: { mean: 191.7, sd: 0.4, min: 0, max: 0 },
      eps: null, rps: null, hps: null, shp: null,
      characters: [], reactions: [], auraUptime: [],
    });

    const head = (p['headline'] as unknown as () => { dps: { value: number; uncertainty: number } })();

    expect(head.dps.value).toBe(192600);
    expect(head.dps.uncertainty).toBe(5700);
  });

  it('is null before a run', () => {
    expect((page()['headline'] as unknown as () => unknown)()).toBeNull();
  });
});

describe('CalculatePage shares', () => {
  it('sums the per-character figures it shows, so a reader can check it', () => {
    const p = page();
    (p['stats'] as unknown as { set: (v: unknown) => void }).set(REPORT);
    // `.call(p, …)`: `shareOf` reads `this.stats()`, and pulling the method off the object
    // detaches it. The first version of this test lost `this` and blamed the code.
    const share = (w: unknown) =>
      (p['shareOf'] as unknown as (this: unknown, w: unknown) => number).call(p, w);

    expect(share(REPORT.characters[0])).toBeCloseTo(0.8);
    expect(share(REPORT.characters[1])).toBeCloseTo(0.2);
  });

  it('gives a source its share of that character, not of the team', () => {
    const p = page();
    const share = p['sourceShare'] as unknown as (w: unknown, s: unknown) => number;
    const skirk = REPORT.characters[0];

    expect(share(skirk, skirk.bySource[0])).toBeCloseTo(0.9);
  });

  it('does not divide by zero for a character who dealt nothing', () => {
    const p = page();
    (p['stats'] as unknown as { set: (v: unknown) => void }).set({ characters: [] });
    expect(
      (p['shareOf'] as unknown as (this: unknown, w: unknown) => number).call(p, { dps: null }),
    ).toBe(0);
  });
});

describe('CalculatePage energy warning', () => {
  it('reports the shortfall the counterfactual found', () => {
    const p = page();
    (p['energyCost'] as unknown as { set: (v: unknown) => void }).set({
      characters: [{ character: 'Furina', seconds: 0, bursts: { real: 2, free: 5 } }],
      dpsCost: 0.07,
    });

    expect((p['energyDelay'] as unknown as () => string)()).toBe(
      'Energy insufficient to burst on time for Furina (2 of 5 bursts) — costing 7.0% DPS.',
    );
  });

  it('says nothing before the second run has finished', () => {
    // The counterfactual runs *after* the numbers are on screen, so the absence of a warning
    // must not read as "energy is fine" while it is still being measured.
    expect((page()['energyDelay'] as unknown as () => unknown)()).toBeNull();
  });
});
