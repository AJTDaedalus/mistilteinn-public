import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { ArtifactsService } from '../artifacts/artifacts.service';
import { BuildsService } from '../builds/builds.service';
import { ExplainService } from '../explain/explain.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService } from '../teams/teams.service';
import {
  candidateConditionState, candidateGroup, FormulaEstimateService, kitKey,
} from './formula-estimate.service';
import { OptimizePage, passiveNote } from './optimize';
import { OptimizeService } from './optimize.service';
import { RECIPE_STORE, RecipeOptimizeService } from './recipe-optimize.service';
import { OptimizationRunsService } from './runs/optimization-runs.service';

/**
 * Weapon comparison under the formula estimate (owner approval 2026-11-14, `DECISIONS.md` §45).
 *
 * **#240 is the failure these guard.** The gcsim weapon comparison once shipped a flat ranking —
 * every weapon at the worn weapon's number, to the decimal — because the candidate's id never
 * reached the scoring and the cache key had no weapon in it. Every test passed the whole time.
 * So these assert that the id reaches both halves of the estimate, that a cache keyed without
 * it cannot answer for another weapon, and that two weapons do **not** tie by construction.
 */

const BUILD = {
  id: 'b1', character_id: 'c1', weapon_id: 'w1', character_level: 90,
  ascension_phase: 6, weapon_level: 90, refinement: 1, constellation_level: 0,
  talent_levels: { elemental_skill: 9 }, notes: '',
  character: {
    id: 'c1', name: 'Lohen', element: 'Geo', weapon_type: 'WEAPON_POLE', nanoka_id: '1',
    gcsim: { status: 'none', key: null, pin: 'b107', missing_actions: [], reason: 'none' },
  },
  weapon: { id: 'w1', name: 'Worn Polearm' },
};

const HITS = [
  { talent: 'elemental_skill', label: 'Skill DMG', index: 0, multiplier: 2.0, hits: 1,
    exclusive: false, scaling_stat: 'atk', extra_terms: [] },
];

/** The search context for a weapon: each candidate's base ATK is its own. */
function context(weaponId?: string) {
  const baseAtk = { undefined: 900, w2: 1050, w3: 900 }[String(weaponId) as 'w2'] ?? 900;
  return {
    base: { base_atk: baseAtk, base_hp: 20000, base_def: 800, crit_rate: 0.05, crit_dmg: 0.5 },
    hit: { multiplier: 2.0, channel: 'geo', scaling_stat: 'atk', amplifying: null,
      extra_terms: [] },
    target: { level: 90, resistance: 0.1, def_reduction: 0, def_ignore: 0 },
    character_level: 90,
    dmg_bonus_quantity: 'geo_dmg_bonus',
    set_bonuses: [],
  };
}

const SLOTS = ['equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring', 'equip_dress'];

/** A weapon passive source that gives 20% ATK — so w3, base-equal to the worn one, differs. */
const W3_SOURCE = {
  id: 'weapon:w3', label: 'Third R1 (Lohen)', giver: 'Lohen', build_id: 'b1',
  status: 'modelled', verified: true, citation: 'GO', giver_stats: {}, kind: 'weapon',
  bonus: {
    conditions: [{ key: 'on', label: 'Passive on', kind: 'toggle', default: 1,
      default_reason: 'self' }],
    unmodelled: [],
    effects: [{ stat: 'atk_pct', value: 0.2, when: [{ condition: 'on', values: [1] }] }],
  },
};

