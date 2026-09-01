import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe, PercentPipe } from '@angular/common';
import { RouterLink } from '@angular/router';

import { BuildsService, type BuildRead } from '../builds/builds.service';
import { RotationsService, type RotationRead, type TeamRoster } from '../rotations/rotations.service';
import { GCSIM_LOADER, runConfig } from '../optimize/recipe-optimize.service';
import { ArtifactsService } from '../artifacts/artifacts.service';
import { CatalogueService } from '../catalogue/catalogue.service';
import { CardPicker, type CardOption } from '../../shared/card-picker/card-picker';
import { CatalogueIcon } from '../../shared/icon/icon';
import {
  energyCost, energyCostMessage, type EnergyCost,
} from '../../sim/energy-delay';
import {
  charactersInConfig, displayNames, parseRotationStats, toPrecision, type RotationStats,
} from '../../sim/rotation-stats';
import { apiErrorMessage } from '../../api/api-error';
import { injectApi } from '../../api/api.client';

/** One character's contribution, and the hits it is made of. */
/**
 * What a rotation actually does, hit by hit.
 *
 * **Renamed from Explain by owner ruling** (`BACKLOG_frontend.md` §8): *"Rename to 'Calculate'.
 * Calculate damage for a rotation, with all of the damage points explainable. … it should start
 * with a team, then a rotation. Unlike Optimize no need to pick a build, the rotation specifies
 * which build does what."*
 *
 * That is a different page, not a different title. The old one explained **one hit** for one
 * build; this runs a whole rotation for a whole team. A rename alone would have promised the
 * second and delivered the first.
 *
 * ## How the number is arrived at
 *
 * gcsim is calibrated **once per character** against the team's rotation, and the resulting
 * recipe is then evaluated at that build's *real* equipped stats. Each recipe hit is one damage
 * point, carrying its own ability, element and terms — so the total is not a figure to take on
 * trust, it is the sum of rows a reader can check.
 *
 * Calibration is the expensive part (~6 s a character); evaluation is 0.048 µs per hit (#159).
 * So this is a job with a button, not something the page does on load.
 */
/**
 * Iterations per run.
 *
 * **100, and the page says so.** gcsim's database pages use 1000; 100 costs about eight
 * seconds in the browser and already gives a standard deviation tight enough to quote — on the
 * owner's team, 192,581 ± 5,732 over 200. `n` is part of the number, not a footnote, which is
 * why it is rendered beside the result rather than hidden here.
 */
const ITERATIONS = 100;

/**
 * The same config, with gcsim told energy is free.
 *
 * `ignore_burst_energy` is a real config option (`pkg/gcs/parser/parseOptions.go`), which is
 * how gcsim's own substat optimizer measures what energy costs — it runs the rotation as if
 * every burst were affordable and compares.
 */
function withFreeEnergy(config: string): string {
  return config.replace(/^options /m, 'options ignore_burst_energy=true ');
}

@Component({
  selector: 'page-calculate',
  imports: [DecimalPipe, PercentPipe, RouterLink, CardPicker, CatalogueIcon],
  templateUrl: './calculate.html',
  styleUrl: './calculate.scss',
})
export class CalculatePage implements OnInit {
  private readonly api = injectApi();
  private readonly rotationsService = inject(RotationsService);
  private readonly buildsService = inject(BuildsService);
  private readonly artifacts = inject(ArtifactsService);
  private readonly catalogue = inject(CatalogueService);
  private readonly loadModule = inject(GCSIM_LOADER);

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly running = signal(false);
  protected readonly progress = signal('');
  /**
   * The gcsim pin a cached recipe is keyed by.
   *
   * Read from `/rotations/{id}/context-key` rather than assumed, because a recipe calibrated
   * at one pin is a different recipe: gcsim's own numbers moved. `/optimize` passes the
   * inventory version here, which is stricter than it needs to be — a calibration replaces
   * the build's artifacts wholesale, so it does not depend on what is equipped.
   */
  private readonly gcsimPin = signal('');

