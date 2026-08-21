import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../api/api.client';
import { DiscsService } from './discs.service';

function setupSvc() {
  TestBed.configureTestingModule({
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  return TestBed.inject(DiscsService);
}

/** Stub fetch with a 200 import response and hand back the spy. */
function stubImportOk(body: Record<string, unknown> = {}) {
  const fetchSpy = vi.fn<typeof globalThis.fetch>(
    async () =>
      new Response(JSON.stringify({ imported: 0, ...body }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
  );
  globalThis.fetch = fetchSpy;
  return fetchSpy;
}

/** The request URL's query params, as a plain object. */
function queryOf(fetchSpy: ReturnType<typeof stubImportOk>) {
  const req = fetchSpy.mock.calls[0][0] as Request;
  return Object.fromEntries(new URL(req.url).searchParams);
}

describe('DiscsService', () => {
  it('importZod() POSTs the payload and returns counts', async () => {
    const result = {
      imported: 1500, skipped_duplicate: 100, skipped_unknown_set: 9,
      skipped_invalid: 0, errors: [],
    };
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify(result), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const out = await svc.importZod({ format: 'ZOD', version: 1, discs: [] });
    expect(out.imported).toBe(1500);
    const req = fetchSpy.mock.calls[0][0] as Request;
    expect(req.method).toBe('POST');
    expect(req.url).toContain('/discs/import');
  });

  it('importZod() sends no query string when no modes are given', async () => {
    const fetchSpy = stubImportOk();
    await setupSvc().importZod({ format: 'ZOD', version: 1, discs: [] });
    const req = fetchSpy.mock.calls[0][0] as Request;
    expect(new URL(req.url).search).toBe('');
  });

  it('importZod() sends disc_mode / build_mode when given', async () => {
    const fetchSpy = stubImportOk();
    await setupSvc().importZod(
      { format: 'eZOD' },
      'overwrite',
      'clean',
      'clean',
    );
    expect(queryOf(fetchSpy)).toEqual({
      build_conflict: 'overwrite',
      disc_mode: 'clean',
      build_mode: 'clean',
    });
  });

  it('importZod() omits the modes it was not given', async () => {
    const fetchSpy = stubImportOk();
    await setupSvc().importZod({ format: 'ZOD' }, undefined, 'clean');
    expect(queryOf(fetchSpy)).toEqual({ disc_mode: 'clean' });
  });

  it('importZod() surfaces the clean-mode deletion counters', async () => {
    stubImportOk({
      discs_deleted: 42,
      builds_deleted: 3,
      teams_deleted: 1,
      combos_deleted: 2,
      team_slots_remapped: 5,
    });
    const out = await setupSvc().importZod({ format: 'eZOD' });
    expect(out.discs_deleted).toBe(42);
    expect(out.builds_deleted).toBe(3);
    expect(out.teams_deleted).toBe(1);
    expect(out.combos_deleted).toBe(2);
    expect(out.team_slots_remapped).toBe(5);
  });

  it('importZod() throws on a 422 from the backend', async () => {
    globalThis.fetch = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({ detail: 'Expected format=ZOD' }), {
          status: 422,
          headers: { 'content-type': 'application/json' },
        }),
    );
    const svc = setupSvc();
    await expect(
      svc.importZod({ format: 'GOOD', discs: [] }),
    ).rejects.toThrow();
  });
});
