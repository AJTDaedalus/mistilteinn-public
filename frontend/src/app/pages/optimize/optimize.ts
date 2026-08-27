import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import { type Amplifying, type ScalingStat } from '../../sim/damage';
import { SLOTS, type SearchResult, type Slot, search } from '../../sim/search';
import { BuildsService, type BuildRead } from '../builds/builds.service';
import { CHANNELS, SCOPES, talentLabel } from '../explain/explain';
import {
  ExplainService,
  type AvailableHit,
  type ExplainResponse,
} from '../explain/explain.service';
import { ArtifactsService } from '../artifacts/artifacts.service';
import { RotationsService } from '../rotations/rotations.service';
import { searchRecipe } from '../../sim/recipe-search';
import {
  RecipeOptimizeService,
  type CalibrationCaveats,
  type CalibrationProgress,
  type CalibrationTarget,
} from './recipe-optimize.service';
import {
  OptimizeService,
  type KernelCandidate,
  type UnreadableArtifact,
} from './optimize.service';

/** One result row, with the pieces named rather than left as ids. */
export interface ResultRow {
  rank: number;
  damage: number;
  artifactIds: string[];
  pieces: string[];
}

/**
 * Describe a build's five pieces from the candidates the search was given.
 *
 * Named from the same candidates the kernel scored, not re-fetched: a second lookup could
 * disagree with what was actually searched, and the row would then describe a build the
 * ranking did not produce.
 */
export function describePieces(
  artifactIds: readonly string[],
  candidates: readonly KernelCandidate[],
  slotName: (slot: string) => string,
): string[] {
  const byId = new Map(candidates.map((c) => [c.id, c]));
  return artifactIds.map((id) => {
    const piece = byId.get(id);
    return piece ? slotName(piece.slot) : id;
  });
}

/**
 * Search a user's own artifacts, in their own browser.
 *
 * `src/app/sim/` has been a verified optimizer that nothing imported — the damage chain
 * pinned against the Python oracle, the search pinned against `artifact_optimizer.optimize`,
 * and four CI gates running all of it as scripts. **This is the page that imports it.**
 *
 * The search runs client-side because `RESEARCH_gcsim_embed.md` §6 settled that: gcsim is
 * ~430× too slow to be an inner loop, so the Chunk F chain stays and a user's inventory is
 * searched on their own machine.
 *
 * **What the result claims is as important as the result.** `isExact` says whether these are
 * the true optimum over the inventory as given; `evaluated` and `paretoRemoved` say how much
 * was actually looked at. A top-10 that is really the top 10 of a pruned subset, shown
 * without saying so, is a confident answer to a question nobody asked — at the scale of a
 * whole feature.
 */
@Component({
  selector: 'page-optimize',
  imports: [FormsModule, RouterLink, DecimalPipe, PercentPipe],
  templateUrl: './optimize.html',
  styleUrl: './optimize.scss',
})
export class OptimizePage implements OnInit {
  protected readonly channels = CHANNELS;
  protected readonly scopes = SCOPES;
  protected readonly talentLabel = talentLabel;