  protected readonly teams = signal<TeamRoster[]>([]);
  protected readonly rotations = signal<RotationRead[]>([]);
  protected readonly builds = signal<BuildRead[]>([]);

  protected readonly teamId = signal('');
  protected readonly rotationId = signal('');

  /**
   * The red line naming who could not burst on time — the owner's wording, gcsim's seconds.
   *
   * **Every character now, not just teammates.** The old path measured this on a calibration
   * that stripped one character's ER to zero; this runs their real gear, so there is no
   * character the number cannot be trusted for.
   */
  protected readonly energyCost = signal<EnergyCost | null>(null);

  /**
   * The red line naming who could not burst on time, and what it costs.
   *
   * Seconds when the rotation waits, missed bursts when it skips — the compiler's `.ready`
   * gates mean this app's own rotations always skip, so a warning built only on seconds is
   * silent exactly where it matters most.
   */
  protected readonly energyDelay = computed(() => {
    const cost = this.energyCost();
    return cost ? energyCostMessage(cost) : null;
  });

  /** gcsim's own report on the last run, or null before one has finished. */
  protected readonly stats = signal<RotationStats | null>(null);

  /** Artifact-set uuid → catalogue id, for turning equipped pieces into a calibration. */
  protected readonly setNanokaIds = signal<Map<string, number>>(new Map());

  protected readonly teamOptions = computed<CardOption[]>(() =>
    this.teams().map((team) => ({
      value: team.id,
      label: team.name,
      // **All four faces, not the first.** `icon` is the singular field; a team has a party,
      // and `CardOption.icons` is what the picker renders as a row — the same shape
      // `shared/team-scope`'s `teamOptions` produces for every other team picker in the app.
      // This showed one character for a team of four.
      icons: team.characters.map((c) => c.icon),
      detail: team.characters.map((c) => c.name).join(', '),
    })),
  );

  /** Only rotations for the chosen team — a rotation is validated against one. */
  protected readonly rotationOptions = computed<CardOption[]>(() =>
    this.rotations()
      .filter((rotation) => rotation.team_id === this.teamId())
      .map((rotation) => ({
        value: rotation.id,
        label: rotation.name,
        detail: `${rotation.steps.length} steps`,
      })),
  );

  /**
   * The headline figures, rounded to what their spread supports.
   *
   * A mean printed to more digits than its standard deviation justifies is a claim the run
   * cannot back — 192,580.52 ± 5,732.01 is eight digits of precision on four of knowledge.
   */
  protected readonly headline = computed(() => {
    const stats = this.stats();
    if (!stats) return null;
    const quote = (spread: { mean: number; sd: number } | null) =>
      spread ? toPrecision(spread.mean, spread.sd) : null;
    return {
      iterations: stats.iterations,
      dps: quote(stats.dps),
      duration: quote(stats.duration),
      eps: quote(stats.eps),
      rps: quote(stats.rps),
      hps: quote(stats.hps),
      shp: quote(stats.shp),
    };
  });

