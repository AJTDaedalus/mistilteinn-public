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

  /**
   * Record — or un-record — that one character has been invited to one set.
   *
   * **Per character per set**, because that is how the reward is given: a set favoured by
   * three characters you own is three invitations and 60 primogems. Idempotent either way.
   */
  async setInvited(suiteId: string, character: string, invited: boolean): Promise<void> {
    const params = {
      params: { path: { suite_id: suiteId, character_nanoka_id: character } },
    };
    const { error } = invited
      ? await this.api.PUT(
          '/api/v1/teapot/suites/{suite_id}/invited/{character_nanoka_id}', params,
        )
      : await this.api.DELETE(
          '/api/v1/teapot/suites/{suite_id}/invited/{character_nanoka_id}', params,
        );
    if (error) throw error;
  }
}
