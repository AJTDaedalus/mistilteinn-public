import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';

import { apiErrorMessage } from '../../api/api-error';
import { type ResinEstimate } from '../../sim/resin-to-upgrade';
import { EstimateCancelled } from '../../sim/upgrade-estimate';
import { ArtifactsService } from '../artifacts/artifacts.service';
import { ArtifactsContextService } from '../artifacts/artifacts-context.service';
import {
  ArtifactRankingService,
  type UpgradeResult,
  type UpgradeSlotRow,
} from '../artifacts/artifact-ranking.service';
import { OptimizeService } from '../optimize/optimize.service';
import {
  CalibrationCancelled,
  type CalibrationProgress,
} from '../optimize/recipe-optimize.service';

/**
 * `/artifacts/upgrade`: how much domain resin until each slot's piece is beaten.
 *
 * `docs/DESIGN_upgrade_estimator.md`. Per slot: the chance one fresh 5-star drop, fully
 * levelled, beats the build by the chosen gain (1% by default, owner 2026-10-24), and the resin
 * that implies — a distribution, not a point. Standard domain claims only; no Strongbox, no
 * Stygian Onslaught, no levelling cost.
 */
@Component({
  selector: 'app-upgrade',
  imports: [],
  templateUrl: './upgrade.html',
  styleUrl: './upgrade.scss',
})
export class UpgradePage implements OnInit, OnDestroy {
  private readonly artifactsService = inject(ArtifactsService);
  private readonly optimize = inject(OptimizeService);
  private readonly ranking = inject(ArtifactRankingService);
  /** The picker, shared with Rank: choices, scoping and selection. */
  private readonly context = inject(ArtifactsContextService);

  protected readonly rotationId = this.context.rotationId;
  protected readonly buildId = this.context.buildId;
  protected readonly rotationChoices = this.context.rotationChoices;
  protected readonly buildChoices = this.context.buildChoices;
  /** Minimum meaningful gain, in percent. */
  protected readonly gainPercent = signal(1);

  protected readonly progress = signal<CalibrationProgress | null>(null);
  /** Calibration finished and the slots are being estimated — what the status line says. */
  protected readonly estimating = signal(false);
  protected readonly running = signal(false);
  protected readonly error = signal('');
  protected readonly rows = signal<UpgradeSlotRow[]>([]);
  protected readonly result = signal<UpgradeResult | null>(null);

  protected readonly slotNames = signal<Record<string, string>>({});
  protected readonly statNames = signal<Record<string, string>>({});
  protected readonly setNames = signal<Map<number, string>>(new Map());

  /**
   * Only for a choice this account can actually ask about. A selection left over from another
   * session would otherwise be an enabled button that requests someone else's ids.
   */
  protected readonly canRun = computed(
    () => this.context.ready() && !this.running() && this.gainPercent() >= 0,
  );

  private cancelled = false;

  ngOnInit(): void {
    void this.loadChoices();
  }

  ngOnDestroy(): void {
    this.cancelled = true;
  }

  /** The vocabulary for labels. The picker's own choices load through the context service. */
  private async loadChoices(): Promise<void> {
    try {
      const [options, sets] = await Promise.all([
        this.artifactsService.options(),
        this.optimize.artifactSets(),
        this.context.load(),
      ]);
      this.slotNames.set(Object.fromEntries(options.slots.map((s) => [s.key, s.display])));
      this.statNames.set(Object.fromEntries(options.stats.map((s) => [s.key, s.display])));
      this.setNames.set(new Map([...sets].map(([id, set]) => [id, set.name])));
    } catch (err) {
      this.error.set(apiErrorMessage(err));
    }
  }

  protected chooseRotation(id: string): void {
    this.context.chooseRotation(id);
  }

  protected async run(): Promise<void> {
    if (!this.canRun()) return;
    this.cancelled = false;
    this.running.set(true);
    this.error.set('');
    this.rows.set([]);
    this.result.set(null);
    this.estimating.set(false);
    this.progress.set({ done: 0, total: 1, current: 'starting', loading: true });
    try {
      const result = await this.ranking.upgradeEstimate({
        buildId: this.buildId(),
        rotationId: this.rotationId(),
        gain: this.gainPercent() / 100,
        onProgress: (p) => this.progress.set(p),
        onCalibrated: () => {
          this.progress.set(null);
          this.estimating.set(true);
        },
        onSlot: (row) => this.rows.update((rows) => [...rows, row]),
        shouldCancel: () => this.cancelled,
      });
      this.result.set(result);
    } catch (err) {
      const cancelled = err instanceof EstimateCancelled || err instanceof CalibrationCancelled;
      if (!cancelled) this.error.set(apiErrorMessage(err));
    } finally {
      this.running.set(false);
      this.estimating.set(false);
      this.progress.set(null);
    }
  }

  /**
   * Read on `change`, not per keystroke, and an emptied box keeps the last value: `Number('')`
   * is 0, and a cleared field silently becoming "any gain counts" would change every answer.
   */
  protected setGain(input: HTMLInputElement): void {
    const raw = input.value;
    const value = Number(raw);
    if (raw.trim() !== '' && Number.isFinite(value) && value >= 0) {
      this.gainPercent.set(value);
    } else {
      // **Put the used value back in the box.** A rejected entry left on screen reads as the
      // gain the estimate ran with; the box must never show a number nobody is using.
      input.value = String(this.gainPercent());
    }
  }

  protected cancel(): void {
    this.cancelled = true;
  }

  /** `50%`, from the cited set share rather than a word written into the template. */
  protected percent(fraction: number): string {
    return `${Math.round(fraction * 100)}%`;
  }

  protected setName(row: UpgradeSlotRow): string {
    if (row.pieceId === null) return 'Empty slot';
    return row.setId === null ? 'No set' : this.setNames().get(row.setId) ?? `Set ${row.setId}`;
  }

  /** `12,340` — resin is a count, so no unit suffix beyond the column's own heading. */
  protected resin(value: number | null): string {
    return value === null ? '—' : Math.round(value).toLocaleString();
  }

  /** `1 in 2,300`, the sentence a reader can check against their own drops. */
  protected oneIn(estimate: ResinEstimate): string {
    if (estimate.unreachable) return 'never';
    const n = 1 / estimate.perDrop;
    return `1 in ${n < 10 ? n.toFixed(1) : Math.round(n).toLocaleString()}`;
  }

  /** The median under the ±1 weight nudges, as a range. */
  protected spread(row: UpgradeSlotRow): string {
    const { cheap, dear } = row.sensitivity;
    if (cheap.unreachable && dear.unreachable) return '—';
    return `${this.resin(cheap.median)}–${dear.unreachable ? 'never' : this.resin(dear.median)}`;
  }
}
