import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import { OptimizerJobsList } from './optimizer-jobs-list';
import type { OptimizationJobSummary } from './optimizer.service';

function makeJob(overrides: Partial<OptimizationJobSummary> = {}): OptimizationJobSummary {
  return {
    id: 'j1',
    status: 'queued',
    job_type: 'optimize',
    agent_name: 'Agent',
    enemy_name: 'Enemy',
    combo_name: 'Combo',
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

describe('OptimizerJobsList', () => {
  it('renders empty state when no jobs', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(OptimizerJobsList);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.jobs-list__empty')).toBeTruthy();
  });

  it('renders a row per job', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(OptimizerJobsList);
    fixture.componentRef.setInput('jobs', [makeJob({ id: 'j1' }), makeJob({ id: 'j2' })]);
    fixture.detectChanges();
    const rows = fixture.nativeElement.querySelectorAll('.jobs-list__row');
    expect(rows.length).toBe(2);
  });

  it('emits view event on View button click for succeeded job', async () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(OptimizerJobsList);
    fixture.componentRef.setInput('jobs', [makeJob({ id: 'j1', status: 'succeeded' })]);
    fixture.detectChanges();

    const viewSpy = vi.fn();
    fixture.componentInstance.view.subscribe(viewSpy);

    const btn = fixture.nativeElement.querySelector('.btn-small:not(.btn-small--danger)');
    btn?.click();
    expect(viewSpy).toHaveBeenCalledWith('j1');
  });

  it('emits delete event on ✕ button click', async () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(OptimizerJobsList);
    fixture.componentRef.setInput('jobs', [makeJob({ id: 'j1', status: 'running' })]);
    fixture.detectChanges();

    const deleteSpy = vi.fn();
    fixture.componentInstance.delete.subscribe(deleteSpy);

    const btn = fixture.nativeElement.querySelector('.btn-small--danger');
    btn?.click();
    expect(deleteSpy).toHaveBeenCalledWith('j1');
  });

  it('shows progress bar for in-flight jobs', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(OptimizerJobsList);
    fixture.componentRef.setInput('jobs', [makeJob({
      status: 'running', assignments_done: 5, assignments_total: 10,
    })]);
    fixture.detectChanges();
    const bar = fixture.nativeElement.querySelector('.jobs-list__progress-bar') as HTMLElement | null;
    expect(bar).toBeTruthy();
    expect(bar?.style.width).toBe('50%');
  });

  it('progressPct returns correct percentage', () => {
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(OptimizerJobsList);
    fixture.detectChanges();
    const comp = fixture.componentInstance;
    expect(comp.progressPct(makeJob({ assignments_done: 3, assignments_total: 10 }))).toBe(30);
    expect(comp.progressPct(makeJob({ assignments_done: 0, assignments_total: 0 }))).toBe(0);
  });
});
