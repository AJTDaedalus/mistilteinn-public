import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type RotationRead = components['schemas']['RotationRead'];
export type LibraryRotationRead = components['schemas']['LibraryRotationRead'];
export type Visibility = RotationRead['visibility'];
export type ContextKeyRead = components['schemas']['ContextKeyRead'];
export type RotationStep = components['schemas']['RotationStep'];
export type RotationOptions = components['schemas']['RotationOptions'];
export type TeamRoster = components['schemas']['TeamRoster'];
export type RosterCharacter = components['schemas']['RosterCharacter'];
/** One move a particular character can be given — the per-character vocabulary (T.3). */
export type ActionOffer = components['schemas']['ActionOffer'];

/** The action a step may name — the ten the backend publishes, not a list restated here. */
export type RotationAction = RotationStep['action'];

/**
 * Reads and writes of user-authored rotations — R.4's endpoints.
 *
 * Every type is generated from the committed `openapi.json`, so nothing here describes the
 * API by hand. That matters more than usual for `RotationAction`: a hand-written union would
 * be a second copy of gcsim's action vocabulary, and the copy that drifted would be the one
 * offering something the backend then refused.
 */
@Injectable({ providedIn: 'root' })
export class RotationsService {
  private api = injectApi();

  /** Everything the editor may offer: the actions, and the caller's teams with rosters. */
  async options(): Promise<RotationOptions> {
    const { data, error } = await this.api.GET('/api/v1/rotations/options');
    if (error) throw new Error('Could not load rotation options');
    return data;
  }

  async list(teamId?: string) {
    const { data, error } = await this.api.GET('/api/v1/rotations', {
      params: { query: teamId ? { team_id: teamId } : {} },
    });
    if (error) throw new Error('Could not load rotations');
    return data;
  }

  async get(id: string): Promise<RotationRead> {
    const { data, error } = await this.api.GET('/api/v1/rotations/{rotation_id}', {
      params: { path: { rotation_id: id } },
    });
    if (error) throw new Error(`No rotation ${id}`);
    return data;
  }

  /**
   * `description` is sent explicitly because the generated request type requires it.
   *
   * openapi-typescript treats a schema field carrying a `default` as required on the way in
   * — the server would happily fill it, but the contract as published does not say so. Left
   * to each caller, that is a field three call sites remember and the fourth forgets.
   */
  async create(body: {
    name: string;
    team_id: string;
    steps: RotationStep[];
    description?: string;
  }) {
    const { data, error } = await this.api.POST('/api/v1/rotations', {
      body: { ...body, description: body.description ?? '' },
    });
    if (error) throw error;
    return data;
  }

  /**
   * Steps are sent whole, never per index.
   *
   * The API replaces them wholesale for the reason R.4 records: "change step 3" and "insert
   * before step 3" are the same edit from here and different ones to a per-index API.
   */
  async update(
    id: string,
    body: { name?: string; steps?: RotationStep[]; visibility?: Visibility },
  ) {
    const { data, error } = await this.api.PATCH('/api/v1/rotations/{rotation_id}', {
      params: { path: { rotation_id: id } },
      body,
    });
    if (error) throw error;
    return data;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.api.DELETE('/api/v1/rotations/{rotation_id}', {
      params: { path: { rotation_id: id } },
    });
    if (error) throw error;
  }

  /**
   * Published rotations, from every user on this instance.
   *
   * `characters` matches a rotation whose character set is **exactly** those ids. The server
   * says so at length; repeating the reasoning here would be a second place to get it wrong,
   * but the shape is worth knowing at the call site: passing a team's four characters finds
   * rotations *for that team*, not rotations that happen to include them.
   */
  async library(params: { characters?: string[]; q?: string; limit?: number } = {}) {
    const { data, error } = await this.api.GET('/api/v1/rotations/library', {
      params: { query: { ...params, limit: params.limit ?? 50 } },
    });
    if (error) throw new Error('Could not load the rotation library');
    return data;
  }

