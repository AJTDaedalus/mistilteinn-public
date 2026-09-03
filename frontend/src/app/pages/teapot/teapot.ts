import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';

import { apiErrorMessage } from '../../api/api-error';
import type { SuiteRow } from './teapot.service';
import { CatalogueService } from '../catalogue/catalogue.service';
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
  private readonly catalogue = inject(CatalogueService);

  protected readonly rows = signal<SuiteRow[]>([]);
  protected readonly reward = signal<number | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly hideDone = signal(false);
  /** Sets nobody on the user's roster favours — noise for most people, so folded away. */
  protected readonly hideUnreachable = signal(true);
  protected readonly busy = signal<string | null>(null);
  /** nanoka id → name, so a chip reads "Noelle" rather than "10000027". */
  protected readonly names = signal<Map<string, string>>(new Map());

  protected readonly visible = computed(() => this.rows().filter((row) => {
    if (this.hideDone() && row.done) return false;
    // A set nobody you own favours is worth nothing now and might be worth something later —
    // hidden by default because it is noise for most rosters, never dropped.
    const reachable = row.available.length > 0 || row.completed.length > 0;
    return !(this.hideUnreachable() && !reachable);
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
    // **Names are decoration, so they load beside the tracker and never block it.** A failure
    // here leaves chips reading their nanoka id, which is worse than a name and much better
    // than an empty page.
    await Promise.all([this.load(), this.loadNames()]);
  }

  private async loadNames(): Promise<void> {
    try {
      // **200 is the endpoint's maximum**, not a guess: `limit` is bounded at 200 and 500
      // was a 422 this method's own `catch` swallowed, so every chip silently read as a
      // nanoka id. The catalogue holds 150 characters, so one page covers it.
      const page = await this.catalogue.listCharacters({ limit: 200 });
      const rows = (page as { items?: { nanoka_id: string; name: string }[] })?.items ?? [];
      // **The pairs are typed explicitly.** `new Map(rows.map((r) => [a, b]))` infers
      // `string[]` rather than a tuple under the container's Angular compiler, which is
      // stricter than the host `tsc` — CLAUDE.md records this exact trap, and `npm run
      // verify` passing here does not mean the container will build it.
      const pairs: [string, string][] = rows.map((row) => [row.nanoka_id, row.name]);
      this.names.set(new Map(pairs));
    } catch {
      this.names.set(new Map());
    }
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
   * Tick or un-tick **one character on one set**.
   *
   * That is the unit the reward is given in, so it is the unit the page works in: a set
   * favoured by three characters you own is three separate 20-primogem invitations.
   *
   * **Optimistic, and reverted if the write fails.** Ticking is the page's whole interaction
   * and a round trip per click would make it feel broken; silently keeping a tick the server
   * refused would be worse, so a failure puts the row back and says so.
   */
  protected async toggle(row: SuiteRow, character: string): Promise<void> {
    const inviting = row.available.includes(character);
    this.busy.set(`${row.suite_id}/${character}`);
    this.apply(row.suite_id, character, inviting);
    try {
      await this.teapot.setInvited(row.suite_id, character, inviting);
    } catch (caught) {
      this.apply(row.suite_id, character, !inviting);
      this.error.set(apiErrorMessage(caught));
    } finally {
      this.busy.set(null);
    }
  }

  /** Move one character between `available` and `completed`, and re-derive the row. */
  private apply(suiteId: string, character: string, invited: boolean): void {
    this.rows.update((rows) => rows.map((row) => {
      if (row.suite_id !== suiteId) return row;
      const available = invited
        ? row.available.filter((c) => c !== character)
        : [...row.available, character].sort();
      const completed = invited
        ? [...row.completed, character].sort()
        : row.completed.filter((c) => c !== character);
      return {
        ...row,
        available,
        completed,
        remaining: available.length,
        // `done` is derived the same way the server derives it: nothing left to claim.
        done: available.length === 0 && completed.length > 0,
        remaining_primogems: this.reward() === null
          ? null
          : available.length * (this.reward() as number),
      };
    }));
  }

  protected busyWith(row: SuiteRow, character: string): boolean {
    return this.busy() === `${row.suite_id}/${character}`;
  }

  /**
   * A character's display name.
   *
   * Falls back to the nanoka id, which is what the tracker holds. **Not a hard failure**: a
   * suite can favour a character this database has not seeded, and an id is a worse label
   * than a name but a much better one than a blank chip.
   */
  protected characterName(nanokaId: string): string {
    return this.names().get(nanokaId) ?? nanokaId;
  }

  protected placement(row: SuiteRow): string {
    return row.placement === 'I' ? 'indoor' : row.placement === 'O' ? 'outdoor' : '';
  }
}
