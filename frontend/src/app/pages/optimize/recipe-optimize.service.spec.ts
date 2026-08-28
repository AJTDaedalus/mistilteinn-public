import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  GCSIM_LOADER,
  RECIPE_STORE,
  RecipeOptimizeService,
} from './recipe-optimize.service';
import { API_BASE_URL } from '../../api/api.client';
import type { RecipeStore } from '../../sim/recipe-cache';

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

function setup(over: { cached?: unknown; sample?: (cfg: string) => string } = {}) {
  const gcsim = {
    validateConfig: () => ({}),
    sample: over.sample ?? ((cfg: string) => sampleJson(cfg.includes('def%') ? { def_per: 0.5 } : {})),
    initializeAggregator: () => undefined,
    initializeWorker: () => undefined,
    simulate: () => new Uint8Array(),
    aggregate: () => undefined,
    flush: () => '{}',
  };

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
      { provide: GCSIM_LOADER, useValue: () => Promise.resolve(gcsim) },
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
      meta: { seed: '12345', staleConversions: [], calibratedSetIds: [], minimumEnergyRecharge: null },
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
      meta: { seed: '1', staleConversions: [], calibratedSetIds: [], minimumEnergyRecharge: 0.3 },
    } as never;

    expect(service.shortfall(recipe, 0.45)).toBeNull();
    expect(service.shortfall(recipe, 0.12)).toMatchObject({ has: 0.12, needs: 0.3 });
  });
});
