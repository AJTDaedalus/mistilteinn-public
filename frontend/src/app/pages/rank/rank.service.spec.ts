import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../api/api.client';
import { BuffContextStore } from '../../shared/buff-context.store';
import {
  type DiscScoreSchema,
  type InventoryScoreInput,
  type RankContextInput,
  type RankFilters,
  RankService,
} from './rank.service';

function setup() {
  TestBed.configureTestingModule({
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  return TestBed.inject(RankService);
}

function mockFetch(body: unknown, status = 200) {
  return vi.fn<typeof globalThis.fetch>(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json' },
      }),
  );
}

const MOCK_SCORE: DiscScoreSchema = {
  disc_id: 'd1',
  rolls_used: 3,
  remaining_rolls: 2,
  current_damage: 10000,
  baseline_damage: 9500,
  max_improvement: 500,
  mean_improvement: 200,
  stddev_improvement: 50,
  p10: 100,
  p50: 200,
  p90: 350,
  distribution: null,
};

const MOCK_RESPONSE = {
  combo_id: 'c1',
  combo_name: 'Combo A',
  agent_name: 'Agent X',
  enemy_name: 'Hollow Zero',
  scores: [MOCK_SCORE],
};

describe('RankService', () => {
  describe('scoreInventory()', () => {
    it('POSTs to /api/v1/scorer/inventory', async () => {
      globalThis.fetch = mockFetch(MOCK_RESPONSE);
      const svc = setup();

      await svc.scoreInventory({ combo_id: 'c1', enemy_profile_id: 'e1' });

      const call = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      expect(call.method).toBe('POST');
      expect(call.url).toContain('/api/v1/scorer/inventory');
    });

    it('sends scope="all" when specified', async () => {
      globalThis.fetch = mockFetch(MOCK_RESPONSE);
      const svc = setup();

      const input: InventoryScoreInput = { combo_id: 'c1', enemy_profile_id: 'e1', scope: 'all' };
      await svc.scoreInventory(input);

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.scope).toBe('all');
    });

    it('defaults scope to "default" when not specified', async () => {
      globalThis.fetch = mockFetch(MOCK_RESPONSE);
      const svc = setup();

      await svc.scoreInventory({ combo_id: 'c1', enemy_profile_id: 'e1' });

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.scope).toBe('default');
    });

    it('returns typed InventoryScoreResponse', async () => {
      globalThis.fetch = mockFetch(MOCK_RESPONSE);
      const svc = setup();

      const result = await svc.scoreInventory({ combo_id: 'c1', enemy_profile_id: 'e1' });

      expect(result.combo_id).toBe('c1');
      expect(result.agent_name).toBe('Agent X');
      expect(result.scores).toHaveLength(1);
      expect(result.scores[0].disc_id).toBe('d1');
      expect(result.scores[0].mean_improvement).toBe(200);
    });

    it('forwards allowed_set_ids when provided', async () => {
      globalThis.fetch = mockFetch(MOCK_RESPONSE);
      const svc = setup();

      await svc.scoreInventory({
        combo_id: 'c1',
        enemy_profile_id: 'e1',
        allowed_set_ids: [31100, 31200],
      });

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.allowed_set_ids).toEqual([31100, 31200]);
    });

    it('forwards allowed_set_ids=null when all sets selected', async () => {
      globalThis.fetch = mockFetch(MOCK_RESPONSE);
      const svc = setup();

      await svc.scoreInventory({ combo_id: 'c1', enemy_profile_id: 'e1', allowed_set_ids: null });

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.allowed_set_ids).toBeNull();
    });

    it('throws on error response', async () => {
      globalThis.fetch = mockFetch({ detail: 'Combo not found' }, 404);
      const svc = setup();

      await expect(
        svc.scoreInventory({ combo_id: 'bad', enemy_profile_id: 'e1' }),
      ).rejects.toThrow();
    });

    it('sends the BuffContextStore context, not hardcoded literals (Task A9)', async () => {
      globalThis.fetch = mockFetch(MOCK_RESPONSE);
      const svc = setup();
      const store = TestBed.inject(BuffContextStore);
      store.seed({
        active_conditions: ['always', 'hp_above_50'],
        stack_counts: { 'agent:stack': 3 },
        disabled_buffs: ['1:core_a'],
      });

      await svc.scoreInventory({ combo_id: 'c1', enemy_profile_id: 'e1' });

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.active_conditions).toEqual(['always', 'hp_above_50']);
      expect(body.stack_counts).toEqual({ 'agent:stack': 3 });
      expect(body.disabled_buffs).toEqual(['1:core_a']);
    });
  });

  describe('rank()', () => {
    const MOCK_JOB_SUMMARY = {
      id: 'job1',
      status: 'queued',
      job_type: 'rank',
      created_at: '2026-01-01T00:00:00Z',
    };

    it('POSTs to /api/v1/scorer/rank', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();

      const ctx: RankContextInput = { build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1' };
      await svc.rank([ctx]);

      const call = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      expect(call.method).toBe('POST');
      expect(call.url).toContain('/api/v1/scorer/rank');
    });

    it('sends contexts with scoring defaults applied', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();

      const ctx: RankContextInput = {
        build_id: 'b1',
        combo_id: 'c1',
        enemy_profile_id: 'e1',
        weight: 2,
        allowed_set_ids: [100, 200],
      };
      await svc.rank([ctx]);

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.contexts).toHaveLength(1);
      expect(body.contexts[0].build_id).toBe('b1');
      expect(body.contexts[0].combo_id).toBe('c1');
      expect(body.contexts[0].enemy_profile_id).toBe('e1');
      expect(body.contexts[0].weight).toBe(2);
      expect(body.contexts[0].allowed_set_ids).toEqual([100, 200]);
      expect(body.contexts[0].crit_mode).toBe('expected');
    });

    it('defaults weight to 1 when not provided', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();

      await svc.rank([{ build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1' }]);

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.contexts[0].weight).toBe(1);
    });

    it('defaults scope to "default" when no scope is passed', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();

      await svc.rank([{ build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1' }]);

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.scope).toBe('default');
    });

    it('sends scope="all" when explicitly passed', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();

      await svc.rank([{ build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1' }], 'all');

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.scope).toBe('all');
    });

    it('sends multiple contexts for priority builds', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();

      const ctxs: RankContextInput[] = [
        { build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1', weight: 1 },
        { build_id: 'b2', combo_id: 'c2', enemy_profile_id: 'e2', weight: 2 },
      ];
      await svc.rank(ctxs);

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.contexts).toHaveLength(2);
      expect(body.contexts[1].build_id).toBe('b2');
    });

    it('returns the job summary', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();

      const result = await svc.rank([{ build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1' }]);
      expect(result.id).toBe('job1');
      expect(result.status).toBe('queued');
    });

    it('sends filters when provided', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();

      const filters: RankFilters = {
        slot: 4,
        set_ids: [31100, 31200],
        rarities: ['S'],
        main_stats: ['crit_rate'],
        level_value: 10,
        level_mode: 'min',
      };
      await svc.rank([{ build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1' }], 'default', filters);

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.filters).toEqual(filters);
    });

    it('sends filters=null when no filters provided', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();

      await svc.rank([{ build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1' }]);

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.filters).toBeNull();
    });

    it('throws on error response', async () => {
      globalThis.fetch = mockFetch({ detail: 'Build not found' }, 404);
      const svc = setup();

      await expect(
        svc.rank([{ build_id: 'bad', combo_id: 'c1', enemy_profile_id: 'e1' }]),
      ).rejects.toThrow();
    });

    it('falls back to the BuffContextStore for contexts that carry no buff state (Task A9)', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();
      const store = TestBed.inject(BuffContextStore);
      store.seed({
        active_conditions: ['always', 'hp_above_50'],
        stack_counts: { 'agent:stack': 3 },
        disabled_buffs: ['1:core_a'],
      });

      await svc.rank([
        { build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1' },
        { build_id: 'b2', combo_id: 'c2', enemy_profile_id: 'e2' },
      ]);

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      for (const ctx of body.contexts) {
        expect(ctx.active_conditions).toEqual(['always', 'hp_above_50']);
        expect(ctx.stack_counts).toEqual({ 'agent:stack': 3 });
        expect(ctx.disabled_buffs).toEqual(['1:core_a']);
      }
    });

    // DESIGN_buff_context.md §2.5 (#95). Before this, `rank()` took one store
    // snapshot outside the map and stamped it onto every context, so a job
    // spanning unrelated builds ranked all of them against one arbitrary buff
    // state — whichever page happened to seed the store last.
    it('sends each context its own buff state, not one shared value (#95)', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();
      const store = TestBed.inject(BuffContextStore);
      store.seed({
        active_conditions: ['always', 'leaked_from_another_page'],
        stack_counts: { 'agent:leaked': 9 },
        disabled_buffs: ['999:leaked'],
      });

      await svc.rank([
        {
          build_id: 'b1',
          combo_id: 'c1',
          enemy_profile_id: 'e1',
          active_conditions: ['always', 'hp_above_50'],
          stack_counts: { 'agent:stack': 3 },
          disabled_buffs: ['1:core_a'],
        },
        {
          build_id: 'b2',
          combo_id: 'c2',
          enemy_profile_id: 'e2',
          active_conditions: ['always'],
          stack_counts: {},
          disabled_buffs: ['2:core_b', '2:m2'],
        },
      ]);

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();

      expect(body.contexts[0].active_conditions).toEqual(['always', 'hp_above_50']);
      expect(body.contexts[0].stack_counts).toEqual({ 'agent:stack': 3 });
      expect(body.contexts[0].disabled_buffs).toEqual(['1:core_a']);

      expect(body.contexts[1].active_conditions).toEqual(['always']);
      expect(body.contexts[1].stack_counts).toEqual({});
      expect(body.contexts[1].disabled_buffs).toEqual(['2:core_b', '2:m2']);

      // The store's value reached neither — per-context state fully replaces it.
      for (const ctx of body.contexts) {
        expect(ctx.active_conditions).not.toContain('leaked_from_another_page');
        expect(ctx.disabled_buffs).not.toContain('999:leaked');
      }
    });

    it('mixes per-context state and the store fallback within one job (#95)', async () => {
      globalThis.fetch = mockFetch(MOCK_JOB_SUMMARY, 202);
      const svc = setup();
      const store = TestBed.inject(BuffContextStore);
      store.seed({
        active_conditions: ['always', 'fallback'],
        stack_counts: {},
        disabled_buffs: [],
      });

      await svc.rank([
        {
          build_id: 'b1',
          combo_id: 'c1',
          enemy_profile_id: 'e1',
          active_conditions: ['always', 'seeded'],
          stack_counts: {},
          disabled_buffs: [],
        },
        { build_id: 'b2', combo_id: 'c2', enemy_profile_id: 'e2' },
      ]);

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.contexts[0].active_conditions).toEqual(['always', 'seeded']);
      expect(body.contexts[1].active_conditions).toEqual(['always', 'fallback']);
    });
  });

  describe('evaluateDiscs()', () => {
    const MOCK_TEAM_CALC_RESPONSE = {
      team_id: 't1',
      team_name: 'Team A',
      dps_build_id: 'b1',
      dps_agent_name: 'Agent X',
      combo_id: 'c1',
      combo_name: 'Combo A',
      enemy_name: 'Hollow Zero',
      auto_conditions: [],
      applied_team_buffs: [],
      total_damage: 1000,
      standard_total: 1000,
      anomaly_total: 0,
      steps: [],
      by_category: [],
      by_element: [],
      total_atk: 1000,
      total_crit_rate: 500,
      total_crit_dmg: 5000,
      total_pen_ratio: 0,
    };

    it('sends the BuffContextStore active_conditions/stack_counts, not hardcoded literals (Task A9)', async () => {
      globalThis.fetch = mockFetch(MOCK_TEAM_CALC_RESPONSE);
      const svc = setup();
      const store = TestBed.inject(BuffContextStore);
      store.seed({
        active_conditions: ['always', 'hp_above_50'],
        stack_counts: { 'agent:stack': 3 },
        disabled_buffs: ['1:core_a'],
      });

      await svc.evaluateDiscs('t1', {
        comboId: 'c1',
        enemyProfileId: 'e1',
        activeIndex: 0,
        discIds: ['d1'],
      });

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.active_conditions).toEqual(['always', 'hp_above_50']);
      expect(body.stack_counts).toEqual({ 'agent:stack': 3 });
      // Since #64, EvaluateDiscsRequest *does* carry disabled_buffs, and sending it is
      // the point: this is the explain view for an optimizer/rank candidate, so a buff
      // the run switched off must be switched off here too, or the explanation shows a
      // number the run could not reproduce.
      expect(body.disabled_buffs).toEqual(['1:core_a']);
    });

    it('explains a ranked candidate with the state that context RANKED under', async () => {
      // Rank derives per-context buff state from build rows and never seeds the shared
      // store, and the server now *replaces* the build columns with whatever the request
      // carries — so reading the store here would apply buffs the ranked run had
      // switched off, and show a total that run cannot reproduce.
      // One mock for both calls: the API client captures `globalThis.fetch` when the
      // service is constructed, so swapping it afterwards would not be seen.
      globalThis.fetch = mockFetch(MOCK_TEAM_CALC_RESPONSE);
      const svc = setup();
      const store = TestBed.inject(BuffContextStore);
      store.seed({
        active_conditions: ['always'],
        stack_counts: {},
        disabled_buffs: ['store:leaked'],
      });

      await svc.rank([
        {
          build_id: 'b1',
          combo_id: 'c1',
          enemy_profile_id: 'e1',
          disabled_buffs: ['1:ranked_with_this_off'],
          active_conditions: ['always', 'hp_above_50'],
        },
      ]);

      await svc.evaluateDiscs('t1', {
        comboId: 'c1',
        enemyProfileId: 'e1',
        activeIndex: 0,
        discIds: ['d1'],
        buildId: 'b1',
      });

      // calls[0] is the rank submit; calls[1] is the evaluate-discs under test.
      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[1][0] as Request;
      const body = await req.json();
      expect(body.disabled_buffs).toEqual(['1:ranked_with_this_off']);
      expect(body.active_conditions).toEqual(['always', 'hp_above_50']);
    });

    it('falls back to the store when no ranked context is named (optimizer grid)', async () => {
      globalThis.fetch = mockFetch(MOCK_TEAM_CALC_RESPONSE);
      const svc = setup();
      const store = TestBed.inject(BuffContextStore);
      store.seed({
        active_conditions: ['always'],
        stack_counts: {},
        disabled_buffs: ['1:core_a'],
      });

      await svc.evaluateDiscs('t1', {
        comboId: 'c1',
        enemyProfileId: 'e1',
        activeIndex: 0,
        discIds: ['d1'],
      });

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.disabled_buffs).toEqual(['1:core_a']);
    });

    it('throws on error response', async () => {
      globalThis.fetch = mockFetch({ detail: 'Team not found' }, 404);
      const svc = setup();

      await expect(
        svc.evaluateDiscs('bad', {
          comboId: 'c1',
          enemyProfileId: 'e1',
          activeIndex: 0,
          discIds: ['d1'],
        }),
      ).rejects.toThrow();
    });
  });

  describe('pollUntilDone()', () => {
    const BASE_JOB = {
      id: 'job-1',
      status: 'running',
      agent_name: 'A',
      enemy_name: 'E',
      combo_name: 'C',
      assignments_done: 0,
      assignments_total: 10,
      evaluated: 0,
      elapsed_seconds: 0,
      eta_seconds: null,
      top_damage: null,
      error_message: null,
      created_at: '2024-01-01T00:00:00',
      started_at: '2024-01-01T00:00:00',
      finished_at: null,
      request: {},
      result: null,
      job_type: 'rank',
    };

    it('resolves immediately when job is already succeeded', async () => {
      const doneJob = { ...BASE_JOB, status: 'succeeded', assignments_done: 10 };
      globalThis.fetch = mockFetch(doneJob);
      const svc = setup();

      const result = await svc.pollUntilDone('job-1', undefined, 0);
      expect(result.status).toBe('succeeded');
    });

    it('resolves when job transitions from running to succeeded', async () => {
      let calls = 0;
      vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
        calls++;
        const status = calls < 3 ? 'running' : 'succeeded';
        return new Response(JSON.stringify({ ...BASE_JOB, status }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      });
      const svc = setup();

      const result = await svc.pollUntilDone('job-1', undefined, 0);
      expect(result.status).toBe('succeeded');
      expect(calls).toBe(3);
    });

    it('resolves on failed status', async () => {
      const failedJob = { ...BASE_JOB, status: 'failed' };
      globalThis.fetch = mockFetch(failedJob);
      const svc = setup();

      const result = await svc.pollUntilDone('job-1', undefined, 0);
      expect(result.status).toBe('failed');
    });

    it('resolves on cancelled status', async () => {
      const cancelledJob = { ...BASE_JOB, status: 'cancelled' };
      globalThis.fetch = mockFetch(cancelledJob);
      const svc = setup();

      const result = await svc.pollUntilDone('job-1', undefined, 0);
      expect(result.status).toBe('cancelled');
    });

    it('calls onProgress for each poll response', async () => {
      let calls = 0;
      vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
        calls++;
        const status = calls < 2 ? 'running' : 'succeeded';
        const done = calls < 2 ? 5 : 10;
        return new Response(JSON.stringify({ ...BASE_JOB, status, assignments_done: done }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      });
      const svc = setup();
      const progressUpdates: number[] = [];

      await svc.pollUntilDone('job-1', (j) => progressUpdates.push(j.assignments_done), 0);

      expect(progressUpdates).toEqual([5, 10]);
    });
  });

  describe('listRankJobs()', () => {
    it('GETs /api/v1/optimizer/jobs with job_type=rank', async () => {
      globalThis.fetch = mockFetch([]);
      const svc = setup();

      await svc.listRankJobs();

      const call = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      expect(call.method).toBe('GET');
      expect(call.url).toContain('/api/v1/optimizer/jobs');
      expect(call.url).toContain('job_type=rank');
    });

    it('returns the job summary array', async () => {
      const jobs = [
        { id: 'j1', status: 'succeeded', job_type: 'rank', created_at: '2026-01-01T00:00:00Z' },
      ];
      globalThis.fetch = mockFetch(jobs);
      const svc = setup();

      const result = await svc.listRankJobs();
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('j1');
    });

    it('throws on error response', async () => {
      globalThis.fetch = mockFetch({ detail: 'server error' }, 500);
      const svc = setup();

      await expect(svc.listRankJobs()).rejects.toThrow();
    });
  });

  describe('cancelJob()', () => {
    it('DELETEs /api/v1/optimizer/jobs/{job_id}', async () => {
      globalThis.fetch = mockFetch({}, 200);
      const svc = setup();

      await svc.cancelJob('job-42');

      const call = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      expect(call.method).toBe('DELETE');
      expect(call.url).toContain('/api/v1/optimizer/jobs/job-42');
    });

    it('throws on error response', async () => {
      globalThis.fetch = mockFetch({ detail: 'not found' }, 404);
      const svc = setup();

      await expect(svc.cancelJob('missing')).rejects.toThrow();
    });
  });
});
