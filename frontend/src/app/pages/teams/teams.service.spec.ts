import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../api/api.client';
import { TeamsService, TeamCreatePayload } from './teams.service';

function setupSvc() {
  TestBed.configureTestingModule({
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  return TestBed.inject(TeamsService);
}

function mockFetch(payload: unknown, status = 200) {
  globalThis.fetch = vi.fn(async () =>
    new Response(JSON.stringify(payload), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  );
}

function lastRequest(spy: ReturnType<typeof vi.fn>): Request {
  const args = spy.mock.calls[0];
  expect(args).toBeDefined();
  return args[0] as Request;
}

const TEAM: Record<string, unknown> = {
  id: 't1',
  name: 'Strike Force',
  build1_id: 'b1',
  build2_id: 'b2',
  build3_id: null,
};

describe('TeamsService', () => {
  it('list() returns teams from paginated response', async () => {
    mockFetch({ items: [TEAM], total: 1, offset: 0, limit: 200 });
    const svc = setupSvc();
    const out = await svc.list();
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe('t1');
  });

  it('list() returns empty array when no teams', async () => {
    mockFetch({ items: [], total: 0, offset: 0, limit: 200 });
    const svc = setupSvc();
    expect(await svc.list()).toEqual([]);
  });

  it('get() fetches single team by id', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(async () =>
      new Response(JSON.stringify(TEAM), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const out = await svc.get('t1');
    expect(out.id).toBe('t1');
    const req = lastRequest(fetchSpy);
    expect(req.url).toContain('/api/v1/teams/t1');
  });

  it('create() POSTs build1_id and optional members, returns created team', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(async () =>
      new Response(JSON.stringify({ ...TEAM, id: 'new-t' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const payload: TeamCreatePayload = { build1_id: 'b1', build2_id: 'b2', build3_id: null };
    const out = await svc.create(payload);
    expect(out.id).toBe('new-t');
    const req = lastRequest(fetchSpy);
    expect(req.method).toBe('POST');
    const body = await req.json();
    expect(body).toMatchObject({ build1_id: 'b1', build2_id: 'b2' });
  });

  it('create() with only build1_id (1-member team)', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(async () =>
      new Response(JSON.stringify({ ...TEAM, build2_id: null, build3_id: null, id: 'solo' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const out = await svc.create({ build1_id: 'b1' });
    expect(out.id).toBe('solo');
    const body = await lastRequest(fetchSpy).json();
    expect(body.build1_id).toBe('b1');
    expect(body.name).toBe('');
  });

  it('update() PATCHes and returns updated team', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(async () =>
      new Response(JSON.stringify({ ...TEAM, name: 'Renamed' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const out = await svc.update('t1', { name: 'Renamed' });
    expect(out.name).toBe('Renamed');
    const req = lastRequest(fetchSpy);
    expect(req.method).toBe('PATCH');
    expect(req.url).toContain('/api/v1/teams/t1');
  });

  it('remove() sends DELETE', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(async () =>
      new Response(null, { status: 204 }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    await svc.remove('t1');
    expect(lastRequest(fetchSpy).method).toBe('DELETE');
    expect(lastRequest(fetchSpy).url).toContain('/api/v1/teams/t1');
  });

  it('list() throws when the API returns an error body', async () => {
    mockFetch({ detail: 'boom' }, 500);
    const svc = setupSvc();
    await expect(svc.list()).rejects.toThrow();
  });
});
