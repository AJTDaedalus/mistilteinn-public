import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type DiscSetSummary = components['schemas']['DiscSetSummary'];

@Injectable({ providedIn: 'root' })
export class DiscSetsService {
  private api = injectApi();
  private cache: DiscSetSummary[] | null = null;

  async listSets(): Promise<DiscSetSummary[]> {
    if (this.cache) return this.cache;
    const { data, error } = await this.api.GET('/api/v1/disc-sets', {
      params: { query: { limit: 200 } },
    });
    if (error) throw new Error(JSON.stringify(error));
    const sets = data.items;
    this.cache = sets;
    return sets;
  }
}
