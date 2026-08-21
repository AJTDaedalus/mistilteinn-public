import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { describe, expect, it, vi } from 'vitest';
import { OptimizerJobDetail } from './optimizer-job-detail';
import { OptimizerResultsGrid } from './optimizer-results-grid';
import { OptimizerService } from './optimizer.service';
import type { OptimizationJobRead } from './optimizer.service';
import { TeamsService } from '../teams/teams.service';
import type { TeamRead } from '../teams/teams.service';

/** resolveBuildId looks up the team (team_id + active_index -> buildN_id)
 * whenever job.request carries a team_id -- stub it so tests don't hit the
 * real API client. */
function makeTeamsServiceStub(team: Partial<TeamRead> = {}) {
  return {
    get: vi.fn().mockResolvedValue({
      id: 't1',
      name: 'Team',
      build1_id: 'b1',
      build2_id: 'b2',
      build3_id: 'b3',
      ...team,
    } satisfies TeamRead),
  };
}
const teamsServiceStub = makeTeamsServiceStub();

function makeJob(overrides: Partial<OptimizationJobRead> = {}): OptimizationJobRead {
  return {
    id: 'job-1',
    status: 'succeeded',
    job_type: 'optimize',
    agent_name: 'Zhu Yuan',
    enemy_name: 'Cyclops',
    combo_name: 'Rotation A',
    assignments_done: 100,
    assignments_total: 100,
    evaluated: 1000,
    elapsed_seconds: 5,
    eta_seconds: null,
    top_damage: 123456,
    error_message: null,
    created_at: '2026-01-01T00:00:00Z',
    started_at: '2026-01-01T00:00:01Z',
    finished_at: '2026-01-01T00:00:06Z',
    request: {},
     
    result: {
      combo_id: 'c1',
      combo_name: 'Rotation A',
      agent_name: 'Zhu Yuan',
      enemy_name: 'Cyclops',
      current_build_damage: null,
      builds: [
        {
          disc_ids: ['d1', 'd2', 'd3', 'd4', 'd5', 'd6'],
          total_damage: 123456,
          set_counts: {},
        },
      ],
      evaluated: 1000,
      pruned_sets: 0,
      pruned_stats: 0,
    } as any,
    ...overrides,
  };
}

function makeService(job: OptimizationJobRead) {
  return { getJob: vi.fn().mockResolvedValue(job) };
}

