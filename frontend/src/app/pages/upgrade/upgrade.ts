import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { apiErrorMessage } from '../../api/api-error';
import { buildsInTeam } from '../../shared/team-scope';
import { type ResinEstimate } from '../../sim/resin-to-upgrade';
import { EstimateCancelled } from '../../sim/upgrade-estimate';
import { BuildsService, type BuildRead } from '../builds/builds.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService, type TeamRead } from '../teams/teams.service';
import { ArtifactsService } from '../artifacts/artifacts.service';
import { ArtifactsContextService } from '../artifacts/artifacts-context.service';
import {
  ArtifactRankingService,
  type UpgradeResult,
  type UpgradeSlotRow,
} from '../artifacts/artifact-ranking.service';
import { OptimizeService } from '../optimize/optimize.service';
import { type CalibrationProgress } from '../optimize/recipe-optimize.service';

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
  imports: [FormsModule],
  templateUrl: './upgrade.html',
  styleUrl: './upgrade.scss',
})
export class UpgradePage implements OnInit, OnDestroy {
  private readonly buildsService = inject(BuildsService);
  private readonly rotationsService = inject(RotationsService);
  private readonly teamsService = inject(TeamsService);
  private readonly artifactsService = inject(ArtifactsService);
  private readonly optimize = inject(OptimizeService);
  private readonly ranking = inject(ArtifactRankingService);
  private readonly context = inject(ArtifactsContextService);

  protected readonly rotationId = this.context.rotationId;
  protected readonly buildId = this.context.buildId;
  /** Minimum meaningful gain, in percent. */
  protected readonly gainPercent = signal(1);

  private readonly allBuilds = signal<BuildRead[]>([]);
  private readonly teams = signal<TeamRead[]>([]);
  private readonly rotationTeam = signal<Map<string, string>>(new Map());
  protected readonly rotationChoices = signal<{ id: string; label: string }[]>([]);

  /** The same scoping Rank uses: only the chosen rotation's team can be asked about. */
  protected readonly buildChoices = computed(() => {
    const teamId = this.rotationTeam().get(this.rotationId());
    const team = this.teams().find((t) => t.id === teamId) ?? null;
    if (!teamId || !team) return [];
    return buildsInTeam(team, this.allBuilds()).map((build) => ({
      id: build.id,
      label: build.character?.name || 'No character',
      detail: `C${build.constellation_level} · `
        + `${build.weapon_display || build.weapon?.name || 'no weapon'}`,
    }));
  });

  protected readonly progress = signal<CalibrationProgress | null>(null);
  protected readonly running = signal(false);
  protected readonly error = signal('');
  protected readonly rows = signal<UpgradeSlotRow[]>([]);
  protected readonly result = signal<UpgradeResult | null>(null);

  protected readonly slotNames = signal<Record<string, string>>({});
  protected readonly statNames = signal<Record<string, string>>({});
  protected readonly setNames = signal<Map<number, string>>(new Map());

  protected readonly canRun = computed(
    () => !!this.buildId() && !!this.rotationId() && !this.running()
      && this.gainPercent() >= 0,
  );

  private cancelled = false;

  ngOnInit(): void {
    void this.loadChoices();
  }

  ngOnDestroy(): void {
    this.cancelled = true;
  }

  private async loadChoices(): Promise<void> {
    try {
      const [builds, rotations, teams, options, sets] = await Promise.all([
        this.buildsService.list(),
        this.rotationsService.list(),
        this.teamsService.list(),
        this.artifactsService.options(),
        this.optimize.artifactSets(),
      ]);
      this.allBuilds.set(builds);
      this.teams.set(teams);
      this.rotationTeam.set(new Map(rotations.items.map((r) => [r.id, r.team_id])));
      this.rotationChoices.set(rotations.items.map((r) => ({ id: r.id, label: r.name })));
      this.slotNames.set(Object.fromEntries(options.slots.map((s) => [s.key, s.display])));
      this.statNames.set(Object.fromEntries(options.stats.map((s) => [s.key, s.display])));
      this.setNames.set(new Map([...sets].map(([id, set]) => [id, set.name])));
    } catch (err) {
      this.error.set(apiErrorMessage(err));
    }
  }

  /** Choosing a rotation re-scopes the builds, so a stale choice must not survive it. */
  protected chooseRotation(id: string): void {
    this.rotationId.set(id);
    if (!this.buildChoices().some((choice) => choice.id === this.buildId())) {
      this.buildId.set('');
    }
  }

  protected async run(): Promise<void> {
    if (!this.canRun()) return;
    this.cancelled = false;
    this.running.set(true);
    this.error.set('');
    this.rows.set([]);
    this.result.set(null);
    this.progress.set({ done: 0, total: 1, current: 'starting', loading: true });
    try {
      const result = await this.ranking.upgradeEstimate({
        buildId: this.buildId(),
        rotationId: this.rotationId(),
        gain: this.gainPercent() / 100,
        onProgress: (p) => this.progress.set(p),
        onSlot: (row) => {
          this.progress.set(null);
          this.rows.update((rows) => [...rows, row]);
        },
        shouldCancel: () => this.cancelled,
      });
      this.result.set(result);
    } catch (err) {
      if (!(err instanceof EstimateCancelled)) this.error.set(apiErrorMessage(err));
    } finally {
      this.running.set(false);
      this.progress.set(null);
    }
  }

  /**
   * Read on `change`, not per keystroke, and an emptied box keeps the last value: `Number('')`
   * is 0, and a cleared field silently becoming "any gain counts" would change every answer.
   */
  protected setGain(raw: string): void {
    if (raw.trim() === '') return;
    const value = Number(raw);
    if (Number.isFinite(value) && value >= 0) this.gainPercent.set(value);
  }

  protected cancel(): void {
    this.cancelled = true;
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
