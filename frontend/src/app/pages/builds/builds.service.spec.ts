import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../api/api.client';
import { BuildsService } from './builds.service';

/**
 * Service-level tests run against a mock fetch so we don't need a
 * live backend. We override the API base URL to a sentinel and
 * intercept fetch globally inside each test.
 */
function setupSvc() {
  TestBed.configureTestingModule({
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  return TestBed.inject(BuildsService);
}

function mockFetch(payload: unknown, status = 200) {
  globalThis.fetch = vi.fn(async () =>
    new Response(JSON.stringify(payload), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  );
}

describe('BuildsService', () => {
  it('list() unwraps the paginated items array', async () => {
    mockFetch({
      items: [{ id: 'b1', name: 'My Build', agent_id: 'a1' }],
      total: 1, offset: 0, limit: 200,
    });
    const svc = setupSvc();
    const out = await svc.list();
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe('b1');
  });

  it('list() returns empty array when nothing to list', async () => {
    mockFetch({ items: [], total: 0, offset: 0, limit: 200 });
    const svc = setupSvc();
    expect(await svc.list()).toEqual([]);
  });

  // openapi-fetch invokes fetch(Request) — so the call's first arg is a
  // Request instance, not a (url, init) pair. Inspect its properties.
  function lastRequest(spy: ReturnType<typeof vi.fn>): Request {
    const args = spy.mock.calls[0];
    expect(args).toBeDefined();
    return args[0] as Request;
  }

  it('create() POSTs the payload and returns the created build', async () => {
    const created = {
      id: 'new-id', name: '', agent_id: 'a1', w_engine_id: null,
      w_engine_refinement: 1, mindscape_level: 0, agent_level: 60,
      skill_levels: '12,12,12,12,12',
      support1_build_id: null, support2_build_id: null,
      support1_agent_id: null, support2_agent_id: null, notes: '',
    };
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify(created), {
          status: 201,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const out = await svc.create({ agent_id: 'a1' });
    expect(out.id).toBe('new-id');
    const req = lastRequest(fetchSpy);
    expect(req.method).toBe('POST');
    expect(await req.json()).toMatchObject({ agent_id: 'a1' });
  });

  it('update() PATCHes and returns the updated build', async () => {
    const updated = {
      id: 'b1', name: 'Renamed', agent_id: 'a1', w_engine_id: null,
      w_engine_refinement: 1, mindscape_level: 6, agent_level: 60,
      skill_levels: '12,12,12,12,12',
      support1_build_id: null, support2_build_id: null,
      support1_agent_id: null, support2_agent_id: null, notes: '',
    };
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify(updated), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const out = await svc.update('b1', { mindscape_level: 6 });
    expect(out.mindscape_level).toBe(6);
    expect(lastRequest(fetchSpy).method).toBe('PATCH');
  });

  it('remove() sends DELETE and succeeds on 204', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () => new Response(null, { status: 204 }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    await svc.remove('b1');
    expect(lastRequest(fetchSpy).method).toBe('DELETE');
  });

  it('list() throws when the API returns an error body', async () => {
    mockFetch({ detail: 'boom' }, 500);
    const svc = setupSvc();
    await expect(svc.list()).rejects.toThrow();
  });

  it('listDiscs() passes filter params as query string', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(
          JSON.stringify({ items: [], total: 0, offset: 0, limit: 2000 }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    await svc.listDiscs({ slot: 4, rarity: 'S', equipped: 'unequipped' });
    const req = lastRequest(fetchSpy);
    const url = new URL(req.url);
    expect(url.searchParams.get('slot')).toBe('4');
    expect(url.searchParams.get('rarity')).toBe('S');
    expect(url.searchParams.get('equipped')).toBe('unequipped');
  });

  it('listDiscsForBuild() uses equipped=<buildId> filter', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(
          JSON.stringify({ items: [], total: 0, offset: 0, limit: 2000 }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    await svc.listDiscsForBuild('build-123');
    const url = new URL(lastRequest(fetchSpy).url);
    expect(url.searchParams.get('equipped')).toBe('build-123');
  });

  it('setPriorityOrder() PUTs ordered IDs and returns ranked builds', async () => {
    const ranked = [
      { id: 'b1', name: 'Build 1', optimizer_priority: 1 },
      { id: 'b2', name: 'Build 2', optimizer_priority: 2 },
    ];
    const fetchSpy = vi.fn<typeof globalThis.fetch>(async () =>
      new Response(JSON.stringify(ranked), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const result = await svc.setPriorityOrder(['b1', 'b2']);

    const req = lastRequest(fetchSpy);
    expect(req.method).toBe('PUT');
    expect(req.url).toContain('/api/v1/builds/priority');
    const body = await req.json();
    expect(body.ordered_build_ids).toEqual(['b1', 'b2']);
    expect(result[0].optimizer_priority).toBe(1);
    expect(result[1].optimizer_priority).toBe(2);
  });

  it('equipAll() PATCHes /equip-discs and returns the updated build', async () => {
    const updatedBuild = { id: 'b1', name: 'Zhu Yuan' };
    const fetchSpy = vi.fn<typeof globalThis.fetch>(async () =>
      new Response(JSON.stringify(updatedBuild), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const result = await svc.equipAll('b1', { 1: 'd1', 2: 'd2', 3: 'd3', 4: 'd4', 5: 'd5', 6: 'd6' });

    const req = lastRequest(fetchSpy);
    expect(req.method).toBe('PATCH');
    expect(req.url).toContain('/api/v1/builds/b1/equip-discs');
    const body = await req.json();
    expect(body.discs['1']).toBe('d1');
    expect(result).toEqual(updatedBuild);
  });
});
