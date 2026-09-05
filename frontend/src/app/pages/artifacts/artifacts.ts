import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { apiErrorMessage } from '../../api/api-error';
import { CardPicker, type CardOption } from '../../shared/card-picker/card-picker';
import { isFilterableMainStat, sortMainStats } from '../../shared/stat-order';
import { CatalogueIcon } from '../../shared/icon/icon';
import { describeStat as describe } from '../../shared/stat-label';
import {
  barsTitle,
  rollBars,
  rollValuePercent,
  substatReadings,
} from '../../shared/substat-bars/substat-bars';
import { CatalogueService } from '../catalogue/catalogue.service';
import { BuildsService, type BuildRead } from '../builds/builds.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService, type TeamRead } from '../teams/teams.service';
import { buildsInTeam } from '../../shared/team-scope';
import {
  ArtifactRankingService,
  type DeepDive,
  type RankingRow,
} from './artifact-ranking.service';
import { type CalibrationProgress } from '../optimize/recipe-optimize.service';
import {
  ArtifactsService,
  type ArtifactOptions,
  type ArtifactRead,
  type ArtifactSlotKey,
  type GoodImportResponse,
  type ImportMode,
} from './artifacts.service';

/** One substat, with whatever could be established about the rolls behind it. */
export interface ArtifactSubstat {
  label: string;
  /**
   * Rolls behind this line, or **null** when the decompositions disagree on how many.
   *
   * 95% of a real inventory has a count. The rest draws no bars rather than a plausible
   * number of them.
   */
  rolls: number | null;
  /**
   * One entry per roll, `0` (worst tier) to `3` (best) — null unless exactly one
   * decomposition fits; where several of that length fit, one is read and `tiersExact` is
   * false.
   *
   * When `rolls` is known but this is not, the card draws that many *undifferentiated*
   * bars: the count is established, the individual qualities are not.
   */
  tiers: number[] | null;
  /** True when `tiers` is the only combination of its length rather than one reading. */
  tiersExact: boolean;
  /** The line as a multiple of one best-case roll. `3.2` reads as "3.2 max rolls". */
  rollValue: number | null;
  /** True when the count is the likeliest reading rather than the only one. */
  estimated: boolean;
}

/** One piece, with everything the row needs already resolved. */
export interface ArtifactRow {
  id: string;
  setName: string;
  setIcon: string | null;
  slot: string;
  stars: number;
  level: number;
  mainStat: string;
  substats: ArtifactSubstat[];
  equipped: boolean;
  /** Sort keys, kept beside the display strings so a comparator never re-parses one. */
  setId: string;
  mainStatKey: string;
  slotKey: string;
  /** The piece's total roll value, or null when its rolls could not be decomposed.
   *  Null sorts last rather than as zero — "unknown" is not "worst". */
  rollValue: number | null;
  /**
   * What this piece is worth to the build the page was last ranked against, or `null` when it
   * has not been ranked. `rank.refusal` non-null means it was ranked and honestly could not be
   * scored — a different state from "no build chosen", and the card says which.
   */
  rank: RankingRow | null;
}

/** How many cards are rendered before "show more", and how many each press adds. */
const INITIAL_ROWS = 120;
const MORE_ROWS = 120;

/**
 * The page sizes offered at the top of the list.
 *
 * **Because the only way forward was at the bottom of an 11,664-pixel page.** Audit finding 5:
 * "Showing 120 of 2369" with a SHOW MORE button eleven screens down — reaching piece 500 meant
 * four full-page scrolls and the end meant twenty, with nothing near the top even hinting that
 * more existed.
 *
 * `Infinity` is "all of them", and it is offered rather than hidden: the alternative is a user
 * pressing SHOW MORE nineteen times. It is last and labelled with the real count, because
 * rendering 2,369 cards is genuinely slow and the number is the warning.
 */
const PAGE_SIZES = [120, 300, 600, Infinity] as const;

export type SortKey =
  | 'rollValue' | 'level' | 'set' | 'slot' | 'stars'
  /** Signed damage change against the build as it stands, with this piece in its slot today. */
  | 'delta'
  /** The same, once the remaining rolls land at their expected values. The upgrade queue. */
  | 'averageDelta'
  /** The ceiling: what this piece could be worth if every remaining roll went the right way. */
  | 'best';

/** The three orderings that only mean anything once a build has been ranked against. */
export const RANK_SORTS: readonly SortKey[] = ['delta', 'averageDelta', 'best'];

