import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';

import { apiErrorMessage } from '../../api/api-error';
import type { SuiteRow } from './teapot.service';
import { TeapotService } from './teapot.service';

/**
 * The furnishing-set tracker — `DESIGN_account_tracking.md` Track 3.
 *
 * Owner: *"sortable by remaining primogems and lets users mark off which they've already done
 * like Seelie does."*
 *
 * ## The reward comes from the server, not from here
 *
 * 20 Primogems per character, cited at `app/services/teapot.py` and **published by the API**
 * rather than restated in this file — a second copy would be the one that drifted when a
 * patch changed it. The page still copes with it being absent, because the endpoint is
 * allowed to say it does not know.
 *
 * **The ordering never depended on it.** The reward is one constant per character, so
 * `reward × remaining` and `remaining` rank identically.
 */
@Component({
  selector: 'app-teapot',
  standalone: true,
  imports: [DecimalPipe],
  templateUrl: './teapot.html',
  styleUrl: './teapot.scss',
})
export class TeapotPage {
  private readonly teapot = inject(TeapotService);

  protected readonly rows = signal<SuiteRow[]>([]);
  protected readonly reward = signal<number | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly hideDone = signal(false);
  /** Sets nobody on the user's roster favours — noise for most people, so folded away. */
  protected readonly hideUnreachable = signal(true);
  protected readonly busy = signal<string | null>(null);

  protected readonly visible = computed(() => this.rows().filter((row) => {
    if (this.hideDone() && row.done) return false;
    return !(this.hideUnreachable() && row.owned_favorites.length === 0 && !row.done);
  }));

  protected readonly claimable = computed(
    () => this.rows().reduce((total, row) => total + row.remaining, 0),
  );
  /** Primogems still on the table, or `null` when the server did not publish a reward. */
  protected readonly primogems = computed(() => {
    const reward = this.reward();
    return reward === null ? null : this.claimable() * reward;
  });
  protected readonly finished = computed(() => this.rows().filter((r) => r.done).length);

  async ngOnInit(): Promise<void> {
    await this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const read = await this.teapot.suites();
      this.rows.set(read.suites ?? []);
      this.reward.set(read.reward_per_character ?? null);
    } catch (caught) {
      this.error.set(apiErrorMessage(caught));
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Tick or un-tick a set.
   *
   * **Optimistic, and reverted if the write fails.** Ticking is the page's whole interaction
   * and a round trip per click would make it feel broken; silently keeping a tick the server
   * refused would be worse, so a failure puts the row back and says so.
   */
  protected async toggle(row: SuiteRow): Promise<void> {
    const next = !row.done;
    this.busy.set(row.suite_id);
    this.apply(row.suite_id, next);
    try {
      await this.teapot.setDone(row.suite_id, next);
    } catch (caught) {
      this.apply(row.suite_id, !next);
      this.error.set(apiErrorMessage(caught));
    } finally {
      this.busy.set(null);
    }
  }

  private apply(suiteId: string, done: boolean): void {
    this.rows.update((rows) => rows.map((row) => (
      row.suite_id === suiteId
        ? { ...row, done, remaining: done ? 0 : row.owned_favorites.length }
        : row
    )));
  }

  protected placement(row: SuiteRow): string {
    return row.placement === 'I' ? 'indoor' : row.placement === 'O' ? 'outdoor' : '';
  }
}
