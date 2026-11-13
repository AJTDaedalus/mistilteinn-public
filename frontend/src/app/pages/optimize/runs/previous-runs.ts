import { Component, OnInit, computed, inject, input, output, signal } from '@angular/core';

import type { OptimizationRunSummary, Visibility } from './optimization-runs.service';
import { OptimizationRunsService } from './optimization-runs.service';

/**
 * The saved runs a user arrives to, before they start anything.
 *
 * `DESIGN_account_tracking.md` Track 2. Owner: *"see a list of previous runs when first going
 * to the optimization page"* — so this is a **glance**, not an archive: enough to recognise a
 * run and re-open it, with the filters that narrow a long list.
 *
 * **Never sorted by score.** A score is a damage number for one character against one enemy,
 * so ordering two runs for different characters by it would invent a comparison the data does
 * not support. The backend refuses to do it and this does not ask.
 */
@Component({
  selector: 'app-previous-runs',
  standalone: true,
  templateUrl: './previous-runs.html',
  styleUrl: './previous-runs.scss',
})
export class PreviousRuns implements OnInit {
  /** Narrow to one character, when the page already knows which build is being optimised. */
  readonly characterId = input<string | null>(null);

  readonly opened = output<string>();

  private readonly runs = inject(OptimizationRunsService);

  protected readonly rows = signal<OptimizationRunSummary[]>([]);
  protected readonly loading = signal(false);
  protected readonly failed = signal(false);
  /** `mine` or `published` — the two lists the owner asked for. */
  protected readonly scope = signal<'mine' | 'published'>('mine');
  protected readonly onlyThisCharacter = signal(false);

  protected readonly empty = computed(
    () => !this.loading() && !this.failed() && this.rows().length === 0,
  );

  async ngOnInit(): Promise<void> {
    await this.load();
  }

  protected async setScope(scope: 'mine' | 'published'): Promise<void> {
    this.scope.set(scope);
    await this.load();
  }

  protected async toggleCharacter(): Promise<void> {
    this.onlyThisCharacter.update((on) => !on);
    await this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.failed.set(false);
    const filters = this.onlyThisCharacter() && this.characterId()
      ? { character_id: this.characterId() as string }
      : {};
    try {
      this.rows.set(
        this.scope() === 'mine'
          ? await this.runs.mine(filters)
          : await this.runs.published(filters),
      );
    } catch {
      // **Failing to list past runs must not stop a new search.** This panel sits above the
      // optimizer, and a dead list that blocked the page would make a convenience into an
      // outage.
      this.failed.set(true);
      this.rows.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  /** A saved formula estimate is labelled as one in the list, never read as a sim run. */
  protected isFormula(row: OptimizationRunSummary): boolean {
    return (row.summary as { formula_estimate?: boolean })?.formula_estimate === true;
  }

  protected energyModel(row: OptimizationRunSummary): string {
    return (row.summary as { energy_model?: string })?.energy_model ?? '';
  }

  protected shared(visibility: Visibility): boolean {
    return visibility === 'published';
  }

  /** `1,376,712` — a score is read, not compared, so it is formatted for reading. */
  protected score(value: number): string {
    return Math.round(value).toLocaleString();
  }

  /** `+3.1 %`, or nothing when there was no runner-up to be ahead of. */
  protected margin(value: number | null | undefined): string {
    return value === null || value === undefined ? '' : `+${(value * 100).toFixed(1)}%`;
  }
}
