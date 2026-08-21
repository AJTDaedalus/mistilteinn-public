import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { API_BASE_URL } from '../../api/api.client';
import { BuildsService } from '../builds/builds.service';
import { DiscSetsService } from '../optimize/disc-sets.service';
import { RankService, type OptimizationJobRead, type OptimizationJobSummary } from './rank.service';
import { RankPage } from './rank-page';
import type { RankContextSelection } from './rank-context-bar';
import type { RankContextInput } from './rank.service';

// ---------- fixtures ----------

const MOCK_RANK_RESULT = [
  {
    disc_id: 'd1',
    per_build: [{ build_id: 'b1', avg_pct: 3.5, max_pct: 7.2 }],
    best_build_avg: 3.5,
    best_build_avg_build_id: 'b1',
    best_build_max: 7.2,
    portfolio_avg: 3.5,
  },
];

const MOCK_JOB_SUMMARY: OptimizationJobSummary = {
  id: 'job-1',
  status: 'queued',
  job_type: 'rank',
  agent_name: 'Agent X',
  enemy_name: 'Hollow Zero',
  combo_name: 'Combo A',
  assignments_done: 0,
  assignments_total: 1,
  evaluated: 0,
  elapsed_seconds: 0,
  eta_seconds: null,
  top_damage: null,
  error_message: null,
  created_at: '2024-01-01T00:00:00',
  started_at: null,
  finished_at: null,
};

const MOCK_JOB_DONE: OptimizationJobRead = {
  ...MOCK_JOB_SUMMARY,
  status: 'succeeded',
  assignments_done: 1,
  result: MOCK_RANK_RESULT as unknown as OptimizationJobRead['result'],
  request: {},
  started_at: '2024-01-01T00:00:01',
  finished_at: '2024-01-01T00:00:02',
};

const MOCK_DISC = {
  id: 'd1',
  build_id: 'b1',
  disc_set_id: 100,
  slot: 1,
  rarity: 'S',
  level: 10,
  main_stat_type: 'flat_hp',
  main_stat_value: 2200,
  substats: [],
  locked: false,
  created_at: '2024-01-01',
  updated_at: '2024-01-01',
};

const MOCK_BUILD = { id: 'b1', agent_id: 'a1', agent_specialty: 'attack', w_engine_id: null,
  w_engine_level: 60, w_engine_refinement: 1, mindscape_level: 0, core_skill_level: 5,
  agent_level: 60, skill_levels: '12,12,12,12,12', notes: '', disabled_buffs: [],
  active_conditions: [], stack_counts: {}, optimizer_priority: null };
const MOCK_AGENT = { id: 'a1', hakushin_id: 1, name: 'Nicole', full_name: 'Nicole',
  element: 'ice', specialty: 'attack', rarity: 'S', faction: 'Victoria', icon_path: null };
const MOCK_SET = { id: '1', hakushin_id: 100, name: 'Chaotic Metal', icon_path: null };

// ---------- helpers ----------

function setupRankService(overrides: Partial<{
  rank: () => Promise<OptimizationJobSummary>;
  pollUntilDone: () => Promise<OptimizationJobRead>;
  getRankJob: () => Promise<OptimizationJobRead>;
  listRankJobs: () => Promise<OptimizationJobSummary[]>;
  cancelJob: () => Promise<void>;
}> = {}) {
  return {
    rank: vi.fn(async () => MOCK_JOB_SUMMARY),
    pollUntilDone: vi.fn(async (_id: string, onProgress?: (j: OptimizationJobRead) => void) => {
      onProgress?.(MOCK_JOB_DONE);
      return MOCK_JOB_DONE;
    }),
    getRankJob: vi.fn(async () => MOCK_JOB_DONE),
    listRankJobs: vi.fn(async () => [] as OptimizationJobSummary[]),
    cancelJob: vi.fn(async () => undefined),
    scoreInventory: vi.fn(async () => { throw new Error('scoreInventory must not be called'); }),
    ...overrides,
  };
}

function setupBuildsService() {
  return {
    listDiscs: vi.fn(async () => [MOCK_DISC]),
    list: vi.fn(async () => [MOCK_BUILD]),
    listAgents: vi.fn(async () => [MOCK_AGENT]),
    listDiscsForBuild: vi.fn(async () => [MOCK_DISC]),
  };
}

function setupDiscSetsService() {
  return {
    listSets: vi.fn(async () => [MOCK_SET]),
  };
}

function setup(overrides: {
  rankService?: ReturnType<typeof setupRankService>;
  buildsService?: ReturnType<typeof setupBuildsService>;
  discSetsService?: ReturnType<typeof setupDiscSetsService>;
} = {}) {
  const rankService = overrides.rankService ?? setupRankService();
  const buildsService = overrides.buildsService ?? setupBuildsService();
  const discSetsService = overrides.discSetsService ?? setupDiscSetsService();

  TestBed.configureTestingModule({
    providers: [
      { provide: API_BASE_URL, useValue: 'http://test' },
      { provide: RankService, useValue: rankService },
      { provide: BuildsService, useValue: buildsService },
      { provide: DiscSetsService, useValue: discSetsService },
    ],
  });

  return {
    component: TestBed.createComponent(RankPage).componentInstance,
    rankService,
    buildsService,
  };
}

