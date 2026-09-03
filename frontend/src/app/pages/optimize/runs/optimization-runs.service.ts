import { Injectable } from '@angular/core';

import { injectApi } from '../../../api/api.client';
import type { components } from '../../../api/api.types';

export type OptimizationRunSummary = components['schemas']['OptimizationRunSummary'];
export type OptimizationRunRead = components['schemas']['OptimizationRunRead'];
export type Visibility = OptimizationRunSummary['visibility'];

/** Filters the list accepts. Every one is answerable from a row without a second fetch. */
export interface RunFilters {
  character_id?: string;
  rotation_id?: string;
  gcsim_pin?: string;
}

/**
 * Saved optimization runs — `DESIGN_account_tracking.md` Track 2.
 *
 * Owner: *"see a list of previous runs when first going to the optimization page… These
 * should be sharable, like the gcsim database sharing results."*
 */
@Injectable({ providedIn: 'root' })
export class OptimizationRunsService {
  private api = injectApi();

  /** The caller's own runs, newest first. */
  async mine(filters: RunFilters = {}): Promise<OptimizationRunSummary[]> {
    const { data, error } = await this.api.GET('/api/v1/optimization-runs', {
      params: { query: filters },
    });
    if (error) throw error;
    return (data ?? []) as OptimizationRunSummary[];
  }

  /** Everyone's published runs. */
  async published(filters: RunFilters = {}): Promise<OptimizationRunSummary[]> {
    const { data, error } = await this.api.GET('/api/v1/optimization-runs/public', {
      params: { query: filters },
    });
    if (error) throw error;
    return (data ?? []) as OptimizationRunSummary[];
  }

  async read(id: string): Promise<OptimizationRunRead> {
    const { data, error } = await this.api.GET('/api/v1/optimization-runs/{run_id}', {
      params: { path: { run_id: id } },
    });
    if (error) throw error;
    return data as OptimizationRunRead;
  }

  /** A published run by its key — readable without owning it. */
  async shared(shareKey: string): Promise<OptimizationRunRead> {
    const { data, error } = await this.api.GET(
      '/api/v1/optimization-runs/shared/{share_key}',
      { params: { path: { share_key: shareKey } } },
    );
    if (error) throw error;
    return data as OptimizationRunRead;
  }

  /**
   * Save a finished search.
   *
   * The body carries a **snapshot** of what the search ran against, not just ids: a build
   * changes, and a stored result that re-read today's gear would show a number that never
   * happened.
   */
  async save(body: Record<string, unknown>): Promise<OptimizationRunRead> {
    const { data, error } = await this.api.POST('/api/v1/optimization-runs', {
      body: body as never,
    });
    if (error) throw error;
    return data as OptimizationRunRead;
  }

  /** Rename, or publish. The result itself is not editable — see the endpoint. */
  async update(
    id: string, changes: { name?: string; visibility?: Visibility },
  ): Promise<OptimizationRunRead> {
    const { data, error } = await this.api.PATCH('/api/v1/optimization-runs/{run_id}', {
      params: { path: { run_id: id } },
      body: changes as never,
    });
    if (error) throw error;
    return data as OptimizationRunRead;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/optimization-runs/{run_id}', {
      params: { path: { run_id: id } },
    });
    if (error) throw error;
  }
}
