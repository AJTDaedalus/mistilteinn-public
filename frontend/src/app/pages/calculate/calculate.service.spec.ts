import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../api/api.client';
import { BuffContextStore } from '../../shared/buff-context.store';
import { CalculateService } from './calculate.service';

function setup() {
  TestBed.configureTestingModule({
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  return TestBed.inject(CalculateService);
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

const MOCK_SIMULATION_RESPONSE = {
  events: [],
  totals: {},
  field_timeline: [],
};

describe('CalculateService', () => {
  describe('simulate()', () => {
    it('POSTs to /api/v1/simulate', async () => {
      const fetchSpy = mockFetch(MOCK_SIMULATION_RESPONSE);
      globalThis.fetch = fetchSpy;
      const svc = setup();

      await svc.simulate({ dps: 'b1' }, [], 'e1');

      const call = fetchSpy.mock.calls[0][0] as Request;
      expect(call.method).toBe('POST');
      expect(call.url).toContain('/api/v1/simulate');
    });

    it('sends the BuffContextStore context as buff_context, not the server defaults (Task A10)', async () => {
      globalThis.fetch = mockFetch(MOCK_SIMULATION_RESPONSE);
      const svc = setup();
      const store = TestBed.inject(BuffContextStore);
      store.seed({
        active_conditions: ['always', 'hp_above_50'],
        stack_counts: { 'agent:stack': 3 },
        disabled_buffs: ['1:core_a'],
      });

      await svc.simulate({ dps: 'b1' }, [], 'e1');

      const req = (globalThis.fetch as ReturnType<typeof mockFetch>).mock.calls[0][0] as Request;
      const body = await req.json();
      expect(body.buff_context).toEqual({
        active_conditions: ['always', 'hp_above_50'],
        stack_counts: { 'agent:stack': 3 },
        disabled_buffs: ['1:core_a'],
        custom_buffs: [],
      });
    });

    it('throws on error response', async () => {
      globalThis.fetch = mockFetch({ detail: 'Enemy profile not found' }, 404);
      const svc = setup();

      await expect(svc.simulate({ dps: 'b1' }, [], 'bad')).rejects.toThrow();
    });
  });
});
