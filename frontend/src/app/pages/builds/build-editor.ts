import {
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { Location } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { BuffTogglesPanel } from './buff-toggles';
import { BuildEditorFormComponent } from './build-editor-form';
import {
  AgentSummary,
  BuildRead,
  BuildsService,
  DiscRead,
  DiscSetRead,
  WEngineSummary,
} from './builds.service';
import { CalculateService, type EnemyProfileRead } from '../calculate/calculate.service';

@Component({
  selector: 'page-build-editor',
  imports: [RouterLink, BuildEditorFormComponent, BuffTogglesPanel],
  templateUrl: './build-editor.html',
  styleUrl: './build-editor.scss',
})
export class BuildEditorPage implements OnInit {
  private svc = inject(BuildsService);
  private calcSvc = inject(CalculateService);
  private route = inject(ActivatedRoute);
  private location = inject(Location);

  // ---- page state ----------------------------------------------------------
  protected buildId = signal<string | null>(null);
  protected dpsBuildRead = signal<BuildRead | null>(null);
  /** Bumped on every successful save so `buff-toggles` refreshes even when `buildId` is unchanged. */
  protected reloadKey = signal(0);

  // ---- reference data ------------------------------------------------------
  protected agents = signal<AgentSummary[]>([]);
  protected wEngines = signal<WEngineSummary[]>([]);
  protected allDiscs = signal<DiscRead[]>([]);
  protected discSets = signal<DiscSetRead[]>([]);
  protected enemies = signal<EnemyProfileRead[]>([]);
  protected defaultEnemyId = computed(() => this.enemies()[0]?.id ?? null);

  // ---- async / status ------------------------------------------------------
  protected loading = signal(true);
  protected error = signal<string | null>(null);

  // ---- derived -------------------------------------------------------------
  protected isCreate = computed(() => this.buildId() === null);

  protected roleToBuildId = computed<Record<string, string | null>>(() => ({
    dps: this.buildId(),
  }));

  protected discsForBuild(bid: string | null): DiscRead[] {
    return this.allDiscs().filter((d) => !d.build_id || d.build_id === bid);
  }

  async ngOnInit() {
    const params = this.route.snapshot.paramMap;
    const id = params.get('id');

    const settled = await Promise.allSettled([
      this.svc.listAgents(),
      this.svc.listWEngines(),
      this.svc.listDiscSets(),
      this.calcSvc.listEnemies(),
    ]);
    const errors: string[] = [];
    if (settled[0].status === 'fulfilled') this.agents.set(settled[0].value as AgentSummary[]);
    else errors.push(`agents: ${(settled[0] as PromiseRejectedResult).reason}`);
    if (settled[1].status === 'fulfilled') this.wEngines.set(settled[1].value as WEngineSummary[]);
    else errors.push(`w-engines: ${(settled[1] as PromiseRejectedResult).reason}`);
    if (settled[2].status === 'fulfilled') this.discSets.set(settled[2].value as DiscSetRead[]);
    else errors.push(`disc sets: ${(settled[2] as PromiseRejectedResult).reason}`);
    if (settled[3].status === 'fulfilled') this.enemies.set(settled[3].value as EnemyProfileRead[]);
    else errors.push(`enemies: ${(settled[3] as PromiseRejectedResult).reason}`);

    try {
      this.allDiscs.set(await this.svc.listDiscs());

      if (id && id !== 'new') {
        const b = await this.svc.get(id);
        this.buildId.set(b.id);
        this.dpsBuildRead.set(b);
      }
    } catch (e) {
      errors.push(e instanceof Error ? e.message : String(e));
    } finally {
      if (errors.length > 0) this.error.set(errors.join(' · '));
      this.loading.set(false);
    }
  }

  // ---- DPS form events -----------------------------------------------------
  protected async onDpsSaved(updated: BuildRead) {
    const wasCreate = !this.buildId();
    this.buildId.set(updated.id);
    this.dpsBuildRead.set(updated);
    this.reloadKey.update((k) => k + 1);
    if (wasCreate) {
      this.location.replaceState(`/builds/${updated.id}`);
    }
  }

  protected async onDpsEquipped(_event: { slot: number; discId: string | null }) {
    this.allDiscs.set(await this.svc.listDiscs());
  }
}
