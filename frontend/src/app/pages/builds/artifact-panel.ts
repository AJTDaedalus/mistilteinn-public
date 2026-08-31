import { Component, computed, effect, inject, input, signal } from '@angular/core';

import { apiErrorMessage } from '../../api/api-error';
import { formatStat } from '../../shared/stat-label';
import {
  ArtifactsService,
  type ArtifactOptions,
  type ArtifactRead,
  type ArtifactSlotKey,
} from '../artifacts/artifacts.service';

/** One of the build's five slots, with what fills it and what could. */
export interface PanelSlot {
  key: ArtifactSlotKey;
  display: string;
  equipped: ArtifactRead | null;
  candidates: ArtifactRead[];
}

/**
 * The five artifact slots on a build.
 *
 * **The picker offers only pieces the API would accept.** A.1 refuses a slot that is already
 * filled, naming the holder rather than swapping — so a picker listing equipped pieces would
 * let a user choose one and be told their own choice is invalid. Each slot therefore offers
 * the *unequipped* pieces of that slot, fetched with the server's own filters.
 *
 * Its own component rather than more of `builds.ts`: the build editor is already a form with
 * eight fields, and five slots each with a picker and two actions is a second thing happening
 * in the same file.
 */
@Component({
  selector: 'build-artifact-panel',
  imports: [],
  templateUrl: './artifact-panel.html',
  styleUrl: './artifact-panel.scss',
})
export class ArtifactPanel {
  /** Null while a new build is being composed — nothing can be equipped to a build yet. */
  readonly buildId = input<string | null>(null);

  // **A piece equipped to another build is not offered here.** The API would take it — A.1
  // refuses a filled *target* slot, not a piece with an owner — but moving one silently
  // strips it from the other build, and the user would find that out from a damage number.
  // Taking it off there first is the visible version of the same move.

  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly slots = signal<PanelSlot[]>([]);

  protected readonly hasBuild = computed(() => this.buildId() !== null);

  private readonly service = inject(ArtifactsService);
  private options: ArtifactOptions | null = null;

  constructor() {
    // Reloads whenever the build changes, including from null when one is first saved.
    effect(() => {
      const id = this.buildId();
      void this.load(id);
    });
  }

  protected async equip(artifactId: string): Promise<void> {
    const id = this.buildId();
    // An empty selection is the "Empty" option, which means "leave this alone" rather than
    // "equip nothing" — there is no piece to send.
    if (!id || !artifactId) return;
    await this.act(() => this.service.equip(artifactId, id));
  }

  protected async unequip(slot: PanelSlot): Promise<void> {
    const piece = slot.equipped;
    if (!piece) return;
    await this.act(() => this.service.equip(piece.id, null));
  }

  /** `CRIT DMG 62.2%` — through the published vocabulary, never a table of our own. */
  protected describe(piece: ArtifactRead): string {
    const stat = this.options?.stats.find((s) => s.key === piece.main_stat_type);
    if (!stat) return String(piece.main_stat_type);
    return `${stat.display} ${formatStat(piece.main_stat_value, stat.percentage)}`;
  }

  private async act(action: () => Promise<unknown>): Promise<void> {
    this.error.set(null);
    try {
      await action();
      await this.load(this.buildId());
    } catch (err) {
      // Verbatim: A.1's refusal names the piece already in the slot, which is more use than
      // anything this panel could invent.
      this.error.set(apiErrorMessage(err));
    }
  }

  private async load(buildId: string | null): Promise<void> {
    if (buildId === null) {
      this.slots.set([]);
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    try {
      this.options ??= await this.service.options();
      // Two requests, not six. `build_id` has to be the server's — fetching every equipped
      // piece to find five scales with the whole inventory. Splitting the *spare* pieces by
      // slot does not: the five slot-filtered requests would carry exactly the same rows
      // between them, so doing it here costs nothing and saves four round trips.
      const [equipped, free] = await Promise.all([
        this.service.list({ build_id: buildId }),
        this.service.list({ equipped: false }),
      ]);
      const held = new Map(equipped.items.map((piece) => [piece.slot, piece]));
      this.slots.set(
        this.options.slots.map((slot) => ({
          key: slot.key as ArtifactSlotKey,
          display: slot.display,
          equipped: held.get(slot.key) ?? null,
          candidates: free.items.filter((piece) => piece.slot === slot.key),
        })),
      );
    } catch {
      // Surfaced rather than left as five empty slots, which would read as "you own nothing
      // that fits" — a different and much more discouraging statement.
      this.error.set('Could not load this build’s artifacts.');
      this.slots.set([]);
    } finally {
      this.loading.set(false);
    }
  }
}