  /** Like or un-like. Both are idempotent server-side, so a double click is not an error. */
  async setLiked(id: string, liked: boolean): Promise<void> {
    const call = liked ? this.api.POST : this.api.DELETE;
    const { error } = await call('/api/v1/rotations/{rotation_id}/like', {
      params: { path: { rotation_id: id } },
    });
    if (error) throw error;
  }

  /**
   * Copy a published rotation onto one of your own teams.
   *
   * Refuses, naming the character, when the team does not field one of them. The refusal is
   * surfaced verbatim — it names what is missing, which is more useful than anything a page
   * could invent.
   */
  async copy(id: string, teamId: string): Promise<RotationRead> {
    const { data, error } = await this.api.POST('/api/v1/rotations/{rotation_id}/copy', {
      params: { path: { rotation_id: id } },
      body: { team_id: teamId },
    });
    if (error) throw error;
    return data;
  }

  /**
   * The cache key for this rotation on one build, and the parts it was hashed from.
   *
   * `rotation_signature` comes back pre-hashed so no client computes that digest a second
   * way — two implementations of it would not disagree loudly, they would make every cached
   * run unattributable and leave nothing in a log to find.
   */
  async contextKey(id: string, buildId: string): Promise<ContextKeyRead> {
    const { data, error } = await this.api.POST(
      '/api/v1/rotations/{rotation_id}/context-key',
      { params: { path: { rotation_id: id } }, body: { build_id: buildId } },
    );
    if (error) throw error;
    return data;
  }

  /**
   * What these steps would compile to, without saving them.
   *
   * `compile()` reads the **stored** rotation, so a live preview of unsaved work needs this:
   * the alternative is a second compiler in TypeScript, and the readiness gates it would have
   * to reimplement are exactly what stop gcsim's two silent failures.
   */
  /**
   * `runnable` asks for a config gcsim can actually run, rather than the action block.
   *
   * The block is what an author reads — the loop and the gates — and it is **not** a config:
   * no `options`, no character, no weapon, no target. "Run once" needs the whole thing, and
   * the server assembles it with the same `build_config` the weapon comparison uses.
   */
  async preview(
    teamId: string, steps: RotationStep[], runnable = false,
  ): Promise<string> {
    const { data, error } = await this.api.POST('/api/v1/rotations/preview', {
      body: { team_id: teamId, steps, runnable },
    });
    if (error) throw error;
    return (data as { config: string }).config;
  }

  /**
   * Read a gcsim config back into steps — a **preview**, which saves nothing.
   *
   * The server refuses rather than guesses: a config using conditionals, `wait`, or a loop
   * that is not `while 1` comes back 422 naming every line it could not express, because
   * dropping an `if .noelle.energy > 40` would leave a rotation that looks like the author's
   * and simulates to a number they never published. `rotation_parser.py` is written at length
   * about why that refusal is the feature.
   *
   * `rewrites` is the other half: what the converter *did* change, in words, so a `for`
   * becoming a `while 1` is met here rather than in a damage number.
   */
  async importFromGcsim(
    teamId: string, config: string,
  ): Promise<{ steps: RotationStep[]; rewrites: string[] }> {
    const { data, error } = await this.api.POST('/api/v1/rotations/import', {
      body: { team_id: teamId, config },
    });
    if (error) throw error;
    const read = data as { steps: RotationStep[]; rewrites?: string[] };
    return { steps: read.steps, rewrites: read.rewrites ?? [] };
  }

  /** The gcsim config this rotation becomes — so a user can see what they authored. */
  async compile(id: string): Promise<string> {
    const { data, error } = await this.api.POST('/api/v1/rotations/{rotation_id}/compile', {
      params: { path: { rotation_id: id } },
    });
    if (error) throw error;
    return (data as { config: string }).config;
  }
}
