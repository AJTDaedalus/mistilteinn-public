import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import { provideRouter, ActivatedRoute, Router } from '@angular/router';
import { signal } from '@angular/core';
import { of } from 'rxjs';

import { OptimizePage } from './optimize-page';
import { BuildsService } from '../builds/builds.service';
import { CombosService } from '../builds/combos.service';
import { CalculateService } from '../calculate/calculate.service';
import { DiscsService } from '../builds/discs.service';
import { DiscSetsService } from './disc-sets.service';
import { OptimizerService } from './optimizer.service';
import { TeamsService } from '../teams/teams.service';
import { API_BASE_URL } from '../../api/api.client';
import { BehaviorSubject } from 'rxjs';

const BUILDS = [
  { id: 'b1', name: 'Zhu Yuan', agent_specialty: 'Attack', w_engine_id: null,
    w_engine_level: 1, w_engine_refinement: 1, mindscape_level: 0,
    core_skill_level: 1, agent_level: 60, skill_levels: '1,1,1,1,1',
    support1_build_id: null, support2_build_id: null,
    support1_agent_id: null, support2_agent_id: null,
    notes: '', disabled_buffs: [], active_conditions: [],
    agent_id: 'a1', support1: null, support2: null, optimizer_priority: 2 },
  { id: 'b2', name: 'Jane Doe', agent_specialty: 'Anomaly', w_engine_id: null,
    w_engine_level: 1, w_engine_refinement: 1, mindscape_level: 0,
    core_skill_level: 1, agent_level: 60, skill_levels: '1,1,1,1,1',
    support1_build_id: null, support2_build_id: null,
    support1_agent_id: null, support2_agent_id: null,
    notes: '', disabled_buffs: [], active_conditions: [],
    agent_id: 'a2', support1: null, support2: null, optimizer_priority: 1 },
];

const TEAMS = [
  { id: 't1', name: 'Team Alpha', build1_id: 'b1', build2_id: 'b2', build3_id: null },
  { id: 't2', name: 'Team Beta',  build1_id: 'b2', build2_id: null,  build3_id: null },
];

const COMBOS = [
  { id: 'c1', name: 'Combo A', team_id: 't1', sequence: [] },
  { id: 'c2', name: 'Combo B', team_id: 't1', sequence: [] },
];

const ENEMIES = [{ id: 'e1', name: 'Dummy', level: 60, defense: 60, rarity: 4 }];

/** Mix of a trash mob, an elite, and two rarity-4 bosses — one of which
 *  (Girtablullu) has a non-1.5x-fallback stun_dmg_taken_ratio, per
 *  docs/LOG_issue_backlog.md's "enemy rank data" note — proves the ratio
 *  varies within rarity 4 and survives the tab filter untouched. */
const ENEMIES_MIXED = [
  { id: 'e-trash', name: 'Notorious Assaulter', level: 60, defense: 60, rarity: 1 },
  { id: 'e-elite', name: 'Corrupted Slime', level: 60, defense: 60, rarity: 2 },
  { id: 'e-boss-1', name: 'Dead End Butcher', level: 60, defense: 60, rarity: 4,
    stun_dmg_taken_ratio: 5000 },
  { id: 'e-boss-2', name: 'Girtablullu - Stagnant Aberrant', level: 60, defense: 60,
    rarity: 4, stun_dmg_taken_ratio: 2500 },
];

