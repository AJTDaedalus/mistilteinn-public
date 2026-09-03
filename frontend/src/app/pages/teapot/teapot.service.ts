import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type SuiteRow = components['schemas']['SuiteRow'];
export type TeapotRead = components['schemas']['TeapotRead'];

/** The furnishing-set tracker — `DESIGN_account_tracking.md` Track 3. */
@Injectable({ providedIn: 'root' })
export class TeapotService {
  private api = injectApi();

  /** Every set, ranked by how much of it this user can still claim. */
  async suites(): Promise<TeapotRead> {
    const { data, error } = await this.api.GET('/api/v1/teapot/suites');
    if (error) throw error;
    return data as TeapotRead;
  }

  /** Mark a set done, or un-mark it. Idempotent either way. */
  async setDone(suiteId: string, done: boolean): Promise<void> {
    const call = done
      ? this.api.PUT('/api/v1/teapot/suites/{suite_id}/done', {
          params: { path: { suite_id: suiteId } },
        })
      : this.api.DELETE('/api/v1/teapot/suites/{suite_id}/done', {
          params: { path: { suite_id: suiteId } },
        });
    const { error } = await call;
    if (error) throw error;
  }
}
