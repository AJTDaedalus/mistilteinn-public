import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CardPicker, type CardFilter, type CardOption } from '../../shared/card-picker/card-picker';
import { characterCardFilters, characterCardOptions } from '../../shared/character-cards';
import { CatalogueIcon } from '../../shared/icon/icon';
import { RosterService } from '../builds/roster.service';
import { CatalogueService, type CharacterSummary, type WeaponSummary } from '../catalogue/catalogue.service';

import {
  WishesService,
  type WishBannerFilter,
  type WishBannerRead,
  type WishCustomBanner,
  type WishFeaturedItem,
  type WishIncomeVersionRead,
  type WishLimits,
  type WishPlanRead,
  type WishMilestoneRead,
  type WishPlanRequest,
  type WishStrategy,
  type WishTarget,
} from './wishes.service';

/** The three spending tiers the bookkeeping workbook publishes. */
const TIERS = ['f2p', 'welkin', 'welkin_bp'] as const;
type Tier = (typeof TIERS)[number];

/** How long to wait after the last keystroke before asking the backend. */
const DEBOUNCE_MS = 250;

/** Copies that take an item to its maximum. */
const MAX_COPIES = { character: 7, weapon: 5 } as const;

/**
 * Most goals a custom plan may hold.
 *
 * **Must match `WishPlanRequest.targets`' `max_length` on the backend.** Without it the page
 * happily builds a thirteenth row and the request comes back 422, which the user reads as
 * "that combination could not be planned" — a refusal about a limit nothing on screen
 * mentioned. A control that can build a state the server refuses is the defect; the error
 * message is only how it surfaces.
 */
const MAX_ROWS = 12;

/** One banner's starting position, as the controls hold it. */
interface Position {
  label: string;
  pity: number;
  guaranteed: boolean;
  lostFiftyFifties: number;
  ownedCopies: number;
}

/** A row of the custom plan. */
interface CustomRow extends Position {
  banner: 'character' | 'weapon';
  targetCopies: number;
  /** Which banner run this row is on. Per row: a custom plan spans banners. */
  bannerSlug: string | null;
}

function position(label = ''): Position {
  return { label, pity: 0, guaranteed: false, lostFiftyFifties: 0, ownedCopies: 0 };
}

type Kind = 'character' | 'weapon';

/** A unit nobody has announced yet. The first choice in every custom-banner picker. */
export const UNKNOWN = '?';

/**
 * The custom banner of each kind — **one each, edited in place, never saved.**
 *
 * Owner, 2026-09-26: *"We don't need to save custom banners, have it be an option people change
 * their custom banner for."* The first version kept a growing list in `localStorage` behind a
 * create-and-save dialog, which made a hypothetical banner a thing to manage rather than a
 * question to ask.
 */
export const CUSTOM_SLUG: Readonly<Record<Kind, string>> = {
  character: 'custom:character',
  weapon: 'custom:weapon',
};

/** One featured 4-star. `constellation` null is "unowned" — sent as such, not as "ask". */
export interface CustomSlot {
  name: string;
  constellation: number | null;
}

export interface CustomBanner {
  five: string;
  fours: CustomSlot[];
}

/** Three featured 4-star characters, or five 4-star weapons. */
function blankCustom(kind: Kind): CustomBanner {
  return {
    five: UNKNOWN,
    fours: Array.from({ length: kind === 'character' ? 3 : 5 }, () => ({
      name: UNKNOWN, constellation: null,
    })),
  };
}

/**
 * Names that pick exactly one catalogue row.
 *
 * The backend resolves a custom banner **by name**, so a name sixteen Travelers or fourteen
 * practice mannequins share cannot be offered — it would price whichever row came back last.
 * Neither is ever on a banner, which is why dropping them loses nothing.
 */