function harness() {
  const contextFn = vi.fn((...args: unknown[]) => Promise.resolve(context(args[5] as string)));
  TestBed.configureTestingModule({
    providers: [
      {
        provide: OptimizeService,
        useValue: {
          context: contextFn,
          inventory: vi.fn().mockResolvedValue({
            version: 'v1', total: 5, truncated: false, unreadable: [],
            artifacts: SLOTS.map((slot) => ({ id: slot, slot, set_id: 1, stats: { atk_pct: 0.1 } })),
          }),
          artifactSets: vi.fn().mockResolvedValue(
            new Map([[1, { id: 'uuid-1', name: 'Set One', simulable: true }]]),
          ),
          setBonuses: vi.fn().mockResolvedValue([]),
        },
      },
      { provide: BuildsService, useValue: { list: vi.fn().mockResolvedValue([BUILD]) } },
      {
        provide: ExplainService,
        useValue: { hits: vi.fn().mockResolvedValue(HITS), refusedHits: vi.fn().mockResolvedValue([]) },
      },
      {
        provide: ArtifactsService,
        useValue: {
          options: vi.fn().mockResolvedValue({ stats: [], rarities: [], slots: [] }),
          list: vi.fn().mockResolvedValue({ items: [] }),
        },
      },
      { provide: RecipeOptimizeService, useValue: { calibrateAll: vi.fn() } },
      { provide: RECIPE_STORE, useValue: { getItem: () => null, setItem: vi.fn() } },
      { provide: TeamsService, useValue: { list: vi.fn().mockResolvedValue([]) } },
      {
        provide: RotationsService,
        useValue: { list: vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 }) },
      },
      { provide: OptimizationRunsService, useValue: { save: vi.fn() } },
    ],
  });
  localStorage.setItem('mistilteinn:optimize:buildId', 'b1');
  const formula = TestBed.inject(FormulaEstimateService);
  vi.spyOn(formula, 'setTiers').mockResolvedValue([]);
  vi.spyOn(formula, 'resonances').mockResolvedValue([]);
  const kits = vi.spyOn(formula, 'kits').mockImplementation((_team, _id, weapon) => Promise.resolve({
    sources: weapon?.id === 'w3' ? [W3_SOURCE as never] : [],
    missing: [],
    subjectWeapon: {
      name: weapon?.id ?? 'Worn Polearm', refinement: weapon?.refinement ?? 1,
      status: weapon?.id === 'w2' ? 'no_passive_data' : 'modelled',
      sourceId: weapon?.id === 'w3' ? 'weapon:w3' : null,
    },
  }));
  const page = TestBed.runInInjectionContext(() => new OptimizePage());
  return { page: page as unknown as Record<string, never>, formula, contextFn, kits };
}

type Fn = (...args: unknown[]) => unknown;
const call = (page: Record<string, never>, key: string, ...args: unknown[]) =>
  (page[key] as unknown as Fn).call(page, ...args);
const read = (page: Record<string, never>, key: string) => (page[key] as unknown as Fn)();
const set = (page: Record<string, never>, key: string, value: unknown) =>
  (page[key] as unknown as { set: (v: unknown) => void }).set(value);

describe('weapon comparison under the formula estimate', () => {
  it('runs one estimate and one search per weapon, the equipped weapon first', async () => {
    const { page, formula, contextFn, kits } = harness();
    await call(page, 'load');
    await call(page, 'loadFilterData');
    call(page, 'toggleSet', 1);
    set(page, 'objective', 'formula');
    formula.ensureTarget('b1', HITS as never);
    set(page, 'selectedWeapons', new Set(['w2', 'w3']));
    await call(page, 'runFormula');

    // The id reaches both halves of the estimate.
    expect(contextFn.mock.calls.map((c) => c[5])).toEqual([undefined, 'w2', 'w3']);
    // (The panel's proc lookup may ask too; the estimate's three asks are what is pinned.)
    const asked = kits.mock.calls.map((c) => c[2]);
    // Each candidate at its refinement: R1 for a weapon not known to be owned (§46).
    expect(asked).toContainEqual({ id: 'w2', refinement: 1 });
    expect(asked).toContainEqual({ id: 'w3', refinement: 1 });
    expect(asked).toContain(undefined);

    const ranking = read(page, 'weaponRanking') as {
      name: string; equipped: boolean; damage: number; passive: string | null;
    }[];
    expect(ranking).toHaveLength(3);
    // **Not flat** (#240): a higher base ATK and a passive each move the number.
    const damages = new Set(ranking.map((r) => r.damage.toFixed(3)));
    expect(damages.size).toBe(3);
    const worn = ranking.find((r) => r.equipped)!;
    expect(worn.passive).toBeNull();
    // A weapon with no passive file competes on base stats, and says so.
    const plain = ranking.find((r) => r.passive === 'passive not modelled');
    expect(plain).toBeDefined();
    // The main result is still the equipped weapon's.
    const main = (read(page, 'result') as { builds: { damage: number }[] }).builds[0].damage;
    expect(main).toBeCloseTo(worn.damage, 6);
  });

  it('with the comparison closed, scores the equipped weapon alone', async () => {
    const { page, formula, contextFn } = harness();
    await call(page, 'load');
    await call(page, 'loadFilterData');
    call(page, 'toggleSet', 1);
    set(page, 'objective', 'formula');
    formula.ensureTarget('b1', HITS as never);
    await call(page, 'runFormula');
    expect(contextFn.mock.calls.map((c) => c[5])).toEqual([undefined]);
    expect(read(page, 'weaponRanking')).toEqual([]);
  });
});

