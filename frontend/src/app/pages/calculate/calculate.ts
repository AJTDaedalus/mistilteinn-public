import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';

import { BuildsService, type BuildRead } from '../builds/builds.service';
import { RotationsService, type RotationRead, type TeamRoster } from '../rotations/rotations.service';
import {
  RecipeOptimizeService,
  type CalibrationResult,
  type CalibrationTarget,
} from '../optimize/recipe-optimize.service';
import { ArtifactsService } from '../artifacts/artifacts.service';
import { CatalogueService } from '../catalogue/catalogue.service';
import { pairKey } from '../../sim/recipe-search';
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
  /** Damage per second over the simulated window — gcsim's headline figure. */
  dps: number;
  /** By ability, biggest first, the way gcsim's results sheet reads. */
  abilities: AbilityLine[];
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
/**
 * The window a rotation is simulated over, in seconds.
 *
 * `build_config`'s own default (`duration: int = 90`), which every calibration this page reads
 * is built with. It is a **second copy of that fact**, so
 * `tests/unit/test_rotation_duration_is_one_number.py` asserts the two agree — a DPS figure
 * divided by the wrong window is wrong in a way nothing on screen would show.
 */
const ROTATION_SECONDS = 90;

/** One ability's share of a character's damage. */
interface AbilityLine {
  ability: string;
  element: string;
  count: number;
  total: number;
  mean: number;
  share: number;
}

