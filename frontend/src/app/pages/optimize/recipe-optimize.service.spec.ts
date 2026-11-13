import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  GCSIM_LOADER,
  RECIPE_STORE,
  RecipeOptimizeService,
  shareEnergyMeasurement,
} from './recipe-optimize.service';
import { API_BASE_URL } from '../../api/api.client';
import type { RecipeStore } from '../../sim/recipe-cache';
import { inlineRunner } from '../../sim/gcsim-runner';

/**
 * R.8 — calibrating one recipe per 4-piece state, and saying what they do not cover.
 *
 * The load-bearing tests are the **caveats**: a cached recipe is named, a stale conversion is
 * named with its damage share, and neither is silently dropped. An optimizer confidently wrong
 * in the case it was built to fix is worse than one that says it does not know.
 *
 * **Dependencies arrive through TestBed, not module mocks.** Angular's test system refuses
 * `vi.mock` for relative imports, and it is right to: a test coupled to how this service gets
 * its gcsim module is a test that breaks when that changes rather than when behaviour does.
 */

const CALC = {
  abil: 'Burst', talent: 2, total_scaling: 1000, base_atk: 1000, atk_per: 0, flat_atk: 0,
  base_hp: 10000, base_def: 800, hp_per: 0, def_per: 0, flat_dmg: 0, flat_hp: 0, flat_def: 0,
  bonus_dmg: 0, cr: 0, cd: 0, def_mod: 0.5, res_mod: 0.9, amp_mult_total: 0,
  use_hp: false, use_def: false, use_em: false,
  base_dmg: 2000, pre_crit_dmg: 900, avg_crit_dmg: 900, damage: 900, ele: 14,
};

const sampleJson = (over: Record<string, unknown> = {}) => JSON.stringify({
  seed: '12345',
  logs: [
    { event: 'damage', logs: { abil: 'Burst', ele: 'cryo', 'attack-tag': 4 } },
    { event: 'calc', logs: { ...CALC, ...over } },
  ],
});

/** An in-memory store, optionally pre-seeded with a cached recipe. */
function store(cached?: unknown): RecipeStore {
  const map = new Map<string, string>();
  if (cached !== undefined) {
    // Seeded under whatever key the service asks for — the key's own construction is
    // `recipe-cache.spec.ts`'s subject, not this one's.
    return {
      getItem: () => JSON.stringify(cached),
      setItem: (k, v) => void map.set(k, v),
      removeItem: (k) => void map.delete(k),
      get length() { return map.size; },
      key: (i) => [...map.keys()][i] ?? null,
    };
  }
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
    get length() { return map.size; },
    key: (i) => [...map.keys()][i] ?? null,
  };
}

/** The module stub, shared so a second test cannot drift from `setup`'s idea of it. */
function gcsimStub(sample?: (cfg: string) => string) {
  return {
    validateConfig: () => ({}),
    sample: sample ?? ((cfg: string) => sampleJson(cfg.includes('def%') ? { def_per: 0.5 } : {})),
    initializeAggregator: () => undefined,
    initializeWorker: () => undefined,
    simulate: () => new Uint8Array(),
    aggregate: () => undefined,
    flush: () => '{}',
  };
}


function setup(over: { cached?: unknown; sample?: (cfg: string) => string } = {}) {
  const gcsim = gcsimStub(over.sample);

  // **Stubbed before the service is constructed.** The API client captures `fetch` when it is
  // created, so a spy installed afterwards never intercepts — the first version of this reached
  // the network and failed on DNS.
  //
  // A fresh `Response` per call, because a body can only be read once and the service makes
  // one request per calibration target.
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(new Response(
    JSON.stringify({
      baseline: 'cfg', probe: 'cfg def%=0.5', energy_recharge: 0.3,
      artifact_set_id: null, probe_stat: 'def%', probe_delta: 0.5,
    }),
    { status: 200, headers: { 'content-type': 'application/json' } },
  )));

  TestBed.configureTestingModule({
    providers: [
      { provide: API_BASE_URL, useValue: 'http://test.local' },
      { provide: GCSIM_LOADER, useValue: () => Promise.resolve(inlineRunner(gcsim)) },
      { provide: RECIPE_STORE, useValue: store(over.cached) },
    ],
  });
  return TestBed.inject(RecipeOptimizeService);
}

