import { Injectable } from '@angular/core';

import { injectApi } from '../api/api.client';

/**
 * Submitting a finished gcsim run to the server's cache.
 *
 * **This is the corpus's only producer.** `DESIGN_client_optimizer.md` says the corpus
 * *"accumulates from real searches"*, and until now nothing in `frontend/src/app` called
 * `POST /api/v1/sim-runs` at all — the endpoint, the repository, the ER bucketing and the
 * coverage query were built, tested and CI-gated with no client. `DECISIONS.md` §25 records
 * the owner's ruling that searches should fill it.
 *
 * ## Failing to cache is not failing to search
 *
 * Every method here swallows its error. The corpus exists so *the next* search is cheaper; a
 * user whose search completed should never be told it did not because a cache write was
 * refused. The one thing that must not happen is silence about a wrong number, and that
 * cannot arise here — a run either reaches the cache or does not.
 */
@Injectable({ providedIn: 'root' })
export class SimRunsService {
  private api = injectApi();

  /**
   * Offer one finished run to the cache.
   *
   * `rotationId` and `rotationSignature` travel together or not at all — the server refuses
   * one without the other, because a run labelled with *which* rotation but not *which
   * version* is how a stale number gets shown as current.
   *
   * Returns whether it was stored, for a caller that wants to say so. Never throws.
   */
  async store(run: {
    contextKey: string;
    erBucket: number;
    gcsimPin: string;
    result: unknown;
    rotationId?: string | null;
    rotationSignature?: string | null;
  }): Promise<boolean> {
    try {
      const { error } = await this.api.POST('/api/v1/sim-runs', {
        params: { query: { gcsim_pin: run.gcsimPin } },
        body: {
          context_key: run.contextKey,
          er_bucket: run.erBucket,
          result: run.result as Record<string, never>,
          rotation_id: run.rotationId ?? null,
          rotation_signature: run.rotationSignature ?? null,
        },
      });
      return !error;
    } catch {
      return false;
    }
  }
}