/** Group a character's hits by ability, biggest contributor first. */
function byAbility(
  hits: readonly { ability: string; element: string; damage: number }[],
  total: number,
): AbilityLine[] {
  const groups = new Map<string, AbilityLine>();
  for (const hit of hits) {
    const line = groups.get(hit.ability) ?? {
      ability: hit.ability, element: hit.element, count: 0, total: 0, mean: 0, share: 0,
    };
    line.count += 1;
    line.total += hit.damage;
    groups.set(hit.ability, line);
  }
  return [...groups.values()]
    .map((line) => ({
      ...line,
      mean: line.count ? line.total / line.count : 0,
      // `|| 0` rather than a guard above: a character who dealt nothing is a real row, and
      // 0/0 would print NaN% beside their name.
      share: total ? line.total / total : 0,
    }))
    .sort((a, b) => b.total - a.total);
}

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
  private readonly artifacts = inject(ArtifactsService);
  private readonly catalogue = inject(CatalogueService);
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

  /** Characters whose recipe could not be built — named rather than silently dropped. */
  protected readonly skipped = signal<string[]>([]);

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

  protected readonly total = computed(() =>
    (this.result() ?? []).reduce((sum, row) => sum + row.total, 0),
  );

  /** The team's damage per second over the simulated window — gcsim's headline figure. */
  protected readonly dps = computed(() => this.total() / ROTATION_SECONDS);

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

  /**
   * The calibration each character's own gear actually asks for.
   *
   * **A set bonus cannot be added as flat stats.** `Calibration`'s docstring is explicit —
   * every 4-piece is conditional, and equipping it in gcsim is *"the only way it can be
   * modelled"*, with the kernel understating an unequipped one by 15–25 %.
   *
   * Calculate used the baseline for everyone, so a Skirk in four Finale of the Deep Galleries
   * was scored as a Skirk in nothing. Measured against gcsim on the owner's team: the page
   * read **12,497,892** for a rotation that deals **15,737,381** — 20.6 % low, inside the
   * range that docstring predicts.
   */
  private async targetFor(buildId: string): Promise<CalibrationTarget> {
    const pieces = await this.artifacts.list({ build_id: buildId });
    const counts = new Map<string, number>();
    for (const piece of pieces.items) {
      const id = piece.artifact_set_id;
      if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
    }
    const nanokaOf = (uuid: string): number | undefined => this.setNanokaIds().get(uuid);

    const four = [...counts].find(([, n]) => n >= 4);
    if (four) {
      const nanoka = nanokaOf(four[0]);
      if (nanoka !== undefined) return { artifactSetIds: [four[0]], setIds: [nanoka], label: '' };
    }
    // A 2+2 is a real loadout, not a fallback: half this game's supports wear one.
    const pairs = [...counts].filter(([, n]) => n >= 2).slice(0, 2);
    if (pairs.length === 2) {
      const ids = pairs.map(([uuid]) => nanokaOf(uuid));
      if (ids.every((n): n is number => n !== undefined)) {
        return { artifactSetIds: pairs.map(([uuid]) => uuid), setIds: ids, label: '' };
      }
    }
    // Nothing reaches a bonus, so the baseline *is* the honest calibration here.
    return { artifactSetIds: [], setIds: [], label: '' };
  }

  /** Which recipe a target's result lands in. */
  private recipeFor(target: CalibrationTarget, calibrated: CalibrationResult): Recipe | null {
    if (target.setIds.length === 1) return calibrated.byFourPieceSet.get(target.setIds[0]) ?? null;
    if (target.setIds.length === 2) {
      return calibrated.byPair.get(pairKey(target.setIds[0], target.setIds[1])) ?? null;
    }
    return calibrated.noFourPiece;
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
      const skipped: string[] = [];
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
        // **The set this character is actually wearing**, not the baseline. See `targetFor`.
        const target = { ...(await this.targetFor(build.id)), label: who };
        const calibrated = await this.recipes.calibrateAll(
          build.id,
          this.rotationId(),
          this.gcsimPin(),
          [target],
          () => undefined,
        );
        const recipe = this.recipeFor(target, calibrated);
        if (!recipe) {
          // **Named, not skipped.** `continue` dropped a character out of the table and out
          // of the total, so the page under-reported without saying anything was missing.
          skipped.push(who);
          continue;
        }
        const stats = await this.equippedStats(build.id);
        rows.push(this.contribution(build, recipe, stats));
      }
      this.result.set(rows);
      this.skipped.set(skipped);
    } catch (err) {
      this.error.set(apiErrorMessage(err));
    } finally {
      this.running.set(false);
      this.progress.set('');
    }
  }

  /** One character's hits, evaluated at their own gear. */
  private contribution(build: BuildRead, recipe: Recipe, stats: CandidateStats): Contribution {
    // **`mine`, or every character is charged for the whole team.**
    //
    // A recipe carries the *rotation's* hits, not one character's: `hit.mine` marks the ones
    // belonging to the character it was calibrated for. Mapping over all of them gave each row
    // its own damage plus every teammate's at their calibration value, so four rows each
    // reported roughly the team's total and the page summed them.
    //
    // Measured on the owner's Skirk team against gcsim on the same seed: Skirk's row read
    // **15,737,381**, which is the whole team; his own hits are **11,335,604**, which matches
    // gcsim to the digit. The page reported **58,082,172** for a rotation that deals
    // **15,737,381** — 3.7x — and the per-character shares were meaningless because every row
    // held nearly the same number.
    //
    // This is the same omission as #206 in the optimizer, in a second place. `evaluateHit`
    // already refuses to *scale* a teammate's hit; nothing was stopping this from *counting*
    // it.
    const hits = recipe.hits.filter((hit) => hit.mine).map((hit) => ({
      ability: hit.abil,
      element: hit.element,
      damage: evaluateHit(hit, stats),
    }));
    const total = hits.reduce((sum, hit) => sum + hit.damage, 0);
    return {
      buildId: build.id,
      name: build.character?.name ?? 'No character',
      icon: build.character?.icon ?? null,
      total,
      dps: total / ROTATION_SECONDS,
      // **Grouped, the way gcsim's results sheet groups.** A flat list of every hit is more
      // rows and less information: a 90-second rotation produces hundreds, and "which ability
      // is carrying this character" is the question the sheet exists to answer. The individual
      // hits stay underneath, because a total nobody can take apart is a number to trust
      // rather than check.
      abilities: byAbility(hits, total),
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