const SELECTION: RankContextSelection = {
  teamId: 't1',
  activeIndex: 0,
  comboId: 'c1',
  enemyProfileId: 'e1',
  allowedSetIds: null,
  mainStats: [],
  rarities: [],
  buffContext: {
    active_conditions: ['always', 'hp_above_50'],
    stack_counts: { 'agent:stack': 2 },
    disabled_buffs: ['1:core_a'],
  },
};

const PRIORITY_CONTEXTS: RankContextInput[] = [
  { build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1', weight: 1, allowed_set_ids: null },
  { build_id: 'b2', combo_id: 'c2', enemy_profile_id: 'e1', weight: 2, allowed_set_ids: [100] },
];

// ---------- tests ----------

describe('RankPage', () => {
  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('initialises discMap from listDiscs', async () => {
    const { component, buildsService } = setup();
    await vi.waitFor(() => buildsService.listDiscs.mock.calls.length > 0);
    await new Promise((r) => setTimeout(r, 0));
    expect(Object.keys(component['discMap']())).toContain('d1');
  });

  it('sets buildNames from builds list', async () => {
    const { component, buildsService } = setup();
    await vi.waitFor(() => buildsService.list.mock.calls.length > 0);
    await new Promise((r) => setTimeout(r, 0));
    expect(component['buildNames']()['b1']).toBe('Nicole');
  });

  it('selection does NOT auto-submit a job', async () => {
    const { component, rankService } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);

    expect(rankService.rank).not.toHaveBeenCalled();
    expect(rankService.scoreInventory).not.toHaveBeenCalled();
  });

  it('scoreSingle submits a 1-context rank job', async () => {
    const { component, rankService } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(rankService.rank).toHaveBeenCalledWith(
      [expect.objectContaining({ team_id: 't1', active_index: 0, combo_id: 'c1', enemy_profile_id: 'e1' })],
      'default',
      null,
    );
    expect(rankService.scoreInventory).not.toHaveBeenCalled();
  });

  it('passes allowedSetIds to rank job context', async () => {
    const { component, rankService } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange']({ ...SELECTION, allowedSetIds: [100, 200] });
    await component['scoreSingle']();

    expect(rankService.rank).toHaveBeenCalledWith(
      [expect.objectContaining({ allowed_set_ids: [100, 200] })],
      'default',
      null,
    );
  });

  it('scoreSingle does nothing if no context is set', async () => {
    const { component, rankService } = setup();
    await new Promise((r) => setTimeout(r, 0));

    await component['scoreSingle']();

    expect(rankService.rank).not.toHaveBeenCalled();
  });

  it('polls via pollUntilDone after submitting', async () => {
    const { component, rankService } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(rankService.pollUntilDone).toHaveBeenCalledWith(
      'job-1',
      expect.any(Function),
    );
  });

  it('populates rankResults from completed job result', async () => {
    const { component } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(component['rankResults']()).toHaveLength(1);
    expect(component['rankResults']()![0].disc_id).toBe('d1');
  });

  it('populates stub scores so table can iterate', async () => {
    const { component } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(component['scores']()).toHaveLength(1);
    expect(component['scores']()[0].disc_id).toBe('d1');
  });

  it('hasResults is true after successful rank job', async () => {
    const { component } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(component['hasResults']).toBe(true);
  });

  it('sets loading=false after successful call', async () => {
    const { component } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(component['loading']()).toBe(false);
  });

  it('clears jobProgress after completion', async () => {
    const { component } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(component['jobProgress']()).toBeNull();
  });

  it('sets scoreError and clears results on job failure', async () => {
    const failingService = setupRankService({
      rank: async () => { throw new Error('server error'); },
    });
    const { component } = setup({ rankService: failingService });
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(component['scoreError']()).toContain('server error');
    expect(component['rankResults']()).toBeNull();
    expect(component['scores']()).toHaveLength(0);
    expect(component['loading']()).toBe(false);
  });

  it('sets scoreError when job status is failed', async () => {
    const failedJob: OptimizationJobRead = { ...MOCK_JOB_DONE, status: 'failed', result: null };
    const failingService = setupRankService({
      pollUntilDone: async () => failedJob,
    });
    const { component } = setup({ rankService: failingService });
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(component['scoreError']()).toContain('failed');
  });

  it('clears scoreError on new successful score run', async () => {
    let fail = true;
    const conditionalService = setupRankService({
      rank: vi.fn(async () => {
        if (fail) throw new Error('oops');
        return MOCK_JOB_SUMMARY;
      }),
    });
    const { component } = setup({ rankService: conditionalService });
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();
    expect(component['scoreError']()).toBeTruthy();

    fail = false;
    await component['scoreSingle']();
    expect(component['scoreError']()).toBeNull();
  });

  it('onSelectionChange updates filter mainStats and rarities', () => {
    const { component } = setup();
    component['onSelectionChange']({ ...SELECTION, mainStats: ['atk_pct'], rarities: ['S'] });
    expect(component['filters']().mainStats).toEqual(['atk_pct']);
    expect(component['filters']().rarities).toEqual(['S']);
  });

  it('priority contexts NOT auto-submitted — scorePriority runs them', async () => {
    const { component, rankService } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onPriorityContextsChange'](PRIORITY_CONTEXTS);
    expect(rankService.rank).not.toHaveBeenCalled();

    await component['scorePriority']();
    expect(rankService.rank).toHaveBeenCalledWith(PRIORITY_CONTEXTS, 'default', null);
  });

  it('scorePriority does nothing when contexts are null', async () => {
    const { component, rankService } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onPriorityContextsChange'](null);
    await component['scorePriority']();

    expect(rankService.rank).not.toHaveBeenCalled();
  });

  it('togglePriorityPanel flips priorityPanelVisible', () => {
    const { component } = setup();
    expect(component['priorityPanelVisible']()).toBe(false);
    component['togglePriorityPanel']();
    expect(component['priorityPanelVisible']()).toBe(true);
    component['togglePriorityPanel']();
    expect(component['priorityPanelVisible']()).toBe(false);
  });

  it('loads job list on init', async () => {
    const listRankJobs = vi.fn(async () => [MOCK_JOB_SUMMARY]);
    const { component } = setup({ rankService: setupRankService({ listRankJobs }) });
    await vi.waitFor(() => listRankJobs.mock.calls.length > 0);
    await new Promise((r) => setTimeout(r, 0));
    expect(component['jobs']()).toHaveLength(1);
    expect(component['jobs']()[0].id).toBe('job-1');
  });

  it('onViewJob fetches job detail and sets results', async () => {
    const jobWithResult: OptimizationJobRead = {
      ...MOCK_JOB_DONE,
      request: { contexts: [{ build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1', weight: 1 }] },
    };
    const getRankJob = vi.fn(async () => jobWithResult);
    const { component } = setup({ rankService: setupRankService({ getRankJob }) });
    await new Promise((r) => setTimeout(r, 0));

    await component['onViewJob']('job-1');

    expect(getRankJob).toHaveBeenCalledWith('job-1');
    expect(component['rankResults']()).toHaveLength(1);
    expect(component['rankResults']()![0].disc_id).toBe('d1');
  });

  it('onViewJob reveals priority panel when job has contexts', async () => {
    const jobWithContexts: OptimizationJobRead = {
      ...MOCK_JOB_DONE,
      request: { contexts: [{ build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1', weight: 1 }] },
    };
    const { component } = setup({
      rankService: setupRankService({ getRankJob: vi.fn(async () => jobWithContexts) }),
    });
    await new Promise((r) => setTimeout(r, 0));

    await component['onViewJob']('job-1');

    expect(component['priorityPanelVisible']()).toBe(true);
  });

  it('onCancelJob calls cancelJob then refreshes list', async () => {
    const cancelJob = vi.fn(async () => undefined);
    const listRankJobs = vi.fn(async () => [] as OptimizationJobSummary[]);
    const { component } = setup({ rankService: setupRankService({ cancelJob, listRankJobs }) });
    await new Promise((r) => setTimeout(r, 0));

    await component['onCancelJob']('job-1');

    expect(cancelJob).toHaveBeenCalledWith('job-1');
    expect(listRankJobs).toHaveBeenCalledTimes(2); // once on init, once after cancel
  });

  it('runRankJob passes mapped filters to rank service', async () => {
    const { component, rankService } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange']({ ...SELECTION, mainStats: ['crit_rate'], rarities: ['S'] });
    component['filters'].update((f) => ({ ...f, slot: 4, levelValue: 10, sets: ['31100'] }));
    await component['scoreSingle']();

    expect(rankService.rank).toHaveBeenCalledWith(
      expect.any(Array),
      'default',
      {
        slot: 4,
        set_ids: [31100],
        rarities: ['S'],
        main_stats: ['crit_rate'],
        level_value: 10,
        level_mode: 'min',
      },
    );
  });

  it('runRankJob passes null filters when filter state is default', async () => {
    const { component, rankService } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(rankService.rank).toHaveBeenCalledWith(expect.any(Array), 'default', null);
  });

  it('runRankJob adds submitted job to list optimistically', async () => {
    const { component } = setup();
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    expect(component['jobs']().some((j) => j.id === 'job-1')).toBe(true);
  });

  it('runRankJob does not duplicate an already-listed job', async () => {
    const listRankJobs = vi.fn(async () => [MOCK_JOB_SUMMARY]);
    const { component } = setup({ rankService: setupRankService({ listRankJobs }) });
    await vi.waitFor(() => listRankJobs.mock.calls.length > 0);
    await new Promise((r) => setTimeout(r, 0));

    component['onSelectionChange'](SELECTION);
    await component['scoreSingle']();

    const ids = component['jobs']().map((j) => j.id);
    expect(ids.filter((id) => id === 'job-1')).toHaveLength(1);
  });
});
