import { TestBed } from '@angular/core/testing';

import { SimRunsService } from './sim-runs.service';

describe('SimRunsService.retrieve', () => {
  let GET: ReturnType<typeof vi.fn>;
  let service: SimRunsService;

  beforeEach(() => {
    GET = vi.fn();
    // The repo's own pattern for a service that calls `injectApi()` in a field initializer:
    // build it inside an injection context, then swap the field. `vi.mock` is refused for
    // relative imports by the Angular unit-test system.
    TestBed.configureTestingModule({});
    service = TestBed.runInInjectionContext(() => new SimRunsService());
    (service as unknown as { api: unknown }).api = { GET, POST: vi.fn() };
  });

  it('returns a cached result when the server has one', async () => {
    GET.mockResolvedValue({ data: { retrieved: { result: { dps: 1 } } }, error: undefined });

    await expect(service.retrieve('ctx', 1.2)).resolves.toEqual({ dps: 1 });
  });

  it('returns null when nothing close enough is cached', async () => {
    // The endpoint answers 200 with a *reason* rather than 404 — an error invites a retry or
    // a swallowed exception, and the second is the silent fallback the design forbids.
    GET.mockResolvedValue({
      data: { retrieved: null, not_retrieved_because: 'nothing is cached' },
      error: undefined,
    });

    await expect(service.retrieve('ctx', 1.2)).resolves.toBeNull();
  });

  it('returns null rather than throwing when the request fails', async () => {
    // A cache that cannot be read is a slower search, not a failed one.
    GET.mockRejectedValue(new Error('offline'));

    await expect(service.retrieve('ctx', 1.2)).resolves.toBeNull();
  });

  it('asks for the context and the ER it actually wants', async () => {
    GET.mockResolvedValue({ data: { retrieved: null }, error: undefined });

    await service.retrieve('ctx-1', 1.45);

    expect(GET).toHaveBeenCalledWith('/api/v1/sim-runs/retrieve', {
      params: { query: { context_key: 'ctx-1', energy_recharge: 1.45 } },
    });
  });
});
