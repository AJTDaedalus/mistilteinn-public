import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type DiscImportResponse = components['schemas']['DiscImportResponse'];
export type DiscRead = components['schemas']['DiscRead'];

/** `merge` keeps what's already there; `clean` wipes it before importing. */
export type ImportMode = 'merge' | 'clean';

@Injectable({ providedIn: 'root' })
export class DiscsService {
  private api = injectApi();

  /** GET /api/v1/discs — returns up to 3000 discs (in-game per-account cap). */
  async list(): Promise<DiscRead[]> {
    const { data, error } = await this.api.GET('/api/v1/discs', {
      params: { query: { limit: 3000 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    return data.items;
  }

  /**
   * POST /api/v1/discs/import — returns counts + per-disc skip reasons.
   *
   * Accepts both ZOD and eZOD payloads (the backend dispatches on the
   * ``format`` field). ``buildConflict`` only applies to eZOD, and only under
   * ``buildMode === 'merge'`` — a clean leaves no build to conflict with.
   * ``buildMode`` is ignored for ZOD payloads, which carry no builds.
   *
   * Omitted modes fall back to the backend's ``merge`` default.
   */
  async importZod(
    payload: unknown,
    buildConflict?: 'skip' | 'overwrite',
    discMode?: ImportMode,
    buildMode?: ImportMode,
  ): Promise<DiscImportResponse> {
    const { data, error } = await this.api.POST('/api/v1/discs/import', {
      // openapi-fetch drops undefined values, so an all-default call still
      // sends a bare URL with no query string.
      params: {
        query: {
          build_conflict: buildConflict,
          disc_mode: discMode,
          build_mode: buildMode,
        },
      },
      // openapi-typescript types this as ``Record<string, never>`` because
      // the backend declares ``body: dict``; cast through to send the raw
      // ZOD/eZOD JSON payload through.
      body: payload as Record<string, never>,
    });
    if (error) throw new Error(JSON.stringify(error));
    return data;
  }
}
