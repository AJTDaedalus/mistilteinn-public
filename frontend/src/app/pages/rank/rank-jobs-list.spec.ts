import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import { RankJobsList } from './rank-jobs-list';
import type { OptimizationJobSummary } from './rank.service';

function makeJob(overrides: Partial<OptimizationJobSummary> = {}): OptimizationJobSummary {
  return {
    id: 'j1',
    status: 'queued',
    job_type: 'rank',
    agent_name: 'Jane / Lighter',
    enemy_name: 'Golem',
    combo_name: 'Default',
    assignments_done: 0,
    assignments_total: 0,
    evaluated: 0,
    elapsed_seconds: 0,
    eta_seconds: null,
    top_damage: null,
    error_message: null,
    created_at: '2026-01-01T00:00:00Z',
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

describe('RankJobsList', () => {
  it('renders empty state when no jobs', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(RankJobsList);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.jobs-list__empty')).toBeTruthy();
  });

  it('renders a row per job', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(RankJobsList);
    fixture.componentRef.setInput('jobs', [makeJob({ id: 'j1' }), makeJob({ id: 'j2' })]);
    fixture.detectChanges();
    const rows = fixture.nativeElement.querySelectorAll('.jobs-list__row');
    expect(rows.length).toBe(2);
  });

  it('emits view on View button click for succeeded job', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(RankJobsList);
    fixture.componentRef.setInput('jobs', [makeJob({ id: 'j1', status: 'succeeded' })]);
    fixture.detectChanges();

    const viewSpy = vi.fn();
    fixture.componentInstance.view.subscribe(viewSpy);

    const btn = fixture.nativeElement.querySelector('.btn-small:not(.btn-small--danger)');
    btn?.click();
    expect(viewSpy).toHaveBeenCalledWith('j1');
  });

  it('emits cancel on Cancel button click for non-terminal job', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(RankJobsList);
    fixture.componentRef.setInput('jobs', [makeJob({ id: 'j1', status: 'running' })]);
    fixture.detectChanges();

    const cancelSpy = vi.fn();
    fixture.componentInstance.cancelJob.subscribe(cancelSpy);

    const btn = fixture.nativeElement.querySelector('.btn-small--danger');
    btn?.click();
    expect(cancelSpy).toHaveBeenCalledWith('j1');
  });

  it('hides Cancel button on terminal jobs', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(RankJobsList);
    fixture.componentRef.setInput('jobs', [makeJob({ id: 'j1', status: 'succeeded' })]);
    fixture.detectChanges();
    const cancelBtn = fixture.nativeElement.querySelector('.btn-small--danger');
    expect(cancelBtn).toBeNull();
  });

  it('shows progress bar for running jobs', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(RankJobsList);
    fixture.componentRef.setInput('jobs', [makeJob({
      status: 'running', assignments_done: 3, assignments_total: 10,
    })]);
    fixture.detectChanges();
    const bar = fixture.nativeElement.querySelector('.jobs-list__progress-bar') as HTMLElement | null;
    expect(bar).toBeTruthy();
    expect(bar?.style.width).toBe('30%');
  });

  it('progressPct returns correct value', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(RankJobsList);
    fixture.detectChanges();
    const comp = fixture.componentInstance;
    expect(comp.progressPct(makeJob({ assignments_done: 5, assignments_total: 10 }))).toBe(50);
    expect(comp.progressPct(makeJob({ assignments_done: 0, assignments_total: 0 }))).toBe(0);
  });
});
