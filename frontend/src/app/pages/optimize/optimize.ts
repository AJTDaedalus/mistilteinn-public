import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, OnInit, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import { CardPicker, type CardOption } from '../../shared/card-picker/card-picker';
import { Combobox } from '../../shared/combobox/combobox';
import { buildOptions, buildsInTeam, teamOptions } from '../../shared/team-scope';
import { ElementChip } from '../../shared/element/element';
import { CatalogueIcon } from '../../shared/icon/icon';
import { ArtifactCard } from '../../shared/artifact-card/artifact-card';
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
import type { ArtifactSetChoice } from './optimize.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService, type TeamRead } from '../teams/teams.service';
import { isFilterableMainStat, sortMainStats } from '../../shared/stat-order';
import { scoreForSlot } from '../../sim/artifact-score';
import type { Recipe } from '../../sim/recipe';
import { evaluateRecipe } from '../../sim/recipe-eval';
import {
  browserStore, recallAmong, recallSelections, remember, rememberSelections,
  type Selections,
} from './remembered';
import type { ArtifactCardModel } from '../../shared/artifact-card/artifact-card';
import { describeStat } from '../../shared/stat-label';
import { substatReadings } from '../../shared/substat-bars/substat-bars';
import { groupStats, type StatAccount, type StatGroup } from '../../shared/stat-groups';
import { energyShortfall, type EnergyShortfall } from '../../sim/recipe-energy';
import { energyDelayMessage } from '../../sim/energy-delay';
import { damageShare, type CharacterShare } from '../../sim/damage-share';
import {
  candidateStatsFrom,
  liveQuantitiesFor,
  searchRecipe,
} from '../../sim/recipe-search';
import {
  RecipeOptimizeService,
  type CalibrationResult,
  type CalibrationCaveats,
  type CalibrationProgress,
  type CalibrationTarget,
} from './recipe-optimize.service';
import {
  OptimizeService,
  type KernelCandidate,
  type UnreadableArtifact,
} from './optimize.service';

/**
 * How much of a recipe's damage must sit behind frozen conversions before the ranking is
 * called into question. Above this the order is not to be trusted; below it the terms are a
 * footnote, which is the distinction `damageShare` was added to make.
 *
 * Five per cent is a judgement, not a measurement — stated so nobody reads it as one. The case
 * this was written for measured 90.3%.
 */
const SHAKY_DAMAGE_SHARE = 0.05;

/** One result row, with the pieces named rather than left as ids. */
export interface ResultRow {
  rank: number;
  damage: number;
  artifactIds: string[];
  pieces: string[];
  /**
   * Damage against the comparator, as a fraction — `0.043` is +4.3%. Null when no comparator
   * could be established, which is not the same as being level with one.
   */
  percent?: number | null;
}

/**
 * Describe a build's five pieces from the candidates the search was given.
 *
 * Named from the same candidates the kernel scored, not re-fetched: a second lookup could
 * disagree with what was actually searched, and the row would then describe a build the
 * ranking did not produce.
 */
/**
 * Damage added by one maximum 5★ roll of each substat, on one build over its rotation.
 *
 * Pure and exported so it can be tested without a page: the interesting behaviour is which
 * quantities it *refuses* to answer for, and that deserves assertions of its own.
 */
export function marginalPerRoll(
  recipe: Recipe,
  pools: readonly Record<string, number>[],
): { quantity: string; delta: number }[] {
  // **Only stats the recipe can respond to.** A recipe is calibrated at one set of stats, so
  // anything it does not read is frozen into its coefficients — Elemental Mastery most of all,
  // whose contribution to a reaction lands in `ampMultiplier` and to Nahida's own bonus in
  // `bonusDmg`. Evaluating a bump in one of those returns exactly zero, and printing that
  // beside real numbers claims the stat is worthless rather than unmodelled.
  //
  // `liveQuantitiesFor` already answers this — it is what the Pareto filter uses to decide
  // which quantities can matter — so the same definition serves both.
  const live = new Set(liveQuantitiesFor(recipe));
  const base = evaluateRecipe(recipe, candidateStatsFrom(pools));
  return Object.entries(ONE_ROLL)
    .filter(([, spec]) => live.has(spec.quantity))
    .map(([quantity, spec]) => {
      const stats = { ...candidateStatsFrom(pools) };
      // Applied to the resolved stats rather than to a pool, so a quantity the pools do not
      // already contain still moves — a build with no EM must still be able to ask what EM
      // would be worth.
      const bumped = {
        ...stats, [quantity]: (stats[quantity as keyof typeof stats] as number) + spec.roll,
      };
      return { quantity, delta: evaluateRecipe(recipe, bumped as typeof stats) - base };
    })
    .filter((row) => Number.isFinite(row.delta))
    .sort((a, b) => b.delta - a.delta);
}

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
 * One maximum 5-star roll of each substat, as a stat delta.
 *
 * The comparison a player makes is "one good roll of each", so these are the top tier. Stated
 * rather than fetched because this table is a *ratio between stats*: mixing rarities would
 * compare a 4-star's CRIT DMG against a 5-star's ATK% and read as a difference in worth.
 *
 * Values are the top-tier rolls in `app/data/yuanshen/snapshot/` that `substat_rolls._tiers_for`
 * reads — flat ATK/HP/DEF omitted deliberately, because their worth depends on a base this
 * table does not carry and showing them beside percentages invites the wrong comparison.
 */
const ONE_ROLL: Readonly<Record<string, { roll: number; quantity: string }>> = {
  atkPercent: { roll: 0.0583, quantity: 'atk_pct' },
  hpPercent: { roll: 0.0583, quantity: 'hp_pct' },
  defPercent: { roll: 0.0729, quantity: 'def_pct' },
  elementalMastery: { roll: 23.31, quantity: 'elemental_mastery' },
  critRate: { roll: 0.0389, quantity: 'crit_rate' },
  critDmg: { roll: 0.0777, quantity: 'crit_dmg' },
};

/** Slots in the order `searchRecipe` returns a build's pieces. */
export const SLOT_ORDER = [
  'equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring', 'equip_dress',
];

/** How many alternatives to name per slot. Enough to choose from, few enough to read. */
const UPGRADES_PER_SLOT = 3;

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
  imports: [
    FormsModule, RouterLink, DecimalPipe, PercentPipe,
    CardPicker, CatalogueIcon, ElementChip, EntityToken, ArtifactCard, Combobox,
  ],
  templateUrl: './optimize.html',
  styleUrl: './optimize.scss',
})
export class OptimizePage implements OnInit {
  protected readonly channels = CHANNELS;
  protected readonly scopes = SCOPES;
  protected readonly talentLabel = talentLabel;

