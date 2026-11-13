import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';

import { AuthService } from '../../api/auth.service';
import { buildsInTeam } from '../../shared/team-scope';
import type { ConditionGroup } from '../../sim/formula-calibration';
import { BuildsService, type BuildRead } from '../builds/builds.service';
import {
  ExplainService,
  type AvailableHit,
  type RefusedHit,
} from '../explain/explain.service';
import {
  FormulaEstimateService,
  type FormulaRequest,
} from '../optimize/formula-estimate.service';
import { OptimizeService } from '../optimize/optimize.service';
import { ArtifactsService } from './artifacts.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService, type TeamRead } from '../teams/teams.service';

/**
 * The rotation and build the Artifacts tabs are asking about, and the choices they pick from.
 *
 * `docs/DESIGN_upgrade_estimator.md` §11. Rank and Upgrade ask different questions of the same
 * build, so choosing it twice was the friction the tabs exist to remove — and the first version
 * shared only the *choice* while each page kept its own copy of the loading and team scoping,
 * which is how two pickers come to label or scope builds differently. One copy, here.
 *
 * A root singleton because the tabs are sibling routes, each a fresh component instance, and the
 * choice has to survive switching between them. **It is reset when the signed-in account
 * changes**: a selection outliving its session would offer the next user an Estimate button
 * for ids they do not own.
 *
 * Optimize keeps its own pickers for now (`remembered.ts` persists them across reloads); folding
 * them in is the part of §11 not yet done.
 */
@Injectable({ providedIn: 'root' })
export class ArtifactsContextService {
  private readonly auth = inject(AuthService);
  private readonly builds = inject(BuildsService);
  private readonly rotations = inject(RotationsService);
  private readonly teamsService = inject(TeamsService);

  readonly rotationId = signal('');
  readonly buildId = signal('');

  /**
   * What scores the build: a gcsim calibration of the chosen rotation (the default), or the
   * formula estimate (math-fallback P1, task 8; D-F3 makes it an opt-in for every team). The
   * estimate needs no rotation, so in that mode the picker is a team and a build instead.
   */
  readonly mode = signal<'gcsim' | 'formula'>('gcsim');
  /** The team the formula estimate reads resonance from; empty means the build alone. */
  readonly formulaTeamId = signal('');

  /** Every build the account has — also what the Inventory tab's "equipped by" line reads. */
  readonly allBuilds = signal<BuildRead[]>([]);
  readonly teams = signal<TeamRead[]>([]);
  private readonly rotationTeam = signal<Map<string, string>>(new Map());
  readonly rotationChoices = signal<{ id: string; label: string }[]>([]);
  private loaded: Promise<void> | null = null;

