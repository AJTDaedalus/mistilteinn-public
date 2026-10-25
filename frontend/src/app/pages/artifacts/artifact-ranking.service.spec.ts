import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { type InventorySnapshot, OptimizeService } from '../optimize/optimize.service';
import {
  type CalibrationResult, type CalibrationTarget, RecipeOptimizeService,
} from '../optimize/recipe-optimize.service';
import { LADDERS, MAIN_VALUES, WEIGHTS, syntheticRecipe } from '../../sim/upgrade-fixtures';
import { ArtifactRankingService } from './artifact-ranking.service';
import { ArtifactsService } from './artifacts.service';

/**
 * `docs/TASKS_artifacts_followups.md` F1.1–F1.2: the four methods that set up a build before
 * scoring it — `rank`, `outcomesFor`, `upgradeEstimate` and the dive (`deepDive`,
 * `sweepBestBuilds`) — pinned on one fixture, and held to one refusal rule.
 *
 * **The two recipes differ on purpose.** The build's own 4-piece recipe has more hits than the
 * no-4-piece one, so every number scored under the wrong recipe moves by about a quarter. A
 * fixture where they were equal could not tell a silent fallback from the right answer.
 */

const WORN_SET = 101;
const OFF_SET = 202;
const THIRD_SET = 303;

const FOUR_PIECE = syntheticRecipe(25);
const NO_FOUR_PIECE = syntheticRecipe(20);

type Candidate = InventorySnapshot['artifacts'][number];

function piece(
  id: string, slot: string, setId: number, stats: Record<string, number>,
  potential: Candidate['potential'] = null, level = 20,
): Candidate {
  return { id, slot, set_id: setId, stats, main_stat: 'x', rarity: 5, level, potential };
}

const SUBS = (lines: string[], remaining: number, gains = false): Candidate['potential'] => ({
  rolls_remaining: remaining, rolls_total: gains ? 8 : 9, gains_a_substat: gains,
  substat_quantities: lines,
});

/** Four of `WORN_SET` and an off-piece circlet: a 4+1 build, the ordinary shape. */
const WORN: Candidate[] = [
  piece('w-flower', 'equip_bracer', WORN_SET,
    { flat_hp: 4780, crit_rate: 0.07, crit_dmg: 0.2, atk_pct: 0.1, flat_def: 20 },
    SUBS(['crit_rate', 'crit_dmg', 'atk_pct', 'flat_def'], 0)),
  piece('w-plume', 'equip_necklace', WORN_SET,
    { flat_atk: 311, crit_rate: 0.1, crit_dmg: 0.14, energy_recharge: 0.11, hp_pct: 0.05 },
    SUBS(['crit_rate', 'crit_dmg', 'energy_recharge', 'hp_pct'], 0)),
  piece('w-sands', 'equip_shoes', WORN_SET,
    { atk_pct: 0.466, crit_rate: 0.06, crit_dmg: 0.21, flat_hp: 500, elemental_mastery: 40 },
    SUBS(['crit_rate', 'crit_dmg', 'flat_hp', 'elemental_mastery'], 0)),
  piece('w-goblet', 'equip_ring', WORN_SET,
    { hydro_dmg_bonus: 0.466, crit_rate: 0.035, crit_dmg: 0.28, flat_atk: 30, def_pct: 0.06 },
    SUBS(['crit_rate', 'crit_dmg', 'flat_atk', 'def_pct'], 0)),
  piece('w-circlet', 'equip_dress', OFF_SET,
    { crit_dmg: 0.622, crit_rate: 0.1, atk_pct: 0.14, flat_atk: 35, energy_recharge: 0.06 },
    SUBS(['crit_rate', 'atk_pct', 'flat_atk', 'energy_recharge'], 0)),
];

/** Pieces the build is not wearing: one keeps the 4-piece, two break it, one is a +0. */
const SPARE: Candidate[] = [
  piece('s-circlet', 'equip_dress', WORN_SET,
    { crit_rate: 0.311, crit_dmg: 0.3, atk_pct: 0.1, flat_atk: 20, hp_pct: 0.05 },
    SUBS(['crit_dmg', 'atk_pct', 'flat_atk', 'hp_pct'], 0)),
  piece('s-flower', 'equip_bracer', OFF_SET,
    { flat_hp: 4780, crit_rate: 0.1, crit_dmg: 0.25, atk_pct: 0.05, flat_atk: 16 },
    SUBS(['crit_rate', 'crit_dmg', 'atk_pct', 'flat_atk'], 0)),
  piece('s-sands', 'equip_shoes', THIRD_SET,
    { atk_pct: 0.466, crit_rate: 0.12, crit_dmg: 0.25, energy_recharge: 0.05, flat_def: 19 },
    SUBS(['crit_rate', 'crit_dmg', 'energy_recharge', 'flat_def'], 0)),
  piece('s-plume-0', 'equip_necklace', WORN_SET,
    { flat_atk: 47, crit_rate: 0.035, crit_dmg: 0.07, atk_pct: 0.05 },
    SUBS(['crit_rate', 'crit_dmg', 'atk_pct'], 5, true), 0),
];

