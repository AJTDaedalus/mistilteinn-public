import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import { run as runConfig } from '../../sim/gcsim';
import { loadGcsim } from '../../sim/gcsim-loader';
import { rank, type RankedCandidate, type Ranking } from '../../sim/weapon-ranking';

export interface CandidateConfig {
  weapon_id: string;
  name: string;
  config: string;
}

export interface RefusedCandidate {
  weapon_id: string;
  reason: string;
}

export interface ComparisonConfigs {
  equipped: CandidateConfig | null;
  candidates: CandidateConfig[];
  refused: RefusedCandidate[];
  iterations: number;
}

/** How far along a comparison is, in configs rather than iterations. */
export interface Progress {
  done: number;
  total: number;
  /** The candidate currently simulating, for a label that is not just a percentage. */
  current: string;
}

/**
 * The gcsim weapon tier: fetch configs, simulate them here, rank with separability.
 *
 * **The server emits configs and never simulates.** `RESEARCH_gcsim_embed.md` §6 put gcsim in
 * the browser, and W.4 measured a full sword pool at ~96 s across four workers — a job on the
 * user's machine, not a request a server holds open.
 *
 * **Serial, deliberately, for now.** W.4's pool measurement was taken in Node, where peak RSS
 * per instance was near 1 GB; browsers cap per-tab memory more aggressively and the honest
 * reading of that table is *"4 is the ceiling worth trying"*, not *"4 works"*. Shipping a
 * pool on a Node measurement would be assuming what W.4 explicitly declined to conclude.
 */
@Injectable({ providedIn: 'root' })
export class CompareService {
  private api = injectApi();

  async configs(
    buildId: string,
    rotationId: string,
    weaponIds: string[],
    iterations: number,
    enemyId: string | null,
  ): Promise<ComparisonConfigs> {
    const { data, error } = await this.api.POST(
      '/api/v1/builds/{build_id}/compare-weapons/gcsim',
      {
        params: { path: { build_id: buildId } },
        body: {
          rotation_id: rotationId,
          weapon_ids: weaponIds,
          iterations,
          enemy_id: enemyId,
        },
      },
    );
    if (error) throw error;
    return data as ComparisonConfigs;
  }

  /**
   * Simulate every config and rank the results.
   *
   * The **equipped** weapon is simulated alongside the candidates and ranked with them, so a
   * user can see that nothing beats what they already wear — which is a result, and one a
   * list of candidates alone cannot express.
   */
  async simulate(
    configs: ComparisonConfigs,
    onProgress: (progress: Progress) => void,
  ): Promise<Ranking> {
    const mod = await loadGcsim();
    const all = configs.equipped
      ? [configs.equipped, ...configs.candidates]
      : configs.candidates;

    const ranked: RankedCandidate[] = [];
    for (const [index, entry] of all.entries()) {
      onProgress({ done: index, total: all.length, current: entry.name });
      const result = runConfig(mod, entry.config, configs.iterations);
      ranked.push({
        weaponId: entry.weapon_id,
        name: entry.name,
        // A config gcsim ran but reported no DPS for is *not* a zero-DPS weapon. It is
        // ranked last either way, but zero would present a missing measurement as a finding.
        dpsMean: result.dps?.mean ?? Number.NaN,
        dpsSd: result.dps?.sd ?? Number.NaN,
        iterations: result.iterations,
      });
      // Yield to the event loop so the progress bar actually paints between configs. Without
      // this the page freezes for the whole run and looks hung rather than busy.
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    onProgress({ done: all.length, total: all.length, current: '' });
    return rank(ranked.filter((c) => Number.isFinite(c.dpsMean)));
  }
}
