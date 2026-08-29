import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import { ElementChip } from '../../shared/element/element';
import { CatalogueIcon } from '../../shared/icon/icon';
import { EntityToken } from '../../shared/token/token';
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
  imports: [FormsModule, RouterLink, DecimalPipe, PercentPipe, CatalogueIcon, ElementChip, EntityToken],
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

  /**
   * The set catalogue by nanoka id — the id an artifact carries.
   *
   * Holds the **uuid** as well as the name, because `/calibrate` resolves `artifact_set_id`
   * with `get_by_id` and 404s on a nanoka id. See `OptimizeService.artifactSets`.
   */
  protected readonly artifactSets = signal<
    ReadonlyMap<number, { id: string; name: string }>
  >(new Map());
  /**
   * Set bonuses for the rotation search.
   *
   * **Unused until 2+2 exists, and correct to wire now.** A 4-piece state leaves at most one
   * other piece and a lone piece grants no bonus, so these change nothing today — but the
   * moment a combination holds 2+2, omitting them would understate it by both 2-piece
   * bonuses, which is the thing the user selected the pair for.
   */
  protected readonly setBonuses = signal<
    { setId: number; piecesRequired: number; stats: Record<string, number> }[]
  >([]);
  /**
   * Which 4-piece sets to search. **Empty by default — a run requires an explicit pick.**
   *
   * Narrowing this is not a convenience. Unrestricted, a real inventory is 4.26e10
   * combinations and 36 calibrations; the filter cuts **both** costs, because a set nobody
   * selected is a set nobody has to calibrate. `docs/FINDINGS_shakedown.md` F2.
   *
   * It defaulted to "everything" until owner ruling 3 (2026-08-28, `docs/DECISIONS.md`).
   * That default cost ~3.8 min before any output, which was tolerable only while a streaming
   * leaderboard was planned to cover it; ruling 2 removed streaming, so the scope is narrowed
   * by the person who knows what they want instead. Three sets is four calibrations.
   *
   * **The accepted cost:** a user with no set in mind has no default to lean on. The picker
   * mitigates it by showing what they own, most-owned first — it does not solve it.
   */
  protected readonly selectedSets = signal<ReadonlySet<number>>(new Set());
  /**
   * A 2+2 pair to search, as catalogue ids. Both or neither.
   *
   * **Opt-in and rare, by owner ruling.** One pair is ~44k combinations and 2.7 s; all
   * `C(35, 2) = 595` of them are not searchable, which is why the user names one rather
   * than the page offering "all 2+2 builds".
   *
   * This replaced `includeNoFourPiece`, which walked *every* combination without a 4-piece —
   * 99.97 % of the space, and it did not finish (B.5). It also closes the one place a
   * conditional 2-piece bonus could be silently dropped: that walk scored 2+2 builds from
   * stat pools, and nine of the sixty 2-piece bonuses have no static stats to pool.
   */
  protected readonly pairFirst = signal<number | null>(null);
  protected readonly pairSecond = signal<number | null>(null);

  /** The explanation of one result row, and which row it belongs to. */
  protected readonly explained = signal<{ rank: number; result: ExplainResponse } | null>(
    null,
  );
  protected readonly explaining = signal(false);

  protected readonly buildId = signal('');
  /**
   * A **signal**, because the `hit` computed reads it.
   *
   * A plain field is invisible to a computed — Angular tracks signal reads — so changing the
   * hit left `hit()` on whatever it had cached, and the page scored the previous selection.
   */
  protected readonly hitIndex = signal(0);
  protected channel = 'physical';
  protected scope = 'normal';
  protected enemyLevel = 90;

  protected readonly build = computed(
    () => this.builds().find((b) => b.id === this.buildId()) ?? null,
  );
  protected readonly hit = computed(() => this.hits()[this.hitIndex()] ?? null);
  protected readonly canSearch = computed(
    () => this.hit() !== null && !this.searching(),
  );

  /** Every set the inventory could field a 4-piece of, most-owned first. */
  protected readonly fourPieceChoices = computed(() => {
    const catalogue = this.artifactSets();
    return [...this.slotsBySet(this.candidates())]
      .filter(([, slots]) => slots.size >= 4)
      .map(([setId, slots]) => ({
        setId,
        name: catalogue.get(setId)?.name ?? `set ${setId}`,
        slots: slots.size,
      }))
      .sort((a, b) => b.slots - a.slots || a.name.localeCompare(b.name));
  });

  /**
   * A rotation search needs a rotation and something to search.
   *
   * Nothing is selected by default (ruling 3), so this is the gate that stops a run whose
   * only work would be the baseline calibration — six seconds to answer a question the user
   * did not ask.
   */
  protected readonly canSearchRotation = computed(
    () => !this.searching()
      && this.rotationId() !== ''
      && (this.selectedSets().size > 0 || this.chosenPair() !== null),
  );

  /**
   * The pair, if both halves are chosen and distinct.
   *
   * Two of the same set is a 4-piece, not a 2+2, and belongs to the other control.
   */
  protected readonly chosenPair = computed<readonly [number, number] | null>(() => {
    const a = this.pairFirst();
    const b = this.pairSecond();
    return a !== null && b !== null && a !== b ? [a, b] : null;
  });

  /** How many recipes the selection implies — the baseline, one per set, one for the pair. */
  protected readonly calibrationCount = computed(
    () => 1
      + this.fourPieceChoices().filter((c) => this.isSelected(c.setId)).length
      + (this.chosenPair() === null ? 0 : 1),
  );

  protected isSelected(setId: number): boolean {
    return this.selectedSets().has(setId);
  }

  protected toggleSet(setId: number): void {
    const picked = new Set(this.selectedSets());
    if (picked.has(setId)) picked.delete(setId);
    else picked.add(setId);
    this.selectedSets.set(picked);
  }

  /** An uncovered set, named. Ids are what the search returns; names are what a user reads. */
  protected setLabel(setId: number): string {
    return this.artifactSets().get(setId)?.name ?? `set ${setId}`;
  }

  protected selectAllSets(): void {
    this.selectedSets.set(new Set(this.fourPieceChoices().map((c) => c.setId)));
  }

  protected selectNoSets(): void {
    this.selectedSets.set(new Set());
  }

  /** Distinct slots each set can fill — four is what a 4-piece needs. */
  private slotsBySet(pieces: readonly KernelCandidate[]): Map<number, Set<string>> {
    const bySet = new Map<number, Set<string>>();
    for (const piece of pieces) {
      if (piece.set_id === null || piece.set_id === undefined) continue;
      const slots = bySet.get(piece.set_id) ?? new Set<string>();
      slots.add(piece.slot);
      bySet.set(piece.set_id, slots);
    }
    return bySet;
  }

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
  /** A signal, because `canSearchRotation` reads it. Same reason as `hitIndex`. */
  protected readonly rotationId = signal('');
  protected readonly calibrating = signal<CalibrationProgress | null>(null);
  /** What the recipes do not cover. **Shown, never swallowed** — R.9. */
  protected readonly caveats = signal<CalibrationCaveats | null>(null);
  /**
   * The recipe search's own reporting, which `SearchResult` has no room for.
   *
   * Kept beside `result` rather than widening it: the single-hit search fills the same signal
   * and has no notion of a set it did not cover.
   */
  protected readonly recipeNotes = signal<
    { uncoveredSets: number[]; boundPruned: number } | null
  >(null);

  private readonly recipeOptimize = inject(RecipeOptimizeService);
  private readonly rotationsService = inject(RotationsService);
  private readonly optimize = inject(OptimizeService);
  private readonly artifacts = inject(ArtifactsService);
  private readonly explain = inject(ExplainService);
  private readonly buildsService = inject(BuildsService);

  ngOnInit(): void {
    void this.load();
    void this.loadFilterData();
  }

  /**
   * The set filter's data — names, and the inventory it filters.
   *
   * Deliberately **not** in `load()`'s `Promise.all`: a user with no artifacts yet should
   * still get a page, and a filter that cannot populate is a missing control rather than a
   * broken route. On failure `fourPieceChoices()` stays empty and a run falls back to every
   * reachable set, which is what the page did before the filter existed.
   */
  private async loadFilterData(): Promise<void> {
    try {
      const [catalogue, snapshot, bonuses] = await Promise.all([
        this.optimize.artifactSets(),
        this.optimize.inventory(),
        this.optimize.setBonuses(),
      ]);
      this.artifactSets.set(catalogue);
      this.setBonuses.set(bonuses.map((bonus) => ({
        setId: bonus.set_id,
        piecesRequired: bonus.pieces_required,
        stats: bonus.stats,
      })));
      this.candidates.set(snapshot.artifacts);
    } catch {
      // Left empty on purpose — see the docstring.
    }
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
      if (rotations.items.length > 0) this.rotationId.set(rotations.items[0].id);
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
    this.hitIndex.set(0);
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
    if (!id || !this.rotationId()) return;
    this.actionError.set(null);
    this.result.set(null);
    this.caveats.set(null);
    this.recipeNotes.set(null);
    this.searching.set(true);
    try {
      const snapshot = await this.optimize.inventory();
      this.candidates.set(snapshot.artifacts);
      this.unreadable.set(snapshot.unreadable);
      this.truncated.set(snapshot.truncated);

      const pieces = snapshot.artifacts.filter((piece) => this.isKnownSlot(piece));
      // Re-derived from the snapshot just fetched, so a set imported since the page loaded is
      // offered rather than silently dropped — then narrowed to what the user picked.
      const chosen = this.reachableSets(pieces).filter((setId) => this.isSelected(setId));

      // Refused, not silently narrowed: a set the catalogue cannot resolve has no uuid to
      // calibrate with, and dropping it would quietly answer a different question.
      const pair = this.chosenPair();
      const unresolved = [...chosen, ...(pair ?? [])]
        .filter((setId) => !this.artifactSets().has(setId));
      if (unresolved.length) {
        this.actionError.set(
          `Could not resolve ${unresolved.length} selected set(s) in the catalogue, so the `
          + 'search was not run. Reload the page to fetch it again.',
        );
        return;
      }
      const targets = this.calibrationTargets(chosen);
      const calibrated = await this.recipeOptimize.calibrateAll(
        id, this.rotationId(), snapshot.version, targets,
        (progress) => this.calibrating.set(progress),
      );
      this.caveats.set(calibrated.caveats);

      if (calibrated.noFourPiece === null) {
        this.actionError.set('No baseline recipe was calibrated, so nothing can be scored.');
        return;
      }
      const found = searchRecipe(
        pieces.map((piece) => ({
          id: piece.id,
          slot: piece.slot as Slot,
          setId: piece.set_id ?? -1,
          stats: piece.stats,
        })),
        {
          recipes: {
            byFourPieceSet: calibrated.byFourPieceSet,
            byPair: calibrated.byPair,
            noFourPiece: calibrated.noFourPiece,
          },
          setBonuses: this.setBonuses(),
          // The baseline is always calibrated — it is the reference every other recipe is
          // measured against — but it is never *searched* as a state: an unrestricted
          // no-4-piece walk is 99.97 % of the space and does not finish (B.5).
          fourPieceSets: chosen,
          twoPiecePairs: pair === null ? [] : [pair],
        },
      );
      this.result.set(found);
      this.recipeNotes.set({
        uncoveredSets: found.uncoveredSets,
        boundPruned: found.boundPruned,
      });
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
  private reachableSets(pieces: readonly KernelCandidate[]): number[] {
    // **Ordered by how much of the set the user actually owns.** R.1 measured a real account
    // at **S = 35**, so 36 calibrations and ~3.8 minutes — three times the plan's estimate,
    // and filtering by rarity or level barely helps (35 → 28 at 5-star +20), because a large
    // account genuinely holds four distinct slots of nearly every set.
    //
    // Ordering does not make it shorter. It makes **stopping early** useful: the sets a user
    // has farmed come first, so an interrupted run has calibrated the ones most likely to
    // matter rather than an arbitrary third.
    return [...this.slotsBySet(pieces)]
      .filter(([, slots]) => slots.size >= 4)
      .sort((a, b) => b[1].size - a[1].size || a[0] - b[0])
      .map(([setId]) => setId);
  }

  /**
   * One calibration per selected set, plus the baseline.
   *
   * The label is the set's **name**: `CalibrationTarget.label` has always said it is "for
   * progress a user can read — 'Blizzard Strayer', not a uuid", and it read `set 15003`.
   */
  private calibrationTargets(chosen: readonly number[]): CalibrationTarget[] {
    const catalogue = this.artifactSets();
    // **Never falls back to an empty list.** That is the baseline state, so an unresolved set
    // would calibrate no set at all and label it with the set's name — a recipe understating
    // itself by the whole bonus, looking like an ordinary result. `runRotation` refuses the
    // run before it gets here.
    const entry = (setId: number) => {
      const found = catalogue.get(setId);
      if (found === undefined) throw new Error(`no catalogue entry for set ${setId}`);
      return found;
    };
    const pair = this.chosenPair();

    return [
      { artifactSetIds: [], setIds: [], label: 'no 4-piece set' },
      ...chosen.map((setId) => ({
        artifactSetIds: [entry(setId).id], setIds: [setId], label: entry(setId).name,
      })),
      ...(pair === null ? [] : [{
        artifactSetIds: [entry(pair[0]).id, entry(pair[1]).id],
        setIds: [pair[0], pair[1]],
        label: `${entry(pair[0]).name} + ${entry(pair[1]).name} (2+2)`,
      }]),
    ];
  }
}