  protected readonly canRun = computed(
    () => !!this.rotationId() && !this.running(),
  );

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [options, rotations, builds, sets] = await Promise.all([
        this.rotationsService.options(),
        this.rotationsService.list(),
        this.buildsService.list(),
        this.catalogue.listArtifactSets({ limit: 200 }),
      ]);
      this.teams.set(options.teams);
      this.rotations.set(rotations.items);
      this.builds.set(builds);
      this.setNanokaIds.set(
        new Map(sets.items.map((set) => [set.id, set.nanoka_id] as const)),
      );
    } catch {
      this.error.set('Could not load your teams and rotations.');
    } finally {
      this.loading.set(false);
    }
  }

  protected pickTeam(id: string): void {
    this.teamId.set(id);
    // A rotation belongs to one team, so the previous choice cannot survive a new team —
    // leaving it selected would run a rotation against a party that never performs it.
    this.rotationId.set('');
    this.stats.set(null);
  }

  /**
   * Run the team's real rotation through gcsim and read what it reports.
   *
   * **Calculate is not a search, so it can run the thing.** It used to calibrate a recipe per
   * character and evaluate it at their gear — the optimizer's machinery, which exists so a
   * search can score thousands of candidates without thousands of runs. One team and one
   * rotation is one run.
   *
   * `POST /rotations/{id}/preview` with `runnable: true` already assembles a config carrying
   * **every character's real gear**, and gcsim's own result object holds every field its
   * results page prints. So this fetches, runs, and reads.
   *
   * What it removes rather than adds: the 1.3 % residual against gcsim — there is no
   * approximation left to be off by — the `mine` filter, per-character 4-piece resolution, and
   * the teammate-versus-optimized asymmetry in the energy warning, since the delay is now
   * measured for everyone from their real gear.
   */
  /** The party's art, by display name — the roster the team picker already loaded. */
  protected iconFor(name: string): string {
    const team = this.teams().find((t) => t.id === this.teamId());
    return team?.characters.find((c) => c.name === name)?.icon ?? '';
  }

  /**
   * One character's share of the team's damage.
   *
   * Summed from the per-character DPS rather than taken from the headline: the two agree, and
   * summing what is on screen means a reader can check the arithmetic themselves.
   */
  protected shareOf(who: { dps: { mean: number } | null }): number {
    const total = (this.stats()?.characters ?? [])
      .reduce((sum, c) => sum + (c.dps?.mean ?? 0), 0);
    return total ? (who.dps?.mean ?? 0) / total : 0;
  }

  /** One source's share of that character's own damage. */
  protected sourceShare(
    who: { bySource: { spread: { mean: number } }[] },
    source: { spread: { mean: number } },
  ): number {
    const total = who.bySource.reduce((sum, s) => sum + s.spread.mean, 0);
    return total ? source.spread.mean / total : 0;
  }

  protected async run(): Promise<void> {
    this.running.set(true);
    this.error.set(null);
    this.stats.set(null);
    this.energyCost.set(null);
    try {
      const rotation = this.rotations().find((r) => r.id === this.rotationId());
      if (!rotation) {
        this.error.set('That rotation could not be found.');
        return;
      }
      this.progress.set('Assembling the config\u2026');
      const config = await this.rotationsService.preview(this.teamId(), rotation.steps, true);

      this.progress.set(`Simulating ${ITERATIONS} iterations\u2026`);
      const mod = await this.loadModule();
      const finished = runConfig(mod, config, ITERATIONS);

      // **From the config, not the roster.** Every per-character array is positional against
      // the order the config declares, which is the subject build then teammates — not the
      // order `/rotations/options` happens to return. Using the roster named Citlali for
      // Furina's missed bursts: a plausible sentence about the wrong character.
      const roster = (this.teams().find((t) => t.id === this.teamId())?.characters ?? [])
        .map((c) => c.name);
      const names = displayNames(charactersInConfig(config), roster);
      this.stats.set(parseRotationStats(finished.raw, names));

      // **A second run with energy free, because a gated rotation hides the shortfall.**
      // The compiler gates every step on `.ready`, so gcsim never attempts a burst it cannot
      // pay for and records no failure — `insufficient_energy` is 0 for a team that is plainly
      // starved. gcsim's own optimizer uses the same counterfactual for the same reason.
      //
      // It doubles the wait, so it runs after the numbers are already on screen.
      this.progress.set('Measuring what energy costs\u2026');
      const free = runConfig(mod, withFreeEnergy(config), ITERATIONS);
      this.energyCost.set(energyCost(finished.raw, free.raw, names));
    } catch (err) {
      this.error.set(apiErrorMessage(err));
    } finally {
      this.running.set(false);
      this.progress.set('');
    }
  }
}