  protected readonly loading = signal(true);
  /** Non-null means the page failed to load. Never rendered as "you have no builds". */
  protected readonly error = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);
  protected readonly searching = signal(false);

  protected readonly builds = signal<BuildRead[]>([]);
  protected readonly hits = signal<AvailableHit[]>([]);
  protected readonly result = signal<SearchResult | null>(null);
  protected readonly candidates = signal<KernelCandidate[]>([]);
  /** Pieces the server could not translate. Shown, never swallowed (OQ-O2). */
  protected readonly unreadable = signal<UnreadableArtifact[]>([]);
  /** True when the inventory itself was capped before the search even began. */
  protected readonly truncated = signal(false);

  /** The explanation of one result row, and which row it belongs to. */
  protected readonly explained = signal<{ rank: number; result: ExplainResponse } | null>(
    null,
  );
  protected readonly explaining = signal(false);

  protected readonly buildId = signal('');
  protected hitIndex = 0;
  protected channel = 'physical';
  protected scope = 'normal';
  protected enemyLevel = 90;

  protected readonly build = computed(
    () => this.builds().find((b) => b.id === this.buildId()) ?? null,
  );
  protected readonly hit = computed(() => this.hits()[this.hitIndex] ?? null);
  protected readonly canSearch = computed(
    () => this.hit() !== null && !this.searching(),
  );

  protected readonly rows = computed<ResultRow[]>(() => {
    const found = this.result();
    if (!found) return [];
    const pieces = this.candidates();
    const names = this.slotNames();
    return found.builds.map((build, index) => ({
      rank: index + 1,
      damage: build.damage,
      artifactIds: build.artifactIds,
      pieces: describePieces(build.artifactIds, pieces, (slot) => names[slot] ?? slot),
    }));
  });

  /**
   * `equip_bracer` → `Flower`, from `/artifacts/options`.
   *
   * **Not a map written here.** `ArtifactSlot.display` already publishes these, and the first
   * draft of this page duplicated them — in the very chunk whose argument is that a second
   * copy of the server's vocabulary is how a silent divergence starts.
   */
  protected readonly slotNames = signal<Record<string, string>>({});

  // ── The rotation objective (R.8/R.9) ──────────────────────────────────────────────────
  //
  // The single-hit search above maximises **one hit**, which is a proxy — and the Chunk F
  // chain cannot see a conditional 4-piece bonus, which is **every 4-piece in the game**. The
  // rotation objective scores against gcsim's own arithmetic instead, at ~1.05x the cost.
  //
  // **Both stay reachable.** The fast one answers a different, legitimate question in
  // microseconds, and OQ-W4 settled the principle: deleting a fast honest answer because a
  // slow better one exists is a downgrade for whoever wanted the fast one.
  protected readonly objective = signal<'hit' | 'rotation'>('hit');
  protected readonly rotations = signal<{ id: string; name: string }[]>([]);
  protected rotationId = '';
  protected readonly calibrating = signal<CalibrationProgress | null>(null);
  /** What the recipes do not cover. **Shown, never swallowed** — R.9. */
  protected readonly caveats = signal<CalibrationCaveats | null>(null);

  private readonly recipeOptimize = inject(RecipeOptimizeService);
  private readonly rotationsService = inject(RotationsService);
  private readonly optimize = inject(OptimizeService);
  private readonly artifacts = inject(ArtifactsService);
  private readonly explain = inject(ExplainService);
  private readonly buildsService = inject(BuildsService);

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [builds, options, rotations] = await Promise.all([
        this.buildsService.list(),
        this.artifacts.options(),
        this.rotationsService.list(),
      ]);
      // Paginated. Reading it as an array leaves the picker empty, which looks exactly like
      // having authored no rotations — the same trap W.6's compare page fell into.
      this.rotations.set(rotations.items.map((r) => ({ id: r.id, name: r.name })));
      if (rotations.items.length > 0) this.rotationId = rotations.items[0].id;
      this.slotNames.set(
        Object.fromEntries(options.slots.map((slot) => [slot.key, slot.display])),
      );
      this.builds.set(builds);
      if (builds.length > 0) await this.selectBuild(builds[0].id);
    } catch {
      this.error.set('Could not load your builds.');
      this.builds.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  protected async selectBuild(id: string): Promise<void> {
    this.buildId.set(id);
    this.hits.set([]);
    this.hitIndex = 0;
    // A result belongs to the build it was searched for. Left up, it would sit under a
    // different character's name — a number that looks right and refers to something else.
    this.result.set(null);
    this.actionError.set(null);
    if (!id) return;
    try {
      this.hits.set(await this.explain.hits(id));
      const element = this.builds().find((b) => b.id === id)?.character?.element;
      if (element) {
        const guess = element.toLowerCase();
        if ((CHANNELS as readonly string[]).includes(guess)) this.channel = guess;
      }
    } catch (err) {
      this.actionError.set(apiErrorMessage(err));
    }
  }

  /**
   * Whether the kernel has a bucket for this slot.
   *
   * A slot it does not know is **reported and excluded** rather than cast through: the search
   * buckets candidates by slot, so an unknown one silently never gets considered — and the
   * ranking would be over four slots while claiming to be over five.
   */
  private isKnownSlot(piece: KernelCandidate): boolean {
    if ((SLOTS as readonly string[]).includes(piece.slot)) return true;
    this.unreadable.update((seen) => [
      ...seen,
      { artifact_id: piece.id, reason: `unknown slot ${piece.slot}` },
    ]);
    return false;
  }

  /**
   * Explain one result — the server's account of the same five pieces.
   *
   * O.4, and the reason M.3 came before it: **a ranking whose winner cannot be explained is
   * a ranking nobody can verify.** `/explain` takes `artifact_ids`, so the winning five go
   * straight back.
   *
   * The two numbers are computed by two different implementations of the chain — the
   * browser's f32 kernel and the backend's f64 — which C.2 measured as diverging by up to
   * 3.4e-07. They are shown together rather than reconciled: a difference outside that is a
   * real disagreement and should be visible, not smoothed over by displaying only one.
   */
  protected async explainRow(row: ResultRow): Promise<void> {
    const hit = this.hit();
    const id = this.buildId();
    if (!hit || !id) return;
    this.actionError.set(null);
    this.explaining.set(true);
    try {
      this.explained.set({
        rank: row.rank,
        result: await this.explain.explain(
          id,
          { talent: hit.talent, label: hit.label, index: hit.index },
          this.channel,
          this.scope,
          this.enemyLevel,
          row.artifactIds,
        ),
      });
    } catch (err) {
      this.explained.set(null);
      this.actionError.set(apiErrorMessage(err));
    } finally {
      this.explaining.set(false);
    }
  }

  /**
   * The explained result and the search row it belongs to, paired.
   *
   * **Found by rank, not by index.** `rows()[rank - 1]` happens to be right as rows are
   * built, and it is an assumption the template should not carry — a filtered or reordered
   * list would silently pair an explanation with a different build, which is precisely the
   * "number that refers to something else" this page is meant to rule out.
   *
   * Injecting the index form back **survives** the suite, and that is honest rather than a
   * gap: the two agree for every list this page can currently produce. The tests below
   * assert the pairing's contract; they cannot distinguish two implementations that are both
   * correct today. This is defensive, and recorded as defensive rather than dressed up as a
   * fix.
   */
  protected readonly pairing = computed(() => {
    const shown = this.explained();
    if (!shown) return null;
    const row = this.rows().find((r) => r.rank === shown.rank);
    return row ? { shown, row } : null;
  });

  /**
   * How far the server's figure is from the kernel's, as a fraction.
   *
   * Shown rather than hidden. C.2 measured the f32/f64 divergence at up to 3.4e-07, so
   * anything of that order is the tolerance doing its job — and anything larger is two
   * implementations of one chain disagreeing, which is exactly what this pairing exists to
   * expose.
   */
  protected divergence(): number | null {
    const paired = this.pairing();
    if (!paired || paired.row.damage === 0) return null;
    return Math.abs(paired.shown.result.damage - paired.row.damage) / paired.row.damage;
  }

  protected async run(): Promise<void> {
    const hit = this.hit();
    const id = this.buildId();
    if (!hit || !id) return;
    this.actionError.set(null);
    this.searching.set(true);
    try {
      const [context, snapshot] = await Promise.all([
        this.optimize.context(
          id,
          { talent: hit.talent, label: hit.label, index: hit.index },
          this.channel,
          this.scope,
          this.enemyLevel,
        ),
        this.optimize.inventory(),
      ]);

      // A stale explanation belongs to the previous ranking. Left up, it would sit under a
      // new winner and describe a build that is no longer on screen.
      this.explained.set(null);
      this.candidates.set(snapshot.artifacts);
      this.unreadable.set(snapshot.unreadable);
      this.truncated.set(snapshot.truncated);

      this.result.set(
        search(
          snapshot.artifacts.filter((piece) => this.isKnownSlot(piece)).map((piece) => ({
            id: piece.id,
            slot: piece.slot as Slot,
            // The kernel counts set pieces by number. A setless piece gets a negative
            // sentinel so it matches nothing rather than joining set 0 — which is a real
            // catalogue id, and would give five starter relics a four-piece bonus.
            setId: piece.set_id ?? -1,
            stats: piece.stats,
          })),
          {
            base: context.base,
            hit: {
              multiplier: context.hit.multiplier,
              // Typed against the kernel's own vocabularies rather than narrowed by a cast.
              // The first draft wrote `as 'atk' | 'hp' | 'def'` and `as null`, which told the
              // compiler two things that are not true — `elemental_mastery` is a scaling stat
              // and `melt` is an amplifying reaction — while at runtime the value passed
              // through regardless. A cast that lies is worse than no type: it stops the
              // compiler noticing the day the two sides stop agreeing.
              scalingStat: context.hit.scaling_stat as ScalingStat,
              flatDamage: 0,
              baseDamageBonus: 0,
              amplifying: context.hit.amplifying as Amplifying | null,
              reactionBonus: 0,
            },
            target: {
              level: context.target.level,
              resistance: context.target.resistance,
              defReduction: context.target.def_reduction,
              defIgnore: context.target.def_ignore,
            },
            characterLevel: context.character_level,
            dmgBonusQuantity: context.dmg_bonus_quantity,
            setBonuses: context.set_bonuses.map((bonus) => ({
              setId: bonus.set_id,
              piecesRequired: bonus.pieces_required,
              stats: bonus.stats,
            })),
          },
        ),
      );
    } catch (err) {
      this.result.set(null);
      this.actionError.set(apiErrorMessage(err));
    } finally {
      this.searching.set(false);
    }
  }

  /**
   * Search against the rotation instead of a single hit.
   *
   * Calibrates one recipe per **4-piece state** the inventory can reach — every 4-piece bonus
   * in the game is conditional, so only a run with the set equipped holds it — then scores
   * every combination against the recipe for *its* set.
   *
   * **This is a job.** Each state is ~3.2 s of gcsim in the browser, so progress is per state
   * and the cache means a second search over the same build pays none of it again.
   */
  protected async runRotation(): Promise<void> {
    const id = this.buildId();
    if (!id || !this.rotationId) return;
    this.actionError.set(null);
    this.result.set(null);
    this.caveats.set(null);
    this.searching.set(true);
    try {
      const snapshot = await this.optimize.inventory();
      this.candidates.set(snapshot.artifacts);
      this.unreadable.set(snapshot.unreadable);
      this.truncated.set(snapshot.truncated);

      const pieces = snapshot.artifacts.filter((piece) => this.isKnownSlot(piece));
      const targets = this.calibrationTargets(pieces);
      const calibrated = await this.recipeOptimize.calibrateAll(
        id, this.rotationId, snapshot.version, targets,
        (progress) => this.calibrating.set(progress),
      );
      this.caveats.set(calibrated.caveats);

      if (calibrated.noFourPiece === null) {
        this.actionError.set('No baseline recipe was calibrated, so nothing can be scored.');
        return;
      }
      this.result.set(searchRecipe(
        pieces.map((piece) => ({
          id: piece.id,
          slot: piece.slot as Slot,
          setId: piece.set_id ?? -1,
          stats: piece.stats,
        })),
        {
          recipes: {
            byFourPieceSet: calibrated.byFourPieceSet,
            noFourPiece: calibrated.noFourPiece,
          },
        },
      ));
    } catch (err) {
      this.result.set(null);
      this.actionError.set(apiErrorMessage(err));
    } finally {
      this.searching.set(false);
      this.calibrating.set(null);
    }
  }

  /**
   * The 4-piece states this inventory can reach, plus the no-four-piece one.
   *
   * **Counted by distinct slots, not by piece count.** Four pieces of a set that share a slot
   * form no combination, and calibrating for them would spend ~3.2 s on a state nothing can
   * reach.
   */
  private calibrationTargets(pieces: readonly KernelCandidate[]): CalibrationTarget[] {
    const slotsBySet = new Map<number, Set<string>>();
    for (const piece of pieces) {
      if (piece.set_id === null || piece.set_id === undefined) continue;
      const slots = slotsBySet.get(piece.set_id) ?? new Set<string>();
      slots.add(piece.slot);
      slotsBySet.set(piece.set_id, slots);
    }
    const targets: CalibrationTarget[] = [{ artifactSetId: null, label: 'no 4-piece set' }];
    for (const [setId, slots] of slotsBySet) {
      if (slots.size >= 4) {
        targets.push({ artifactSetId: String(setId), label: `set ${setId}` });
      }
    }
    return targets;
  }
}
