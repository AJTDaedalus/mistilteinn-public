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
   * Ask the server whether it already has this run.
   *
   * **The read half, which existed and had no caller.** `GET /sim-runs/retrieve` — the
   * endpoint, the ER bucketing, the neighbour rule and the stated-reason outcome — has been
   * built, tested and CI-gated since the corpus was designed, and nothing in `frontend/src`
   * ever called it. `POST` was in the same state until #183; this is the other half of the
   * same gap, and it is the whole of what makes the corpus **cross-device and cross-user**
   * rather than a write-only log.
   *
   * Returns the cached result, or `null` when there is none close enough. **Never throws**:
   * a cache that cannot be read is a slower search, not a failed one.
   *
   * The endpoint always answers 200 with a *reason* rather than a 404 — see
   * `RetrievalOutcome` — because an error invites a retry or a swallowed exception, and the
   * second is the silent fallback the design forbids by name.
   */
  async retrieve(contextKey: string, energyRecharge: number): Promise<unknown | null> {
    try {
      const { data, error } = await this.api.GET('/api/v1/sim-runs/retrieve', {
        params: { query: { context_key: contextKey, energy_recharge: energyRecharge } },
      });
      if (error) return null;
      return (data as { retrieved?: { result?: unknown } | null })?.retrieved?.result ?? null;
    } catch {
      return null;
    }
  }

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
