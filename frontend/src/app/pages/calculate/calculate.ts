import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';

import { BuildsService, type BuildRead } from '../builds/builds.service';
import { RotationsService, type RotationRead, type TeamRoster } from '../rotations/rotations.service';
import { RecipeOptimizeService } from '../optimize/recipe-optimize.service';
import { CardPicker, type CardOption } from '../../shared/card-picker/card-picker';
import { CatalogueIcon } from '../../shared/icon/icon';
import { evaluateHit, type CandidateStats, NO_STATS } from '../../sim/recipe-eval';
import type { Recipe } from '../../sim/recipe';
import { apiErrorMessage } from '../../api/api-error';
import { injectApi } from '../../api/api.client';

/** One character's contribution, and the hits it is made of. */
interface Contribution {
  buildId: string;
  name: string;
  icon: string | null;
  total: number;
  hits: { ability: string; element: string; damage: number }[];
}

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
@Component({
  selector: 'page-calculate',
  imports: [DecimalPipe, RouterLink, CardPicker, CatalogueIcon],
  templateUrl: './calculate.html',
  styleUrl: './calculate.scss',
})
export class CalculatePage implements OnInit {
  private readonly api = injectApi();
  private readonly rotationsService = inject(RotationsService);
  private readonly buildsService = inject(BuildsService);
  private readonly recipes = inject(RecipeOptimizeService);

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
  protected readonly result = signal<Contribution[] | null>(null);

  protected readonly teamOptions = computed<CardOption[]>(() =>
    this.teams().map((team) => ({
      value: team.id,
      label: team.name,
      icon: team.characters[0]?.icon ?? null,
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

  protected readonly total = computed(() =>
    (this.result() ?? []).reduce((sum, row) => sum + row.total, 0),
  );

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
      const [options, rotations, builds] = await Promise.all([
        this.rotationsService.options(),
        this.rotationsService.list(),
        this.buildsService.list(),
      ]);
      this.teams.set(options.teams);
      this.rotations.set(rotations.items);
      this.builds.set(builds);
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
    this.result.set(null);
  }

  /** The pin the recipes will be keyed by, from the server rather than guessed. */
  private async readPin(buildId: string): Promise<void> {
    const { data, error } = await this.api.POST(
      '/api/v1/rotations/{rotation_id}/context-key',
      {
        params: { path: { rotation_id: this.rotationId() } },
        body: { build_id: buildId },
      },
    );
    if (error) throw new Error('Could not read the gcsim pin');
    this.gcsimPin.set(data.gcsim_pin);
  }

  /** The builds on the chosen team, in slot order. */
  private teamBuilds(): BuildRead[] {
    const team = this.teams().find((t) => t.id === this.teamId());
    if (!team) return [];
    const wanted = new Set(team.characters.map((c) => c.nanoka_id));
    return this.builds().filter((b) => wanted.has(b.character?.nanoka_id ?? ''));
  }

  protected async run(): Promise<void> {
    this.running.set(true);
    this.error.set(null);
    this.result.set(null);
    try {
      const rows: Contribution[] = [];
      const builds = this.teamBuilds();
      if (!builds.length) {
        this.error.set('That team has no builds to calculate.');
        return;
      }
      await this.readPin(builds[0].id);
      for (const [index, build] of builds.entries()) {
        const who = build.character?.name ?? 'someone';
        this.progress.set(`Calibrating ${who} (${index + 1} of ${builds.length})…`);

        // **One target, the baseline.** A 4-piece recipe answers "what if this build wore
        // that set"; here the build's own gear is the question, so the reference calibration
        // is the right one and the equipped stats supply the rest.
        const calibrated = await this.recipes.calibrateAll(
          build.id,
          this.rotationId(),
          this.gcsimPin(),
          [{ artifactSetIds: [], setIds: [], label: who }],
          () => undefined,
        );
        const recipe = calibrated.noFourPiece;
        if (!recipe) continue;
        const stats = await this.equippedStats(build.id);
        rows.push(this.contribution(build, recipe, stats));
      }
      this.result.set(rows);
    } catch (err) {
      this.error.set(apiErrorMessage(err));
    } finally {
      this.running.set(false);
      this.progress.set('');
    }
  }

  /** One character's hits, evaluated at their own gear. */
  private contribution(build: BuildRead, recipe: Recipe, stats: CandidateStats): Contribution {
    const hits = recipe.hits.map((hit) => ({
      ability: hit.abil,
      element: hit.element,
      damage: evaluateHit(hit, stats),
    }));
    return {
      buildId: build.id,
      name: build.character?.name ?? 'No character',
      icon: build.character?.icon ?? null,
      total: hits.reduce((sum, hit) => sum + hit.damage, 0),
      hits,
    };
  }

  /**
   * The build's equipped gear, in the kernel's quantities.
   *
   * From the server, because the `FIGHT_PROP` → quantity translation lives there and a
   * client-side copy would be a second definition of what every stat means — with a silent
   * failure mode, since a mis-mapped substat produces a plausible number for the wrong stat.
   */
  private async equippedStats(buildId: string): Promise<CandidateStats> {
    const { data, error } = await this.api.GET('/api/v1/builds/{build_id}/equipped-stats', {
      params: { path: { build_id: buildId } },
    });
    if (error) throw new Error('Could not read the build’s equipped stats');
    const pool = data.stats;
    const elementBonus: Record<string, number> = {};
    for (const [quantity, value] of Object.entries(pool)) {
      if (quantity.endsWith('_dmg_bonus')) {
        elementBonus[quantity.slice(0, -'_dmg_bonus'.length)] = value;
      }
    }
    return {
      ...NO_STATS,
      atkPercent: pool['atk_pct'] ?? 0,
      atkFlat: pool['flat_atk'] ?? 0,
      hpPercent: pool['hp_pct'] ?? 0,
      hpFlat: pool['flat_hp'] ?? 0,
      defPercent: pool['def_pct'] ?? 0,
      defFlat: pool['flat_def'] ?? 0,
      elementalMastery: pool['elemental_mastery'] ?? 0,
      critRate: pool['crit_rate'] ?? 0,
      critDmg: pool['crit_dmg'] ?? 0,
      elementBonus,
    };
  }
}