describe('OptimizerJobDetail', () => {
  it('renders results grid after fetching job', async () => {
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(makeJob()) },
        { provide: TeamsService, useValue: teamsServiceStub },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const grid = fixture.nativeElement.querySelector('optimizer-results-grid');
    expect(grid).toBeTruthy();
  });

  it('emits back event on back button click', () => {
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(makeJob()) },
        { provide: TeamsService, useValue: teamsServiceStub },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();

    const backSpy = vi.fn();
    fixture.componentInstance.back.subscribe(backSpy);

    const btn = fixture.nativeElement.querySelector('.btn-back');
    btn?.click();
    expect(backSpy).toHaveBeenCalled();
  });

  it('shows the auto-prefilter notice when the result reports auto_prefilter_k', async () => {
    const job = makeJob({
      result: {
        combo_id: 'c1',
        combo_name: 'Rotation A',
        agent_name: 'Zhu Yuan',
        enemy_name: 'Cyclops',
        current_build_damage: null,
        builds: [],
        evaluated: 1000,
        pruned_sets: 0,
        pruned_stats: 0,
        auto_prefilter_k: 7,
      } as any,
    });
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(job) },
        { provide: TeamsService, useValue: teamsServiceStub },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const notice = fixture.nativeElement.querySelector('.job-detail__notice');
    expect(notice).toBeTruthy();
    expect(notice.textContent).toContain('K=7');
  });

  it('omits the auto-prefilter notice when auto_prefilter_k is absent', async () => {
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(makeJob()) },
        { provide: TeamsService, useValue: teamsServiceStub },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const notice = fixture.nativeElement.querySelector('.job-detail__notice');
    expect(notice).toBeFalsy();
  });

  it('threads team_id/combo_id/enemy_profile_id/active_index from job.request into the results grid', async () => {
    const job = makeJob({
      request: {
        team_id: 't1',
        combo_id: 'c1',
        enemy_profile_id: 'e1',
        active_index: 2,
      },
    });
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(job) },
        { provide: TeamsService, useValue: teamsServiceStub },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const grid = fixture.debugElement.query(By.directive(OptimizerResultsGrid))
      .componentInstance as OptimizerResultsGrid;
    expect(grid.teamId()).toBe('t1');
    expect(grid.comboId()).toBe('c1');
    expect(grid.enemyProfileId()).toBe('e1');
    expect(grid.activeIndex()).toBe(2);
  });

  it('falls back to combo_ids[0] and defaults active_index to 0 when absent', async () => {
    const job = makeJob({
      request: { team_id: 't1', combo_ids: ['c9', 'c2'], enemy_profile_id: 'e1' },
    });
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(job) },
        { provide: TeamsService, useValue: teamsServiceStub },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const grid = fixture.debugElement.query(By.directive(OptimizerResultsGrid))
      .componentInstance as OptimizerResultsGrid;
    expect(grid.comboId()).toBe('c9');
    expect(grid.activeIndex()).toBe(0);
  });

  it('leaves deep-link context null when job.request has no team_id (legacy job)', async () => {
    const job = makeJob({ request: { combo_id: 'c1', enemy_profile_id: 'e1' } });
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(job) },
        { provide: TeamsService, useValue: teamsServiceStub },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const grid = fixture.debugElement.query(By.directive(OptimizerResultsGrid))
      .componentInstance as OptimizerResultsGrid;
    expect(grid.teamId()).toBeNull();
  });

  it('resolves buildId via team_id + active_index and emits it on equip', async () => {
    const job = makeJob({
      request: { team_id: 't1', combo_id: 'c1', enemy_profile_id: 'e1', active_index: 1 },
    });
    const teamsService = makeTeamsServiceStub({ build2_id: 'b2-active' });
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(job) },
        { provide: TeamsService, useValue: teamsService },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    await teamsService.get.mock.results[0].value;
    fixture.detectChanges();

    expect(teamsService.get).toHaveBeenCalledWith('t1');
    const equipSpy = vi.fn();
    fixture.componentInstance.equip.subscribe(equipSpy);
    fixture.componentInstance['onEquip'](['d1']);
    expect(equipSpy).toHaveBeenCalledWith({ discIds: ['d1'], buildId: 'b2-active' });
  });

  it('does not call TeamsService and does not emit equip for a legacy job with no team_id', async () => {
    const job = makeJob({ request: { combo_id: 'c1', enemy_profile_id: 'e1' } });
    const teamsService = makeTeamsServiceStub();
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(job) },
        { provide: TeamsService, useValue: teamsService },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(teamsService.get).not.toHaveBeenCalled();
    const equipSpy = vi.fn();
    fixture.componentInstance.equip.subscribe(equipSpy);
    fixture.componentInstance['onEquip'](['d1']);
    expect(equipSpy).not.toHaveBeenCalled();
  });

  it('shows the search_summary banner when present on the result', async () => {
    const job = makeJob({
      result: {
        combo_id: 'c1',
        combo_name: 'Rotation A',
        agent_name: 'Zhu Yuan',
        enemy_name: 'Cyclops',
        current_build_damage: null,
        builds: [],
        evaluated: 48210,
        pruned_sets: 0,
        pruned_stats: 0,
        search_summary:
          'Searched 48,210 of ~1.2M combinations (top-K prefilter K=8 applied — results are near-exact; run exact search to verify).',
      } as any,
    });
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(job) },
        { provide: TeamsService, useValue: teamsServiceStub },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const banner = fixture.nativeElement.querySelector('.job-detail__search-summary');
    expect(banner).toBeTruthy();
    expect(banner.textContent).toContain('near-exact');
  });

  it('omits the search_summary banner when absent (older jobs pre-B5)', async () => {
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(makeJob()) },
        { provide: TeamsService, useValue: teamsServiceStub },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const banner = fixture.nativeElement.querySelector('.job-detail__search-summary');
    expect(banner).toBeFalsy();
  });

  it('shows defensive error when result is null but status is succeeded', async () => {
    const job = makeJob({ result: null });
    TestBed.configureTestingModule({
      providers: [
        { provide: OptimizerService, useValue: makeService(job) },
        { provide: TeamsService, useValue: teamsServiceStub },
      ],
    });
    const fixture = TestBed.createComponent(OptimizerJobDetail);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const err = fixture.nativeElement.querySelector('.job-detail__error');
    expect(err).toBeTruthy();
    expect(err.textContent).toContain('Result data missing');
  });
});