/** A formula comparison of the picked weapons, ready to run. */
async function comparing(picked: string[]) {
  const h = harness();
  await call(h.page, 'load');
  await call(h.page, 'loadFilterData');
  call(h.page, 'toggleSet', 1);
  set(h.page, 'objective', 'formula');
  h.formula.ensureTarget('b1', HITS as never);
  set(h.page, 'selectedWeapons', new Set(picked));
  return h;
}

type Ranked = { name: string; equipped: boolean; damage: number }[];

describe('owner rulings of 2026-11-15 (DECISIONS §46)', () => {
  it('scores a candidate at the refinement owned, else R1, else the one the user set', async () => {
    const { page, kits } = await comparing(['w2', 'w3']);
    set(page, 'ownedWeapons', new Map([['w3', 4]]));
    await call(page, 'runFormula');
    let asked = kits.mock.calls.map((c) => c[2]);
    expect(asked).toContainEqual({ id: 'w3', refinement: 4 });
    expect(asked).toContainEqual({ id: 'w2', refinement: 1 });

    call(page, 'setWeaponRefinement', 'w2', '5');
    kits.mockClear();
    await call(page, 'runFormula');
    asked = kits.mock.calls.map((c) => c[2]);
    expect(asked).toContainEqual({ id: 'w2', refinement: 5 });
    // The ranking names the refinement each was scored at.
    const names = (read(page, 'weaponRanking') as Ranked).map((r) => r.name).sort();
    expect(names).toEqual(['Worn Polearm R1', 'weapon R4', 'weapon R5'].sort());
  });

  it('offers the weapons owned, unless the unowned are asked for', async () => {
    const { page } = harness();
    await call(page, 'load');
    set(page, 'weapons', [
      { id: 'w1', name: 'Worn Polearm', stars: 4 },
      { id: 'w2', name: 'Second', stars: 4 },
      { id: 'w3', name: 'Third', stars: 5 },
    ]);
    set(page, 'ownedWeapons', new Map([['w3', 2]]));
    const values = () => (read(page, 'weaponOptions') as { value: string; detail: string }[]);
    expect(values().map((o) => o.value)).toEqual(['w3']);
    expect(values()[0].detail).toContain('owned R2');

    call(page, 'setIncludeUnowned', true);
    expect(values().map((o) => o.value).sort()).toEqual(['w2', 'w3']);
    expect(values().find((o) => o.value === 'w2')!.detail).toContain('not owned');

    // Back to owned only drops an unowned pick rather than hiding it.
    set(page, 'selectedWeapons', new Set(['w2', 'w3']));
    call(page, 'setIncludeUnowned', false);
    expect([...(read(page, 'selectedWeapons') as Set<string>)]).toEqual(['w3']);
  });

  it('offers nothing when what is owned could not be loaded — never "owns nothing" read as all', () => {
    const { page } = harness();
    set(page, 'weapons', [{ id: 'w2', name: 'Second', stars: 4 }]);
    set(page, 'ownedWeapons', null);
    expect(read(page, 'weaponOptions')).toEqual([]);
  });

  it('runs each candidate on its own passive conditions, not the equipped run\'s', async () => {
    const { page, formula } = await comparing(['w3']);
    await call(page, 'runFormula');
    const on = (read(page, 'weaponRanking') as Ranked);
    const worn = on.find((r) => r.equipped)!.damage;
    const w3On = on.find((r) => !r.equipped)!.damage;
    expect(w3On).toBeGreaterThan(worn);

    // The same key in the page's state is not the candidate's (a teammate's copy can hold it).
    formula.setCondition('weapon:w3/on', 0);
    await call(page, 'runFormula');
    expect((read(page, 'weaponRanking') as Ranked).find((r) => !r.equipped)!.damage)
      .toBeCloseTo(w3On, 6);

    // Its own toggle off: base-equal to the worn weapon, so the same number.
    formula.setCandidateCondition('w3', 'on', 0);
    await call(page, 'runFormula');
    expect((read(page, 'weaponRanking') as Ranked).find((r) => !r.equipped)!.damage)
      .toBeCloseTo(worn, 6);
  });
});