const AGENTS = [
  { id: 'a1', name: 'Caesar' },
  { id: 'a2', name: 'Burnice' },
];
function makeBuildsService() {
  return {
    list: vi.fn().mockResolvedValue(BUILDS),
    listAgents: vi.fn().mockResolvedValue(AGENTS),
    equipAll: vi.fn(),
  };
}
function makeCombosService() {
  return { listForTeam: vi.fn().mockResolvedValue(COMBOS) };
}
function makeCalcService(enemies: unknown[] = ENEMIES) {
  return { listEnemies: vi.fn().mockResolvedValue(enemies) };
}
function makeDiscsService() {
  return { list: vi.fn().mockResolvedValue([]) };
}
function makeDiscSetsService() {
  return { listSets: vi.fn().mockResolvedValue([]) };
}
function makeTeamsService() {
  return { list: vi.fn().mockResolvedValue(TEAMS) };
}
function makeOptimizerService(overrides: Partial<{ listJobs: unknown; submit: unknown; deleteJob: unknown }> = {}) {
  return {
    listJobs: vi.fn().mockResolvedValue([]),
    submit: vi.fn().mockResolvedValue({ id: 'j-new', status: 'queued', job_type: 'optimize',
      agent_name: '', enemy_name: '', combo_name: '',
      assignments_done: 0, assignments_total: 0, evaluated: 0,
      elapsed_seconds: 0, eta_seconds: null, top_damage: null,
      error_message: null, created_at: new Date().toISOString(),
      started_at: null, finished_at: null }),
    deleteJob: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

async function flushAsync(fixture: ReturnType<typeof TestBed.createComponent>) {
  await fixture.whenStable();
  await new Promise((r) => setTimeout(r, 0));
  fixture.detectChanges();
}

async function setup(
  queryParams: Record<string, string> = {},
  optimizerOverrides = {},
  enemies: unknown[] = ENEMIES,
) {
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      { provide: API_BASE_URL, useValue: 'http://test' },
      { provide: BuildsService, useValue: makeBuildsService() },
      { provide: CombosService, useValue: makeCombosService() },
      { provide: CalculateService, useValue: makeCalcService(enemies) },
      { provide: DiscsService, useValue: makeDiscsService() },
      { provide: DiscSetsService, useValue: makeDiscSetsService() },
      { provide: TeamsService, useValue: makeTeamsService() },
      { provide: OptimizerService, useValue: makeOptimizerService(optimizerOverrides) },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { queryParamMap: { get: (k: string) => queryParams[k] ?? null } },
          queryParams: of(queryParams),
        },
      },
    ],
  });

  const fixture = TestBed.createComponent(OptimizePage);
  fixture.detectChanges();
  await flushAsync(fixture);
  return fixture;
}