/**
 * A piece's total roll value, or null when any substat could not be decomposed.
 *
 * **Null rather than a partial sum.** 3.5% of the owner's real export cannot be decomposed,
 * and adding up the three substats that could be would rank a piece by less than it has —
 * quietly, and always downward. Sorting puts null last, because "unknown" is not "worst".
 */
export function totalRollValue(
  analysis: readonly { roll_value?: number | null }[] | null | undefined,
): number | null {
  if (!analysis?.length) return null;
  let total = 0;
  for (const sub of analysis) {
    if (typeof sub.roll_value !== 'number') return null;
    total += sub.roll_value;
  }
  return total;
}

/**
 * Sort by a ranked number, sinking every row that does not have one.
 *
 * **A refused or unranked piece is not a bad piece.** Sorting it as zero would bury a real
 * artifact among the junk, or — worse, on a descending delta — float it above pieces that were
 * actually measured. `rollValue` already sinks undecomposable pieces for the same reason, and
 * this is that rule applied to the ranking columns.
 */
function byRanked(pick: (row: ArtifactRow) => number | null | undefined) {
  return (a: ArtifactRow, b: ArtifactRow): number => {
    const left = pick(a);
    const right = pick(b);
    const leftOk = typeof left === 'number' && Number.isFinite(left);
    const rightOk = typeof right === 'number' && Number.isFinite(right);
    if (!leftOk && !rightOk) return b.level - a.level;
    if (!leftOk) return 1;
    if (!rightOk) return -1;
    return right - left;
  };
}

/** Orderings, each descending in the direction a player cares about. */
export function comparator(key: SortKey): (a: ArtifactRow, b: ArtifactRow) => number {
  switch (key) {
    case 'delta':
      return byRanked((row) => row.rank?.delta);
    case 'averageDelta':
      return byRanked((row) => row.rank?.averageDelta);
    case 'best':
      return byRanked((row) => row.rank?.best);
    case 'level':
      return (a, b) => b.level - a.level || a.setName.localeCompare(b.setName);
    case 'set':
      return (a, b) => a.setName.localeCompare(b.setName) || a.slotKey.localeCompare(b.slotKey);
    case 'slot':
      return (a, b) => a.slotKey.localeCompare(b.slotKey) || b.level - a.level;
    case 'stars':
      return (a, b) => b.stars - a.stars || b.level - a.level;
    case 'rollValue':
    default:
      // Undecomposed pieces sink to the bottom whichever way the list is read, rather than
      // sorting as zero and looking like the worst artifacts the user owns.
      return (a, b) => {
        if (a.rollValue === null && b.rollValue === null) return b.level - a.level;
        if (a.rollValue === null) return 1;
        if (b.rollValue === null) return -1;
        return b.rollValue - a.rollValue;
      };
  }
}


/**
 * The artifact inventory, and the GOOD import that fills it.
 *
 * **The import result is rendered in full.** The endpoint rejects individual artifacts rather
 * than failing the file — someone with 800 pieces and two odd ones wants the 798 — so a page
 * showing only "imported 798" has thrown away the only record of the two. Every rejection is
 * listed with its reason.
 *
 * **`mode` defaults to `replace`** (owner ruling, 2026-08-28). It was deliberately empty
 * before, on the reasoning that a default would be this page deciding whether to delete
 * someone's inventory. In practice a re-scan *is* the inventory — GOOD carries no stable
 * per-artifact id, so `append` on a second scan of the same account duplicates every piece,
 * which is the outcome the empty default was steering people into. `replace` is what the
 * common case wants, `append` stays one click away, and N.3 already re-equips what it can
 * and names what it could not.
 *
 * Rows are drawn from the vocabulary at `/artifacts/options`: `slot` and `main_stat_type`
 * carry the source's internal spellings, and the stored values are units-dependent — `4780`
 * is flat HP and `0.466` is 46.6%. A page translating those itself would be a second copy of
 * `StatType.display` and `is_percentage`.
 */
