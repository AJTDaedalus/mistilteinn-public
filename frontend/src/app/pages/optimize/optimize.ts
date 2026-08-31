import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import { CardPicker, type CardOption } from '../../shared/card-picker/card-picker';
import { buildOptions, buildsInTeam, teamOptions } from '../../shared/team-scope';
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
import type { ArtifactSetChoice } from './optimize.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService, type TeamRead } from '../teams/teams.service';
import { isFilterableMainStat, sortMainStats } from '../../shared/stat-order';
import { scoreForSlot } from '../../sim/artifact-score';
import type { Recipe } from '../../sim/recipe';
import { evaluateRecipe } from '../../sim/recipe-eval';
import { candidateStatsFrom, liveQuantitiesFor, searchRecipe } from '../../sim/recipe-search';
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
/**
 * How much of a recipe's damage must sit behind frozen conversions before the ranking is
 * called into question. Above this the order is not to be trusted; below it the terms are a
 * footnote, which is the distinction `damageShare` was added to make.
 *
 * Five per cent is a judgement, not a measurement — stated so nobody reads it as one. The case
 * this was written for measured 90.3%.
 */
const SHAKY_DAMAGE_SHARE = 0.05;

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
const SLOT_ORDER = ['equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring', 'equip_dress'];

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
    CardPicker, CatalogueIcon, ElementChip, EntityToken,
  ],
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
      if (heldElsewhere.length) {
        this.actionError.set(
          `${heldElsewhere.length} of these pieces are equipped to another build `
          + `(${heldElsewhere.map((p) => p.set_name || p.slot).join(', ')}). `
          + 'Nothing was changed — take them off that build first.',
        );
        return;
      }

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
      this.equipped.set(
        already.size === row.artifactIds.length
          ? 'Already equipped — this build is wearing #' + row.rank + ' already.'
          : `Equipped ${moved} piece(s) from #${row.rank}`
            + (already.size ? `; ${already.size} were already on this build.` : '.'),
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
  protected readonly marginalPerRoll = computed<{ quantity: string; delta: number }[]>(() => {
    const recipe = this.scoredRecipe();
    const pools = this.winningPools();
    if (!recipe || !pools) return [];

    // **Only stats the recipe can respond to.** A recipe is calibrated at one set of stats, so
    // anything it does not read is frozen into its coefficients — Elemental Mastery most of
    // all, whose contribution to a reaction lands in `ampMultiplier` and to Nahida's own bonus
    // in `bonusDmg`. Evaluating a bump in one of those returns exactly zero, and printing that
    // beside real numbers claims the stat is worthless rather than unmodelled.
    //
    // `liveQuantitiesFor` already answers this — it is what the Pareto filter uses to decide
    // which quantities can matter — so the same definition serves both.
    const live = new Set(liveQuantitiesFor(recipe));
    const base = evaluateRecipe(recipe, candidateStatsFrom(pools));
    return Object.entries(ONE_ROLL)
      .filter(([, spec]) => live.has(spec.quantity))
      .map(([quantity, spec]) => {
        const size = spec.roll;
        const stats = { ...candidateStatsFrom(pools) };
        // Applied to the resolved stats rather than to a pool, so a quantity the pools do not
        // already contain still moves — a build with no EM must still be able to ask what EM
        // would be worth.
        const bumped = {
          ...stats, [quantity]: (stats[quantity as keyof typeof stats] as number) + size,
        };
        return { quantity, delta: evaluateRecipe(recipe, bumped as typeof stats) - base };
      })
      .filter((row) => Number.isFinite(row.delta))
      .sort((a, b) => b.delta - a.delta);
  });

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

  protected readonly upgrades = computed<
    { slot: string; rows: { id: string; label: string; delta: number }[] }[]
  >(() => {
    const recipe = this.scoredRecipe();
    const pools = this.winningPools();
    if (!recipe || !pools) return [];

    const names = this.slotNames();
    const bySlot = new Map<string, { id: string; stats: Record<string, number> }[]>();
    for (const piece of this.constrained(this.candidates())) {
      const list = bySlot.get(piece.slot) ?? [];
      list.push({ id: piece.id, stats: piece.stats });
      bySlot.set(piece.slot, list);
    }

    return SLOT_ORDER.flatMap((slot, index) => {
      const candidates = bySlot.get(slot) ?? [];
      if (!candidates.length) return [];
      const scored = scoreForSlot(recipe, pools, candidates, index)
        // **Strictly better only.** A zero delta is the piece already worn, or one identical
        // to it; listing those as "upgrades" would pad the answer with non-answers.
        .filter(({ score }) => score.delta > 0)
        .sort((a, b) => b.score.delta - a.score.delta)
        .slice(0, UPGRADES_PER_SLOT)
        .map(({ id, score }) => ({ id, label: this.describe(id), delta: score.delta }));
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
      if (rotations.items.length > 0) this.rotationId.set(rotations.items[0].id);
      this.slotNames.set(
        Object.fromEntries(options.slots.map((slot) => [slot.key, slot.display])),
      );
      this.slotKeys.set(options.slots.map((slot) => slot.key));
      this.statNames.set(
        Object.fromEntries(options.stats.map((stat) => [stat.key, stat.display ?? stat.key])),
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

  /**
   * Choosing a team narrows the build grid, and keeps the chosen build only if it is in there.
   *
   * Silently leaving a build selected that the team does not field would put this page's whole
   * answer under a character the user just filtered away.
   */
  protected async selectTeam(ids: readonly string[]): Promise<void> {
    this.teamId.set(ids[0] ?? '');
    const inScope = this.buildsInScope();
    if (inScope.some((b) => b.id === this.buildId())) return;
    await this.selectBuild(inScope[0]?.id ?? '');
  }

  protected async pickBuild(ids: readonly string[]): Promise<void> {
    await this.selectBuild(ids[0] ?? '');
  }

  protected async selectBuild(id: string): Promise<void> {
    this.buildId.set(id);
    this.hits.set([]);
    this.hitIndex.set(0);
    // A result belongs to the build it was searched for. Left up, it would sit under a
    // different character's name — a number that looks right and refers to something else.
    this.result.set(null);
    // And so does the note saying what was equipped from it.
    this.equipped.set(null);
    // …and everything the rotation search found about the *previous* build's winner.
    this.clearRotationFindings();
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
    if (notes.unstable.length > 0) return true;
    // **Thresholded, because `damageShare` exists for exactly this.** `staleConversionsIn`'s
    // own docstring: *"83 hits carrying 2% of the damage is a footnote, and 5 hits carrying
    // 40% is not."* Firing on any entry gave a single 0.3%-share frozen term the same red
    // sentence as the 90.3% case this was written for, which is the cry-wolf shape that makes
    // a warning worth ignoring.
    return notes.staleConversions.some((s) => s.damageShare >= SHAKY_DAMAGE_SHARE);
  }

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
    return this.objective() === 'rotation' ? this.runRotation() : this.run();
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
      this.scoredRecipe.set(
        calibrated.byFourPieceSet.get(chosen[0]) ?? calibrated.noFourPiece,
      );
      this.winningPools.set(
        winner ? winner.artifactIds.map((id) => byId.get(id) ?? {}) : null,
      );
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
