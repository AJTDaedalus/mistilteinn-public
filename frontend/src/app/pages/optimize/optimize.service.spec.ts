import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { OptimizeService } from './optimize.service';

/**
 * Math-fallback P0: the search-context body names the talent and **no scaling stat**.
 *
 * It used to send `scaling_stat: 'atk'` with every talent, and the server took it, so the
 * single-hit search scored Neuvillette, Furina, Nilou, Yelan, Itto, Noelle and every other
 * HP/DEF/EM scaler off ATK. The talent's own row decides now, and the resolved stats come
 * back on the context's `hit` — which is what the kernel reads.
 */
describe('OptimizeService.context', () => {
  function serviceWithCapture() {
    const calls: { body: Record<string, unknown> }[] = [];
    // `injectApi()` is a field initializer, so the service needs an injection context.
    TestBed.configureTestingModule({});
    const service = TestBed.runInInjectionContext(() => new OptimizeService());
    (service as unknown as { api: unknown }).api = {
      POST: (_path: string, init: { body: Record<string, unknown> }) => {
        calls.push(init);
        return Promise.resolve({ data: {}, error: undefined });
      },
    };
    return { service, calls };
  }

  it('sends the talent and lets its row decide the scaling stat', async () => {
    const { service, calls } = serviceWithCapture();

    await service.context(
      'b1', { talent: 'elemental_burst', label: 'Skill DMG', index: 0 }, 'hydro', 'burst', 90,
    );

    const hit = (calls[0].body as { hit: Record<string, unknown> }).hit;
    expect(hit['talent']).toEqual({ talent: 'elemental_burst', label: 'Skill DMG', index: 0 });
    expect('scaling_stat' in hit).toBe(false);
  });
});