beforeEach(() => {
  vi.restoreAllMocks();
  TestBed.resetTestingModule();
});

describe('RecipeOptimizeService', () => {
  it('does not let the two energy models share one cache entry', async () => {
    // **#240's lesson, applied before it bit.** A client-side option that never reaches the
    // cache key produces two identical answers — which reads as the two models *agreeing*
    // rather than as the option doing nothing. They do not agree: measured on the owner's own
    // team, Energy Recharge is worth +7.3 % skipping against +44.4 % waiting.
    const written: string[] = [];
    const recording: RecipeStore = {
      getItem: () => null,
      setItem: (k) => void written.push(k),
      removeItem: () => undefined,
      get length() { return 0; },
      key: () => null,
    };
    TestBed.resetTestingModule();
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(new Response(
      JSON.stringify({
        baseline: 'cfg', probe: 'cfg def%=0.5', energy_recharge: 0.3,
        artifact_set_id: null, probe_stat: 'def%', probe_delta: 0.5,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    )));
    TestBed.configureTestingModule({
      providers: [
        { provide: API_BASE_URL, useValue: 'http://test.local' },
        { provide: GCSIM_LOADER, useValue: () => Promise.resolve(inlineRunner(gcsimStub())) },
        { provide: RECIPE_STORE, useValue: recording },
      ],
    });
    const service = TestBed.inject(RecipeOptimizeService);
    const target = [{ artifactSetIds: [], setIds: [], label: 'baseline' }];
    const ignoreProgress = () => undefined;

    await service.calibrateAll('b1', 'r1', 'pin', target, ignoreProgress, undefined, false);
    await service.calibrateAll('b1', 'r1', 'pin', target, ignoreProgress, undefined, true);

    expect(written.length).toBeGreaterThan(1);
    expect(new Set(written).size).toBe(written.length);
  });

  it('does not let two weapons share one cache entry', async () => {
    // **The feature shipped broken and every test passed.** The backend substitution had an
    // integration test, the search loop had unit tests, the energy ladder grouping had unit
    // tests — and on a real two-weapon run Azurelight and Haran Geppaku Futsu came back at
    // **1,376,712.1 each, to the decimal**. A flat ranking reads as "these weapons are
    // equivalent" rather than as a bug, which is a conclusion a user would believe.
    //
    // Two causes. The client never passed the id, because a string replace matched the wrong
    // indentation and changed nothing while reporting success. And `context` is asked for
    // once, per build, *before* the weapon loop — so even once passed, every weapon shared one
    // cache entry and the second read the first's recipe.
    //
    // This asserts the half a unit test can see: two weapons, two keys.
    const written: string[] = [];
    const recording: RecipeStore = {
      getItem: () => null,
      setItem: (k) => void written.push(k),
      removeItem: () => undefined,
      get length() { return 0; },
      key: () => null,
    };
    TestBed.resetTestingModule();
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(new Response(
      JSON.stringify({
        baseline: 'cfg', probe: 'cfg def%=0.5', energy_recharge: 0.3,
        artifact_set_id: null, probe_stat: 'def%', probe_delta: 0.5,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    )));
    TestBed.configureTestingModule({
      providers: [
        { provide: API_BASE_URL, useValue: 'http://test.local' },
        { provide: GCSIM_LOADER, useValue: () => Promise.resolve(inlineRunner(gcsimStub())) },
        { provide: RECIPE_STORE, useValue: recording },
      ],
    });
    const service = TestBed.inject(RecipeOptimizeService);
    const target = [{ artifactSetIds: [], setIds: [], label: 'baseline' }];
    const ignoreProgress = () => undefined;

    await service.calibrateAll('b1', 'r1', 'pin', target, ignoreProgress, 'w-one');
    await service.calibrateAll('b1', 'r1', 'pin', target, ignoreProgress, 'w-two');

    expect(written.length).toBeGreaterThan(1);
    expect(new Set(written).size).toBe(written.length);
  });



  it('calibrates one recipe per target and keys them by set', async () => {
    const service = setup();
    const out = await service.calibrateAll('b1', 'r1', 'pin', [
      { artifactSetIds: [], setIds: [], label: 'no 4-piece' },
      { artifactSetIds: ['uuid-7'], setIds: [7], label: 'Blizzard Strayer' },
    ], () => undefined);

    expect(out.noFourPiece).not.toBeNull();
    expect(out.byFourPieceSet.get(7)).toBeDefined();
  });

  it('records the set a recipe was calibrated with, so its bonus is not paid twice', async () => {
    // **The double-count `RESEARCH_recipe_risks.md` §2 records.** Equipping a set to
    // calibrate also applies its 2-piece, so a recipe that does not name the set lets the
    // search add that tier a second time.
    //
    // This passed `null` unconditionally and was harmless only while no set bonuses reached
    // the search at all. B.1 made them reach it.
    const service = setup();

    const out = await service.calibrateAll('b1', 'r1', 'pin', [
      { artifactSetIds: ['uuid-7'], setIds: [7], label: 'Blizzard Strayer' },
    ], () => undefined);

    expect(out.byFourPieceSet.get(7)?.meta.calibratedSetIds).toEqual([7]);
  });

  it('keys recipes by the catalogue id, not by parsing the uuid', async () => {
    // `artifactSetId` is what `/calibrate` resolves — a uuid — so `Number()` of it is NaN and
    // every 4-piece recipe would land under one key. It read as an integer only while the
    // page was sending nanoka ids to an endpoint that wanted uuids (#122).
    const service = setup();

    const out = await service.calibrateAll('b1', 'r1', 'pin', [
      { artifactSetIds: ['01a025dd-eef7-7da0-9a65-533415ee1053'], setIds: [15003], label: 'A' },
      { artifactSetIds: ['01a025dd-f02a-7122-aeba-b9b6b0459c49'], setIds: [15044], label: 'B' },
    ], () => undefined);

    expect([...out.byFourPieceSet.keys()].sort()).toEqual([15003, 15044]);
  });

  it('reports progress per state, and flags the wasm load separately', async () => {
    // The 41 MB load is the slow first step and looks like a hang if it is not named.
    const service = setup();
    const seen: { current: string; loading: boolean }[] = [];
    await service.calibrateAll('b1', 'r1', 'pin',
      [{ artifactSetIds: [], setIds: [], label: 'no 4-piece' }],
      (p) => seen.push({ current: p.current, loading: p.loading }));

    expect(seen[0].loading).toBe(true);
    expect(seen.some((s) => s.current === 'no 4-piece')).toBe(true);
  });

  it('names a recipe served from cache rather than passing it off as fresh', async () => {
    const cached = {
      hits: [], seed: '12345',
      meta: { seed: '12345', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [], minimumEnergyRecharge: null },
    };
    const service = setup({ cached });

    const out = await service.calibrateAll('b1', 'r1', 'pin',
      [{ artifactSetIds: [], setIds: [], label: 'no 4-piece' }], () => undefined);

    expect(out.caveats.fromCache).toEqual(['no 4-piece']);
  });

  it('carries a stale conversion up with its damage share', async () => {
    // "83 hits affected" is not actionable; the share of the damage is.
    // A flat term that moves by a factor no stat ratio matches — unresolvable, so stale.
    const service = setup({
      sample: (cfg: string) => sampleJson(
        cfg.includes('def%') ? { flat_dmg: 400, def_per: 0.5 } : { flat_dmg: 320 },
      ),
    });

    const out = await service.calibrateAll('b1', 'r1', 'pin',
      [{ artifactSetIds: [], setIds: [], label: 'no 4-piece' }], () => undefined);

    expect(out.caveats.staleConversions).toHaveLength(1);
    expect(out.caveats.staleConversions[0]).toMatchObject({
      label: 'no 4-piece', term: 'flatDamage',
    });
    expect(out.caveats.staleConversions[0].damageShare).toBeGreaterThan(0);
  });

  it('reports an energy shortfall against the recipe’s own minimum', () => {
    const service = setup();
    const recipe = {
      hits: [], seed: '1',
      meta: { seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [], minimumEnergyRecharge: 0.3 },
    } as never;

    expect(service.shortfall(recipe, 0.45)).toBeNull();
    expect(service.shortfall(recipe, 0.12)).toMatchObject({ has: 0.12, needs: 0.3 });
  });
});


describe('shareEnergyMeasurement', () => {
  /**
   * The energy measurement is taken once per search, on the **set-free** target — because the
   * aggregate is filed in the run corpus under a key that names the context and not the
   * artifacts, so one run has to answer for every set.
   *
   * It was then stored on that target only, and that target is the baseline: the recipe
   * `unscoredLabels` exists to say nobody ranks on. Every 4-piece recipe — the ones that
   * actually score — came back with no ladder, so `energyRatio` was 1 for every candidate and
   * `liveQuantitiesFor` saw a flat ladder and went on pruning ER.
   *
   * That is the second half of the owner's report. Fixing the Pareto layer alone changes
   * nothing while the ladder never reaches the recipe being scored.
   */
  const sweep = [
    { energyRecharge: 0, burstInstances: 1, standardDeviation: 0, dps: 50 },
    { energyRecharge: 1, burstInstances: 2, standardDeviation: 0, dps: 100 },
  ];
  const cost = { characters: [{ character: 'Furina', seconds: 0, bursts: { real: 2, free: 5 } }], dpsCost: 0.07 };

  const recipe = (meta: Record<string, unknown> = {}) => ({
    hits: [], seed: '1',
    meta: {
      seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [],
      minimumEnergyRecharge: null, ...meta,
    },
  } as unknown as Parameters<typeof shareEnergyMeasurement>[0][number]);

  it('gives the ladder to the recipes that actually score', () => {
    const baseline = recipe({ energySweep: sweep, calibratedEnergyDps: 100, energyCost: cost });
    const fourPiece = recipe();

    shareEnergyMeasurement([baseline, fourPiece]);

    expect(fourPiece.meta.energySweep).toBe(sweep);
    expect(fourPiece.meta.calibratedEnergyDps).toBe(100);
    expect(fourPiece.meta.energyCost).toBe(cost);
  });

  it('does nothing when no ladder was swept', () => {
    // Not every rotation is energy-constrained, and inventing a flat one would make
    // `liveQuantitiesFor` keep ER live for every search that has no reason to.
    const a = recipe();
    const b = recipe();

    shareEnergyMeasurement([a, b]);

    expect(b.meta.energySweep).toBeUndefined();
    expect(b.meta.calibratedEnergyDps).toBeUndefined();
  });

  it('does not overwrite a recipe that measured its own cost', () => {
    const own = { characters: [], dpsCost: 0 };
    const baseline = recipe({ energySweep: sweep, calibratedEnergyDps: 100, energyCost: cost });
    const other = recipe({ energyCost: own });

    shareEnergyMeasurement([baseline, other]);

    expect(other.meta.energyCost).toBe(own);
    // The ladder is still shared: it is what scoring reads, and there was none to keep.
    expect(other.meta.energySweep).toBe(sweep);
  });
});
