import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { FORMULA_LABEL, FORMULA_SCORE_LABEL } from '../../sim/formula-calibration';
import { ArtifactsService } from '../artifacts/artifacts.service';
import { BuildsService } from '../builds/builds.service';
import { ExplainService } from '../explain/explain.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService } from '../teams/teams.service';
import { FormulaEstimateService } from './formula-estimate.service';
import { OptimizePage } from './optimize';
import { OptimizeService } from './optimize.service';
import { RECIPE_STORE, RecipeOptimizeService } from './recipe-optimize.service';
import { OptimizationRunsService } from './runs/optimization-runs.service';

/**
 * Math-fallback P1, task 8 — routing to the formula estimate on Optimize.
 *
 * D-F3 (`DECISIONS.md` §38): the estimate is an opt-in for every team, and where gcsim refuses
 * a member the 422 becomes a choice (DESIGN §2.5). These pin the routing, the label, and that a
 * formula search never touches gcsim, the recipe cache or the run corpus.
 */

const LOHEN_REFUSAL = "gcsim has no character key for 'Lohen' (normalised 'lohen') at pin "
  + 'b107b5dc5cb8. It is most likely released after the pin, or is one gcsim does not implement.';

const BUILD = {
  id: 'b1', character_id: 'c1', weapon_id: 'w1', character_level: 90,
  ascension_phase: 6, weapon_level: 90, refinement: 1, constellation_level: 0,
  talent_levels: { elemental_skill: 9 }, notes: '',
  character: {
    id: 'c1', name: 'Lohen', element: 'Geo', weapon_type: 'WEAPON_POLE',
    gcsim: { status: 'none', key: null, pin: 'b107', missing_actions: [], reason: LOHEN_REFUSAL },
  },
  weapon: { id: 'w1', name: 'A Polearm' },
};

const HITS = [
  { talent: 'elemental_skill', label: 'Skill DMG', index: 0, multiplier: 2.0, hits: 1,
    exclusive: false, scaling_stat: 'atk', extra_terms: [] },
  { talent: 'elemental_burst', label: 'Burst DMG', index: 0, multiplier: 4.0, hits: 1,
    exclusive: false, scaling_stat: 'atk', extra_terms: [] },
];

const CONTEXT = {
  base: { base_atk: 1000, base_hp: 20000, base_def: 800, crit_rate: 0.05, crit_dmg: 0.5 },
  hit: { multiplier: 2.0, channel: 'geo', scaling_stat: 'atk', amplifying: null, extra_terms: [] },
  target: { level: 90, resistance: 0.1, def_reduction: 0, def_ignore: 0 },
  character_level: 90,
  dmg_bonus_quantity: 'geo_dmg_bonus',
  set_bonuses: [],
};

const SLOTS = ['equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring', 'equip_dress'];

function inventory() {
  return SLOTS.flatMap((slot) => [
    { id: `${slot}-weak`, slot, set_id: 1, stats: { flat_atk: 10 } },
    { id: `${slot}-strong`, slot, set_id: 1, stats: { flat_atk: 100 } },
  ]);
}

function harness(calibrateAll = vi.fn().mockRejectedValue({ detail: LOHEN_REFUSAL })) {
  const store = { getItem: vi.fn(() => null), setItem: vi.fn(), removeItem: vi.fn(), length: 0,
    key: vi.fn(() => null) };
  const save = vi.fn().mockResolvedValue({ id: 'run-1' });
  TestBed.configureTestingModule({
    providers: [
      {
        provide: OptimizeService,
        useValue: {
          context: vi.fn().mockResolvedValue(CONTEXT),
          inventory: vi.fn().mockResolvedValue({
            version: 'v1', artifacts: inventory(), total: 10, truncated: false, unreadable: [],
          }),
          // Set 1 is one gcsim has no key for: the formula mode offers it anyway.
          artifactSets: vi.fn().mockResolvedValue(
            new Map([[1, { id: 'uuid-1', name: 'Set One', simulable: false }]]),
          ),
          setBonuses: vi.fn().mockResolvedValue([]),
        },
      },
      { provide: BuildsService, useValue: { list: vi.fn().mockResolvedValue([BUILD]) } },
      {
        provide: ExplainService,
        useValue: {
          hits: vi.fn().mockResolvedValue(HITS),
          refusedHits: vi.fn().mockResolvedValue([]),
        },
      },
      {
        provide: ArtifactsService,
        useValue: {
          options: vi.fn().mockResolvedValue({ stats: [], rarities: [], slots: [] }),
          list: vi.fn().mockResolvedValue({ items: [] }),
        },
      },
      { provide: RecipeOptimizeService, useValue: { calibrateAll } },
      { provide: RECIPE_STORE, useValue: store },
      { provide: TeamsService, useValue: { list: vi.fn().mockResolvedValue([]) } },
      {
        provide: RotationsService,
        useValue: {
          list: vi.fn().mockResolvedValue({
            items: [{ id: 'r1', name: 'Burst', team_id: 't1' }], total: 1, offset: 0, limit: 50,
          }),
        },
      },
      { provide: OptimizationRunsService, useValue: { save } },
    ],
  });
  localStorage.setItem('mistilteinn:optimize:buildId', 'b1');
  localStorage.setItem('mistilteinn:optimize:rotationId', 'r1');
  const formula = TestBed.inject(FormulaEstimateService);
  vi.spyOn(formula, 'setTiers').mockResolvedValue([]);
  vi.spyOn(formula, 'resonances').mockResolvedValue([]);
  vi.spyOn(formula, 'kits').mockResolvedValue({ sources: [], missing: [] });
  const page = TestBed.runInInjectionContext(() => new OptimizePage());
  return { page: page as unknown as Record<string, never>, calibrateAll, store, save, formula };
}