function snapshot(overrides: { freshDrop?: boolean } = {}): InventorySnapshot {
  const artifacts = [...WORN, ...SPARE];
  return {
    version: 'v-test',
    artifacts,
    total: artifacts.length,
    truncated: false,
    unreadable: [],
    draw_model: {
      roll_tiers: {
        '5': Object.entries(LADDERS).map(([quantity, values]) => ({ quantity, values: [...values] })),
      },
      substat_weights: { ...WEIGHTS },
      weights_caveat: 'cited weights',
      fresh_drop: overrides.freshDrop === false ? null : {
        five_star_per_run: 1.065,
        four_line_share: 0.2,
        set_share: 0.5,
        slot_share: 0.2,
        resin_per_run: 20,
        // One main stat per slot except the circlet, so the enumeration stays small.
        main_stat_probabilities: {
          equip_bracer: { flat_hp: 1 },
          equip_necklace: { flat_atk: 1 },
          equip_shoes: { atk_pct: 1 },
          equip_ring: { hydro_dmg_bonus: 1 },
          equip_dress: { crit_rate: 0.5, crit_dmg: 0.5 },
        },
        main_stat_values: { ...MAIN_VALUES },
        sets_without_domain_drop: [],
      },
    },
  };
}

interface Setup {
  /** The build's own 4-piece recipe is missing from the calibration, as when gcsim fails on it. */
  wornRecipeMissing?: boolean;
  freshDrop?: boolean;
}

function setUp(options: Setup = {}) {
  const calibrateAll = vi.fn(async (
    _build: string, _rotation: string, _epoch: string, targets: CalibrationTarget[],
  ): Promise<CalibrationResult> => {
    const byFourPieceSet = new Map();
    for (const target of targets) {
      const [setId] = target.setIds;
      if (setId === WORN_SET && !options.wornRecipeMissing) byFourPieceSet.set(setId, FOUR_PIECE);
    }
    return {
      byFourPieceSet,
      byPair: new Map(),
      noFourPiece: NO_FOUR_PIECE,
      caveats: { unstable: [], staleConversions: [] } as unknown as CalibrationResult['caveats'],
    };
  });
  const sets = new Map([WORN_SET, OFF_SET, THIRD_SET].map((id) => [
    id, { id: `uuid-${id}`, name: `Set ${id}`, icon: null },
  ]));

  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      {
        provide: OptimizeService,
        useValue: {
          inventory: vi.fn(async () => snapshot({ freshDrop: options.freshDrop })),
          artifactSets: vi.fn(async () => sets),
        },
      },
      {
        provide: ArtifactsService,
        useValue: {
          list: vi.fn(async () => ({
            items: WORN.map((p) => ({ id: p.id, slot: p.slot })),
          })),
        },
      },
      { provide: RecipeOptimizeService, useValue: { calibrateAll } },
    ],
  });
  return { service: TestBed.inject(ArtifactRankingService), calibrateAll };
}

const REQUEST = { buildId: 'b1', rotationId: 'r1' };

/**
 * Printed from the code at `bbb04af`, before the setup was merged (F1.1), and not edited since.
 * A refactor that changes any of these changed a number, which is the one thing it may not do.
 */
const PINNED = {
  baseline: 124306.82703160266,
  rankDeltas: {
    's-circlet': 10776.9852037175,
    's-flower': -22118.17513721589,
    's-sands': -17382.96170890557,
    's-plume-0': -13858.966553780221,
  },
  plumeOdds: 0.0000038116663914067313,
  outcomes: { mean: 110377.13999723323, current: 102202.42168080075, bins: 60 },
  upgrade: [
    ['equip_bracer', 0.01057199945343677, 12320],
    ['equip_necklace', 0.037188887117280175, 3500],
    ['equip_shoes', 0.047843817287375044, 2720],
    ['equip_ring', 0.06636937990091868, 1960],
    ['equip_dress', 0.07047322092350575, 920],
  ],
  dive: { after: 138188.85515310548, gain: 0.11167550852193805, without: 143457.42507069267 },
  sweep: 0.154059101148333,
} as const;

