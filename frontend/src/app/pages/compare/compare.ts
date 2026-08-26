import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import type { Ranking } from '../../sim/weapon-ranking';
import { BuildsService, type BuildRead } from '../builds/builds.service';
import { RotationsService } from '../rotations/rotations.service';
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
 */
@Component({
  selector: 'page-compare',
  imports: [FormsModule, RouterLink, DecimalPipe, PercentPipe],
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

  protected buildId = '';
  protected rotationId = '';
  protected iterations = 100;
  /** Comma-separated catalogue ids. Deliberately plain until a picker exists. */
  protected weaponIds = '';

  private readonly compare = inject(CompareService);
  private readonly buildsService = inject(BuildsService);
  private readonly rotationsService = inject(RotationsService);

  protected readonly build = computed(
    () => this.builds().find((b) => b.id === this.buildId) ?? null,
  );

  /** Ids by weapon, so a row can name what it was not separated from rather than list uuids. */
  protected readonly nameById = computed(() => {
    const rows = this.ranking()?.rows ?? [];
    return new Map(rows.map((r) => [r.weaponId, r.name]));
  });

  protected notSeparatedNames(ids: readonly string[]): string {
    const names = this.nameById();
    return ids.map((id) => names.get(id) ?? id).join(', ');
  }

  /** The candidate ids as typed, cleaned of blanks. */
  protected parsedWeaponIds(): string[] {
    return this.weaponIds.split(',').map((s) => s.trim()).filter(Boolean);
  }

  protected readonly canRun = computed(() => !this.running());

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [builds, rotations] = await Promise.all([
        this.buildsService.list(),
        this.rotationsService.list(),
      ]);
      this.builds.set(builds);
      // `list()` is paginated, so the rotations live under `items`. Reading the response
      // as an array yields `undefined` for `.length` and silently renders an empty picker,
      // which looks exactly like "you have no rotations".
      const items = rotations.items;
      this.rotations.set(items.map((r) => ({ id: r.id, name: r.name })));
      if (builds.length > 0) this.buildId = builds[0].id;
      if (items.length > 0) this.rotationId = items[0].id;
    } catch {
      this.error.set('Could not load your builds and rotations.');
    } finally {
      this.loading.set(false);
    }
  }

  protected async run(): Promise<void> {
    const ids = this.parsedWeaponIds();
    if (!this.buildId || !this.rotationId || ids.length === 0) return;
    this.actionError.set(null);
    // A stale ranking belongs to the previous run. Left up while a new one computes, it would
    // sit under a different build's name and describe weapons nobody asked about this time.
    this.ranking.set(null);
    this.configs.set(null);
    this.running.set(true);
    this.progress.set(null);
    try {
      const configs = await this.compare.configs(
        this.buildId, this.rotationId, ids, this.iterations, null,
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
