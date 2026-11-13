import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type ExplainResponse = components['schemas']['ExplainResponse'];
export type AvailableHit = components['schemas']['AvailableHitRead'];
export type RefusedHit = components['schemas']['RefusedHitRead'];
export type StatAccount = components['schemas']['StatAccountRead'];
export type HitSpec = components['schemas']['HitSpec'];

/**
 * Why a build scores what it scores.
 *
 * `/explain` returns the derivation, not just a total: every stat with the parts that summed
 * to it and where each came from. Nothing here recomputes anything — a second implementation
 * of the chain would be free to disagree with the first (DESIGN §1 A6), which is the same
 * reason the endpoint refuses to accept contributions in its body.
 */
@Injectable({ providedIn: 'root' })
export class ExplainService {
  private api = injectApi();

  /** The hits this build can be asked about, at its own talent levels (M.2). */
  async hits(buildId: string): Promise<AvailableHit[]> {
    const { data, error } = await this.api.GET('/api/v1/builds/{build_id}/hits', {
      params: { path: { build_id: buildId } },
    });
    if (error) throw new Error('Could not load this build’s talents');
    return data;
  }

  /**
   * The damage rows this build has that cannot be scored, each with the parser's reason.
   *
   * Owner, 2026-11-13: they must not vanish from the hit pickers. Shown greyed out, never
   * offered — `/hits` stays the list of things `/explain` accepts. **Best effort**: a failure
   * here leaves the picker as it was rather than failing the page over an annotation.
   */
  async refusedHits(buildId: string): Promise<RefusedHit[]> {
    const { data, error } = await this.api.GET('/api/v1/builds/{build_id}/hits/refused', {
      params: { path: { build_id: buildId } },
    });
    if (error) return [];
    return data;
  }

  /**
   * Score one hit.
   *
   * The talent is **named**, never a multiplier typed here: M.2 resolves it from the build's
   * own character at its own talent level, and a number entered on this page would be a
   * second source for something the server already knows.
   */
  async explain(
    buildId: string,
    hit: { talent: AvailableHit['talent']; label: string; index: number },
    channel: string,
    scope: string,
    enemyLevel: number,
    /** The five to explain. Omit to explain what is currently equipped. */
    artifactIds?: readonly string[],
  ): Promise<ExplainResponse> {
    const { data, error } = await this.api.POST('/api/v1/builds/{build_id}/explain', {
      params: { path: { build_id: buildId } },
      body: {
        // Every field openapi-typescript marks required because it carries a server default
        // is sent explicitly. `flat_damage` on the hit, `compare_to_equipped` on the request —
        // each reproduces the server's own default, so the request says what it means rather
        // than relying on two sides agreeing silently.
        //
        // **`scaling_stat` is deliberately absent.** It used to be `'atk'` here, and the server
        // took it, so an HP scaler such as Neuvillette was explained off ATK (math-fallback
        // P0). A named talent's own row says what it scales off; the server refuses a value
        // that disagrees.
        hit: {
          channel,
          scope,
          talent: hit,
          flat_damage: 0,
        } as HitSpec,
        // False: this page explains **what is equipped**, and the comparison mode answers a
        // different question — "is this proposed set better" — which needs artifacts to
        // propose. There are none here.
        compare_to_equipped: false,
        // O.4: the optimizer hands back its winner's five, so the server accounts for the
        // same combination the kernel scored. `null` means "what is equipped", which is what
        // the explain page asks for.
        artifact_ids: artifactIds ? [...artifactIds] : null,
        // `resistances` and `default_resistance` carry server defaults, and
        // openapi-typescript marks a field with a default as required on the way in. Sent
        // once here rather than at each call site — the same field-with-a-default trap T.3
        // met with `description`.
        //
        // `{}` and `0.1` reproduce the server's own defaults: no per-channel override, and
        // the ordinary trash-mob 10%. `EnemySpec` documents why those are not the same
        // thing as "unknown".
        enemy: { level: enemyLevel, resistances: {}, default_resistance: 0.1 },
      },
    });
    if (error) throw error;
    return data;
  }
}
