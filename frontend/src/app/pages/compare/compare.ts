import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import { Combobox, type ComboboxOption } from '../../shared/combobox/combobox';
import { CardPicker } from '../../shared/card-picker/card-picker';
import { buildOptions, buildsInTeam, teamOptions } from '../../shared/team-scope';
import { EntityToken } from '../../shared/token/token';
import type { Ranking } from '../../sim/weapon-ranking';
import { BuildsService, type BuildRead } from '../builds/builds.service';
import {
  CatalogueService,
  type WeaponSummary,
} from '../catalogue/catalogue.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService, type TeamRead } from '../teams/teams.service';
import { CompareService, type ComparisonConfigs, type Progress } from './compare.service';

/**
 * Comparing weapons by simulating them — the tier that knows passives.
 *
 * `POST /compare-weapons` ranks on base ATK and the substat, and reports every candidate with
 * a passive as `unmodelled_passives`. That is **not a precision caveat**: 242 of 260 weapons
 * carry a passive and 5 are expressible in the Chunk F chain, so a stat-stick can outrank the
 * weapon whose passive is the entire reason to equip it. This page asks gcsim instead.
 *
 * **It is a job, not a request.** W.4 measured ~4.9 s per config per 100 iterations, so a full
 * sword pool is minutes. Progress is reported per candidate, and the run happens in this
 * browser — the server only emits configs.
 *
 * **The ranking shows what it could not separate.** At 100 iterations the standard error is
 * ~1.2 %, so two weapons three percent apart are indistinguishable; presenting them as first
 * and second would answer a question the run did not resolve. Same rule as `isExact` on the
 * optimizer.
 *
 * **Candidates are picked, not typed.** This page used to take them as a comma-separated
 * string of catalogue ids — the only place in the app that asked for an opaque identifier,
 * on a page whose whole job is comparing things by name. The picker is filtered to what the
 * chosen build's character can actually hold, which is the server's rule (T.1 refuses a
 * mismatched class) and is applied here only to avoid offering what the API will refuse.
 */