type Fn = (...args: unknown[]) => unknown;
const call = (page: Record<string, never>, key: string, ...args: unknown[]) =>
  (page[key] as unknown as Fn).call(page, ...args);
const read = (page: Record<string, never>, key: string) => (page[key] as unknown as Fn)();

async function ready(page: Record<string, never>) {
  await call(page, 'load');
  await call(page, 'loadFilterData');
}

describe('Optimize routes to the formula estimate', () => {
  it('knows before the click that gcsim cannot run a member', async () => {
    const { page } = harness();
    await ready(page);
    expect(read(page, 'gcsimBlocked')).toEqual(['Lohen']);
  });

  it('turns the 422 naming a member into a choice, not an error', async () => {
    const { page, calibrateAll } = harness();
    await ready(page);
    call(page, 'toggleSet', 1);
    // A rotation search on a set gcsim has no key for is refused before it starts, so the
    // refusal under test is the character's: offer the set by marking it simulable here.
    (page['artifactSets'] as unknown as { set: (m: Map<number, unknown>) => void }).set(
      new Map([[1, { id: 'uuid-1', name: 'Set One', simulable: true }]]),
    );
    await call(page, 'runRotation');

    expect(calibrateAll).toHaveBeenCalled();
    expect(read(page, 'gcsimRefused')).toMatchObject({ kind: 'character', name: 'Lohen' });
    expect(read(page, 'actionError')).toBeNull();
  });

  it('keeps any other failure an error', async () => {
    const { page } = harness(vi.fn().mockRejectedValue({ detail: 'something else broke' }));
    await ready(page);
    (page['artifactSets'] as unknown as { set: (m: Map<number, unknown>) => void }).set(
      new Map([[1, { id: 'uuid-1', name: 'Set One', simulable: true }]]),
    );
    call(page, 'toggleSet', 1);
    await call(page, 'runRotation');

    expect(read(page, 'gcsimRefused')).toBeNull();
    expect(read(page, 'actionError')).toBe('something else broke');
  });

  it('"Use the formula estimate" switches mode and scores without gcsim', async () => {
    const { page, calibrateAll, store } = harness();
    await ready(page);
    call(page, 'toggleSet', 1);
    TestBed.tick();
    await call(page, 'useFormulaEstimate');

    expect(read(page, 'objective')).toBe('formula');
    expect(read(page, 'result')).not.toBeNull();
    expect(read(page, 'resultIsFormula')).toBe(true);
    expect(read(page, 'scoreLabel')).toBe(FORMULA_SCORE_LABEL);
    // Never DPS, and the strong piece in every slot wins.
    const winner = (read(page, 'result') as { builds: { artifactIds: string[] }[] }).builds[0];
    expect(winner.artifactIds.every((id) => id.endsWith('-strong'))).toBe(true);
    // **No gcsim, no recipe cache.**
    expect(calibrateAll).not.toHaveBeenCalled();
    expect(store.setItem).not.toHaveBeenCalled();
    expect((read(page, 'formulaAssumptions') as string[]).join('\n'))
      .toMatch(/no simulation/);
  });

  it('offers a set gcsim has no key for in formula mode only', async () => {
    const { page } = harness();
    await ready(page);
    expect(read(page, 'fourPieceChoices')).toEqual([]);
    (page['objective'] as unknown as { set: (v: string) => void }).set('formula');
    expect((read(page, 'fourPieceChoices') as { setId: number }[]).map((c) => c.setId))
      .toEqual([1]);
  });

  it('a multi-row target sums its rows', async () => {
    const { page, formula } = harness();
    await ready(page);
    call(page, 'toggleSet', 1);
    (page['objective'] as unknown as { set: (v: string) => void }).set('formula');
    formula.ensureTarget('b1', HITS as never);
    await call(page, 'runFormula');
    const one = (read(page, 'result') as { builds: { damage: number }[] }).builds[0].damage;

    formula.addRow(HITS[0] as never);
    formula.updateRow(formula.rows()[1].id, { count: 2 });
    await call(page, 'runFormula');
    const three = (read(page, 'result') as { builds: { damage: number }[] }).builds[0].damage;
    // The same context answers every row in this harness, so 1 + 2 rows is three times one.
    expect(three / one).toBeCloseTo(3, 5);
  });

  it('saves a formula result as one: labelled, with no rotation', async () => {
    const { page, save, formula } = harness();
    await ready(page);
    call(page, 'toggleSet', 1);
    (page['objective'] as unknown as { set: (v: string) => void }).set('formula');
    formula.ensureTarget('b1', HITS as never);
    await call(page, 'runFormula');
    await call(page, 'saveRun');

    const body = save.mock.calls[0][0] as {
      objective: Record<string, unknown>; rotation_id: string | null;
    };
    expect(body.objective['kind']).toBe('formula-estimate');
    expect(body.objective['label']).toBe(FORMULA_LABEL);
    expect(body.rotation_id).toBeNull();
  });
});