  /** Where the last selection is kept. Read once: it cannot change under the page. */
  private readonly store = browserStore();
  /**
   * A card per artifact named by the current results, keyed by id (§16).
   *
   * **Fetched by id after a search, not carried by the search.** What the kernel ranks is
   * `KernelCandidate` — id, slot, set, stats, main stat — which has no level, no art and no
   * substats, and widening it would widen `/artifacts/inventory`: the *whole* inventory,
   * ETag'd precisely so it is not re-sent. Ten rows of five pieces is fifty rows to fetch.
   *
   * Empty is a normal state, not an error: the cards are an enrichment, and a row still shows
   * its rank, its damage and its slot names without them.
   */
  protected readonly cards = signal<Map<string, ArtifactCardModel>>(new Map());
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
  protected readonly artifactSets = signal<ReadonlyMap<number, ArtifactSetChoice>>(new Map());
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
   * Start from a team, then pick who in it (owner's audit, §6).
   *
   * **Optional, deliberately.** A build in no team would otherwise be unreachable from this
   * page — 75 builds and eight teams on the owner's account, so most of them. Clearing the
   * team widens the build grid back to everything rather than emptying it.
   */
  protected readonly teams = signal<TeamRead[]>([]);
  protected readonly teamId = signal('');

  protected readonly team = computed(
    () => this.teams().find((t) => t.id === this.teamId()) ?? null,
  );

  /** The builds the chosen team fields, in slot order, or every build when none is chosen. */
  protected readonly buildsInScope = computed(
    () => buildsInTeam(this.team(), this.builds()),
  );

  protected readonly teamOptions = computed(() => teamOptions(this.teams(), this.builds()));

  protected readonly buildOptions = computed(() => buildOptions(this.buildsInScope()));
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
      // **And that gcsim implements.** Offering one it has no key for is offering a run that
      // cannot happen: the backend refuses the whole calibration with a 422 naming the set, so
      // a mixed selection returned *nothing* rather than the sets it could have done. "All
      // 4-piece" made that the one-click default.
      //
      // `!== false`, not `?? false`: a set the catalogue has **no entry for** is unknown, not
      // known-bad. `loadFilterData` swallows its own failure by design, and treating an empty
      // catalogue as "nothing is simulable" would turn that into a silently disabled feature —
      // the same shape as a gate with nothing able to satisfy it.
      .filter(([setId]) => catalogue.get(setId)?.simulable !== false)
      .map(([setId, slots]) => ({
        setId,
        name: catalogue.get(setId)?.name ?? `set ${setId}`,
        slots: slots.size,
      }))
      .sort((a, b) => b.slots - a.slots || a.name.localeCompare(b.name));
  });

  /**
   * Sets the inventory can field four of that gcsim cannot simulate at the pin.
   *
   * **Named rather than silently dropped.** A set vanishing from the picker with no
   * explanation is indistinguishable from not owning enough of it, and the reason is worth
   * saying: it is usually a set released after the pin, which is a re-pin rather than a fault.
   */
  protected readonly unsimulableSets = computed(() => {
    const catalogue = this.artifactSets();
    return [...this.slotsBySet(this.candidates())]
      .filter(([, slots]) => slots.size >= 4)
      .filter(([setId]) => catalogue.get(setId)?.simulable === false)
      .map(([setId]) => catalogue.get(setId)?.name ?? `set ${setId}`)
      .sort((a, b) => a.localeCompare(b));
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

  /**
   * The two set controls, as card grids (owner's audit, §6).
   *
   * ## The two are mutually exclusive, per set
   *
   * A set chosen as a 4-piece is not offered as half of a 2+2 pair, and the reverse. Both are
   * *configurations of the same five slots*, so a set can only be one of them in any build the
   * search actually returns — offering it in both is offering a choice the answer cannot honour.
   *
   * ## A lone 2-piece is not a filter
   *
   * `chosenPair` already required two distinct sets, and the pair control is capped at two for
   * the same reason: this search enumerates a 4-piece or a 2+2, and "two of X plus three of
   * anything" is neither. One set selected is an unfinished pair, said out loud rather than
   * silently searching nothing.
   */
  private cardFor(setId: number, slots: number): CardOption {
    const known = this.artifactSets().get(setId);
    return {
      value: String(setId),
      label: known?.name ?? `set ${setId}`,
      icon: known?.icon,
      detail: `${slots} slots`,
      // The 4-piece bonus in the set's own words — what anyone is actually choosing between,
      // and too long for a card.
      tooltip: known?.fourPieceText ?? undefined,
    };
  }

  protected readonly fourPieceOptions = computed<CardOption[]>(() => {
    const inPair = new Set([this.pairFirst(), this.pairSecond()]);
    return this.fourPieceChoices()
      .filter((choice) => !inPair.has(choice.setId))
      .map((choice) => this.cardFor(choice.setId, choice.slots));
  });

  protected readonly pairOptions = computed<CardOption[]>(() =>
    this.fourPieceChoices()
      .filter((choice) => !this.selectedSets().has(choice.setId))
      .map((choice) => this.cardFor(choice.setId, choice.slots)),
  );

  protected readonly fourPieceSelected = computed(() =>
    [...this.selectedSets()].map(String),
  );

  protected readonly pairSelected = computed(() =>
    [this.pairFirst(), this.pairSecond()]
      .filter((id): id is number => id !== null)
      .map(String),
  );

  protected setFourPiece(ids: readonly string[]): void {
    this.selectedSets.set(new Set(ids.map(Number)));
  }

  /**
   * Keep the **last two** picked rather than refusing the third.
   *
   * A capped multi-select that ignores a click is a control that looks broken; one that drops
   * the oldest choice does what the user plainly meant — they are swapping, not adding.
   */
  protected setPair(ids: readonly string[]): void {
    const kept = ids.slice(-2).map(Number);
    this.pairFirst.set(kept[0] ?? null);
    this.pairSecond.set(kept[1] ?? null);
  }

  /** An uncovered set, named. Ids are what the search returns; names are what a user reads. */
  protected setLabel(setId: number): string {
    return this.artifactSets().get(setId)?.name ?? `set ${setId}`;
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

  /**
   * Fetch a card for every piece the current results name (§16).
   *
   * An effect rather than a call at the end of `run()`: there are two searches on this page
   * and both set `result`, so hanging this off the results themselves is the version that
   * cannot be half-wired. A rotation search that forgot the call would show cards on the
   * single-hit tab and none on the tab the page exists for.
   */
  private readonly fetchCards = effect(() => {
    void this.loadCards(this.rows());
  });

  /**
   * The artifacts behind the current rows, by id.
   *
   * **Never fatal.** The cards enrich a row that is already complete without them — rank,
   * damage, and the five slot names — so a failure here leaves them off rather than replacing
   * a good ranking with an error.
   */
  private async loadCards(rows: readonly ResultRow[]): Promise<void> {
    const ids = [...new Set(rows.flatMap((row) => row.artifactIds))];
    if (ids.length === 0) {
      this.cards.set(new Map());
      return;
    }
    // **Which results these cards are for.** Two searches can be in flight — the single-hit
    // one is fast and the rotation one is minutes — so a slow reply can land after a newer
    // ranking has replaced the rows it was fetched for. Painting it then would put the
    // previous search's pieces under the current search's numbers, which is the failure this
    // page already guards against by dropping `result` when the build changes: a row that
    // looks right and refers to something else.
    const wanted = ids.join(',');
    const stillWanted = (): boolean =>
      [...new Set(this.rows().flatMap((row) => row.artifactIds))].join(',') === wanted;
    try {
      const [page, options] = await Promise.all([
        this.artifacts.list({ ids }),
        this.artifacts.options(),
      ]);
      const pieces = page.items;
      const stats = new Map(options.stats.map((stat) => [stat.key, stat]));
      const slots = this.slotNames();
      // The artifact carries the catalogue's set id; `artifactSets` is keyed by nanoka's.
      // Re-key rather than look up by the wrong one — the two id spaces are the trap this
      // page already documents on `artifactSets`.
      //
      // **Per slot, falling back to the set's own icon.** nanoka's set icon is the *flower*,
      // so using it everywhere drew five flowers per build — the owner's "do we not have
      // icons for anything but the flowers?". `part_icons` is null on a database seeded
      // before that column, and the fallback is then exactly the old behaviour.
      const art = new Map<string, { set: string | null; parts: Record<string, string> | null }>();
      for (const set of this.artifactSets().values()) {
        art.set(set.id, { set: set.icon ?? null, parts: set.partIcons });
      }

      if (!stillWanted()) return;
      this.cards.set(new Map(pieces.map((piece) => [piece.id, {
        id: piece.id,
        icon: (() => {
          const found = art.get(piece.artifact_set_id ?? '');
          return found?.parts?.[piece.slot] ?? found?.set ?? null;
        })(),
        setName: piece.set_name ?? 'No set',
        slot: slots[piece.slot] ?? piece.slot,
        level: piece.level,
        mainStat: describeStat(piece.main_stat_type, piece.main_stat_value, stats),
        substats: substatReadings(
          piece.substats as { stat?: string; value?: unknown }[],
          piece.substat_analysis,
          (stat, value) => describeStat(stat, value, stats),
        ),
      }])));
    } catch {
      // Same guard on the failure path: clearing the cards for results that are no longer on
      // screen would blank the ones that are.
      if (stillWanted()) this.cards.set(new Map());
    }
  }

  /**
   * The character's current build, scored on the recipe matching the set it wears (§11).
   *
   * Returns null rather than a number this page cannot stand behind. Three ways that happens,
   * and each is a real state rather than an error:
   *
   * - the build has fewer than five artifacts on it, so there is no build to score;
   * - a piece it wears was not in the search's candidate pool (a main-stat filter removed it),
   *   so its stats are not to hand;
   * - it wears a 4-piece nobody calibrated, and scoring it on another set's recipe would
   *   credit it a bonus it does not have — the same mistake §10 just removed from `upgrades`.
   *
   * The caller falls back to rank 1, which is the owner's stated fallback for a character with
   * no build at all.
   */
  private comparatorFrom(
    pieces: readonly KernelCandidate[],
    calibrated: CalibrationResult,
  ): { damage: number; label: string } | null {
    const equipped = this.equippedIds();
    if (equipped.length !== SLOT_ORDER.length) return null;

    const byId = new Map(pieces.map((piece) => [piece.id, piece]));
    const worn = equipped.map((id) => byId.get(id));
    if (worn.some((piece) => piece === undefined)) return null;

    const present = worn as KernelCandidate[];
    const counts = new Map<number, number>();
    for (const piece of present) {
      const setId = piece.set_id ?? -1;
      counts.set(setId, (counts.get(setId) ?? 0) + 1);
    }
    let fourPiece: number | null = null;
    for (const [setId, count] of counts) if (count >= 4) fourPiece = setId;

    // A build wearing no 4-piece is scorable only if the no-four-piece recipe exists; a build
    // wearing one nobody calibrated is not scorable at all. Both come back null here rather
    // than borrowing another set's recipe, which would credit a bonus the build does not have
    // — the mistake §10 removed from `upgrades`, and it would be worse here because every row
    // on the page is a percentage of this number.
    const recipe = fourPiece === null
      ? calibrated.noFourPiece
      : calibrated.byFourPieceSet.get(fourPiece);
    if (!recipe) return null;

    // In `SLOT_ORDER`, matching `winningPools`, so the two are assembled the same way.
    //
    // **Not for correctness**: `candidateStatsFrom` sums the pools, so the order genuinely
    // cannot change the number. An earlier version of this comment claimed it could, which
    // would have been a good reason and is not a true one.
    const pools = SLOT_ORDER.map(
      (slot) => present.find((piece) => piece.slot === slot)?.stats ?? {},
    );
    return {
      damage: evaluateRecipe(recipe, candidateStatsFrom(pools)),
      label: 'your current build',
    };
  }

  /**
   * The expanded row's stats, grouped as a reader thinks of them rather than as the server
   * happened to record them. A `computed`, so it is not rebuilt on every change-detection
   * tick — the same trap `marginalForExpanded` documents.
   */
  protected readonly statGroups = computed<StatGroup[]>(() => {
    const shown = this.pairing()?.shown;
    if (!shown) return [];
    return groupStats(
      shown.result.stats as unknown as StatAccount[],
      // The resolved values the chain acts on. Empty from a server that predates the field,
      // which renders groups without a headline rather than inventing one.
      (shown.result.totals ?? {}) as Record<string, number>,
      this.slotNames(),
    );
  });

  /**
   * Who actually deals this row's damage — gcsim reports it and this page did not.
   *
   * Evaluated with the row's own pieces, so it is the share *for this result*: the optimized
   * character's slice grows with their artifacts while teammates stay where gcsim measured
   * them. It is also what makes a small delta legible — a build whose teammates are 86% of the
   * damage cannot move the total much, and that is the rotation's shape rather than a fault.
   */
  protected readonly rowDamageShare = computed<CharacterShare[]>(() => {
    const row = this.pairing()?.row;
    const recipe = this.scoredRecipe();
    if (!row || !recipe) return [];
    const pools = this.poolsFor(row);
    return pools ? damageShare(recipe, candidateStatsFrom(pools)) : [];
  });

  /** The cards for one row, in the order the row names its pieces. */
  protected cardsFor(row: ResultRow): ArtifactCardModel[] {
    const known = this.cards();
    return row.artifactIds
      .map((id) => known.get(id))
      .filter((card): card is ArtifactCardModel => card !== undefined);
  }

  protected readonly rows = computed<ResultRow[]>(() => {
    const found = this.result();
    if (!found) return [];
    const pieces = this.candidates();
    const names = this.slotNames();
    // Rank 1 is the fallback comparator, so a page with no equipped build still shows a
    // gradient rather than five bare numbers (§11).
    const against = this.comparator()?.damage ?? found.builds[0]?.damage ?? null;
    return found.builds.map((build, index) => ({
      rank: index + 1,
      damage: build.damage,
      artifactIds: build.artifactIds,
      pieces: describePieces(build.artifactIds, pieces, (slot) => names[slot] ?? slot),
      // Null rather than 0 when there is nothing to compare against: "the same as the
      // comparator" and "there is no comparator" are different, and both would render as 0%.
      percent: against ? (build.damage - against) / against : null,
    }));
  });

  /**
   * Put a result's five pieces onto the build that was searched for (owner, 2026-08-29).
   *
   * ## It checks before it moves anything
   *
   * A piece held by *another* build is refused by the API, naming the holder (A.1) — and by
   * then this would already have taken the build's own pieces off, leaving it half equipped
   * because of a refusal it could have seen coming. So every winning piece is read first, and
   * a single one held elsewhere aborts the whole thing with nothing changed.
   *
   * That refusal is the honest one until **build priority** exists (backlog §3, *later*):
   * "steal it from the lower-ranked character" needs a ranking to know which character that
   * is, and silently unequipping someone else's piece without one is the same operation with
   * the accountability removed.
   *
   * ## What it reports
   *
   * How many moved, and how many were already there — because "equipped 5 pieces" after a
   * search that changed nothing reads as a change that did not happen.
   */
  protected async equipRow(row: ResultRow): Promise<void> {
    const buildId = this.buildId();
    if (!buildId || this.equipping()) return;
    let moving = false;
    this.equipping.set(true);
    this.equipped.set(null);
    this.actionError.set(null);
    try {
      const pieces = await Promise.all(row.artifactIds.map((id) => this.artifacts.get(id)));
      const heldElsewhere = pieces.filter(
        // `!= null` catches undefined as well: the generated type makes `build_id` optional,
        // and an absent field means the same thing as an explicit null — nobody holds it.
        (piece) => piece.build_id != null && piece.build_id !== buildId,
      );

      // **The ranking decides who keeps the piece** — `BACKLOG_frontend.md` §3, *"let a
      // higher-ranked character steal an artifact from a lower-ranked one"*. Until this, the
      // answer was always "nobody moves, go and undress the other build yourself", which is
      // the friction the ranking exists to remove.
      //
      // Lower number ranks higher; `null` is unranked and loses to anything ranked. **An
      // unranked build takes from no one**: without a rank there is no claim to make, and
      // silently preferring the build you happen to be looking at is how someone loses a
      // piece off a character they care about.
      const mine = this.builds().find((b) => b.id === buildId);
      const myRank = mine?.optimizer_priority ?? null;
      const outranks = (holderId: string): boolean => {
        if (myRank === null) return false;
        const holder = this.builds().find((b) => b.id === holderId);
        const theirs = holder?.optimizer_priority ?? null;
        return theirs === null || theirs > myRank;
      };
      const nameOf = (holderId: string): string =>
        this.builds().find((b) => b.id === holderId)?.character?.name ?? 'another build';

      const blocked = heldElsewhere.filter((piece) => !outranks(piece.build_id!));
      if (blocked.length) {
        const holders = [...new Set(blocked.map((piece) => nameOf(piece.build_id!)))];
        this.actionError.set(
          `${blocked.length} of these pieces are equipped to ${holders.join(', ')}, `
          + (myRank === null
            ? 'and this build has no priority. Rank it above them on Builds, or take the '
              + 'pieces off by hand.'
            : 'which rank above this build. Nothing was changed.'),
        );
        return;
      }

      // Taken, not silently moved: the report below names who lost what.
      const taken = heldElsewhere.map(
        (piece) => `${piece.set_name || piece.slot} from ${nameOf(piece.build_id!)}`,
      );
      for (const piece of heldElsewhere) await this.artifacts.equip(piece.id, null);

      const already = new Set(pieces.filter((p) => p.build_id === buildId).map((p) => p.id));
      const winners = new Set(row.artifactIds);
      // Past this line the build is being changed, so a failure is no longer "nothing
      // happened" — it is a build wearing some of two sets. Said plainly rather than left to
      // a bare API message that describes one request and not the state it left behind.
      moving = true;
      // Off first, then on. Equipping into a filled slot is refused rather than swapped (A.1),
      // so the order is not a preference — it is the only one that works.
      const current = await this.artifacts.list({ build_id: buildId });
      for (const piece of current.items) {
        if (!winners.has(piece.id)) await this.artifacts.equip(piece.id, null);
      }
      for (const id of row.artifactIds) {
        if (!already.has(id)) await this.artifacts.equip(id, buildId);
      }
      const moved = row.artifactIds.length - already.size;
      // **A piece taken off another build is said out loud.** The whole point of the ranking
      // is that a suggested piece is *owned*; a silent steal would leave someone wondering
      // later why a character they were not looking at is missing a goblet.
      const tookFrom = taken.length ? ` Took ${taken.join(', ')}.` : '';
      this.equipped.set(
        already.size === row.artifactIds.length
          ? `Already equipped — this build is wearing #${row.rank} already.`
          : `Equipped ${moved} piece${moved === 1 ? '' : 's'} from #${row.rank}`
            + (already.size ? `; ${already.size} were already on this build.` : '.')
            + tookFrom,
      );
    } catch (err) {
      // Verbatim: the API's refusal names the holding build, which is more useful than
      // anything this page could invent.
      this.actionError.set(
        apiErrorMessage(err)
        + (moving ? ' — pieces were already being moved, so check the build.' : ''),
      );
    } finally {
      this.equipping.set(false);
    }
  }

  /**
   * The red line naming who cannot burst on time, and by how long.
   *
   * Owner's wording. It reads off the recipe's `energyDelays`, which carry gcsim's own
   * per-character seconds; a rotation that stalls on energy loses DPS with nothing else on
   * screen to explain it — measured at **67 seconds** on the owner's own team.
   */
  protected readonly energyDelay = computed(
    () => energyDelayMessage(this.caveats()?.energyDelays ?? []),
  );

  protected readonly equipping = signal(false);
  /** Non-null after an equip that succeeded, saying what actually moved. */
  protected readonly equipped = signal<string | null>(null);

  /**
   * `equip_bracer` → `Flower`, from `/artifacts/options`.
   *
   * **Not a map written here.** `ArtifactSlot.display` already publishes these, and the first
   * draft of this page duplicated them — in the very chunk whose argument is that a second
   * copy of the server's vocabulary is how a silent divergence starts.
   */
  protected readonly slotNames = signal<Record<string, string>>({});
  /**
   * The five slots, in the order `/artifacts/options` gives them.
   *
   * From the payload rather than written out here: the slot vocabulary is the server's, and a
   * list restated in a template is the copy that goes stale.
   */
  protected readonly slotKeys = signal<string[]>([]);
  /** Raw main-stat key → display, from `/artifacts/options` — the one place stats are named. */
  protected readonly statNames = signal<Record<string, string>>({});

  /**
   * The main stats wanted per slot — `{ equip_ring: ['FIGHT_PROP_FIRE_ADD_HURT'] }`.
   *
   * **The first thing anyone decides about a Genshin build**, and the search had no way to
   * say it. A goblet is the clearest case: a DPS wants one elemental damage bonus and every
   * other goblet in the inventory is noise, so the constraint is not only a preference, it is
   * the largest single cut to a search space this page already fights to make finish.
   *
   * Empty means "any", per slot. Flower and plume are deliberately still offered even though
   * their main stat is fixed — hiding them would encode a game rule in a control's presence,
   * and a rule stated by an absence is one nobody can check.
   */
  protected readonly mainStatBySlot = signal<Record<string, readonly string[]>>({});

  /** The main stats actually present in the inventory for one slot, with their labels. */
  /**
   * The main stats this inventory holds for one slot, in the owner's order.
   *
   * **Flat stats are filtered out, which removes flower and plume entirely** — the audit asks
   * for exactly that (`BACKLOG_frontend.md` §6), and it reverses the argument #146 made for
   * offering them. That argument was that hiding a control states a game rule by an absence.
   * It is still true; the owner has weighed it against five controls where two can only ever
   * hold one value, and chosen. `stat-order` carries the reasoning so the trade is visible
   * rather than lost.
   */
  protected mainStatsFor(slot: string): { key: string; display: string }[] {
    const names = this.statNames();
    const keys = new Set(
      this.candidates().filter((c) => c.slot === slot).map((c) => c.main_stat),
    );
    return sortMainStats(
      [...keys]
        .filter(isFilterableMainStat)
        .map((key) => ({ key, display: names[key] ?? key })),
    );
  }

  /**
   * Toggle one main stat for one slot. **Several may be wanted at once** (owner, 2026-08-30).
   *
   * A user who will take ATK% *or* Elemental Mastery on the sands had to run the search twice
   * and compare two rankings by eye — which is the search doing less than it could, since both
   * are one walk over a slightly larger bucket.
   *
   * An empty list still means "any", so clearing the last one restores the whole slot rather
   * than leaving a constraint nothing satisfies.
   */
  protected toggleMainStat(slot: string, key: string): void {
    this.mainStatBySlot.update((current) => {
      const wanted = new Set(current[slot] ?? []);
      if (wanted.has(key)) wanted.delete(key);
      else wanted.add(key);
      return { ...current, [slot]: [...wanted] };
    });
  }

  /** Clear a slot back to "any". */
  protected clearMainStat(slot: string): void {
    this.mainStatBySlot.update((current) => ({ ...current, [slot]: [] }));
  }

  protected wantsMainStat(slot: string, key: string): boolean {
    return (this.mainStatBySlot()[slot] ?? []).includes(key);
  }

  protected anyMainStat(slot: string): boolean {
    return (this.mainStatBySlot()[slot] ?? []).length === 0;
  }

  /**
   * Candidates after the per-slot main-stat constraint.
   *
   * Applied to the **candidate list**, not inside the kernel: a piece the user has ruled out
   * should not be scored, calibrated against, or counted in a progress total. Filtering later
   * would make the search slower and the numbers it reports wrong.
   */
  protected constrained(pieces: readonly KernelCandidate[]): KernelCandidate[] {
    const wanted = this.mainStatBySlot();
    return pieces.filter((piece) => {
      const required = wanted[piece.slot] ?? [];
      // Empty is "any". A slot wanting several keeps a piece matching **one** of them.
      return required.length === 0 || required.includes(piece.main_stat);
    });
  }

  /** Slots whose constraint no piece satisfies — a search that would return nothing. */
  protected impossibleSlots(): string[] {
    const names = this.slotNames();
    const wanted = this.mainStatBySlot();
    const kept = this.constrained(this.candidates());
    return Object.keys(wanted)
      .filter((slot) => (wanted[slot] ?? []).length > 0 && !kept.some((p) => p.slot === slot))
      .map((slot) => names[slot] ?? slot);
  }

  // ── The rotation objective (R.8/R.9) ──────────────────────────────────────────────────
  //
  // The single-hit search above maximises **one hit**, which is a proxy — and the Chunk F
  // chain cannot see a conditional 4-piece bonus, which is **every 4-piece in the game**. The
  // rotation objective scores against gcsim's own arithmetic instead, at ~1.05x the cost.
  //
  // **Both stay reachable.** The fast one answers a different, legitimate question in
  // microseconds, and OQ-W4 settled the principle: deleting a fast honest answer because a
  // slow better one exists is a downgrade for whoever wanted the fast one.
  /**
   * Which question Optimize answers.
   *
   * **One button, not two** (owner, 2026-08-30). The page used to render `Search` in the top
   * row unconditionally *and* `Search rotation` beside this control, so choosing "best across
   * rotation" and then pressing the top button ran the single-hit search and silently ignored
   * everything the rotation block had been set to — the set filter included. The owner picked
   * a 4-piece, pressed the wrong one of two buttons that both said "search", and got a message
   * about their whole inventory. One button cannot be pressed by mistake.
   */
  /**
   * **Rotation, because that is what this page is for** (§15). Choosing which tool is in
   * front is not the same as inventing the user's data, and the two rules only look opposed:
   * the fields below start empty, this one does not.
   */
  protected readonly objective = signal<'hit' | 'rotation'>('rotation');
  protected readonly rotations = signal<{ id: string; name: string }[]>([]);

  /** The same list, in the shape `mist-combobox` reads. */
  protected readonly rotationOptions = computed(() =>
    this.rotations().map((r) => ({ value: r.id, label: r.name })),
  );
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
  /**
   * The recipe the last rotation search scored against, kept so the page can answer more than
   * one question with it.
   *
   * Calibration is the expensive part — roughly six seconds per set — and evaluating a
   * candidate afterwards is 0.048 µs per hit (#159). Throwing the recipe away at the end of a
   * search meant paying that six seconds again to ask anything else about the same build.
   */
  protected readonly scoredRecipe = signal<Recipe | null>(null);
  /** The five slot pools of the winning build, in `SLOTS` order — what a swap is measured against. */
  protected readonly winningPools = signal<Record<string, number>[] | null>(null);
  /**
   * The no-four-piece recipe from the same calibration, kept so a swap that *breaks* the
   * winner's set can be scored under the state it would actually be in.
   */
  protected readonly baselineRecipe = signal<Recipe | null>(null);
  /** The 4-piece set `scoredRecipe` assumes, or null when it is the no-four-piece recipe. */
  protected readonly scoredSetId = signal<number | null>(null);
  /** The set each of the winner's five pieces belongs to, in `SLOTS` order. */
  protected readonly winningSetIds = signal<number[] | null>(null);
  /**
   * What every row is a percentage *of* — §11, the owner's design.
   *
   * **The character's current build**, scored on whichever calibrated recipe matches the set
   * it actually wears, so the comparison is between two builds rather than between a build
   * and an abstraction. The page's other "baseline" — the calibration's `noFourPiece` recipe —
   * is a *scoring* artefact and was never meant to be read as one: the owner's "the 'no 4p'
   * baseline doesn't make any sense" was about seeing it in the interface, and it is right,
   * because nobody's build is "no four-piece".
   *
   * Null when it cannot be computed: the build wears a set nothing calibrated, or has no five
   * pieces on it yet. The page then falls back to **rank 1**, which is the owner's own
   * fallback for a character with no build — that row reads +0% and everything below it is
   * negative.
   */
  protected readonly comparator = signal<{ damage: number; label: string } | null>(null);
  /** The artifact ids the chosen build is wearing, for the comparator above. */
  protected readonly equippedIds = signal<string[]>([]);
  /**
   * The whole calibration from the last search, so a *row* can be answered about rather than
   * only the winner: row 3 may field a different 4-piece from row 1, and the marginal-roll
   * table under its details has to use its own recipe.
   */
  protected readonly calibration = signal<CalibrationResult | null>(null);

  /**
   * What one more roll of each substat is worth, in damage, on the winning build.
   *
   * **The Fribbels audit's third recommendation**, and the cheapest thing this page can now
   * answer: it already holds a calibrated recipe, and a roll is a stat delta. Fribbels shows
   * the same table as `+1x Substat → Δ Combo DMG`.
   *
   * It is also the honest form of what `DESIGN_artifact_ranking.md` first proposed as a
   * "weight vector" — measured against the real rotation rather than derived from a single
   * hit, which is the owner's ruling (`DECISIONS.md` §22).
   *
   * The roll sizes are the **maximum** roll for a 5-star, which is the comparison a player
   * makes: one good roll of each. They are stated here rather than fetched because this is a
   * ratio between stats, and a table that varied by rarity would compare a 4-star's CRIT DMG
   * against a 5-star's ATK%.
   */
  /**
   * What one more roll of each substat is worth, in damage, **on the build being looked at**.
   *
   * Owner: *"Let's roll 'what one more roll is worth' under details then, so it's relevant to
   * the set the user is looking at."* It used to be a standalone section computed only for the
   * winner, which made it a fact about rank 1 printed next to a list of ten.
   *
   * **The Fribbels audit's third recommendation**, and the cheapest thing this page can now
   * answer: it already holds a calibrated recipe, and a roll is a stat delta. Fribbels shows
   * the same table as `+1x Substat → Δ Combo DMG`.
   *
   * It is also the honest form of what `DESIGN_artifact_ranking.md` first proposed as a
   * "weight vector" — measured against the real rotation rather than derived from a single
   * hit, which is the owner's ruling (`DECISIONS.md` §22).
   *
   * The roll sizes are the **maximum** roll for a 5-star, which is the comparison a player
   * makes: one good roll of each. They are stated here rather than fetched because this is a
   * ratio between stats, and a table that varied by rarity would compare a 4-star's CRIT DMG
   * against a 5-star's ATK%.
   */
  /**
   * A `computed`, and called once from the template rather than per row.
   *
   * **The page runs on default change detection**, so a method called from the template runs
   * on every tick. This one rebuilds two `Map`s over the whole candidate list — 2,370 pieces
   * on the owner's account — and evaluates the recipe nine times. As `marginalFor(row)` inside
   * the `@for`, that ran for as long as a details pane stayed open, on every keystroke and
   * mouse event the page saw.
   *
   * Only one row is ever expanded, so this depends on `pairing()` and recomputes when the
   * expanded row changes rather than when anything at all does.
   */
  protected readonly marginalForExpanded = computed<{ quantity: string; delta: number }[]>(
    () => {
      const row = this.pairing()?.row;
      if (!row) return [];
      const pools = this.poolsFor(row);
      const recipe = this.recipeFor(row);
      return pools && recipe ? marginalPerRoll(recipe, pools) : [];
    },
  );

  /**
   * A bar's width as a percentage of the best line in the same table (§14).
   *
   * Guarded against a zero or negative best rather than trusting the sort: the list is ordered
   * descending, so `best` is the largest — but if every quantity evaluated to nothing, dividing
   * by it yields `Infinity` or `NaN` and Angular writes that straight into a style attribute.
   */
  protected barWidth(delta: number, best: number): number {
    if (!(best > 0)) return 0;
    return Math.max(0, Math.min(100, (delta / best) * 100));
  }

  /** One row's five stat pools, in `SLOT_ORDER`. Null if a piece it names is not to hand. */
  private poolsFor(row: ResultRow): Record<string, number>[] | null {
    const byId = new Map(this.candidates().map((piece) => [piece.id, piece]));
    const worn = row.artifactIds.map((id) => byId.get(id));
    if (worn.some((piece) => piece === undefined)) return null;
    const present = worn as KernelCandidate[];
    return SLOT_ORDER.map(
      (slot) => present.find((piece) => piece.slot === slot)?.stats ?? {},
    );
  }

  /**
   * The recipe this row was scored with — its own 4-piece state, not the winner's.
   *
   * The whole point of moving the table under details: row 3 may field a different set from
   * row 1, and answering "what is one more CRIT roll worth" with the winner's recipe would
   * describe a build the reader is not looking at.
   */
  private recipeFor(row: ResultRow): Recipe | null {
    const calibrated = this.calibration();
    if (!calibrated) return null;
    const byId = new Map(this.candidates().map((piece) => [piece.id, piece.set_id ?? -1]));
    const counts = new Map<number, number>();
    for (const id of row.artifactIds) {
      const setId = byId.get(id) ?? -1;
      counts.set(setId, (counts.get(setId) ?? 0) + 1);
    }
    for (const [setId, count] of counts) {
      if (count >= 4) return calibrated.byFourPieceSet.get(setId) ?? null;
    }
    return calibrated.noFourPiece;
  }

  /** Pieces in the inventory that would beat what the winning build wears, per slot. */
  /**
   * A piece, named the way a player would recognise it: set and main stat.
   *
   * **Not the id.** These are uuid7 and therefore *time-ordered*, so every artifact imported in
   * the same second shares a prefix — a truncated id rendered `01a04dfd` for all fifteen
   * upgrades on screen, an identifier that identifies nothing. Seen in a screenshot.
   */
  protected describe(id: string): string {
    const piece = this.candidates().find((c) => c.id === id);
    if (!piece) return id.slice(0, 8);
    // `.name`, not the row: `artifactSets()` maps to `{ id, name }`, and interpolating the
    // object rendered `[object Object]` on every upgrade. Seen in a screenshot.
    const set = piece.set_id != null ? this.artifactSets().get(piece.set_id)?.name : null;
    const stat = this.statNames()[piece.main_stat] ?? piece.main_stat;
    return set ? `${set} · ${stat}` : stat;
  }

  /**
   * Better pieces for each slot, scored **in the state the swap would actually leave**.
   *
   * §10. `scoreForSlot` has no notion of set membership — a set bonus is a constant baked into
   * the recipe — so scoring every swap under the winner's 4-piece recipe credited a bonus that
   * some swaps would remove. The owner's framing is the one that matters: a 4-piece build has
   * **one free slot**, so an off-set piece is legal and belongs in this list; what it needs is
   * for the cost of taking that slot to be visible.
   *
   * | the winning build | swap | before | now |
   * |---|---|---|---|
   * | five of the set | any slot for an off-set piece | leaves four — correct | unchanged |
   * | four + one off-set | a set slot for another off-set piece | leaves three — **wrong** | scored on the no-four-piece recipe |
   * | four + one off-set | the off-set slot | stays four — correct | unchanged |
   *
   * The middle row is the fix. Its delta is now usually negative, so it drops out of the list
   * on its own — which is the honest form of "they need to justify their existence": a piece
   * that pays for the whole set bonus and still wins is a real upgrade, and one that does not
   * was never one.
   */
  protected readonly upgrades = computed<
    { slot: string; rows: { id: string; label: string; delta: number; breaksSet: boolean }[] }[]
  >(() => {
    const recipe = this.scoredRecipe();
    const pools = this.winningPools();
    if (!recipe || !pools) return [];

    const names = this.slotNames();
    const setOf = new Map<string, number>();
    const bySlot = new Map<string, { id: string; stats: Record<string, number> }[]>();
    for (const piece of this.constrained(this.candidates())) {
      const list = bySlot.get(piece.slot) ?? [];
      list.push({ id: piece.id, stats: piece.stats });
      bySlot.set(piece.slot, list);
      setOf.set(piece.id, piece.set_id ?? -1);
    }

    // Null when the winner was scored on the no-four-piece recipe: no bonus exists, so no
    // swap can break one, and every candidate keeps the plain single-recipe scoring.
    const assumed = this.scoredSetId();
    const worn = this.winningSetIds();
    const fallback = this.baselineRecipe();
    const held = assumed === null || !worn
      ? 0
      : worn.filter((setId) => setId === assumed).length;

    return SLOT_ORDER.flatMap((slot, index) => {
      const candidates = bySlot.get(slot) ?? [];
      if (!candidates.length) return [];

      /** Does putting `id` in this slot still leave four of the assumed set? */
      const keepsSet = (id: string): boolean => {
        if (assumed === null || !worn) return true;
        const without = held - (worn[index] === assumed ? 1 : 0);
        return without + (setOf.get(id) === assumed ? 1 : 0) >= 4;
      };

      const scored = scoreForSlot(
        recipe, pools, candidates, index,
        // Without a no-four-piece recipe to fall back on there is nothing honest to score a
        // bonus-breaking swap with, so those are dropped below rather than scored wrongly.
        fallback ? (id) => (keepsSet(id) ? recipe : fallback) : undefined,
      )
        .filter(({ id }) => fallback !== null || keepsSet(id))
        // **Strictly better only.** A zero delta is the piece already worn, or one identical
        // to it; listing those as "upgrades" would pad the answer with non-answers.
        .filter(({ score }) => score.delta > 0)
        .sort((a, b) => b.score.delta - a.score.delta)
        .slice(0, UPGRADES_PER_SLOT)
        .map(({ id, score }) => ({
          id, label: this.describe(id), delta: score.delta, breaksSet: !keepsSet(id),
        }));
      return scored.length ? [{ slot: names[slot] ?? slot, rows: scored }] : [];
    });
  });

  protected readonly recipeNotes = signal<
    { uncoveredSets: number[]; boundPruned: number } | null
  >(null);

  private readonly recipeOptimize = inject(RecipeOptimizeService);
  private readonly rotationsService = inject(RotationsService);
  private readonly teamsService = inject(TeamsService);
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
      const [builds, options, rotations, teams] = await Promise.all([
        this.buildsService.list(),
        this.artifacts.options(),
        this.rotationsService.list(),
        // Never fatal: a team is a way to narrow the build grid, and a page that refused to
        // open because that convenience failed would be worse than one without it.
        this.teamsService.list().catch(() => []),
      ]);
      this.teams.set(teams);
      // Paginated. Reading it as an array leaves the picker empty, which looks exactly like
      // having authored no rotations — the same trap W.6's compare page fell into.
      this.rotations.set(rotations.items.map((r) => ({ id: r.id, name: r.name })));
      // **Not `items[0]`.** Picking the first rotation stated a choice the user never made;
      // §15's rule is to recall their last one and otherwise leave it empty.
      this.rotationId.set(recallAmong(this.store, 'rotationId', this.rotations()));
      this.slotNames.set(
        Object.fromEntries(options.slots.map((slot) => [slot.key, slot.display])),
      );
      this.slotKeys.set(options.slots.map((slot) => slot.key));
      this.statNames.set(
        Object.fromEntries(options.stats.map((stat) => [stat.key, stat.display ?? stat.key])),
      );
      this.builds.set(builds);
      // Likewise: the page opened on Aino because she sorts first, which read as a
      // recommendation. An empty picker is the honest state when nothing is remembered.
      const remembered = recallAmong(this.store, 'buildId', builds);
      if (remembered) await this.selectBuild(remembered);
    } catch {
      this.error.set('Could not load your builds.');
      this.builds.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Choosing a team narrows the build grid, and keeps the chosen build only if it is in there.
   *
   * Silently leaving a build selected that the team does not field would put this page's whole
   * answer under a character the user just filtered away.
   */
  protected async selectTeam(ids: readonly string[]): Promise<void> {
    this.teamId.set(ids[0] ?? '');
    remember(this.store, 'teamId', ids[0] ?? '');
    const inScope = this.buildsInScope();
    if (inScope.some((b) => b.id === this.buildId())) return;
    await this.selectBuild(inScope[0]?.id ?? '');
  }

  /** The search settings as they stand, for `rememberSelections`. */
  private currentSelections(): Selections {
    const pair = this.chosenPair();
    return {
      objective: this.objective(),
      sets: [...this.selectedSets()],
      pair: pair === null ? null : [pair[0], pair[1]],
      // Copied, not aliased: the signal's value is readonly and `Selections` is a plain
      // record that gets JSON-serialised.
      mainStats: Object.fromEntries(
        Object.entries(this.mainStatBySlot()).map(([slot, keys]) => [slot, [...keys]]),
      ),
    };
  }

  /**
   * Put back what was chosen last time — for this character first, then page-wide.
   *
   * **Sets are filtered against what this inventory can actually field.** A set remembered
   * from a character whose pieces have since been equipped elsewhere would otherwise sit
   * selected and uncalibratable, and the search would refuse with a message about a set the
   * user did not knowingly pick.
   */
  private restoreSelections(characterId: string | null): void {
    const found = recallSelections(this.store, characterId);
    if (!found) return;
    if (found.objective === 'hit' || found.objective === 'rotation') {
      this.objective.set(found.objective);
    }
    const reachable = new Set(this.fourPieceChoices().map((c) => c.setId));
    this.selectedSets.set(new Set(found.sets.filter((id) => reachable.has(id))));
    this.pairFirst.set(found.pair?.[0] ?? null);
    this.pairSecond.set(found.pair?.[1] ?? null);
    this.mainStatBySlot.set(found.mainStats ?? {});
  }

  /** Chosen rotations are remembered; the picker no longer starts on an arbitrary one. */
  protected pickRotation(id: string): void {
    this.rotationId.set(id);
    remember(this.store, 'rotationId', id);
  }

  protected async pickBuild(ids: readonly string[]): Promise<void> {
    await this.selectBuild(ids[0] ?? '');
  }

  protected async selectBuild(id: string): Promise<void> {
    this.buildId.set(id);
    remember(this.store, 'buildId', id);
    this.hits.set([]);
    this.hitIndex.set(0);
    // A result belongs to the build it was searched for. Left up, it would sit under a
    // different character's name — a number that looks right and refers to something else.
    this.result.set(null);
    // And so does the note saying what was equipped from it.
    this.equipped.set(null);
    // …and everything the rotation search found about the *previous* build's winner.
    this.clearRotationFindings();
    this.equippedIds.set([]);
    this.actionError.set(null);
    if (!id) return;
    try {
      this.hits.set(await this.explain.hits(id));
      // What this character is wearing now — the comparator every result is a percentage of
      // (§11). Its own failure is swallowed on purpose: without it the page falls back to
      // ranking against rank 1, which is a worse comparison but not a broken page.
      try {
        const worn = await this.artifacts.list({ build_id: id });
        this.equippedIds.set(worn.items.map((piece) => piece.id));
      } catch {
        this.equippedIds.set([]);
      }
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

  /**
   * Whether the recipes this ranking rests on could not be calibrated cleanly.
   *
   * **Exhaustive and trustworthy are different claims.** `isExact` says every combination was
   * scored; it says nothing about whether the scorer could see what it was scoring. A rotation
   * that does not run the same way twice leaves the probe unable to resolve its conversions,
   * and a recipe carrying frozen terms over 90% of the damage ranks mostly on the tenth it can
   * still respond to. Printing "Exact" alone above that is the confident-looking number this
   * repo exists to refuse.
   *
   * `calibrate.ts` is explicit that an unstable recipe is not to be ranked on at all. This does
   * not go that far — refusing would leave a user with nothing where they now get something
   * caveated, which is a product decision rather than a defect — but the word "Exact" must not
   * carry the claim.
   */
  protected recipeIsShaky(): boolean {
    const notes = this.caveats();
    if (notes === null) return false;
    // **Only recipes that scored the ranking get to judge it** (owner ruling, 2026-08-31).
    // The baseline is calibrated so the upgrade list can score a set-breaking swap, but
    // `searchRecipe` never visits the no-four-piece state, so no row on screen was scored
    // with it. Its instability was flipping this to "Scoring unreliable" — a claim about an
    // order it played no part in producing.
    const unscored = new Set(notes.unscoredLabels);
    if (notes.unstable.some((entry) => !unscored.has(entry.label))) return true;
    // **Thresholded, because `damageShare` exists for exactly this.** `staleConversionsIn`'s
    // own docstring: *"83 hits carrying 2% of the damage is a footnote, and 5 hits carrying
    // 40% is not."* Firing on any entry gave a single 0.3%-share frozen term the same red
    // sentence as the 90.3% case this was written for, which is the cry-wolf shape that makes
    // a warning worth ignoring.
    return notes.staleConversions.some(
      (s) => !unscored.has(s.label) && s.damageShare >= SHAKY_DAMAGE_SHARE,
    );
  }

  /**
   * The caveats split by whether the recipe they belong to actually scored the ranking.
   *
   * The baseline's problems are real and worth showing — the upgrade list uses that recipe to
   * price a swap that breaks the winner's set — but they say nothing about the order of the
   * results, and printing them in one undifferentiated red block said otherwise.
   */
  protected readonly rankingCaveats = computed(() => this.splitCaveats(false));
  protected readonly asideCaveats = computed(() => this.splitCaveats(true));

  private splitCaveats(unscored: boolean): {
    unstable: { label: string; abilities: string[] }[];
    staleConversions: { label: string; term: string; damageShare: number }[];
  } {
    const notes = this.caveats();
    if (notes === null) return { unstable: [], staleConversions: [] };
    const held = new Set(notes.unscoredLabels);
    return {
      unstable: notes.unstable.filter((entry) => held.has(entry.label) === unscored),
      staleConversions: notes.staleConversions.filter(
        (stale) => held.has(stale.label) === unscored,
      ),
    };
  }

  /**
   * Whether the winning build can actually perform the rotation — §9.
   *
   * **`recipe-energy.ts` had no input and no consumer**: nothing passed `calibrate` a sweep, so
   * `minimumEnergyRecharge` was always null, and nothing read it either. Both ends dead, in a
   * module whose own docstring says why it matters — *a build that cannot burst when the
   * rotation says to burst is not performing that rotation*.
   *
   * Null when the build clears the threshold, **and also when no threshold was measured**. The
   * sweep only runs for an unstable rotation whose burst is what varied, so most searches have
   * no minimum — and an unmeasured threshold is not a passed one. `recipe-energy` makes the
   * caller that skipped the measurement say so; here that is the warning above, which already
   * names the ability whose count moved.
   */
  protected readonly energyGap = computed<EnergyShortfall | null>(() => {
    const recipe = this.scoredRecipe();
    const pools = this.winningPools();
    if (!recipe || !pools) return null;
    // The winner's artifact-borne ER — the same pools the ranking scored it with, so the
    // number in the warning is the number that produced the row above it.
    const has = pools.reduce((sum, pool) => sum + (pool['energy_recharge'] ?? 0), 0);
    return energyShortfall(has, recipe.meta.minimumEnergyRecharge);
  });

  /** Whether Optimize can run at all, in whichever mode is chosen. */
  protected canOptimize(): boolean {
    // **Including the check the page already made.** With a main-stat combination no owned
    // piece satisfies, the page says so directly above this button — and then let you press
    // it, which in rotation mode spends a six-second gcsim calibration to return the empty
    // list it had just predicted.
    if (this.impossibleSlots().length > 0) return false;
    return this.objective() === 'rotation' ? this.canSearchRotation() : this.canSearch();
  }

  /** The one button. It runs the mode that is chosen, which is the whole point of there being one. */
  protected optimizeNow(): Promise<void> {
    this.clearRotationFindings();
    // **Saved when the search runs, not on every toggle.** Pressing Optimize is the signal
    // that this combination is what the user meant; a filter switched on and off again would
    // otherwise be remembered as a decision.
    this.keepSelections();
    return this.objective() === 'rotation' ? this.runRotation() : this.run();
  }

  /** This character's settings and the page-wide ones, written together. */
  private keepSelections(): void {
    const character = this.builds().find((b) => b.id === this.buildId())?.character?.id ?? null;
    rememberSelections(this.store, character, this.currentSelections());
  }

  /**
   * Drop everything that describes a *rotation* ranking.
   *
   * `run()` replaced `result` but left `scoredRecipe`, `winningPools`, `caveats` and
   * `recipeNotes` standing — so switching to single hit and pressing Optimize left "Pieces
   * that would beat the winner" on screen, computed from the previous rotation's recipe, under
   * a heading naming a winner that is now a different build.
   *
   * **The mode select is the natural way to compare the two now that there is one button**, so
   * this is the sequence the change invites rather than an unlikely one.
   */
  private clearRotationFindings(): void {
    this.scoredRecipe.set(null);
    this.winningPools.set(null);
    this.baselineRecipe.set(null);
    this.scoredSetId.set(null);
    this.winningSetIds.set(null);
    this.comparator.set(null);
    this.calibration.set(null);
    this.caveats.set(null);
    this.recipeNotes.set(null);
  }

  protected async run(): Promise<void> {
    const hit = this.hit();
    const id = this.buildId();
    if (!hit || !id) return;
    this.actionError.set(null);
    // The equip note belongs to the result it was equipped from. A new search replaces that
    // result, and a note left over it would describe a ranking nobody can see any more.
    this.equipped.set(null);
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
          this.constrained(
            snapshot.artifacts.filter((piece) => this.isKnownSlot(piece)),
          ).map((piece) => ({
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
    this.equipped.set(null);
    this.result.set(null);
    this.caveats.set(null);
    this.recipeNotes.set(null);
    this.searching.set(true);
    try {
      const snapshot = await this.optimize.inventory();
      this.candidates.set(snapshot.artifacts);
      this.unreadable.set(snapshot.unreadable);
      this.truncated.set(snapshot.truncated);

      // Constrained **once, here**, so everything downstream sees the same list. Applying it
      // only at the search would leave `reachableSets` offering — and `calibrateAll` paying
      // six seconds for — a set no surviving piece belongs to.
      const pieces = this.constrained(
        snapshot.artifacts.filter((piece) => this.isKnownSlot(piece)),
      );
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
      // Keep what the search used, so the marginal table and the per-slot upgrades below can
      // be computed without a second calibration.
      const winner = found.builds[0];
      const byId = new Map(pieces.map((piece) => [piece.id, piece.stats]));
      const fourPiece = calibrated.byFourPieceSet.get(chosen[0]);
      this.scoredRecipe.set(fourPiece ?? calibrated.noFourPiece);
      this.baselineRecipe.set(calibrated.noFourPiece);
      // Null when the winner was scored on the no-four-piece recipe: there is then no bonus a
      // swap could break, and `upgrades()` must not invent one to protect.
      this.scoredSetId.set(fourPiece ? chosen[0] : null);
      const setById = new Map(pieces.map((piece) => [piece.id, piece.set_id ?? -1]));
      this.winningSetIds.set(
        winner ? winner.artifactIds.map((id) => setById.get(id) ?? -1) : null,
      );
      this.winningPools.set(
        winner ? winner.artifactIds.map((id) => byId.get(id) ?? {}) : null,
      );
      this.recipeNotes.set({
        uncoveredSets: found.uncoveredSets,
        boundPruned: found.boundPruned,
      });
      this.calibration.set(calibrated);
      this.comparator.set(this.comparatorFrom(pieces, calibrated));
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
    // The same filter `fourPieceChoices` applies, said again **here** — this is the list that
    // becomes the request, and a set gcsim cannot key fails the whole calibration with a 422.
    // Nothing puts an unsimulable id into `selectedSets` today, because selection can only come
    // from the picker; that is one layer away from the thing that provokes the refusal, and
    // nothing prunes a selection when the catalogue changes under it.
    const catalogue = this.artifactSets();
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
      .filter(([setId]) => catalogue.get(setId)?.simulable !== false)
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
      // **The baseline, and it must not read as a set the user chose.** Reported from
      // production: *"it's weird 'no 4p' was an option"* — the progress line said "Calibrating
      // no 4-piece set" beside a picker where only Finale was selected, so a target nobody
      // picked looked like one they had. It is not optional and never was: every combination
      // that reaches no 4-piece is scored against it, so a search without it can rank nothing.
      { artifactSetIds: [], setIds: [], label: 'the baseline (no 4-piece bonus)' },
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
