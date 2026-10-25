import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';

import { AuthService } from '../../api/auth.service';
import { buildsInTeam } from '../../shared/team-scope';
import { BuildsService, type BuildRead } from '../builds/builds.service';
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

  /** Every build the account has — also what the Inventory tab's "equipped by" line reads. */
  readonly allBuilds = signal<BuildRead[]>([]);
  private readonly teams = signal<TeamRead[]>([]);
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

  /** True when the current choice is one this account can actually ask about. */
  readonly ready = computed(
    () => this.rotationChoices().some((c) => c.id === this.rotationId())
      && this.buildChoices().some((c) => c.id === this.buildId()),
  );

  constructor() {
    effect(() => {
      this.auth.token();
      untracked(() => this.reset());
    });
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
    this.allBuilds.set([]);
    this.teams.set([]);
    this.rotationTeam.set(new Map());
    this.rotationChoices.set([]);
    this.loaded = null;
  }
}
