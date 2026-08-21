import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../api/api.client';
import { BuffContextStore } from '../../shared/buff-context.store';
import {
  type OptimizationJobRead,
  type OptimizationJobSummary,
  type OptimizeInput,
  OptimizerService,
} from './optimizer.service';

function setup() {
  TestBed.configureTestingModule({
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  return TestBed.inject(OptimizerService);
}

function mockFetch(body: unknown, status = 200) {
  const noBody = status === 204 || status === 304;
  return vi.fn<typeof globalThis.fetch>(async () =>
    new Response(noBody ? null : JSON.stringify(body), {
      status,
      headers: noBody ? {} : { 'content-type': 'application/json' },
    }),
  );
}

const MOCK_JOB_SUMMARY: OptimizationJobSummary = {
  id: 'job-1',
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
};

const MOCK_JOB_READ: OptimizationJobRead = {
  ...MOCK_JOB_SUMMARY,
  request: { combo_id: 'c1' },
  result: null,
};

describe('OptimizerService', () => {
  describe('submit()', () => {
    it('POSTs to /api/v1/optimizer/discs and returns OptimizationJobSummary', async () => {
      const fetchSpy = mockFetch(MOCK_JOB_SUMMARY, 202);
      globalThis.fetch = fetchSpy;
      const svc = setup();

      const req: OptimizeInput = { combo_id: 'c1', enemy_profile_id: 'e1' };
      const result = await svc.submit(req);

      const call = fetchSpy.mock.calls[0][0] as Request;
      expect(call.method).toBe('POST');
      expect(call.url).toContain('/api/v1/optimizer/discs');
      expect(result.id).toBe('job-1');
      expect(result.status).toBe('queued');
    });

    it('sends combo_ids in the body', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();
      await svc.submit({ combo_ids: ['c1', 'c2'], enemy_profile_id: 'e1' });
      const body = await (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const parsed = await body.json();
      expect(parsed.combo_ids).toEqual(['c1', 'c2']);
    });

    it('throws on error response', async () => {
      globalThis.fetch = mockFetch({ detail: 'Combo not found' }, 404);
      const svc = setup();
      await expect(svc.submit({ combo_id: 'bad', enemy_profile_id: 'e1' })).rejects.toThrow();
    });

    it('sends the BuffContextStore context, not hardcoded literals (Task A10)', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();
      const store = TestBed.inject(BuffContextStore);
      store.seed({
        active_conditions: ['always', 'hp_above_50'],
        stack_counts: { 'agent:stack': 3 },
        disabled_buffs: ['1:core_a'],
      });

      await svc.submit({ combo_id: 'c1', enemy_profile_id: 'e1' });

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.active_conditions).toEqual(['always', 'hp_above_50']);
      expect(body.stack_counts).toEqual({ 'agent:stack': 3 });
      expect(body.disabled_buffs).toEqual(['1:core_a']);
    });

    it('lets an explicit input override the store context', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();
      const store = TestBed.inject(BuffContextStore);
      store.seed({
        active_conditions: ['always', 'hp_above_50'],
        stack_counts: {},
        disabled_buffs: [],
      });

      await svc.submit({
        combo_id: 'c1',
        enemy_profile_id: 'e1',
        active_conditions: ['always'],
      });

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.active_conditions).toEqual(['always']);
    });
  });

  describe('listJobs()', () => {
    it('GETs /api/v1/optimizer/jobs', async () => {
      globalThis.fetch = mockFetch([MOCK_JOB_SUMMARY]);
      const svc = setup();
      const result = await svc.listJobs();
      const call = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      expect(call.method).toBe('GET');
      expect(call.url).toContain('/api/v1/optimizer/jobs');
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('job-1');
    });

    it('passes status filter as query param', async () => {
      globalThis.fetch = mockFetch([]);
      const svc = setup();
      await svc.listJobs({ status: 'running,queued' });
      const call = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      expect(call.url).toContain('status=running%2Cqueued');
    });
  });

  describe('getJob()', () => {
    it('GETs /api/v1/optimizer/jobs/{id}', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_READ);
      const svc = setup();
      const result = await svc.getJob('job-1');
      const call = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      expect(call.url).toContain('/api/v1/optimizer/jobs/job-1');
      expect(result.request).toEqual({ combo_id: 'c1' });
    });

    it('throws on 404', async () => {
      globalThis.fetch = mockFetch({ detail: 'Not found' }, 404);
      const svc = setup();
      await expect(svc.getJob('missing')).rejects.toThrow();
    });
  });

  describe('deleteJob()', () => {
    it('DELETEs /api/v1/optimizer/jobs/{id}', async () => {
      globalThis.fetch = mockFetch(null, 204);
      const svc = setup();
      await svc.deleteJob('job-1');
      const call = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      expect(call.method).toBe('DELETE');
      expect(call.url).toContain('/api/v1/optimizer/jobs/job-1');
    });

    it('throws on 404', async () => {
      globalThis.fetch = mockFetch({ detail: 'Not found' }, 404);
      const svc = setup();
      await expect(svc.deleteJob('missing')).rejects.toThrow();
    });
  });
});