function uniquelyNamed<T extends { name: string }>(rows: readonly T[]): T[] {
  const seen = new Map<string, number>();
  for (const r of rows) seen.set(r.name, (seen.get(r.name) ?? 0) + 1);
  return rows
    .filter((r) => seen.get(r.name) === 1)
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** The catalogue endpoints' own ceiling (`le=200`). */
const CATALOGUE_PAGE = 200;

/**
 * Every row of a paged catalogue list.
 *
 * **Paged because one request cannot hold them.** The first version asked for `limit: 300` and
 * `limit: 400` against an endpoint capped at 200; both came back 422, the `.catch` turned that
 * into an empty list, and every custom-banner picker offered `?` and nothing else — with no
 * error anywhere. There are 260 weapons, so one page of the maximum is not enough either.
 */
async function everyPage<T>(
  fetch: (offset: number) => Promise<{ items: T[]; total: number } | undefined>,
): Promise<T[]> {
  const rows: T[] = [];
  for (;;) {
    const page = await fetch(rows.length);
    const items = page?.items ?? [];
    rows.push(...items);
    if (!items.length || rows.length >= (page?.total ?? 0)) return rows;
  }
}

/**
 * A fresh row.
 *
 * **No placeholder label.** The free-text editor is gone, so a made-up `"Weapon 2"` could never
 * be changed and went out as the goal's name — the ladder printed `Weapon 2 R1`. Empty means the
 * banner has not named it yet, and `plan_campaign` builds the rung label with `.strip()`.
 */
function row(banner: 'character' | 'weapon', label = ''): CustomRow {
  return { ...position(label), banner, targetCopies: 1, bannerSlug: null };
}

/**
 * The wish planner — odds of reaching a constellation or refinement on a given budget.
 *
 * `docs/DESIGN_wish_planner.md`. Laid out after Fribbels' Warp Planner, deliberately, so that
 * anyone who has used that one already knows this one.
 *
 * **Two modes, as Fribbels has.** *Simple* plans one character and optionally their signature
 * weapon, ordered by a strategy. *Custom* takes an explicit ordered list of goals across as
 * many characters as you like. Both spend **one** budget: the thing a per-banner ladder
 * cannot do, because two separate ladders each assume they own the whole wallet and can both
 * read "almost certain" when affording both is impossible.
 *
 * Genshin-specific additions Fribbels has no equivalent of: **Capturing Radiance**, as a
 * "50/50s lost" control, and **whole patches** of projected income rather than half-patches,
 * because the source workbook has no phase structure.
 */
/**
 * The refund choice meaning "price it from my roster".
 *
 * A fallback for the literal `/limits` publishes — used only before that request lands, so
 * the control has a sane default on first paint rather than an empty dropdown.
 */
const ACCOUNT_REFUND = 'account';

@Component({
  selector: 'app-wishes',
  imports: [FormsModule, DecimalPipe, NgTemplateOutlet, CatalogueIcon, CardPicker],
  templateUrl: './wishes.html',
  styleUrl: './wishes.scss',
})
export class WishesPage {
  private service = inject(WishesService);
  private catalogue = inject(CatalogueService);
  private roster = inject(RosterService);

  protected readonly allCharacters = signal<CharacterSummary[]>([]);
  protected readonly allWeapons = signal<WeaponSummary[]>([]);
  /** Constellation of every character the account owns, by name. Empty until it loads. */
  protected readonly held = signal<ReadonlyMap<string, number>>(new Map());
  /**
   * Highest refinement of every weapon the account owns, by name.
   *
   * **The highest copy, not a sum.** Two R1 copies are not an R2 until one is fed to the other,
   * and the planner's question is what the best copy needs to reach the goal.
   */
  protected readonly heldWeapons = signal<ReadonlyMap<string, number>>(new Map());

  /** The custom banner of each kind, as currently edited. */
  protected readonly custom = signal<Record<Kind, CustomBanner>>({
    character: blankCustom('character'),
    weapon: blankCustom('weapon'),
  });

  // -- banner search. Sent to the server: the page holds one page of a ~300-row table.
  protected readonly bannerQuery = signal('');
  protected readonly bannerKind = signal<Kind | null>(null);
  protected readonly bannerElement = signal<WishBannerFilter['element'] | null>(null);
  protected readonly bannerWeapon = signal<WishBannerFilter['weapon_type'] | null>(null);

  protected readonly mode = signal<'simple' | 'custom'>('simple');

  // -- banners
  protected readonly banners = signal<WishBannerRead[]>([]);
  protected readonly bannerTotal = signal(0);
  protected readonly chosenBanner = signal<string | null>(null);
  protected readonly bannersOpen = signal(true);

  // -- simple mode
  protected readonly character = signal<Position>(position('Character'));
  protected readonly weapon = signal<Position>(position('Weapon'));
  protected readonly planWeapon = signal(true);
  // Typed to the contract's own union, so a strategy the backend does not accept is a
  // compile error rather than a 422.
  protected readonly strategy = signal<WishStrategy>('c0_first');

  // -- custom mode
  protected readonly rows = signal<CustomRow[]>([row('character', 'Character')]);
  /** Which row's banner picker is open, or null. One at a time keeps the page short. */
  protected readonly pickingFor = signal<number | null>(null);

  // -- wallet
  protected readonly primogems = signal(0);
  protected readonly intertwined = signal(0);
  // **Defaults to the account.** The exact figure is the better answer whenever the roster
  // can give it, and a tier is the fallback rather than the starting point.
  protected readonly refund = signal(ACCOUNT_REFUND);
  protected readonly tier = signal<Tier>('f2p');
  protected readonly selectedVersions = signal<ReadonlySet<string>>(new Set());

  protected readonly limits = signal<WishLimits | null>(null);
  protected readonly income = signal<WishIncomeVersionRead[]>([]);
  protected readonly plan = signal<WishPlanRead | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly pending = signal(false);

  protected readonly strategies = computed(() => this.limits()?.strategies ?? []);
  protected readonly refundTiers = computed(() =>
    Object.keys(this.limits()?.starglitter_refund_tiers ?? { none: 0 }),
  );

  /** Every refund choice, the account first. */
  protected readonly refundOptions = computed(() => [
    this.limits()?.account_refund ?? ACCOUNT_REFUND,
    ...this.refundTiers(),
  ]);

  protected readonly characterHardPity = computed(
    () => this.limits()?.banners['character']?.hard_pity ?? 90,
  );
  protected readonly weaponHardPity = computed(
    () => this.limits()?.banners['weapon']?.hard_pity ?? 80,
  );
  protected readonly maxLosses = computed(() => this.limits()?.max_lost_fifty_fifties ?? 3);
  /** 0..maxLosses. Built from the backend's own ceiling rather than a literal `[0,1,2,3]`. */
  protected readonly lossOptions = computed(() =>
    Array.from({ length: this.maxLosses() + 1 }, (_, n) => n),
  );

  /** True once the counter alone guarantees the next 50/50, so the page can say why. */
  protected readonly radianceIsCertain = computed(
    () => this.character().lostFiftyFifties >= this.maxLosses(),
  );

  /**
   * Versions still ahead, oldest first.
   *
   * **Filtered on `is_estimate`, which is the only forward marker the store has.** It held
   * the last eight rows of the whole history, and six of those had already shipped — so
   * ticking 6.5 added ~88 wishes the player had already earned *and already counted in their
   * primogem box*, silently inflating every success chance. The workbook carries no dates, so
   * "has this patch happened" cannot be asked any other way; an estimate is by definition a
   * patch that has not finished.
   */
  protected readonly upcoming = computed(() =>
    this.income().filter((version) => version.is_estimate),
  );

  /**
   * Wishes from the patches ticked, at the chosen tier.
   *
   * **Summed over `upcoming()`, not over the whole store.** Filtering only what is *offered*
   * left the total counting anything already selected, so a version that stopped being
   * offered — because it shipped — kept contributing invisibly. The set of things that can
   * be counted and the set that can be ticked have to be the same set.
   */
  protected readonly projectedWishes = computed(() => {
    const chosen = this.selectedVersions();
    const tier = this.tier();
    return Math.floor(
      this.upcoming()
        .filter((version) => chosen.has(version.version))
        .reduce((total, version) => total + version[tier], 0),
    );
  });

  /** The banner currently picked, if it is still in the loaded page. */
  /**
   * The weapon banner running beside the chosen character banner — their signature's banner.
   *
   * **One direction only.** A character banner names exactly one concurrent weapon banner, so
   * character → weapon is unambiguous. The reverse is not: a weapon banner runs beside *two*
   * character banners and carries *two* 5-star weapons, and nothing in the source says which
   * is whose. Pairing backwards would be a guess dressed as a fact.
   */
  protected readonly pairedWeaponBanner = computed(
    () => this.banner()?.signature_banner ?? null,
  );

  /** The custom banners as the grid draws them, in the same shape as a real one. */
  protected readonly customBanners = computed<WishBannerRead[]>(() =>
    (['character', 'weapon'] as const).map((kind) => {
      const banner = this.custom()[kind];
      return {
        slug: CUSTOM_SLUG[kind],
        name: kind === 'character' ? 'Custom character banner' : 'Custom weapon banner',
        kind,
        starts_at: null,
        ends_at: null,
        featured_five: [this.featured(kind, banner.five)],
        featured_four: banner.fours.map((slot) => ({
          name: slot.name,
          icon: this.artFor(slot.name),
          owned_copies: slot.constellation,
        })),
        signature_banner: null,
        alongside: [],
      };
    }),
  );

  /**
   * Every card the grid draws: **the custom banners first**, then the loaded page.
   *
   * First because a hypothetical banner is what someone reaches for when the real ones do not
   * have their target — scrolling past eight reruns to find it was half of what made it clunky.
   * The kind chip applies to them too; the text and element chips do not, since a custom banner
   * is whatever the user makes it.
   */
  protected readonly allBanners = computed<WishBannerRead[]>(() => [
    ...this.customBanners().filter((b) => !this.bannerKind() || b.kind === this.bannerKind()),
    ...this.banners(),
  ]);

  /** Characters a custom banner may feature, by rarity. */
  private characterPool(rarity: 'five_star' | 'four_star'): CharacterSummary[] {
    return uniquelyNamed(this.allCharacters().filter((c) => c.rarity === rarity));
  }

  private weaponPool(rarity: 'five_star' | 'four_star'): WeaponSummary[] {
    return uniquelyNamed(this.allWeapons().filter((w) => w.rarity === rarity));
  }

  /**
   * The picker's cards: **`?` first**, then the catalogue alphabetically.
   *
   * The card value is the **name**, because that is what the backend resolves a custom banner
   * by; `characterCardOptions` keys on the row id for pickers that save one. A held unit carries
   * its constellation or refinement as a badge on the art — the owner's ask, and where other
   * planners put it — so the choice is made with the account in view rather than discovered
   * after.
   */
  private cardOptions(kind: Kind, rarity: 'five_star' | 'four_star'): CardOption[] {
    const unknown: CardOption = {
      value: UNKNOWN,
      label: '? Unannounced',
      detail: kind === 'character' ? 'Any character' : 'Any weapon',
    };
    if (kind === 'character') {
      const pool = this.characterPool(rarity);
      const held = this.held();
      return [
        unknown,
        ...characterCardOptions(pool).map((option, index) => {
          const constellation = held.get(pool[index].name);
          return {
            ...option,
            value: pool[index].name,
            badge: constellation === undefined ? undefined : `C${constellation}`,
          };
        }),
      ];
    }
    return [
      unknown,
      ...this.weaponPool(rarity).map((w) => ({
        value: w.name,
        badge: this.heldWeapons().has(w.name) ? `R${this.heldWeapons().get(w.name)}` : undefined,
        label: w.name,
        icon: w.icon,
        detail: w.is_beta ? `${w.weapon_type_display} · beta` : w.weapon_type_display,
        tags: { weapon: w.weapon_type ?? '' },
      })),
    ];
  }

  /** The same chips the character grid offers; a weapon only answers to its class. */
  private cardFilters(kind: Kind): CardFilter[] {
    if (kind === 'character') return characterCardFilters(this.allCharacters());
    const classes = new Map<string, { label: string; icon: string }>();
    for (const w of this.allWeapons()) {
      if (w.weapon_type && w.weapon_type_icon && !classes.has(w.weapon_type)) {
        classes.set(w.weapon_type, { label: w.weapon_type_display, icon: w.weapon_type_icon });
      }
    }
    return [{
      group: 'weapon',
      label: 'Weapon',
      options: [...classes].sort().map(([value, { label, icon }]) => ({ value, label, icon })),
    }];
  }

  /**
   * Each picker's cards and chips, built once per catalogue or roster change.
   *
   * Computed rather than called from the template: a method there rebuilt some 150 cards on
   * every change detection for each of up to six pickers, and handed `CardPicker` a new array
   * each time, which re-renders an `OnPush` component for nothing.
   */
  protected readonly pickerOptions = computed(() => ({
    character: {
      five: this.cardOptions('character', 'five_star'),
      four: this.cardOptions('character', 'four_star'),
      filters: this.cardFilters('character'),
    },
    weapon: {
      five: this.cardOptions('weapon', 'five_star'),
      four: this.cardOptions('weapon', 'four_star'),
      filters: this.cardFilters('weapon'),
    },
  }));

  /** The chips above the banner grid: vision and weapon class, as on the character grid. */
  protected readonly bannerChips = computed(() => characterCardFilters(this.allCharacters()));

  /**
   * The paired banner's row, when it happens to be on the loaded page.
   *
   * **Only for the highlight.** Pricing uses the slug, which the backend resolves over the
   * whole table; searching the page for it reported "no weapon banner" whenever the partner
   * was off-page, which over the committed table is 2 of the 6 character banners on the first
   * page. That null was indistinguishable from a phase with no weapon banner, and no phase has
   * none, so it was always a pagination artefact.
   */
  protected readonly pairedWeaponRow = computed(() => {
    const slug = this.pairedWeaponBanner();
    return slug ? this.known().find((b) => b.slug === slug) ?? null : null;
  });

  /**
   * Every real banner the user has picked, kept by slug whatever the list shows now.
   *
   * **The list is a filtered server page, so it cannot be where a choice lives.** Pressing the
   * Weapon chip after picking a character banner replaced the page, the lookup came back null,
   * and the plan went out with `banner_slug: null` on both legs — the account refund silently
   * gone, with the card the user picked no longer drawn to show why. Found in review of #338.
   */
  private readonly picked = signal<ReadonlyMap<string, WishBannerRead>>(new Map());

  /**
   * Every banner the page can resolve a slug against — **whatever the chips hide.** Custom
   * banners come first so an edit to one is what gets read; the picks outlive the page.
   */
  private readonly known = computed(() => [
    ...this.customBanners(), ...this.banners(), ...this.picked().values(),
  ]);

  private remember(banner: WishBannerRead | null): void {
    if (!banner || this.isCustom(banner.slug)) return;
    this.picked.update((all) => new Map(all).set(banner.slug, banner));
  }

  protected readonly banner = computed(() =>
    this.known().find((b) => b.slug === this.chosenBanner()) ?? null,
  );

  protected readonly hasMoreBanners = computed(
    () => this.banners().length < this.bannerTotal(),
  );

  /**
   * Which rung the chart draws, by index into the plan's milestones.
   *
   * Null follows the plan: the first rung that has a histogram. Set, it is the rung the user
   * clicked. Reset whenever a new plan arrives, because index 3 of one ladder is not the same
   * goal as index 3 of another.
   */
  protected readonly chartedIndex = signal<number | null>(null);

  /**
   * The label of the chosen rung, so a reshape that keeps the ladder's *length* is still caught.
   *
   * Length alone was not enough and the doc above the guard claimed otherwise. Flipping the
   * strategy from `c0_first` to `r1_first` keeps **12** milestones and swaps rungs 0 and 1, so
   * a click on R1 silently ended up drawing C0 — measured. Labels repeat in a custom plan (two
   * rows can both be "C0"), so this pairs with the index rather than replacing it.
   */
  private chartedLabel: string | null = null;

  /**
   * The rung the chart draws.
   *
   * **Milestones are cumulative**, so a rung's distribution is already "reach this *and*
   * everything before it" — C1 is C0+C1, the second row of a custom plan is both characters,
   * and the weapon rung after C0 is C0R1. Selecting one needs no new maths; each milestone
   * carries its own PMF.
   */
  protected readonly charted = computed(() => {
    const milestones = this.plan()?.milestones ?? [];
    const chosen = this.chartedIndex();
    if (chosen !== null && (milestones[chosen]?.histogram ?? []).length) {
      return milestones[chosen];
    }
    return milestones.find((m) => (m.histogram ?? []).length) ?? null;
  });

  /** True for the rung the chart is drawing, so the ladder can say which one that is. */
  protected isCharted(milestone: WishMilestoneRead): boolean {
    return this.charted() === milestone;
  }

  /** Draw this rung's distribution. A rung with no histogram is not selectable. */
  protected chart(index: number): void {
    const milestone = this.plan()?.milestones[index];
    if (!milestone || !(milestone.histogram ?? []).length) return;
    this.chartedLabel = milestone.label;
    this.chartedIndex.set(index);
  }

  /** First and last wish counts the chart covers. Computed here because indexing an
   *  optional array in a template is a type error the Angular compiler catches and
   *  `npx tsc` does not. */
  protected readonly chartFrom = computed(
    () => this.charted()?.histogram?.[0]?.start ?? 0,
  );

  protected readonly chartTo = computed(() => {
    const bins = this.charted()?.histogram ?? [];
    return bins.length ? bins[bins.length - 1].end : 0;
  });

  /**
   * True when the account was asked for the refund and could not answer.
   *
   * **The backend's verdict, not a guess from here.** `refund_source: 'none'` is returned
   * only for a request that asked for the account and got nothing, which is exactly this
   * case — reconstructing it client-side meant duplicating the rule and getting it wrong,
   * and the first version read a response field that does not exist.
   *
   * An empty wallet is excluded: with no wishes there is nothing to refund, so the account
   * declines for a reason that has nothing to do with the roster.
   */
  protected readonly noConstellationData = computed(() => {
    const result = this.plan();
    // `no_banner` is a separate verdict precisely so this cannot claim it: the page's own
    // default state names no banner, and this used to tell a fully-imported roster that it
    // had no constellation data.
    return !!result && result.refund_source === 'none' && result.wallet_wishes > 0;
  });

  /** Tallest bar, so the chart can scale to it rather than to 1. */
  protected readonly chartPeak = computed(() =>
    Math.max(...(this.charted()?.histogram ?? []).map((b) => b.probability), 1e-9),
  );

  private timer: ReturnType<typeof setTimeout> | null = null;
  /** Sequence guard: a slower earlier request must not overwrite a faster later one. */
  private latest = 0;

  constructor() {
    void this.load();
    // Debounced. Firing per keystroke would send `9`, `99`, `999` on the way to `9999` — the
    // defect CLAUDE.md records for the materials editor, one layer up.
    effect(() => {
      const request = this.request();
      if (this.timer) clearTimeout(this.timer);
      this.timer = setTimeout(() => void this.recompute(request), DEBOUNCE_MS);
    });
  }

  private target(from: Position, banner: 'character' | 'weapon'): WishTarget {
    return {
      banner,
      label: from.label,
      pity: from.pity,
      guaranteed: from.guaranteed,
      // Capturing Radiance is the character banner's, and it is one account-wide counter, so
      // only the first target of a plan may carry it.
      lost_fifty_fifties: banner === 'character' ? from.lostFiftyFifties : 0,
      owned_copies: from.ownedCopies,
    };
  }

  /**
   * The plan request.
   *
   * **Typed, not cast.** `recompute` used to pass this through `as never`, which erased the
   * only check that the object still matches the generated contract — so moving `banner_slug`
   * from the request onto each target could not have failed `npm run verify`.
   */
  protected request(): WishPlanRequest {
    const custom_banners = this.customBannersPayload();
    const wallet = {
      primogems: this.primogems(),
      intertwined_fate: this.intertwined(),
      extra_wishes: this.projectedWishes(),
      starglitter_refund: this.refund(),
    };

    if (this.mode() === 'custom') {
      return {
        ...wallet,
        // Ignored for custom targets -- each row names its own goal -- but the generated
        // contract makes a defaulted field non-optional, so sending it keeps the request
        // typed rather than cast.
        strategy: this.strategy(),
        // **A complete row is dropped, not sent.** Owning the maximum leaves no rung above
        // it, so the row describes a goal that is already met; sending it would ask the
        // backend to plan "from C6 to C6".
        targets: this.plannableRows().map((entry, index) => ({
          ...this.target(entry, entry.banner),
          // Only the first row declares the counter; the backend refuses a later one.
          lost_fifty_fifties:
            index === 0 ? this.target(entry, entry.banner).lost_fifty_fifties : 0,
          target_copies: entry.targetCopies,
          banner_slug: entry.bannerSlug,
        })),
        custom_banners,
      };
    }

    return {
      ...wallet,
      // **Only the leg whose kind the picked banner actually is.** Simple mode has one
      // picker and two legs, and sending the same slug to both made the client assert
      // something it does not know: a character banner priced the *weapon* leg's pulls with
      // featured 4-star characters, a 50 % featured rate against 75 %, and collapsed both
      // legs onto one key so the per-leg split did nothing here at all. `null` means "this
      // leg earns nothing", which under-states rather than invents.
      character: { ...this.target(this.character(), 'character'),
                   banner_slug: this.slugForKind('character') },
      weapon: this.planWeapon()
        ? { ...this.target(this.weapon(), 'weapon'), banner_slug: this.slugForKind('weapon') }
        : null,
      strategy: this.strategy(),
      custom_banners,
    };
  }

  /**
   * The custom banners a request actually names, and only those.
   *
   * Each 4-star character is sent **with** its constellation, null included: the slot was
   * prefilled from the roster and may since have been overridden, so the value on screen is the
   * user's answer and the backend reads a sent null as "unowned" rather than asking the account
   * again. A weapon banner's 4-stars earn no refund the planner models, so they go bare.
   */
  private customBannersPayload(): WishCustomBanner[] {
    const used = new Set(
      this.mode() === 'custom'
        ? this.rows().map((entry) => entry.bannerSlug)
        : [this.slugForKind('character'), this.slugForKind('weapon')],
    );
    return (['character', 'weapon'] as const)
      .filter((kind) => used.has(CUSTOM_SLUG[kind]))
      .map((kind) => {
        const banner = this.custom()[kind];
        return {
          slug: CUSTOM_SLUG[kind],
          name: 'Custom banner',
          kind,
          featured_five: [banner.five],
          featured_four: banner.fours.map((slot) =>
            kind === 'character'
              ? { name: slot.name, constellation: slot.constellation }
              : { name: slot.name },
          ),
        };
      });
  }

  private artFor(name: string): string | null {
    if (!name || name === UNKNOWN) return null;
    const char = this.allCharacters().find((ch) => ch.name === name);
    if (char?.icon) return char.icon;
    const weapon = this.allWeapons().find((w) => w.name === name);
    return weapon?.icon ?? null;
  }

  private async load(): Promise<void> {
    // **Not awaited.** The units only feed the custom-banner pickers and the banner chips; the
    // planner's own reference data should not wait for 460 catalogue rows to arrive.
    void this.loadUnits();
    try {
      const [limits, income] = await Promise.all([this.service.limits(), this.service.income()]);
      this.limits.set(limits);
      this.income.set(income.versions);
      await this.loadBanners(0);
    } catch {
      this.error.set('Could not load the planner’s reference data.');
    }
  }

  /** Characters, weapons, and what the account holds — for the custom banner. */
  private async loadUnits(): Promise<void> {
    // **Beta units included.** A leaked character is exactly who a hypothetical banner is
    // for; the card says "beta" so it is not mistaken for a released one.
    const [characters, weapons, roster, owned] = await Promise.all([
      everyPage((offset) => this.catalogue.listCharacters(
        { limit: CATALOGUE_PAGE, offset, include_beta: true },
      )).catch(() => null),
      everyPage((offset) => this.catalogue.listWeapons(
        { limit: CATALOGUE_PAGE, offset, include_beta: true },
      )).catch(() => null),
      // Not fatal: without it the slots start unowned and say nothing about the account.
      this.roster.list().catch(() => null),
      everyPage((offset) => this.catalogue.listOwnedWeapons(
        { limit: CATALOGUE_PAGE, offset },
      )).catch(() => null),
    ]);
    this.allCharacters.set(characters ?? []);
    this.allWeapons.set(weapons ?? []);
    // Owned **and** a constellation said: an owned row with no constellation is "nobody has
    // said how many", which is not C0.
    const entries = roster?.entries ?? [];
    const names = new Map<string, number>();
    for (const e of entries) names.set(e.name, (names.get(e.name) ?? 0) + 1);
    this.held.set(new Map(
      entries
        .filter((e) => e.owned === true && e.constellation !== null && names.get(e.name) === 1)
        .map((e) => [e.name, e.constellation as number]),
    ));
    const best = new Map<string, number>();
    for (const copy of owned ?? []) {
      const name = copy.weapon?.name;
      if (name) best.set(name, Math.max(best.get(name) ?? 0, copy.refinement));
    }
    this.heldWeapons.set(best);
  }

  /** Sequence guard: every *replace* takes a ticket, and anything older is dropped. */
  private bannerTicket = 0;
  private bannerTimer: ReturnType<typeof setTimeout> | null = null;
  /** True while a replace or an append is in flight. */
  private bannersBusy = false;
  /** The filter the list on screen was fetched with, as a key. */
  private listedFilter = '';

  /**
   * Fetch a page of banners. `offset` 0 replaces, anything else appends.
   *
   * **An append is refused while the list is about to change.** "Show more" during a search
   * appended page two of the *new* filter onto page one of the *old*, and — because it took a
   * newer ticket — threw away the search's own reply, so the mixed list stayed. An append now
   * belongs to the list on screen or does not happen; the pending replace draws the right one.
   */
  protected async loadBanners(offset: number): Promise<void> {
    const page = this.limits()?.banner_page ?? 8;
    const filter = this.bannerFilter();
    const key = JSON.stringify(filter);
    if (offset && (this.bannersBusy || this.bannerTimer || key !== this.listedFilter)) return;
    const ticket = offset ? this.bannerTicket : ++this.bannerTicket;
    this.bannersBusy = true;
    try {
      const body = await this.service.banners(offset, page, filter);
      if (ticket !== this.bannerTicket) return;
      this.banners.set(offset ? [...this.banners(), ...body.banners] : body.banners);
      this.bannerTotal.set(body.total);
      this.listedFilter = key;
    } catch {
      if (ticket !== this.bannerTicket) return;
      // Not fatal: the planner works without a banner, it just cannot read the refund from
      // the account. Blanking the page over it would be the worse trade.
      this.bannerTotal.set(this.banners().length);
    } finally {
      if (ticket === this.bannerTicket) this.bannersBusy = false;
    }
  }

  /** The chips and the search box, as the endpoint spells them. Unset fields are left out. */
  private bannerFilter(): WishBannerFilter {
    const filter: WishBannerFilter = {};
    const q = this.bannerQuery().trim();
    if (q) filter.q = q;
    if (this.bannerKind()) filter.kind = this.bannerKind()!;
    if (this.bannerElement()) filter.element = this.bannerElement()!;
    if (this.bannerWeapon()) filter.weapon_type = this.bannerWeapon()!;
    return filter;
  }

  /** Typed: debounced, for the same `9`, `99`, `999` reason the plan is. */
  protected searchBanners(text: string): void {
    this.bannerQuery.set(text);
    if (this.bannerTimer) clearTimeout(this.bannerTimer);
    this.bannerTimer = setTimeout(() => {
      this.bannerTimer = null;
      void this.loadBanners(0);
    }, DEBOUNCE_MS);
  }

  /** A chip: pressing the lit one clears it, as a single-choice chip row reads. */
  protected toggleBannerChip(group: 'kind' | 'element' | 'weapon', value: string): void {
    const next = this.bannerChipOn(group, value) ? null : value;
    if (group === 'kind') this.bannerKind.set(next as Kind | null);
    else if (group === 'element') this.bannerElement.set(next as WishBannerFilter['element']);
    else this.bannerWeapon.set(next as WishBannerFilter['weapon_type']);
    void this.loadBanners(0);
  }

  protected bannerChipOn(group: 'kind' | 'element' | 'weapon', value: string): boolean {
    const current =
      group === 'kind' ? this.bannerKind()
        : group === 'element' ? this.bannerElement()
          : this.bannerWeapon();
    return current === value;
  }

  /** True when anything narrows the list, so the empty state can say it is the filter. */
  protected readonly bannersFiltered = computed(
    () => !!(this.bannerQuery().trim() || this.bannerKind() || this.bannerElement()
      || this.bannerWeapon()),
  );

  protected showMoreBanners(): void {
    void this.loadBanners(this.banners().length);
  }

  /**
   * Pick a banner, filling in what it knows.
   *
   * The name and the banner kind come from the banner; **pity, guarantee and owned copies
   * stay whatever the user last said**, because the banner cannot know them and silently
   * resetting a typed pity to zero is worse than leaving it.
   */
  /** The chosen banner's slug, but only for the leg it is actually a banner for. */
  private slugForKind(kind: 'character' | 'weapon'): string | null {
    const picked = this.banner();
    if (picked && picked.kind === kind) return picked.slug;
    // **The signature weapon runs on its own banner.** Sending null here priced the weapon
    // leg at nothing; sending the character's slug priced it at the character banner's
    // 4-star economics. The banner beside it is the actual answer, and the row knows it.
    if (kind === 'weapon') return this.pairedWeaponBanner();
    return null;
  }

  protected chooseBanner(banner: WishBannerRead | null): void {
    this.remember(banner);
    this.chosenBanner.set(banner?.slug ?? null);
    if (!banner) return;
    if (this.isCustom(banner.slug)) {
      const kind = banner.kind as Kind;
      if (kind === 'weapon') this.planWeapon.set(true);
      this.patch(kind, this.customTarget(kind));
      return;
    }
    if (banner.kind === 'character') {
      // The roster's answer, in simple mode too. Reading it only in custom mode left the
      // default mode asking the user to retype the constellation the response just delivered.
      this.patch('character', this.fromFeatured(banner.featured_five[0]));
      // **The weapon goal is left as the user set it.** Forcing it off here meant one click
      // lit the paired banner in brass, captioned it "Signature", and sent `weapon: null` --
      // two halves of one screen asserting opposite things. The new test only passed because
      // it set `planWeapon(true)` on the next line, undoing the one thing production did.
    } else {
      this.planWeapon.set(true);
      // A weapon banner has two 5-stars and no weapon roster exists, so this names the first
      // and carries no owned count — `fromFeatured` returns 0 for a null, which is "None".
      this.patch('weapon', this.fromFeatured(banner.featured_five[0]));
    }
  }

  /** True for the picked banner and for the weapon banner paired with it. */
  protected isPaired(slug: string): boolean {
    return this.pairedWeaponBanner() === slug;
  }

  protected isChosen(slug: string): boolean {
    return this.chosenBanner() === slug;
  }

  /** Open or close the banner picker for one custom row. */
  protected togglePicker(index: number): void {
    this.pickingFor.set(this.pickingFor() === index ? null : index);
  }

  /** Pick a banner for one row of a custom plan, filling in what the banner knows. */
  protected chooseRowBanner(index: number, banner: WishBannerRead | null): void {
    if (!this.rows()[index]) return;
    this.remember(banner);
    const change: Partial<CustomRow> = { bannerSlug: banner?.slug ?? null };
    if (banner) {
      change.banner = banner.kind as 'character' | 'weapon';
      if (this.isCustom(banner.slug)) {
        Object.assign(change, this.customTarget(banner.kind as Kind));
      } else if (banner.featured_five.length === 1) {
        // A character banner has one 5-star, so it is the goal. A weapon banner has two, and
        // which one the user wants is theirs to say -- picking for them would be the same guess
        // as deciding whose signature a weapon is.
        Object.assign(change, this.fromFeatured(banner.featured_five[0]));
      } else {
        change.label = '';
        change.ownedCopies = 0;
      }
    }
    this.patchRow(index, change);
    this.pickingFor.set(null);
  }

  /** Name a row's goal from a featured unit, carrying what the roster already knows. */
  protected chooseRowUnit(index: number, item: WishFeaturedItem): void {
    if (!this.rows()[index]) return;
    this.patchRow(index, this.fromFeatured(item));
  }

  /**
   * A featured unit as row fields.
   *
   * **`owned_copies` on the wire is a constellation; the row counts copies.** C3 is four
   * copies and holding none is 0, so this is `constellation + 1` — reading it straight across
   * would say a C3 account holds three copies and make a fresh C0 pull read as "from C2".
   * Null stays 0: "nobody has said" is not "I have one".
   */
  private fromFeatured(item: WishFeaturedItem | undefined): Partial<CustomRow> {
    if (!item) return { label: '' };
    // **Only when the roster actually knows.** Null is "nobody has said", and writing that
    // across as 0 would wipe a count the user had typed themselves and replace it with a
    // claim the account never made.
    if (item.owned_copies === null || item.owned_copies === undefined) {
      return { label: item.name };
    }
    return { label: item.name, ownedCopies: item.owned_copies + 1 };
  }

  /** The featured 5-stars a row may name its goal after. */
  protected rowUnits(entry: CustomRow): WishFeaturedItem[] {
    return this.rowBanner(entry)?.featured_five ?? [];
  }

  /**
   * True when this row is the first of its banner kind, which is the only row whose pity and
   * guarantee the planner reads.
   *
   * **`plan_campaign` applies both only `if first_on_banner`** (`planner.py:256-258`), because
   * the state carries: obtaining a copy is a 5-star, which resets pity and spends the
   * guarantee, so a later leg on the same banner starts from what the simulation produced
   * rather than from anything the user could type. Offering the controls on every row gave
   * three boxes that accepted a number and reported nothing -- measured, row 2's pity moved
   * the averages not at all (93.446/186.113 at pity 0 and at pity 89) while row 1's moved them
   * to 32.149.
   *
   * It is also what made the guarantee a dead end: `request()` zeroes `lost_fifty_fifties` for
   * every row but the first, so arming ✓ on row 2 sent `guaranteed: true` with no losses --
   * exactly the state `_validate_leg` refuses -- and the control that would have fixed it is
   * only rendered on row 0.
   */
  protected leadsItsBanner(index: number): boolean {
    const entry = this.rows()[index];
    if (!entry) return false;
    return this.rows().findIndex((row) => row.banner === entry.banner) === index;
  }

  /** Hard pity for whichever banner this row is on. */
  protected rowHardPity(entry: CustomRow): number {
    return entry.banner === 'character' ? this.characterHardPity() : this.weaponHardPity();
  }

  /**
   * Guaranteed and the loss counter are not independent for a row either — arming the
   * guarantee requires having lost a 50/50, and `guaranteed` with zero losses is a state the
   * backend refuses with a 422.
   */
  protected setRowGuaranteed(index: number, next: boolean): void {
    const current = this.rows()[index];
    if (!current) return;
    const losses =
      current.banner === 'character' && next && current.lostFiftyFifties === 0
        ? 1
        : current.lostFiftyFifties;
    this.patchRow(index, { guaranteed: next, lostFiftyFifties: losses });
  }

  protected setRowLosses(index: number, next: number): void {
    const current = this.rows()[index];
    if (!current) return;
    this.patchRow(index, {
      lostFiftyFifties: next,
      guaranteed: next === 0 ? false : current.guaranteed,
    });
  }

  /** The banner a custom row is on, when it is one of the loaded ones. */
  protected rowBanner(entry: CustomRow): WishBannerRead | null {
    return this.known().find((b) => b.slug === entry.bannerSlug) ?? null;
  }

  /** `2026-09-23 11:00:00` as `Sep 2026` — the banner list is scanned, not read. */
  protected bannerWhen(banner: WishBannerRead): string {
    const raw = banner.starts_at;
    if (!raw) return '';
    const parsed = new Date(raw.replace(' ', 'T'));
    return Number.isNaN(parsed.getTime())
      ? raw.slice(0, 7)
      : parsed.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
  }

  private async recompute(request: ReturnType<WishesPage['request']>): Promise<void> {
    // Debouncing cancels a pending *timer*, not a request already in flight. Without this
    // guard a slow request A and a fast request B can land out of order and the table shows
    // A's answer for B's inputs — no error, no cue, just the wrong numbers.
    const ticket = ++this.latest;
    this.pending.set(true);
    try {
      const plan = await this.service.plan(request);
      if (ticket !== this.latest) return;
      // **Keep the chosen rung across a recompute, drop it when the ladder changes shape.**
      // Typing a primogem re-plans the same goals, and resetting there would throw the
      // selection away on every keystroke; adding or removing a goal makes index 3 a
      // different thing, and keeping it would silently chart the wrong one.
      const chosen = this.chartedIndex();
      if (chosen === null || plan.milestones[chosen]?.label !== this.chartedLabel) {
        this.chartedIndex.set(null);
        this.chartedLabel = null;
      }
      this.plan.set(plan);
      this.error.set(null);
    } catch (caught) {
      if (ticket !== this.latest) return;
      this.plan.set(null);
      this.chartedIndex.set(null);
      this.chartedLabel = null;
      this.error.set(this.describe(caught));
    } finally {
      if (ticket === this.latest) this.pending.set(false);
    }
  }

  private describe(caught: unknown): string {
    const detail = (caught as { detail?: unknown })?.detail;
    if (typeof detail === 'string') return detail;
    return 'That combination could not be planned.';
  }

  /**
   * `Number('')` is 0, so an emptied box would silently read as "I have none" — the trap
   * CLAUDE.md records from the materials editor. An unparseable value keeps the last one.
   */
  protected parse(target: EventTarget | null, max?: number): number | null {
    const raw = (target as HTMLInputElement | null)?.value ?? '';
    if (raw.trim() === '') return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0) return null;
    return max === undefined ? Math.floor(value) : Math.min(Math.floor(value), max);
  }

  protected setNumber(
    target: EventTarget | null,
    into: (value: number) => void,
    max?: number,
  ): void {
    const value = this.parse(target, max);
    if (value !== null) into(value);
  }

  /** Update one field of a simple-mode position. */
  protected patch(which: 'character' | 'weapon', change: Partial<Position>): void {
    const signal = which === 'character' ? this.character : this.weapon;
    signal.set({ ...signal(), ...change });
  }

  /**
   * Guaranteed and the loss counter are not independent. Arming the guarantee *requires*
   * losing a 50/50, so `guaranteed` with zero losses is a state the game cannot produce.
   * Selecting it here raises the counter rather than sending a 422.
   */
  protected setGuaranteed(which: 'character' | 'weapon', next: boolean): void {
    const current = which === 'character' ? this.character() : this.weapon();
    const losses =
      which === 'character' && next && current.lostFiftyFifties === 0
        ? 1
        : current.lostFiftyFifties;
    this.patch(which, { guaranteed: next, lostFiftyFifties: losses });
  }

  protected setLosses(next: number): void {
    const current = this.character();
    this.patch('character', {
      lostFiftyFifties: next,
      guaranteed: next === 0 ? false : current.guaranteed,
    });
  }

  // -- custom rows

  /** True when the plan is full, so the add buttons can say so rather than fail on use. */
  protected readonly canAddRow = computed(() => this.rows().length < MAX_ROWS);

  protected addRow(banner: 'character' | 'weapon'): void {
    if (!this.canAddRow()) return;
    // Unnamed until a banner names it. The invented `"Weapon 2"` had no editor to change it and
    // was sent as the goal's name, so the ladder printed `Weapon 2 R1`.
    this.rows.set(this.normalised([...this.rows(), row(banner)]));
  }

  protected removeRow(index: number): void {
    // Never leave the plan empty: a request with no targets is refused, and the page would
    // show an error rather than an empty state.
    if (this.rows().length === 1) return;
    // Removing the row that led its banner kind promotes another, so the invariant has to be
    // re-established here as well.
    this.rows.set(this.normalised(this.rows().filter((_, i) => i !== index)));
  }

  protected moveRow(index: number, by: -1 | 1): void {
    const next = [...this.rows()];
    const to = index + by;
    if (!next[index] || to < 0 || to >= next.length) return;
    [next[index], next[to]] = [next[to], next[index]];
    this.rows.set(this.normalised(next));
  }

  /**
   * Strip pity, guarantee and losses from rows that cannot carry them.
   *
   * Reordering changes *which* row leads its banner kind, so a row that legitimately held a
   * guarantee can end up second -- where `request()` zeroes its loss counter and the pair
   * becomes the state the backend refuses. Rather than leave a 422 for the user to discover
   * from a drag, the fields are cleared on the rows the planner will ignore anyway.
   */
  private normalised(rows: CustomRow[]): CustomRow[] {
    return rows.map((entry, index) => {
      const leads = rows.findIndex((row) => row.banner === entry.banner) === index;
      if (leads && index === 0) return entry;
      if (!leads) return { ...entry, pity: 0, guaranteed: false, lostFiftyFifties: 0 };
      // Leads its kind but is not row 0: it may hold pity and a guarantee, but only row 0 may
      // carry the account-wide Capturing Radiance counter, so a guarantee here has nothing to
      // rest on.
      return { ...entry, guaranteed: false, lostFiftyFifties: 0 };
    });
  }

  protected patchRow(index: number, change: Partial<CustomRow>): void {
    const next = [...this.rows()];
    // **Guarded.** Spreading a row that does not exist produced one out of the change alone,
    // so `ownedCopies` became `undefined`, the clamp below turned it into `NaN`, and it went
    // out as `null` — a 422 whose message named a field the user never touched, on a row
    // they never added.
    if (!next[index]) return;
    next[index] = { ...next[index], ...change };
    // Changing the banner can leave a goal above the new banner's cap.
    const cap = MAX_COPIES[next[index].banner];
    // **Pity is capped per banner too.** Character hard pity is 90 and the weapon banner's is
    // 80, so a row switched from one to the other kept a pity the new banner cannot have and
    // the request came back 400 "must be within [0, 79]" from a control that looked valid.
    const hardPity = this.rowHardPity(next[index]);
    next[index].pity = Math.min(Math.max(next[index].pity, 0), Math.max(hardPity - 1, 0));
    next[index].targetCopies = Math.min(next[index].targetCopies, cap);
    // **Clamped to the cap, not to one below it.** `cap - 1` turned a C6 account into "from
    // C5 to C6" and priced a copy they already hold. Holding the maximum is a real state; it
    // just leaves nothing to plan, which `rowIsComplete` reports rather than papering over.
    next[index].ownedCopies = Math.min(Math.max(next[index].ownedCopies, 0), cap);
    if (next[index].targetCopies <= next[index].ownedCopies) {
      // Capped: a complete row has no rung above it, and `owned + 1` would send a goal past
      // the banner's maximum. `rowIsComplete` is what the request and the UI read instead.
      next[index].targetCopies = Math.min(next[index].ownedCopies + 1, cap);
    }
    this.rows.set(this.normalised(next));
  }

  protected copyOptions(banner: 'character' | 'weapon'): number[] {
    return Array.from({ length: MAX_COPIES[banner] }, (_, i) => i + 1);
  }

  protected ownedOptions(banner: 'character' | 'weapon'): number[] {
    // 0 ("None") through the maximum, inclusive: a C6 character is a thing an account can be,
    // and leaving it out is what made the roster's own answer unrepresentable.
    return Array.from({ length: MAX_COPIES[banner] + 1 }, (_, i) => i);
  }

  /** True when the row's goal is already held, so there is nothing left to pull for. */
  protected rowIsComplete(entry: CustomRow): boolean {
    return entry.ownedCopies >= MAX_COPIES[entry.banner];
  }

  /** The rows that describe a goal still to reach. */
  protected readonly plannableRows = computed(
    () => this.rows().filter((entry) => !this.rowIsComplete(entry)),
  );

  /** "C3" for the fourth copy of a character, "R2" for the second of a weapon. */
  protected rung(banner: 'character' | 'weapon', copies: number): string {
    return banner === 'character' ? `C${copies - 1}` : `R${copies}`;
  }

  /**
   * What *holding* `copies` is called — which is not the same as the rung `copies` reaches.
   *
   * Holding none is "None", not "C0": a character you have never pulled is not a C0
   * character. Getting this wrong made a fresh row read "from C0 to C0", which is both
   * self-contradictory and a goal the backend refuses.
   */
  protected ownedLabel(banner: 'character' | 'weapon', copies: number): string {
    return copies === 0 ? 'None' : this.rung(banner, copies);
  }

  // -- income

  protected toggleVersion(version: string): void {
    const next = new Set(this.selectedVersions());
    if (next.has(version)) next.delete(version);
    else next.add(version);
    this.selectedVersions.set(next);
  }

  protected isSelected(version: string): boolean {
    return this.selectedVersions().has(version);
  }

  protected tierLabel(tier: Tier): string {
    return { f2p: 'F2P', welkin: 'Welkin', welkin_bp: 'Welkin + BP' }[tier];
  }

  protected strategyLabel(value: string): string {
    return value === 'r1_first' ? 'R1 first' : `${value.slice(0, 2).toUpperCase()} first`;
  }

  protected refundLabel(tier: string): string {
    if (tier === (this.limits()?.account_refund ?? ACCOUNT_REFUND)) {
      return 'Calculate with my account';
    }
    const percent = (this.limits()?.starglitter_refund_tiers[tier] ?? 0) * 100;
    if (tier === 'none') return 'None';
    const shape = { low: 'Low', average: 'Average', high: 'High' }[tier] ?? tier;
    return `${percent.toFixed(1)}% (${shape})`;
  }

  protected readonly tiers = TIERS;

  /** Percent for the bar behind a goal chip. */
  protected percent(chance: number): number {
    return Math.round(chance * 1000) / 10;
  }

  /** Green through red, so a row reads before any digit does. */
  protected barClass(chance: number): string {
    if (chance >= 0.9) return 'bar bar--sure';
    if (chance >= 0.6) return 'bar bar--likely';
    if (chance >= 0.25) return 'bar bar--even';
    if (chance > 0) return 'bar bar--unlikely';
    return 'bar bar--none';
  }

  // -- custom banners

  protected isCustom(slug: string | null | undefined): boolean {
    return !!slug && slug.startsWith('custom:');
  }

  /** A custom banner's unit as a featured item, with the account's constellation if held. */
  private featured(kind: Kind, name: string): WishFeaturedItem {
    const held = kind === 'character' ? this.held().get(name) : undefined;
    return { name, icon: this.artFor(name), owned_copies: held ?? null };
  }

  /**
   * The goal a custom banner names, as position fields.
   *
   * **Owned copies are always written, never left as they were** — the fix #337 made, kept.
   * Switching from a C3 goal to an unannounced one and keeping "from C3" would plan a copy
   * nobody holds. An unannounced unit is unowned by definition; a named one is whatever the
   * account says — the roster's constellation, or the best owned copy's refinement — and
   * unowned when it says nothing.
   */
  private customTarget(kind: Kind): Partial<Position> {
    const name = this.custom()[kind].five;
    if (kind === 'weapon') {
      // Refinement *is* the copy count: R1 is one copy, R5 five.
      return { label: name, ownedCopies: this.heldWeapons().get(name) ?? 0 };
    }
    const held = this.held().get(name);
    return { label: name, ownedCopies: held === undefined ? 0 : held + 1 };
  }

  /** Name the custom banner's 5-star, and carry it to every goal on that banner. */
  protected setCustomFive(kind: Kind, picked: readonly string[]): void {
    const name = picked[0] ?? UNKNOWN;
    this.custom.update((all) => ({ ...all, [kind]: { ...all[kind], five: name } }));
    const target = this.customTarget(kind);
    if (this.mode() === 'simple' && this.chosenBanner() === CUSTOM_SLUG[kind]) {
      this.patch(kind, target);
    }
    this.rows().forEach((entry, index) => {
      if (entry.bannerSlug === CUSTOM_SLUG[kind]) this.patchRow(index, target);
    });
  }

  /** Name one featured 4-star. Its constellation starts at what the account holds. */
  protected setCustomSlot(kind: Kind, index: number, picked: readonly string[]): void {
    const name = picked[0] ?? UNKNOWN;
    const constellation = kind === 'character' ? this.held().get(name) ?? null : null;
    this.updateSlot(kind, index, { name, constellation });
  }

  /** `'none'` is unowned; anything else a constellation. */
  protected setCustomSlotConstellation(kind: Kind, index: number, value: string): void {
    this.updateSlot(kind, index, {
      constellation: value === 'none' ? null : Number(value),
    });
  }

  /** True when the slot is priced at exactly what the account holds, so the page can say so. */
  protected slotFromAccount(slot: CustomSlot): boolean {
    const held = this.held().get(slot.name);
    return held !== undefined && held === slot.constellation;
  }

  /** Put the custom banner of this kind back to all `?`. */
  protected resetCustom(kind: Kind): void {
    this.custom.update((all) => ({ ...all, [kind]: blankCustom(kind) }));
    this.setCustomFive(kind, [UNKNOWN]);
  }

  private updateSlot(kind: Kind, index: number, change: Partial<CustomSlot>): void {
    this.custom.update((all) => {
      const fours = [...all[kind].fours];
      if (!fours[index]) return all;
      fours[index] = { ...fours[index], ...change };
      return { ...all, [kind]: { ...all[kind], fours } };
    });
  }

  /**
   * Which kind of custom banner to edit under a custom row, if any.
   *
   * **Under the first row on it only.** One custom banner of each kind is shared by every row
   * that picks it, so drawing the editor under each would be two controls for one value.
   */
  protected editsCustom(index: number): Kind | null {
    const slug = this.rows()[index]?.bannerSlug;
    if (!this.isCustom(slug)) return null;
    return this.rows().findIndex((entry) => entry.bannerSlug === slug) === index
      ? (slug === CUSTOM_SLUG.weapon ? 'weapon' : 'character')
      : null;
  }

  /** The simple mode's editor: shown while a custom banner is the one picked. */
  protected readonly editingCustom = computed<Kind | null>(() => {
    const slug = this.chosenBanner();
    if (slug === CUSTOM_SLUG.character) return 'character';
    if (slug === CUSTOM_SLUG.weapon) return 'weapon';
    return null;
  });

  protected readonly constellations = [0, 1, 2, 3, 4, 5, 6];
}