  /**
   * The builds the chosen rotation's team actually fields.
   *
   * Labelled by **character**, with constellation and weapon as the detail — the decision
   * `shared/team-scope.buildOptions` already made for `/optimize` and `/builds`. A build's own
   * `name` is not used: all 84 builds in the local database have an empty one, so a label of
   * `${character} — ${name}` rendered as "Furina —" seventy-five times over.
   */
  readonly buildChoices = computed(() => {
    if (this.mode() === 'formula') return this.formulaBuildChoices();
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

  /** The formula mode's builds: the chosen team's, or every build when none is chosen. */
  private readonly formulaBuildChoices = computed(() => {
    const team = this.teams().find((t) => t.id === this.formulaTeamId()) ?? null;
    return buildsInTeam(team, this.allBuilds()).map((build) => ({
      id: build.id,
      label: build.character?.name || 'No character',
      detail: `C${build.constellation_level} · `
        + `${build.weapon_display || build.weapon?.name || 'no weapon'}`,
    }));
  });

  /** The chosen build, for the formula estimate's element and weapon class. */
  readonly build = computed(
    () => this.allBuilds().find((b) => b.id === this.buildId()) ?? null,
  );

  /**
   * The builds the formula estimate treats as the team: the chosen team when it fields the
   * build, otherwise the build alone.
   */
  readonly formulaTeam = computed(() => {
    const build = this.build();
    if (!build) return [];
    const team = this.teams().find((t) => t.id === this.formulaTeamId()) ?? null;
    const members = team ? buildsInTeam(team, this.allBuilds()) : [];
    return members.some((b) => b.id === build.id) ? members : [build];
  });

  /** True when the current choice is one this account can actually ask about. */
  readonly ready = computed(
    () => (this.mode() === 'formula'
      || this.rotationChoices().some((c) => c.id === this.rotationId()))
      && this.buildChoices().some((c) => c.id === this.buildId()),
  );

  /**
   * Members of the chosen rotation's team gcsim has no key for — the catalogue's `gcsim` block
   * (task 3), so the page can offer the estimate **before** a calibration ends in a 422.
   */
  readonly gcsimBlocked = computed(() => {
    if (this.mode() !== 'gcsim') return [];
    const teamId = this.rotationTeam().get(this.rotationId());
    const team = this.teams().find((t) => t.id === teamId) ?? null;
    if (!team) return [];
    return buildsInTeam(team, this.allBuilds())
      .filter((b) => b.character?.gcsim?.status === 'none')
      .map((b) => b.character?.name ?? 'a member');
  });

  /**
   * "Use the formula estimate" from a gcsim refusal: the same build, scored by formula, with
   * the rotation's team kept as the team resonance is read from.
   */
  useFormulaEstimate(): void {
    this.formulaTeamId.set(this.rotationTeam().get(this.rotationId()) ?? '');
    this.chooseMode('formula');
  }

  /** Switch between gcsim and the formula estimate; a build the new picker lacks is cleared. */
  chooseMode(mode: 'gcsim' | 'formula'): void {
    this.mode.set(mode);
    if (!this.buildChoices().some((choice) => choice.id === this.buildId())) {
      this.buildId.set('');
    }
  }

  /** The formula mode's team. Choosing one re-scopes the builds, like a rotation does. */
  chooseFormulaTeam(id: string): void {
    this.formulaTeamId.set(id);
    if (!this.buildChoices().some((choice) => choice.id === this.buildId())) {
      this.buildId.set('');
    }
  }

  private readonly explain = inject(ExplainService);
  private readonly formula = inject(FormulaEstimateService);
  private readonly optimize = inject(OptimizeService);
  private readonly artifacts = inject(ArtifactsService);

  /** The chosen build's hits, for the formula target's pickers. */
  readonly formulaHits = signal<AvailableHit[]>([]);
  /** Rows the parser refuses — greyed in the pickers with their reasons (owner, 2026-11-13). */
  readonly formulaRefused = signal<RefusedHit[]>([]);
  /** The conditions the assumptions panel draws: the team's resonance and the worn sets. */
  readonly formulaGroups = signal<ConditionGroup[]>([]);

  /**
   * What `ArtifactRankingService` needs to score with the formula estimate, or `null` in gcsim
   * mode. The element is the build's own and the scope follows each row's move
   * (`FormulaEstimateService.estimate`).
   */
  readonly formulaRequest = computed<Omit<FormulaRequest, 'buildId' | 'fourPieceSetIds'> | null>(
    () => {
      const build = this.build();
      if (this.mode() !== 'formula' || !build) return null;
      return {
        build,
        team: this.formulaTeam(),
        channel: (build.character?.element ?? 'physical').toLowerCase(),
        scope: 'normal',
        enemyLevel: 90,
      };
    },
  );

  constructor() {
    effect(() => {
      this.auth.token();
      untracked(() => this.reset());
    });
    // The target's pickers and the panel's conditions follow the build in formula mode.
    effect(() => {
      const id = this.buildId();
      const team = this.formulaTeam();
      if (this.mode() !== 'formula' || !id) {
        this.formulaHits.set([]);
        this.formulaRefused.set([]);
        this.formulaGroups.set([]);
        return;
      }
      untracked(() => void this.loadFormula(id, team));
    });
  }

  private async loadFormula(id: string, team: readonly BuildRead[]): Promise<void> {
    try {
      const [hits, refused] = await Promise.all([
        this.explain.hits(id),
        this.explain.refusedHits?.(id) ?? Promise.resolve([]),
      ]);
      if (this.buildId() !== id) return;
      this.formulaHits.set(hits);
      this.formulaRefused.set(refused);
      this.formula.ensureTarget(id, hits);
      // The sets the build wears two or more of: the conditions a ranking of it starts from.
      const [worn, catalogue] = await Promise.all([
        this.artifacts.list({ build_id: id }),
        this.optimize.artifactSets(),
      ]);
      const byUuid = new Map([...catalogue].map(([nanoka, set]) => [set.id, nanoka]));
      const counts = new Map<number, number>();
      for (const piece of worn.items) {
        const nanoka = piece.artifact_set_id ? byUuid.get(piece.artifact_set_id) : undefined;
        if (nanoka !== undefined) counts.set(nanoka, (counts.get(nanoka) ?? 0) + 1);
      }
      const sets = [...counts].filter(([, n]) => n >= 2).map(([setId]) => setId);
      const groups = await this.formula.groups(team, sets);
      if (this.buildId() === id) this.formulaGroups.set(groups);
    } catch {
      // Best effort: an empty panel leaves the defaults in force, and the estimate's own
      // assumptions list every one of them after a run.
      this.formulaGroups.set([]);
    }
  }

  /**
   * Load the choices once per session; later calls share the same request.
   *
   * **Silent on failure, by design.** A picker that offers nothing leaves the rest of the page
   * working; surfacing this as a page error would make a working inventory look broken.
   */
  load(): Promise<void> {
    this.loaded ??= (async () => {
      try {
        const [builds, rotations, teams] = await Promise.all([
          this.builds.list(),
          this.rotations.list(),
          this.teamsService.list(),
        ]);
        this.allBuilds.set(builds);
        this.teams.set(teams);
        this.rotationTeam.set(new Map(rotations.items.map((r) => [r.id, r.team_id])));
        this.rotationChoices.set(rotations.items.map((r) => ({ id: r.id, label: r.name })));
      } catch {
        this.loaded = null;
      }
    })();
    return this.loaded;
  }

  /** Choosing a rotation re-scopes the builds, so a stale choice must not survive it. */
  chooseRotation(id: string): void {
    this.rotationId.set(id);
    if (!this.buildChoices().some((choice) => choice.id === this.buildId())) {
      this.buildId.set('');
    }
  }

  private reset(): void {
    this.rotationId.set('');
    this.buildId.set('');
    this.mode.set('gcsim');
    this.formulaTeamId.set('');
    this.allBuilds.set([]);
    this.teams.set([]);
    this.rotationTeam.set(new Map());
    this.rotationChoices.set([]);
    this.loaded = null;
  }
}