@Component({
  selector: 'page-compare',
  imports: [
    FormsModule, RouterLink, DecimalPipe, PercentPipe, CardPicker, Combobox, EntityToken,
  ],
  templateUrl: './compare.html',
  styleUrl: './compare.scss',
})
export class ComparePage implements OnInit {
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);
  protected readonly running = signal(false);

  protected readonly builds = signal<BuildRead[]>([]);
  protected readonly rotations = signal<{ id: string; name: string }[]>([]);
  protected readonly configs = signal<ComparisonConfigs | null>(null);
  protected readonly ranking = signal<Ranking | null>(null);
  protected readonly progress = signal<Progress | null>(null);

  /**
   * A signal, like `buildId`. It was a plain field read inside the `canRun` computed, which
   * Angular cannot invalidate on — so `canRun` only re-evaluated when something else in it
   * changed. Harmless today because the template gates on `rotations().length === 0`, and a
   * stale-disabled button the moment that gate is relaxed.
   */
  protected readonly rotationId = signal('');
  protected iterations = 100;

  /** Every weapon the chosen build's character can hold. Reloaded when the build changes. */
  protected readonly weapons = signal<WeaponSummary[]>([]);
  /** The candidates, in the order they were added. */
  protected readonly chosen = signal<WeaponSummary[]>([]);

  private readonly compare = inject(CompareService);
  private readonly buildsService = inject(BuildsService);
  private readonly rotationsService = inject(RotationsService);
  private readonly catalogue = inject(CatalogueService);
  private readonly teamsService = inject(TeamsService);

  /**
   * Start from a team, then who in it — the same entry point as Optimize (#171).
   *
   * Copied rather than shared, and that is worth naming: three pages now build a team card and
   * narrow a build grid by it, and the fourth is the rotation library. If a fifth appears
   * before then, this belongs in `shared/` rather than in a fourth page.
   */
  protected readonly teams = signal<TeamRead[]>([]);
  protected readonly teamId = signal('');

  protected readonly team = computed(
    () => this.teams().find((t) => t.id === this.teamId()) ?? null,
  );

  protected readonly buildsInScope = computed(
    () => buildsInTeam(this.team(), this.builds()),
  );

  protected readonly teamOptions = computed(() => teamOptions(this.teams(), this.builds()));

  protected readonly buildOptions = computed(() => buildOptions(this.buildsInScope()));

  /** Narrowing the grid without narrowing the selection would keep answering for a character
   *  the user has just filtered away. */
  protected async selectTeam(ids: readonly string[]): Promise<void> {
    this.teamId.set(ids[0] ?? '');
    const inScope = this.buildsInScope();
    if (inScope.some((b) => b.id === this.buildId())) return;
    await this.selectBuild(inScope[0]?.id ?? '');
  }

  protected async pickBuild(ids: readonly string[]): Promise<void> {
    await this.selectBuild(ids[0] ?? '');
  }

  /** A signal, so changing the build can reload the weapon pool it constrains. */
  protected readonly buildId = signal('');

  protected readonly build = computed(
    () => this.builds().find((b) => b.id === this.buildId()) ?? null,
  );

  /** What the picker offers: holdable weapons, minus the ones already chosen. */
  protected readonly weaponOptions = computed<ComboboxOption[]>(() => {
    const taken = new Set(this.chosen().map((w) => w.id));
    return this.weapons()
      .filter((w) => !taken.has(w.id))
      .map((w) => ({
        value: w.id,
        label: w.name,
        detail: `${w.rarity}★`,
        icon: w.icon,
      }));
  });

  /** Ids by weapon, so a row can name what it was not separated from rather than list uuids. */
  protected readonly nameById = computed(() => {
    const rows = this.ranking()?.rows ?? [];
    return new Map(rows.map((r) => [r.weaponId, r.name]));
  });

  protected notSeparatedNames(ids: readonly string[]): string {
    const names = this.nameById();
    return ids.map((id) => names.get(id) ?? id).join(', ');
  }

  /** Art by weapon id, so a result row can show the weapon rather than only name it. */
  protected readonly iconById = computed(
    () => new Map(this.weapons().map((w) => [w.id, w.icon ?? null])),
  );

  protected weaponIcon(id: string): string | null {
    return this.iconById().get(id) ?? null;
  }

  protected add(id: string | null): void {
    if (!id) return;
    const weapon = this.weapons().find((w) => w.id === id);
    // Already-chosen weapons are filtered out of the options, so this only fires on a stale
    // pick — but a duplicate candidate would be simulated twice and ranked against itself.
    if (!weapon || this.chosen().some((w) => w.id === id)) return;
    this.chosen.update((current) => [...current, weapon]);
  }

  protected drop(id: string): void {
    this.chosen.update((current) => current.filter((w) => w.id !== id));
  }

  /**
   * A run needs a build, a rotation and at least one candidate.
   *
   * The old button was enabled whenever a run was not in flight, so pressing it with an
   * empty id list did nothing at all and said nothing about why.
   */
  protected readonly canRun = computed(
    () =>
      !this.running() &&
      this.buildId() !== '' &&
      this.rotationId() !== '' &&
      this.chosen().length > 0,
  );

  /**
   * Load the weapons the chosen build's character can hold.
   *
   * `weapon_type` is passed through verbatim — the source's own spelling — rather than
   * translated here, and the filter narrows the *offer* only. The server is still the
   * authority on what a character may equip.
   */
  protected async selectBuild(id: string): Promise<void> {
    this.buildId.set(id);
    // Candidates belong to the character they were picked for. Carrying them across would
    // hand the API a sword for a claymore user and collect a row of refusals.
    this.chosen.set([]);
    this.weapons.set([]);
    // And so does the result. `run()` clears these for the stated reason that "a stale
    // ranking left up sits under a new build's name and describes weapons from the previous
    // run" — changing the build is the *other* way into exactly that, and the one where it
    // is worse: the `.subject` token at the top re-renders as the new character while the
    // table below still ranks the old one, and its icons vanish as `iconById` rebuilds from
    // a weapon pool that no longer contains them.
    this.ranking.set(null);
    this.configs.set(null);
    this.progress.set(null);
    this.actionError.set(null);
    const type = this.build()?.character?.weapon_type;
    if (!type) return;
    try {
      const page = await this.catalogue.listWeapons({ weapon_type: type, limit: 200 });
      this.weapons.set(page.items);
    } catch {
      this.actionError.set('Could not load the weapons for that character.');
    }
  }

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [builds, rotations, teams] = await Promise.all([
        this.buildsService.list(),
        this.rotationsService.list(),
        // Never fatal: a team narrows a grid, and a page that refused to open because that
        // convenience failed would be worse than one without it.
        this.teamsService.list().catch(() => []),
      ]);
      this.builds.set(builds);
      this.teams.set(teams);
      // `list()` is paginated, so the rotations live under `items`. Reading the response
      // as an array yields `undefined` for `.length` and silently renders an empty picker,
      // which looks exactly like "you have no rotations".
      const items = rotations.items;
      this.rotations.set(items.map((r) => ({ id: r.id, name: r.name })));
      if (items.length > 0) this.rotationId.set(items[0].id);
      if (builds.length > 0) await this.selectBuild(builds[0].id);
    } catch {
      this.error.set('Could not load your builds and rotations.');
    } finally {
      this.loading.set(false);
    }
  }

  protected async run(): Promise<void> {
    const ids = this.chosen().map((w) => w.id);
    if (!this.canRun()) return;
    this.actionError.set(null);
    // A stale ranking belongs to the previous run. Left up while a new one computes, it would
    // sit under a different build's name and describe weapons nobody asked about this time.
    this.ranking.set(null);
    this.configs.set(null);
    this.running.set(true);
    this.progress.set(null);
    try {
      const configs = await this.compare.configs(
        this.buildId(), this.rotationId(), ids, this.iterations, null,
      );
      this.configs.set(configs);
      this.ranking.set(
        await this.compare.simulate(configs, (p) => this.progress.set(p)),
      );
    } catch (err) {
      this.ranking.set(null);
      this.actionError.set(apiErrorMessage(err));
    } finally {
      this.running.set(false);
    }
  }
}