describe('OptimizePage', () => {
  it('renders team select with all teams', async () => {
    const fixture = await setup();
    const select = fixture.nativeElement.querySelector('#opt-team');
    expect(select).toBeTruthy();
    const options = Array.from(select.querySelectorAll('option') as NodeListOf<HTMLOptionElement>)
      .filter((o: HTMLOptionElement) => o.value !== '');
    expect(options.length).toBe(2);
  });

  it('shows empty state when no team is selected', async () => {
    const fixture = await setup();
    const hint = fixture.nativeElement.querySelector('.opt__empty');
    expect(hint).toBeTruthy();
  });

  it('job history loads on init without submitting a run', async () => {
    const existingJob = {
      id: 'j-existing', status: 'succeeded' as const, job_type: 'optimize',
      agent_name: 'Zhu Yuan', enemy_name: 'Dummy', combo_name: 'Combo A',
      assignments_done: 64, assignments_total: 64, evaluated: 64,
      elapsed_seconds: 1.0, eta_seconds: null, top_damage: 1234567,
      error_message: null, created_at: '2026-01-01T00:00:00Z',
      started_at: '2026-01-01T00:00:00Z', finished_at: '2026-01-01T00:00:01Z',
    };
    const fixture = await setup({}, { listJobs: vi.fn().mockResolvedValue([existingJob]) });
    await flushAsync(fixture);

    const comp = fixture.componentInstance as unknown as { jobs: ReturnType<typeof signal<unknown[]>> };
    expect(comp.jobs()).toHaveLength(1);
    expect((comp.jobs()[0] as { id: string }).id).toBe('j-existing');
  });

  it('preselects team from ?teamId query param', async () => {
    const combosService = makeCombosService();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: API_BASE_URL, useValue: 'http://test' },
        { provide: BuildsService, useValue: makeBuildsService() },
        { provide: CombosService, useValue: combosService },
        { provide: CalculateService, useValue: makeCalcService() },
        { provide: DiscsService, useValue: makeDiscsService() },
        { provide: DiscSetsService, useValue: makeDiscSetsService() },
        { provide: TeamsService, useValue: makeTeamsService() },
        { provide: OptimizerService, useValue: makeOptimizerService() },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { queryParamMap: { get: (k: string) => (k === 'teamId' ? 't1' : null) } },
            queryParams: of({ teamId: 't1' }),
          },
        },
      ],
    });
    const fixture = TestBed.createComponent(OptimizePage);
    fixture.detectChanges();
    await flushAsync(fixture);
    await flushAsync(fixture);

    expect(combosService.listForTeam).toHaveBeenCalledWith('t1');
  });

  it('selecting a team loads combos via listForTeam', async () => {
    const combosService = makeCombosService();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: API_BASE_URL, useValue: 'http://test' },
        { provide: BuildsService, useValue: makeBuildsService() },
        { provide: CombosService, useValue: combosService },
        { provide: CalculateService, useValue: makeCalcService() },
        { provide: DiscsService, useValue: makeDiscsService() },
        { provide: DiscSetsService, useValue: makeDiscSetsService() },
        { provide: TeamsService, useValue: makeTeamsService() },
        { provide: OptimizerService, useValue: makeOptimizerService() },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { queryParamMap: { get: () => null } },
            queryParams: of({}),
          },
        },
      ],
    });
    const fixture = TestBed.createComponent(OptimizePage);
    fixture.detectChanges();
    await flushAsync(fixture);

    const comp = fixture.componentInstance as unknown as { onTeamChange: (id: string) => void };
    comp.onTeamChange('t1');
    await flushAsync(fixture);

    expect(combosService.listForTeam).toHaveBeenCalledWith('t1');
  });

  it('Run button stays clickable but shows the missing prerequisite when set pool is empty', async () => {
    const fixture = await setup({ teamId: 't1' });
    await flushAsync(fixture);

    const runBtn = fixture.nativeElement.querySelector('.opt__run');
    expect(runBtn).toBeTruthy();
    expect(runBtn.disabled).toBe(false);

    const hint = fixture.nativeElement.querySelector('[data-test="run-hint"]');
    expect(hint?.textContent).toContain('4-piece');
  });

  it('Run button is enabled when frames are non-empty', async () => {
    const fixture = await setup({ teamId: 't1' });
    await flushAsync(fixture);

    const component = fixture.componentInstance as unknown as {
      setFilterState: ReturnType<typeof signal>;
      selectedEnemyId: ReturnType<typeof signal>;
    };

    component.setFilterState.set({
      fourPieceSets: [100],
      twoPieceSets: [],
      frames: [{ counts: { 100: 6 } }],
    });
    fixture.detectChanges();

    const runBtn = fixture.nativeElement.querySelector('.btn-primary');
    expect(runBtn?.disabled).toBe(false);
  });

  it('run() sends combo_ids, team_id, and active_index', async () => {
    const optimizerSpy = vi.fn().mockResolvedValue({
      id: 'j1', status: 'queued', agent_name: 'Agent', enemy_name: 'Dummy',
      combo_name: 'Combo A', assignments_done: 0, assignments_total: 0,
      evaluated: 0, elapsed_seconds: 0, eta_seconds: null, top_damage: null,
      error_message: null, created_at: '2026-01-01T00:00:00Z',
      started_at: null, finished_at: null,
    });
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: API_BASE_URL, useValue: 'http://test' },
        { provide: BuildsService, useValue: makeBuildsService() },
        { provide: CombosService, useValue: makeCombosService() },
        { provide: CalculateService, useValue: makeCalcService() },
        { provide: DiscsService, useValue: makeDiscsService() },
        { provide: DiscSetsService, useValue: makeDiscSetsService() },
        { provide: TeamsService, useValue: makeTeamsService() },
        { provide: OptimizerService, useValue: { submit: optimizerSpy, listJobs: vi.fn().mockResolvedValue([]) } },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { queryParamMap: { get: (k: string) => (k === 'teamId' ? 't1' : null) } },
            queryParams: of({ teamId: 't1' }),
          },
        },
      ],
    });
    const fixture = TestBed.createComponent(OptimizePage);
    fixture.detectChanges();
    await flushAsync(fixture);
    await flushAsync(fixture);

    const component = fixture.componentInstance as unknown as {
      setFilterState: ReturnType<typeof signal>;
    };
    component.setFilterState.set({
      fourPieceSets: [100],
      twoPieceSets: [],
      frames: [{ counts: { 100: 6 } }],
    });
    fixture.detectChanges();

    const runBtn = fixture.nativeElement.querySelector('.btn-primary');
    runBtn.click();
    await flushAsync(fixture);

    expect(optimizerSpy).toHaveBeenCalledOnce();
    const call = optimizerSpy.mock.calls[0][0];
    expect(call.combo_ids).toEqual(expect.any(Array));
    expect(call.team_id).toBe('t1');
    expect(call.active_index).toBe(0);
    expect(call.enemy_profile_id).toBe('e1');
    expect(call.allowed_frames).toEqual([{ counts: { 100: 6 } }]);
  });

  it('run() warns and does not submit when no disc set is picked', async () => {
    const optimizerSpy = vi.fn().mockResolvedValue({ id: 'j1', status: 'queued' });
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: API_BASE_URL, useValue: 'http://test' },
        { provide: BuildsService, useValue: makeBuildsService() },
        { provide: CombosService, useValue: makeCombosService() },
        { provide: CalculateService, useValue: makeCalcService() },
        { provide: DiscsService, useValue: makeDiscsService() },
        { provide: DiscSetsService, useValue: makeDiscSetsService() },
        { provide: TeamsService, useValue: makeTeamsService() },
        { provide: OptimizerService, useValue: { submit: optimizerSpy, listJobs: vi.fn().mockResolvedValue([]) } },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { queryParamMap: { get: (k: string) => (k === 'teamId' ? 't1' : null) } },
            queryParams: of({ teamId: 't1' }),
          },
        },
      ],
    });
    const fixture = TestBed.createComponent(OptimizePage);
    fixture.detectChanges();
    await flushAsync(fixture);
    await flushAsync(fixture);

    // team/combo/enemy resolved, but no set frames picked
    const runBtn = fixture.nativeElement.querySelector('.opt__run');
    expect(runBtn.disabled).toBe(false); // clickable so the warning can fire
    runBtn.click();
    await flushAsync(fixture);

    expect(optimizerSpy).not.toHaveBeenCalled();
    const toast = fixture.nativeElement.querySelector('.toast__text');
    expect(toast?.textContent).toContain('4-piece');
  });

  it('member selector shows when team has >1 member', async () => {
    const fixture = await setup({ teamId: 't1' });
    await flushAsync(fixture);

    const select = fixture.nativeElement.querySelector('#opt-member');
    expect(select).toBeTruthy();
    const options = Array.from(select.querySelectorAll('option') as NodeListOf<HTMLOptionElement>);
    expect(options.length).toBe(2); // t1 has build1_id + build2_id
  });

  it('member selector hidden when team has 1 member', async () => {
    const fixture = await setup({ teamId: 't2' });
    await flushAsync(fixture);

    const select = fixture.nativeElement.querySelector('#opt-member');
    expect(select).toBeNull();
  });

  describe('T9 — inventory scope toggle', () => {
    async function setupWithOptimizer(optimizerSpy: ReturnType<typeof vi.fn>) {
      TestBed.configureTestingModule({
        providers: [
          provideRouter([]),
          { provide: API_BASE_URL, useValue: 'http://test' },
          { provide: BuildsService, useValue: makeBuildsService() },
          { provide: CombosService, useValue: makeCombosService() },
          { provide: CalculateService, useValue: makeCalcService() },
          { provide: DiscsService, useValue: makeDiscsService() },
          { provide: DiscSetsService, useValue: makeDiscSetsService() },
          { provide: TeamsService, useValue: makeTeamsService() },
          { provide: OptimizerService, useValue: { submit: optimizerSpy, listJobs: vi.fn().mockResolvedValue([]) } },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: { queryParamMap: { get: (k: string) => (k === 'teamId' ? 't1' : null) } },
              queryParams: of({ teamId: 't1' }),
            },
          },
        ],
      });
      const fixture = TestBed.createComponent(OptimizePage);
      fixture.detectChanges();
      await flushAsync(fixture);
      await flushAsync(fixture);
      return fixture;
    }

    it('defaults inventory_scope to this_build', async () => {
      const spy = vi.fn().mockResolvedValue({
        id: 'j1', status: 'queued', agent_name: 'A', enemy_name: 'E',
        combo_name: 'C', assignments_done: 0, assignments_total: 0,
        evaluated: 0, elapsed_seconds: 0, eta_seconds: null, top_damage: null,
        error_message: null, created_at: '2026-01-01T00:00:00Z',
        started_at: null, finished_at: null,
      });
      const fixture = await setupWithOptimizer(spy);
      const comp = fixture.componentInstance as unknown as {
        setFilterState: ReturnType<typeof signal>;
        inventoryScope: ReturnType<typeof signal>;
      };
      comp.setFilterState.set({ fourPieceSets: [100], twoPieceSets: [], frames: [{ counts: { 100: 6 } }] });
      fixture.detectChanges();

      expect(comp.inventoryScope()).toBe('this_build');

      fixture.nativeElement.querySelector('.btn-primary').click();
      await flushAsync(fixture);

      expect(spy.mock.calls[0][0].inventory_scope).toBe('this_build');
    });

    it('sends inventory_scope: priority when toggled', async () => {
      const spy = vi.fn().mockResolvedValue({
        id: 'j1', status: 'queued', agent_name: 'A', enemy_name: 'E',
        combo_name: 'C', assignments_done: 0, assignments_total: 0,
        evaluated: 0, elapsed_seconds: 0, eta_seconds: null, top_damage: null,
        error_message: null, created_at: '2026-01-01T00:00:00Z',
        started_at: null, finished_at: null,
      });
      const fixture = await setupWithOptimizer(spy);
      const comp = fixture.componentInstance as unknown as {
        setFilterState: ReturnType<typeof signal>;
        inventoryScope: ReturnType<typeof signal>;
      };
      comp.setFilterState.set({ fourPieceSets: [100], twoPieceSets: [], frames: [{ counts: { 100: 6 } }] });
      comp.inventoryScope.set('priority');
      fixture.detectChanges();

      fixture.nativeElement.querySelector('.btn-primary').click();
      await flushAsync(fixture);

      expect(spy.mock.calls[0][0].inventory_scope).toBe('priority');
    });

    it('higherPriorityBuilds lists builds with lower priority number', async () => {
      const fixture = await setup({ teamId: 't1' });
      await flushAsync(fixture);
      // t1.build1_id='b1' (priority 2), active_index=0 → selectedBuild=b1
      // b2 has priority 1 → outranks b1
      const comp = fixture.componentInstance as unknown as {
        higherPriorityBuilds: ReturnType<typeof import('@angular/core').computed>;
      };
      const higher = comp.higherPriorityBuilds() as { id: string }[];
      expect(higher.map((b) => b.id)).toContain('b2');
      expect(higher.map((b) => b.id)).not.toContain('b1');
    });
  });

  describe('D5/D6 — Equip + undo + Δ% invalidation', () => {
    const DISC_IDS = ['d1', 'd2', 'd3', 'd4', 'd5', 'd6'];
    const mockBuild = { ...BUILDS[0], id: 'b1' };

    async function setupEquip() {
      const buildsService = { ...makeBuildsService(), equipAll: vi.fn().mockResolvedValue(mockBuild) };
      TestBed.configureTestingModule({
        providers: [
          provideRouter([]),
          { provide: API_BASE_URL, useValue: 'http://test' },
          { provide: BuildsService, useValue: buildsService },
          { provide: CombosService, useValue: makeCombosService() },
          { provide: CalculateService, useValue: makeCalcService() },
          { provide: DiscsService, useValue: makeDiscsService() },
          { provide: DiscSetsService, useValue: makeDiscSetsService() },
          { provide: TeamsService, useValue: makeTeamsService() },
          { provide: OptimizerService, useValue: makeOptimizerService() },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: { queryParamMap: { get: (k: string) => (k === 'teamId' ? 't1' : null) } },
              queryParams: of({ teamId: 't1' }),
            },
          },
        ],
      });
      const fixture = TestBed.createComponent(OptimizePage);
      fixture.detectChanges();
      await flushAsync(fixture);
      await flushAsync(fixture);
      return { fixture, buildsService };
    }

    it('onEquip() calls equipAll with the correct slot map', async () => {
      const { fixture, buildsService } = await setupEquip();
      const comp = fixture.componentInstance as unknown as { onEquip: (ids: string[], buildId: string) => Promise<void> };
      await comp.onEquip(DISC_IDS, 'b1');
      await flushAsync(fixture);

      expect(buildsService.equipAll).toHaveBeenCalledWith('b1', {
        1: 'd1', 2: 'd2', 3: 'd3', 4: 'd4', 5: 'd5', 6: 'd6',
      });
    });

    it('onEquip() invalidates currentBuildDamage (D6)', async () => {
      const { fixture } = await setupEquip();
      const comp = fixture.componentInstance as unknown as {
        onEquip: (ids: string[], buildId: string) => Promise<void>;
        currentBuildDamage: ReturnType<typeof signal>;
      };
      comp.currentBuildDamage.set(9999);
      await comp.onEquip(DISC_IDS, 'b1');
      await flushAsync(fixture);

      expect(comp.currentBuildDamage()).toBeNull();
    });

    it('onEquip() shows error toast on failure (D7)', async () => {
      const buildsService = { ...makeBuildsService(), equipAll: vi.fn().mockRejectedValue(new Error('net fail')) };
      TestBed.configureTestingModule({
        providers: [
          provideRouter([]),
          { provide: API_BASE_URL, useValue: 'http://test' },
          { provide: BuildsService, useValue: buildsService },
          { provide: CombosService, useValue: makeCombosService() },
          { provide: CalculateService, useValue: makeCalcService() },
          { provide: DiscsService, useValue: makeDiscsService() },
          { provide: DiscSetsService, useValue: makeDiscSetsService() },
          { provide: TeamsService, useValue: makeTeamsService() },
          { provide: OptimizerService, useValue: makeOptimizerService() },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: { queryParamMap: { get: () => null } },
              queryParams: of({}),
            },
          },
        ],
      });
      const fixture = TestBed.createComponent(OptimizePage);
      fixture.detectChanges();
      await flushAsync(fixture);
      await flushAsync(fixture);

      const comp = fixture.componentInstance as unknown as {
        onEquip: (ids: string[], buildId: string) => Promise<void>;
        errorMessage: ReturnType<typeof signal>;
      };
      await comp.onEquip(DISC_IDS, 'b1');
      await flushAsync(fixture);

      expect(comp.errorMessage()).toContain('net fail');
    });
  });

  describe('T5.5 — ?job query-param routing', () => {
    const JOB_DETAIL = {
      id: 'j1', status: 'succeeded' as const,
      agent_name: 'Zhu Yuan', enemy_name: 'Dummy', combo_name: 'Combo A',
      assignments_done: 64, assignments_total: 64, evaluated: 64,
      elapsed_seconds: 1.2, eta_seconds: null, top_damage: 999999,
      error_message: null, created_at: '2026-01-01T00:00:00Z',
      started_at: '2026-01-01T00:00:00Z', finished_at: '2026-01-01T00:00:01Z',
      request: {}, result: { builds: [], current_build_damage: null },
    };

    async function setupJobRouting(initialParams: Record<string, string> = {}) {
      const queryParams$ = new BehaviorSubject<Record<string, string>>(initialParams);
      const getJobMock = vi.fn().mockResolvedValue(JOB_DETAIL);
      const routerSpy = { navigate: vi.fn().mockResolvedValue(true) };

      TestBed.configureTestingModule({
        providers: [
          provideRouter([]),
          { provide: API_BASE_URL, useValue: 'http://test' },
          { provide: BuildsService, useValue: makeBuildsService() },
          { provide: CombosService, useValue: makeCombosService() },
          { provide: CalculateService, useValue: makeCalcService() },
          { provide: DiscsService, useValue: makeDiscsService() },
          { provide: DiscSetsService, useValue: makeDiscSetsService() },
          { provide: TeamsService, useValue: makeTeamsService() },
          {
            provide: OptimizerService,
            useValue: {
              listJobs: vi.fn().mockResolvedValue([]),
              getJob: getJobMock,
            },
          },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: { queryParamMap: { get: (k: string) => initialParams[k] ?? null } },
              queryParams: queryParams$.asObservable(),
            },
          },
          { provide: Router, useValue: routerSpy },
        ],
      });

      const fixture = TestBed.createComponent(OptimizePage);
      fixture.detectChanges();
      await flushAsync(fixture);
      return { fixture, queryParams$, routerSpy, getJobMock };
    }

    it('onViewJob navigates with ?job=<id>', async () => {
      const { fixture, routerSpy } = await setupJobRouting();
      const comp = fixture.componentInstance as unknown as { onViewJob: (id: string) => void };
      comp.onViewJob('j1');
      expect(routerSpy.navigate).toHaveBeenCalledWith(
        [], { queryParams: { job: 'j1' }, queryParamsHandling: 'merge' },
      );
    });

    it('selectedJobId reflects ?job query param', async () => {
      const { fixture, queryParams$ } = await setupJobRouting();
      const comp = fixture.componentInstance as unknown as {
        selectedJobId: ReturnType<typeof import('@angular/core').computed>;
      };

      expect(comp.selectedJobId()).toBeNull();

      queryParams$.next({ job: 'j1' });
      fixture.detectChanges();
      expect(comp.selectedJobId()).toBe('j1');
    });

    it('renders optimizer-job-detail when ?job is set', async () => {
      const { fixture } = await setupJobRouting({ job: 'j1' });
      await flushAsync(fixture);
      const detail = fixture.nativeElement.querySelector('optimizer-job-detail');
      expect(detail).toBeTruthy();
    });

    it('shows dashboard (no job-detail) when ?job is absent', async () => {
      const fixture = await setup();
      const detail = fixture.nativeElement.querySelector('optimizer-job-detail');
      expect(detail).toBeNull();
    });

    it('onBack navigates to clear ?job', async () => {
      const { fixture, routerSpy } = await setupJobRouting({ job: 'j1' });
      const comp = fixture.componentInstance as unknown as { onBack: () => void };
      comp.onBack();
      expect(routerSpy.navigate).toHaveBeenCalledWith(
        [], { queryParams: { job: null }, queryParamsHandling: 'merge' },
      );
    });
  });

  describe('enemy picker tabs (#55)', () => {
    it('defaults to the "Endgame Bosses" tab, listing only rarity-4 enemies', async () => {
      const fixture = await setup({ teamId: 't1' }, {}, ENEMIES_MIXED);
      const select = fixture.nativeElement.querySelector('#opt-enemy') as HTMLSelectElement;
      const names = Array.from(select.querySelectorAll('option'))
        .map((o) => o.textContent?.trim())
        .filter((t): t is string => !!t && t !== '— choose —');
      expect(names).toEqual([
        'Dead End Butcher Lv60',
        'Girtablullu - Stagnant Aberrant Lv60',
      ]);
    });

    it('defaults the selected enemy to the first boss, not enemies[0]', async () => {
      const fixture = await setup({}, {}, ENEMIES_MIXED);
      const comp = fixture.componentInstance as unknown as {
        selectedEnemyId: ReturnType<typeof signal<string | null>>;
      };
      // enemies[0] is 'e-trash' — the fix must not default to it under Bosses.
      expect(comp.selectedEnemyId()).toBe('e-boss-1');
    });

    it('"All Enemies" tab lists every profile, including trash mobs', async () => {
      const fixture = await setup({ teamId: 't1' }, {}, ENEMIES_MIXED);
      const comp = fixture.componentInstance as unknown as {
        onEnemyTabChange: (tab: 'bosses' | 'all') => void;
      };
      comp.onEnemyTabChange('all');
      fixture.detectChanges();
      const select = fixture.nativeElement.querySelector('#opt-enemy') as HTMLSelectElement;
      const names = Array.from(select.querySelectorAll('option'))
        .map((o) => o.textContent?.trim())
        .filter((t): t is string => !!t && t !== '— choose —');
      expect(names).toContain('Notorious Assaulter Lv60');
      expect(names).toHaveLength(4);
    });

    it('switching back to Bosses re-defaults selection once the current pick is filtered out', async () => {
      const fixture = await setup({}, {}, ENEMIES_MIXED);
      const comp = fixture.componentInstance as unknown as {
        onEnemyTabChange: (tab: 'bosses' | 'all') => void;
        selectedEnemyId: ReturnType<typeof signal<string | null>>;
      };
      comp.onEnemyTabChange('all');
      comp.selectedEnemyId.set('e-trash');
      comp.onEnemyTabChange('bosses');
      expect(comp.selectedEnemyId()).toBe('e-boss-1');
    });

    it('a boss whose stun ratio is not the 1.5x fallback (Girtablullu) is a ' +
      'selectable option under the default tab, alongside a differently-ratioed boss', async () => {
      const fixture = await setup({ teamId: 't1' }, {}, ENEMIES_MIXED);
      const select = fixture.nativeElement.querySelector('#opt-enemy') as HTMLSelectElement;
      const values = Array.from(select.querySelectorAll('option')).map((o) => o.getAttribute('value'));
      expect(values).toContain('e-boss-1'); // stun_dmg_taken_ratio 5000
      expect(values).toContain('e-boss-2'); // stun_dmg_taken_ratio 2500 — proves it varies within rarity 4
    });
  });
});