describe('ArtifactRankingService: characterisation (F1.1)', () => {
  it('rank: the baseline is the 4-piece build, and each spare scores against it', async () => {
    const { service } = setUp();
    const ranked = await service.rank(REQUEST);
    expect(ranked.baseline).toBeCloseTo(PINNED.baseline, 6);
    const byId = new Map(ranked.rows.map((row) => [row.id, row]));
    for (const piece of WORN) expect(byId.get(piece.id)?.averageDelta).toBe(0);
    for (const [id, delta] of Object.entries(PINNED.rankDeltas)) {
      expect(byId.get(id)?.averageDelta).toBeCloseTo(delta, 6);
    }
    expect(byId.get('s-plume-0')?.upgradeOdds).toBeCloseTo(PINNED.plumeOdds, 12);
  });

  it('outcomesFor: the +0 plume, against the 4-piece baseline', async () => {
    const { service } = setUp();
    const outcomes = await service.outcomesFor({ ...REQUEST, artifactId: 's-plume-0' });
    expect(outcomes?.reference).toBeCloseTo(PINNED.baseline, 6);
    expect(outcomes?.mean).toBeCloseTo(PINNED.outcomes.mean, 6);
    expect(outcomes?.current).toBeCloseTo(PINNED.outcomes.current, 6);
    expect(outcomes?.bins.length).toBe(PINNED.outcomes.bins);
  });

  it('upgradeEstimate: every slot', async () => {
    const { service } = setUp();
    const upgrade = await service.upgradeEstimate(REQUEST);
    expect(upgrade.baseline).toBeCloseTo(PINNED.baseline, 6);
    expect(upgrade.rows.map((row) => row.slot)).toEqual(PINNED.upgrade.map(([slot]) => slot));
    upgrade.rows.forEach((row, i) => {
      expect(row.pBeat).toBeCloseTo(PINNED.upgrade[i][1], 12);
      expect(row.estimate.median).toBe(PINNED.upgrade[i][2]);
    });
  });

  it('deepDive and sweepBestBuilds: measured from the 4-piece build', async () => {
    const { service } = setUp();
    const dive = await service.deepDive({ ...REQUEST, artifactId: 's-flower' });
    expect(dive.before).toBeCloseTo(PINNED.baseline, 6);
    expect(dive.after).toBeCloseTo(PINNED.dive.after, 6);
    expect(dive.gain).toBeCloseTo(PINNED.dive.gain, 12);
    expect(dive.bestWithout).toBeCloseTo(PINNED.dive.without, 6);

    const sweep = await service.sweepBestBuilds({
      ...REQUEST, artifactIds: ['s-circlet', 's-sands'],
    });
    expect(sweep.get('s-circlet')).toBeCloseTo(PINNED.sweep, 12);
    expect(sweep.get('s-sands')).toBeCloseTo(PINNED.sweep, 12);
  });
});

/**
 * F1.2. When the build's own 4-piece recipe is missing, scoring under `noFourPiece` would
 * understate the build by its own set bonus, and not uniformly. Rank refused; the outcome
 * chart, the dive and the sweep fell back silently. One rule now, and one message.
 */
describe('ArtifactRankingService: one refusal rule (F1.2)', () => {
  const MISSING = /4-piece set \(101\) that was not calibrated/;

  it.each([
    ['rank', (s: ArtifactRankingService) => s.rank(REQUEST)],
    ['outcomesFor', (s: ArtifactRankingService) =>
      s.outcomesFor({ ...REQUEST, artifactId: 's-plume-0' })],
    ['upgradeEstimate', (s: ArtifactRankingService) => s.upgradeEstimate(REQUEST)],
    ['deepDive', (s: ArtifactRankingService) => s.deepDive({ ...REQUEST, artifactId: 's-flower' })],
    ['sweepBestBuilds', (s: ArtifactRankingService) =>
      s.sweepBestBuilds({ ...REQUEST, artifactIds: ['s-circlet'] })],
  ])('%s refuses when the build\'s own 4-piece recipe is missing', async (_name, call) => {
    const { service } = setUp({ wornRecipeMissing: true });
    await expect(call(service)).rejects.toThrow(MISSING);
  });

  it('upgradeEstimate refuses a missing drop model before calibrating', async () => {
    const { service, calibrateAll } = setUp({ freshDrop: false });
    await expect(service.upgradeEstimate(REQUEST)).rejects.toThrow(/no drop model/);
    expect(calibrateAll).not.toHaveBeenCalled();
  });

  it.each([
    ['outcomesFor', (s: ArtifactRankingService) =>
      s.outcomesFor({ ...REQUEST, artifactId: 'nope' })],
    ['deepDive', (s: ArtifactRankingService) => s.deepDive({ ...REQUEST, artifactId: 'nope' })],
  ])('%s refuses an unknown artifact before calibrating', async (_name, call) => {
    const { service, calibrateAll } = setUp();
    await expect(call(service)).rejects.toThrow(/not in the inventory/);
    expect(calibrateAll).not.toHaveBeenCalled();
  });
});