describe('candidateConditionState', () => {
  it('drops the page\'s keys under the candidate\'s source and writes its own', () => {
    const state = { 'weapon:x/on': 1, 'weapon:x:2/on': 1, 'set:1/stacks': 2 };
    expect(candidateConditionState(state, 'weapon:x', { on: 0 })).toEqual({
      'weapon:x/on': 0, 'weapon:x:2/on': 1, 'set:1/stacks': 2,
    });
    expect(candidateConditionState(state, 'weapon:x', {})).toEqual({
      'weapon:x:2/on': 1, 'set:1/stacks': 2,
    });
    expect(candidateConditionState(state, null, { on: 0 })).toEqual(state);
  });
});

describe('candidateGroup', () => {
  it('lists a candidate\'s conditions under its own name, marked as the candidate\'s', () => {
    const group = candidateGroup({
      sources: [W3_SOURCE as never], missing: [],
      subjectWeapon: { name: 'Third', refinement: 3, status: 'modelled', sourceId: 'weapon:w3' },
    }, { id: 'w3', refinement: 3 }, 'Third');
    expect(group.label).toBe('Candidate: Third R3');
    expect(group.candidate).toEqual({ weaponId: 'w3' });
    expect(group.conditions.map((c) => c.key)).toEqual(['on']);
    expect(group.citation).toBe('GO');
  });

  it('says a candidate with no passive data competes on base stats', () => {
    const group = candidateGroup({
      sources: [], missing: [],
      subjectWeapon: { name: 'Second', refinement: 1, status: 'no_passive_data', sourceId: null },
    }, { id: 'w2', refinement: 1 }, 'Second');
    expect(group.kind).toBe('no-weapon');
    expect(group.unmodelled[0].reason).toMatch(/base ATK and substat only/);
  });
});

describe('the kit cache keys on the weapon (#240)', () => {
  it('kitKey differs for two weapons and for two refinements of one', () => {
    const team = ['b1', 'b2'];
    expect(kitKey('b1', team)).not.toBe(kitKey('b1', team, { id: 'w2' }));
    expect(kitKey('b1', team, { id: 'w2' })).not.toBe(kitKey('b1', team, { id: 'w3' }));
    expect(kitKey('b1', team, { id: 'w2', refinement: 1 }))
      .not.toBe(kitKey('b1', team, { id: 'w2', refinement: 5 }));
  });

  it('asks the server once per weapon and never answers one weapon with another', async () => {
    TestBed.configureTestingModule({});
    const service = TestBed.inject(FormulaEstimateService);
    const get = vi.fn((_path: string, init: { params: { query: Record<string, unknown> } }) =>
      Promise.resolve({
        data: {
          sources: [], members: [], raised_talents: [],
          weapons: [{
            build_id: 'b1', wielder: 'Lohen', weapon: String(init.params.query['subject_weapon_id']
              ?? 'Worn'), refinement: 1, status: 'no_passive_data', verified: false,
            is_subject: true, source_id: null,
          }],
        },
      }));
    (service as unknown as { api: { GET: typeof get } }).api = { GET: get };
    const team = [{ id: 'b1' }] as never;
    const worn = await service.kits(team, 'b1');
    const other = await service.kits(team, 'b1', { id: 'w2' });
    const again = await service.kits(team, 'b1', { id: 'w2' });
    expect(get).toHaveBeenCalledTimes(2);
    expect(get.mock.calls[1][1].params.query['subject_weapon_id']).toBe('w2');
    expect(get.mock.calls[0][1].params.query['subject_weapon_id']).toBeUndefined();
    expect(worn.subjectWeapon?.name).toBe('Worn');
    expect(other.subjectWeapon?.name).toBe('w2');
    expect(again).toBe(other);
  });
});

describe('passiveNote', () => {
  it('says why a weapon competes on base stats', () => {
    expect(passiveNote('modelled')).toBeNull();
    expect(passiveNote('no_damage_effect')).toBeNull();
    expect(passiveNote('no_passive_data')).toBe('passive not modelled');
    expect(passiveNote('partial')).toBe('passive partly modelled');
  });
});