@Component({
  selector: 'page-artifacts',
  imports: [FormsModule, CatalogueIcon, CardPicker],
  templateUrl: './artifacts.html',
  styleUrl: './artifacts.scss',
})
export class ArtifactsPage implements OnInit {
  protected readonly loading = signal(true);
  /** Non-null means the page failed to load. Never rendered as "you have no artifacts". */
  protected readonly error = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);

  protected readonly options = signal<ArtifactOptions | null>(null);
  protected readonly artifacts = signal<ArtifactRead[]>([]);
  protected readonly total = signal(0);
  protected readonly truncated = signal(false);

  protected slotFilter = '';
  /** Non-null after an import, so the result stays on screen to be read. */
  protected readonly importResult = signal<GoodImportResponse | null>(null);
  protected readonly importing = signal(false);
  /** `replace` by default — see the class docstring. */
  protected mode: ImportMode | '' = 'replace';
  protected payloadText = '';
  /**
   * Also rebuild builds from the export's `characters`, `weapons` and each artifact's
   * `location`.
   *
   * **On by default, and safe to be.** It never overwrites a build that already exists, so
   * the worst case for a returning user is a report saying nothing changed — while for a
   * first import it removes the whole manual setup the inventory otherwise leads into.
   */
  protected rebuildBuilds = true;
  /** The name of a file chosen through the picker, shown so a paste and a file cannot be
   *  confused for one another. */
  protected readonly fileName = signal<string | null>(null);

  protected readonly slots = computed(() => this.options()?.slots ?? []);

  /**
   * Set id → art, joined here rather than added to `ArtifactRead`.
   *
   * `/artifact-sets` already publishes the basename and there are 65 of them, so this is one
   * extra request against a list the app can hold entirely. Widening the artifact schema
   * would put the same value on every one of a user's several hundred pieces.
   *
   * Empty until it loads, and a miss yields null — which `CatalogueIcon` renders as nothing.
   * Art arriving late must never hold up the inventory.
   */
  /**
   * `{set id: {slot: icon}}`, with the set's own icon under `''`.
   *
   * **A set has five pictures, not one.** nanoka's set icon is the flower, so keying art by
   * set alone drew a flower on every plume, sands, goblet and circlet in the inventory —
   * which is what the owner noticed. `part_icons` names the rest; the set icon stays as the
   * fallback for a database seeded before that column existed.
   */
  protected readonly setIcons = signal<Map<string, Record<string, string | null>>>(new Map());

  protected readonly rows = computed<ArtifactRow[]>(() => {
    const opts = this.options();
    if (!opts) return [];
    const stats = new Map(opts.stats.map((s) => [s.key, s]));
    const slots = new Map(opts.slots.map((s) => [s.key, s.display]));
    const stars = new Map(opts.rarities.map((r) => [r.key, r.stars]));
    const setArt = this.setIcons();
    const ranked = this.ranked();
    return this.artifacts().map((piece) => ({
      id: piece.id,
      setName: piece.set_name ?? 'No set',
      setIcon: (() => {
        const art = setArt.get(piece.artifact_set_id ?? '');
        return art?.[piece.slot] ?? art?.[''] ?? null;
      })(),
      slot: slots.get(piece.slot) ?? piece.slot,
      stars: stars.get(piece.rarity) ?? 0,
      level: piece.level,
      mainStat: describe(piece.main_stat_type, piece.main_stat_value, stats),
      substats: substatReadings(
        piece.substats as { stat?: string; value?: unknown }[],
        piece.substat_analysis,
        (stat, value) => describe(stat, value, stats),
      ),
      equipped: piece.build_id !== null,
      setId: piece.artifact_set_id ?? '',
      mainStatKey: piece.main_stat_type,
      slotKey: piece.slot,
      rollValue: totalRollValue(piece.substat_analysis),
      rank: ranked.get(piece.id) ?? null,
    }));
  });

  // ── narrowing and ordering ────────────────────────────────────────────────
  //
  // All client-side, over an array the page already holds in full. The API's own `set_id`
  // filter exists, but re-fetching on every dropdown change would trade one cheap array pass
  // for a round trip, and the slot filter already goes to the server for `total`.

  protected readonly setFilter = signal('');
  protected readonly mainStatFilter = signal('');
  protected readonly equippedFilter = signal<'' | 'yes' | 'no'>('');
  protected readonly sortBy = signal<SortKey>('rollValue');

  // ── Ranking against a build (A.7) ──────────────────────────────────────────
  //
  // The picker lives here rather than on /optimize because this is the page a player is on
  // while holding a new drop. `AUDIT_fribbels_parity.md` §2 lists "a per-piece score" as the
  // last thing missing from this page, and this is it.

  /**
   * **The rotation is chosen first, and it names the team.**
   *
   * The first draft offered every build against every rotation — 75 x N — and a real run
   * returned `422: build is not in the rotation's team`. Most of that cross-product does not
   * exist: `POST /rotations/{id}/context-key` requires the build to be one of the team's four,
   * because a cache key for "this build running this rotation" is meaningless otherwise. So
   * the picker offers only what can actually be asked, which is what `/optimize` already does
   * with `buildsInTeam`.
   */
  private readonly allBuilds = signal<BuildRead[]>([]);
  private readonly teams = signal<TeamRead[]>([]);
  private readonly rotationTeam = signal<Map<string, string>>(new Map());

  protected readonly rotationChoices = signal<{ id: string; label: string }[]>([]);
  protected readonly rankBuildId = signal('');
  protected readonly rankRotationId = signal('');

  /**
   * The builds the chosen rotation's team actually fields.
   *
   * Labelled by **character**, with constellation and weapon as the detail — the decision
   * `shared/team-scope.buildOptions` already made for `/optimize` and `/builds`. A build's own
   * `name` is not used, and driving the page is how that was learned: all 84 builds in the
   * local database have an empty name, so a label of `${character} — ${name}` rendered as
   * "Furina —" seventy-five times over.
   */
  protected readonly buildChoices = computed(() => {
    const teamId = this.rotationTeam().get(this.rankRotationId());
    const team = this.teams().find((t) => t.id === teamId) ?? null;
    if (!teamId || !team) return [];
    return buildsInTeam(team, this.allBuilds()).map((build) => ({
      id: build.id,
      label: build.character?.name || 'No character',
      detail: `C${build.constellation_level} · `
        + `${build.weapon_display || build.weapon?.name || 'no weapon'}`,
    }));
  });
  /** Null when idle. A calibration is ~3.2 s of gcsim and must never block a click. */
  protected readonly rankProgress = signal<CalibrationProgress | null>(null);
  protected readonly rankError = signal('');
  /**
   * What the last ranking said, keyed by artifact id.
   *
   * A map rather than a field written onto each row, because the rows are rebuilt whenever the
   * inventory reloads and a ranking outlives that. `rows()` reads it back in.
   */
  protected readonly ranked = signal<Map<string, RankingRow>>(new Map());
  /** The build's own damage, so the page can express a delta as a percentage of something. */
  protected readonly rankBaseline = signal(0);
  /** Carried from the draw model: these weights are cited, not measured. */
  protected readonly rankCaveat = signal('');
  protected readonly rankCaveats = signal<{ unstable: string[]; staleConversions: string[] }>({
    unstable: [], staleConversions: [],
  });
  /**
   * Sets whose pieces were refused because nothing calibrated them (OQ-A8).
   *
   * Offered rather than silently calibrated: each is ~3.2 s of gcsim, and calibrating all 65
   * because one piece asked would be a three-minute wait nobody requested.
   */
  protected readonly uncalibratedSets = signal<
    { setId: number; uuid: string; name: string; pieces: number }[]
  >([]);
  /** Sets the user has asked for, carried into the next ranking run. */
  private readonly extraSets = signal<{ uuid: string; setId: number; name: string }[]>([]);

  // ── The deep dive (A.12) ───────────────────────────────────────────────────
  //
  // #291's headline: "the best build with this artifact levelled up vs current for the % gain".
  // One piece at a time and deliberately — 2,370 pinned searches at five seconds each is three
  // hours, which is why the column above finds the candidates and this settles them.

  /** The artifact currently being asked about, or `''`. */
  protected readonly diveId = signal('');
  protected readonly diveRunning = signal(false);
  protected readonly diveError = signal('');
  protected readonly dive = signal<DeepDive | null>(null);

  /**
   * Hide pieces with no upgrades left.
   *
   * **Genshin Optimizer's Artifact Upgrader defaults its level filter to 0–19**, and
   * `docs/AUDIT_go_handson.md` §4 records why: the tool is for pieces you have *not* levelled,
   * because a +20 has no potential left to model. Driving this page confirmed the need from the
   * other side — sorted by expected upgrade value, the whole first screen was `+20` pieces
   * whose four numbers are necessarily identical, which reads as a broken calculation and is
   * in fact the correct answer to a question nobody asked.
   *
   * Off by default, because the page is an inventory first and a ranker second, and a filter
   * that hid two thirds of it on load would be a surprise.
   */
  protected readonly upgradableOnly = signal(false);

  protected readonly canRank = computed(
    () => !!this.rankBuildId() && !!this.rankRotationId() && !this.rankProgress(),
  );
  protected readonly hasRanking = computed(() => this.ranked().size > 0);

  /**
   * How many cards are actually put in the DOM.
   *
   * **This is the fix for the audit's largest finding.** The page rendered all 2,370 pieces at
   * once — roughly 30,000 nodes, and a full-page screenshot of 313 megapixels. It renders,
   * which is why it survived; it should not have to.
   *
   * A cap with an explicit "show more" rather than a virtual scroller: `@angular/cdk` is a
   * dependency this app does not otherwise carry, and the anonymous-volume dance in
   * `frontend/CLAUDE.md` makes adding one a heavier change than the problem needs. The count
   * line always says how many of how many, so a capped view can never be mistaken for the
   * whole inventory.
   */
  protected readonly shown = signal(INITIAL_ROWS);

  /**
   * The sets this inventory actually contains, as picker cards.
   *
   * Cards rather than a `<select>` — the owner's audit asks for this in four places and calls
   * it out as a pattern: *"pop-up square icon grids with cards for things with images. This
   * applies everywhere."* An artifact set is the clearest case, because sixty-five names in a
   * drop-down is a list nobody reads and the art is how anyone actually recognises them.
   */
  protected readonly setOptions = computed<CardOption[]>(() => {
    const seen = new Map<string, { name: string; icon: string | null; count: number }>();
    for (const row of this.rows()) {
      if (!row.setId) continue;
      const found = seen.get(row.setId);
      if (found) found.count += 1;
      else seen.set(row.setId, { name: row.setName, icon: row.setIcon, count: 1 });
    }
    return [...seen]
      .map(([value, { name, icon, count }]) => ({
        value,
        label: name,
        icon,
        // How many you own of it. The number a person uses to decide whether a set is worth
        // opening at all, and it is free here.
        detail: `${count}`,
      }))
      .sort((a, b) => a.label.localeCompare(b.label));
  });

  /**
   * Main stats present in the inventory, in the owner's order and without the flat ones.
   *
   * Ordered by `shared/stat-order`, which the optimizer's per-slot constraint uses too — the
   * audit asks for the same order in both places, and two sorts would eventually disagree.
   */
  protected readonly mainStatOptions = computed(() => {
    const stats = new Map(
      (this.options()?.stats ?? []).map((s) => [s.key, s.display ?? s.key]),
    );
    const keys = new Set(this.rows().map((r) => r.mainStatKey));
    return sortMainStats(
      [...keys]
        .filter(isFilterableMainStat)
        .map((key) => ({ key, display: stats.get(key) ?? key })),
    );
  });

  /** Every row that passes the filters, in sort order — before the render cap. */
  protected readonly matching = computed<ArtifactRow[]>(() => {
    const set = this.setFilter();
    const main = this.mainStatFilter();
    const equipped = this.equippedFilter();
    const upgradable = this.upgradableOnly();
    const kept = this.rows().filter((row) =>
      (!set || row.setId === set)
      && (!main || row.mainStatKey === main)
      && (!equipped || (equipped === 'yes') === row.equipped)
      && (!upgradable || (row.rank?.rollsRemaining ?? 0) > 0),
    );
    return [...kept].sort(comparator(this.sortBy()));
  });

  /** What the template draws. */
  protected readonly visible = computed(() => this.matching().slice(0, this.shown()));

  protected readonly hasMore = computed(() => this.matching().length > this.shown());

  protected readonly pageSizes = PAGE_SIZES;

  /** Label for a size chip: the number, or "All" with the count it means. */
  protected sizeLabel(size: number): string {
    return Number.isFinite(size) ? String(size) : `All ${this.matching().length}`;
  }

  protected setPageSize(size: number): void {
    this.shown.set(Number.isFinite(size) ? size : this.matching().length);
  }

  /** Which chip reads as pressed. `Infinity` matches once everything is on screen. */
  protected isPageSize(size: number): boolean {
    return Number.isFinite(size)
      ? this.shown() === size
      : !this.hasMore() && this.matching().length > 0;
  }

  protected showMore(): void {
    this.shown.update((n) => n + MORE_ROWS);
  }

  /** Any narrowing at all resets the cap: page 3 of the old filter is not page 1 of the new. */
  protected narrow(apply: () => void): void {
    apply();
    this.shown.set(INITIAL_ROWS);
  }

  private readonly service = inject(ArtifactsService);
  private readonly catalogue = inject(CatalogueService);
  private readonly buildsService = inject(BuildsService);
  private readonly rotationsService = inject(RotationsService);
  private readonly teamsService = inject(TeamsService);
  private readonly rankingService = inject(ArtifactRankingService);

  /**
   * Rank every owned piece against the chosen build and rotation.
   *
   * **A job with progress, never a request that blocks.** A cold calibration is ~3.2 s of gcsim
   * in this tab; `RESEARCH_recipe_cost.md` is explicit that anything in this area is a job the
   * user can walk away from. A warm `recipe-cache.ts` entry — which the user already has if
   * they have optimized this build — skips it entirely.
   */
  /** Choosing a rotation re-scopes the builds, so a stale choice must not survive it. */
  protected chooseRotation(rotationId: string): void {
    this.rankRotationId.set(rotationId);
    if (!this.buildChoices().some((choice) => choice.id === this.rankBuildId())) {
      this.rankBuildId.set('');
    }
  }

  protected async rankAgainstBuild(): Promise<void> {
    if (!this.canRank()) return;
    this.rankError.set('');
    this.rankProgress.set({ done: 0, total: 1, current: 'starting', loading: true });
    try {
      const result = await this.rankingService.rank({
        buildId: this.rankBuildId(),
        rotationId: this.rankRotationId(),
        onProgress: (progress) => this.rankProgress.set(progress),
        extraSets: this.extraSets(),
      });
      this.ranked.set(new Map(result.rows.map((row) => [row.id, row])));
      this.uncalibratedSets.set(result.uncalibratedSets);
      this.rankBaseline.set(result.baseline);
      this.rankCaveat.set(result.weightsCaveat);
      this.rankCaveats.set(result.caveats);
      // Sorting by the thing just computed, because leaving the list in roll-value order after
      // a 3-second job would make the result invisible — the defect this page already shipped
      // once, with a page-size control eleven screens down.
      this.narrow(() => this.sortBy.set('averageDelta'));
    } catch (err) {
      this.rankError.set(apiErrorMessage(err));
      this.ranked.set(new Map());
      this.uncalibratedSets.set([]);
    } finally {
      this.rankProgress.set(null);
    }
  }

  /**
   * Calibrate one more 4-piece set and rank again (OQ-A8).
   *
   * The set is **added** to what has already been asked for rather than replacing it, so
   * unlocking a second set does not silently re-refuse the first — and `recipe-cache.ts` means
   * the ones already calibrated cost nothing the second time.
   */
  protected async calibrateSet(set: { setId: number; uuid: string; name: string }): Promise<void> {
    if (this.extraSets().some((chosen) => chosen.setId === set.setId)) return;
    this.extraSets.update((chosen) => [
      ...chosen, { uuid: set.uuid, setId: set.setId, name: set.name },
    ]);
    await this.rankAgainstBuild();
  }

  /**
   * Re-optimize the whole build around one piece, at its projected max level.
   *
   * The number issue #291 actually asks for. The column's delta is a **lower bound** on this,
   * because a re-search may keep the same four neighbours and never does worse.
   */
  protected async diveInto(row: ArtifactRow): Promise<void> {
    if (this.diveRunning()) return;
    this.diveId.set(row.id);
    this.dive.set(null);
    this.diveError.set('');
    this.diveRunning.set(true);
    try {
      this.dive.set(await this.rankingService.deepDive({
        buildId: this.rankBuildId(),
        rotationId: this.rankRotationId(),
        artifactId: row.id,
        extraSets: this.extraSets(),
      }));
    } catch (err) {
      this.diveError.set(apiErrorMessage(err));
    } finally {
      this.diveRunning.set(false);
    }
  }

  protected closeDive(): void {
    this.diveId.set('');
    this.dive.set(null);
    this.diveError.set('');
  }

  /** A signed percentage, for a number that is a share of the build's own damage. */
  protected asPercent(fraction: number): string {
    const pct = fraction * 100;
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
  }

  /** How the winning build differs from what is worn, in slots. */
  protected movedCount(dive: DeepDive): number {
    return dive.moved.filter((piece) => piece.changed).length;
  }

  /** `delta` as a share of the build's own damage — #291's "% gain". */
  protected deltaPercent(row: ArtifactRow, which: 'delta' | 'averageDelta' | 'best'): string {
    const base = this.rankBaseline();
    const rank = row.rank;
    if (!rank || rank.refusal || !base) return '';
    const value = which === 'best' ? rank.best - base : rank[which];
    if (!Number.isFinite(value)) return '';
    const pct = (value / base) * 100;
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
  }

  /** Why a ranked piece has no number, in words a user can act on. */
  protected refusalText(row: ArtifactRow): string {
    switch (row.rank?.refusal) {
      case 'noSchedule':
        return 'no upgrade schedule for this rarity and level';
      case 'noLadders':
        return 'no roll data for this rarity';
      case 'needsCalibration':
        return 'would complete an uncalibrated set — see above';
      default:
        return '';
    }
  }

  ngOnInit(): void {
    void this.load();
    void this.loadRankingChoices();
  }

  /**
   * The builds and rotations the ranking picker offers.
   *
   * Not awaited by `load` and not inside its `Promise.all`: the inventory is the page, and a
   * list of cards that will not render until an unrelated endpoint answers is the same mistake
   * the set art already avoids here.
   */
  private async loadRankingChoices(): Promise<void> {
    try {
      const [builds, rotations, teams] = await Promise.all([
        this.buildsService.list(),
        this.rotationsService.list(),
        this.teamsService.list(),
      ]);
      this.allBuilds.set(builds);
      this.teams.set(teams);
      this.rotationTeam.set(new Map(rotations.items.map((r) => [r.id, r.team_id])));
      this.rotationChoices.set(
        rotations.items.map((rotation) => ({ id: rotation.id, label: rotation.name })),
      );
    } catch {
      // Silent by design: the ranking panel simply offers nothing, and the inventory below it
      // is unaffected. Surfacing this as a page error would make a working page look broken.
      this.allBuilds.set([]);
      this.teams.set([]);
      this.rotationChoices.set([]);
    }
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [options, page] = await Promise.all([
        this.service.options(),
        this.service.list(this.filters()),
      ]);
      this.options.set(options);
      this.artifacts.set(page.items);
      this.total.set(page.total);
      this.truncated.set(page.truncated);
      // Deliberately not awaited and deliberately not in the `Promise.all` above: art is
      // decoration, and an inventory that will not render until the set catalogue arrives
      // is an inventory held hostage by a picture.
      void this.loadSetArt();
    } catch {
      // Surfaced, not swallowed: an empty inventory and a failed request look identical, and
      // only one of them means the account has nothing in it.
      this.error.set('Could not load your artifacts.');
      this.artifacts.set([]);
      this.total.set(0);
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Fill {@link setIcons}. Failure is silent — the pieces render without art.
   *
   * Once per session. `load()` re-runs on every slot filter and every page change, and the
   * 65 artifact sets do not change between them; without this guard, filtering to Circlets
   * refetched the whole set catalogue to rebuild an identical map.
   */
  private async loadSetArt(): Promise<void> {
    if (this.setIcons().size > 0) return;
    try {
      const page = await this.catalogue.listArtifactSets({ limit: 200 });
      this.setIcons.set(new Map(page.items.map((set) => [
        set.id, { ...(set.part_icons ?? {}), '': set.icon ?? null },
      ])));
    } catch {
      // No `error` signal: this failing means the cards have no pictures, which is not a
      // state worth telling somebody about while their inventory is on screen.
    }
  }

  /** `[1..stars]`, so the template can draw one ★ per rarity point. */
  protected starList(stars: number): number[] {
    return Array.from({ length: Math.max(0, stars) }, (_, i) => i + 1);
  }

  /**
   * The bars, the tooltip and the roll-value column all come from `shared/substat-bars`.
   *
   * They were defined here first and the optimize page needed the same three (§16). What is
   * shared is not the markup but **what a bar claims** — an unknown tier is not tier zero, an
   * estimated count is not a fact, a tie is weaker than an estimate — and a second copy would
   * have kept the colours and quietly lost the caveats.
   */
  protected readonly rollBars = rollBars;
  protected readonly barsTitle = barsTitle;
  protected readonly rollValuePercent = rollValuePercent;

  /**
   * The piece's roll value as **what it got out of what those rolls could have been**.
   *
   * A bare `789%` is a number with no scale — it means nothing without knowing the piece had
   * nine rolls to spend. Against the maximum those nine could have produced (`900%`) it says
   * the thing a reader actually wants: how well this artifact rolled.
   *
   * Null unless every substat contributed both a value and a count, because a total silently
   * short one line reads as a worse artifact rather than as an incomplete sum.
   */
  protected totalRollValue(row: ArtifactRow): { got: number; max: number | null } | null {
    if (!row.substats.length) return null;
    let sum = 0;
    let rolls = 0;
    let counted = true;
    for (const sub of row.substats) {
      // The numerator needs no roll count — `roll_value` is value over the best single roll.
      // Only the denominator does, so a line without a count costs the *scale*, not the
      // number. Returning null for the whole thing took the headline off 11% of pieces that
      // had shown one, which is the opposite of the point.
      if (sub.rollValue === null) return null;
      sum += sub.rollValue;
      if (sub.rolls === null) counted = false;
      else rolls += sub.rolls;
    }
    return { got: Math.round(sum * 100), max: counted ? rolls * 100 : null };
  }

  protected canImport(): boolean {
    return this.mode !== '' && this.payloadText.trim().length > 0 && !this.importing();
  }

  /**
   * Read a chosen `.json` into the same buffer a paste fills.
   *
   * One path through the importer, not two: the file becomes text and everything downstream
   * — the `JSON.parse` that distinguishes a bad file from a server error, the rejection
   * list, the re-equip report — is unchanged. A separate upload endpoint would be a second
   * implementation of a flow that already reports carefully.
   *
   * A 2,370-artifact export is a couple of megabytes, which `text()` handles without a
   * streaming reader.
   */
  protected async chooseFile(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    this.actionError.set(null);
    this.importResult.set(null);
    try {
      this.payloadText = await file.text();
      this.fileName.set(file.name);
    } catch {
      // A file the browser cannot read — removed mid-pick, or a permissions failure. Said
      // plainly rather than left as an empty box the Import button silently refuses.
      this.fileName.set(null);
      this.actionError.set(`Could not read ${file.name}.`);
    } finally {
      // Cleared so re-picking the *same* file fires `change` again. Without this, a user who
      // edits their export and re-selects it sees nothing happen.
      input.value = '';
    }
  }

  /** Drop a loaded file, so the box is visibly empty rather than holding a stale export. */
  protected clearPayload(): void {
    this.payloadText = '';
    this.fileName.set(null);
    this.importResult.set(null);
    this.actionError.set(null);
  }

  /**
   * True while a `replace` would delete pieces that already exist.
   *
   * The default is `replace` by owner ruling, which is right for a re-scan — but paste-then-
   * Import would then permanently delete an inventory in one click, and a scanner that died
   * half way through 2,370 pieces writes a *valid* GOOD file holding a fraction of them.
   * The default stays; the irreversible one-click path does not.
   */
  protected readonly confirmingReplace = signal(false);

  protected needsConfirmation(): boolean {
    return this.mode === 'replace' && this.total() > 0;
  }

  protected cancelReplace(): void {
    this.confirmingReplace.set(false);
  }

  protected async runImport(): Promise<void> {
    if (!this.canImport()) return;
    if (this.needsConfirmation() && !this.confirmingReplace()) {
      this.confirmingReplace.set(true);
      return;
    }
    this.confirmingReplace.set(false);
    this.actionError.set(null);
    this.importResult.set(null);
    this.importing.set(true);
    try {
      const parsed: unknown = JSON.parse(this.payloadText);
      this.importResult.set(
        await this.service.importGood(
          this.mode as ImportMode, parsed, this.rebuildBuilds,
        ),
      );
      await this.load();
    } catch (err) {
      // A `SyntaxError` from `JSON.parse` is the user's file, not the server's fault — said
      // as such rather than as an API error, which would send them looking in the wrong place.
      this.actionError.set(
        err instanceof SyntaxError
          ? 'That file is not valid JSON. A GOOD export is a .json file.'
          : apiErrorMessage(err),
      );
    } finally {
      this.importing.set(false);
    }
  }

  protected async remove(row: ArtifactRow): Promise<void> {
    this.actionError.set(null);
    try {
      await this.service.remove(row.id);
      await this.load();
    } catch (err) {
      this.actionError.set(apiErrorMessage(err));
    }
  }

  protected async filterBySlot(slot: string): Promise<void> {
    this.slotFilter = slot;
    await this.load();
  }

  /** Server-side, so `total` is computed with the same `WHERE` the list used. */
  private filters(): { slot?: ArtifactSlotKey } {
    return this.slotFilter ? { slot: this.slotFilter as ArtifactSlotKey } : {};
  }
}



