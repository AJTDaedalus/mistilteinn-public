import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CatalogueIcon } from '../../shared/icon/icon';

import {
  WishesService,
  type WishBannerRead,
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

function row(banner: 'character' | 'weapon', label: string): CustomRow {
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
  imports: [FormsModule, DecimalPipe, DatePipe, CatalogueIcon],
  templateUrl: './wishes.html',
  styleUrl: './wishes.scss',
})
export class WishesPage {
  private service = inject(WishesService);

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
  protected readonly incomeFetchedAt = signal<string | null>(null);
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
  protected readonly pairedWeaponBanner = computed(() => {
    const picked = this.banner();
    if (!picked || picked.kind !== 'character') return null;
    return this.banners().find(
      (b) => b.kind === 'weapon' && (picked.alongside ?? []).includes(b.slug),
    ) ?? null;
  });

  protected readonly banner = computed(() =>
    this.banners().find((b) => b.slug === this.chosenBanner()) ?? null,
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
        targets: this.rows().map((entry, index) => ({
          ...this.target(entry, entry.banner),
          // Only the first row declares the counter; the backend refuses a later one.
          lost_fifty_fifties:
            index === 0 ? this.target(entry, entry.banner).lost_fifty_fifties : 0,
          target_copies: entry.targetCopies,
          banner_slug: entry.bannerSlug,
        })),
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
    };
  }

  private async load(): Promise<void> {
    try {
      const [limits, income] = await Promise.all([this.service.limits(), this.service.income()]);
      this.limits.set(limits);
      this.income.set(income.versions);
      this.incomeFetchedAt.set(income.fetched_at ?? null);
      await this.loadBanners(0);
    } catch {
      this.error.set('Could not load the planner’s reference data.');
    }
  }

  /** Fetch a page of banners. `offset` 0 replaces, anything else appends. */
  protected async loadBanners(offset: number): Promise<void> {
    const page = this.limits()?.banner_page ?? 8;
    try {
      const body = await this.service.banners(offset, page);
      this.banners.set(offset ? [...this.banners(), ...body.banners] : body.banners);
      this.bannerTotal.set(body.total);
    } catch {
      // Not fatal: the planner works without a banner, it just cannot read the refund from
      // the account. Blanking the page over it would be the worse trade.
      this.bannerTotal.set(this.banners().length);
    }
  }

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
    if (kind === 'weapon') return this.pairedWeaponBanner()?.slug ?? null;
    return null;
  }

  protected chooseBanner(banner: WishBannerRead | null): void {
    this.chosenBanner.set(banner?.slug ?? null);
    if (!banner) return;
    if (banner.kind === 'character') {
      this.patch('character', { label: banner.featured_five[0]?.name ?? '' });
      this.planWeapon.set(false);
    } else {
      this.planWeapon.set(true);
      this.patch('weapon', { label: banner.featured_five[0]?.name ?? '' });
    }
  }

  /** True for the picked banner and for the weapon banner paired with it. */
  protected isPaired(slug: string): boolean {
    return this.pairedWeaponBanner()?.slug === slug;
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
    const change: Partial<CustomRow> = { bannerSlug: banner?.slug ?? null };
    if (banner) {
      change.banner = banner.kind as 'character' | 'weapon';
      // A character banner has one 5-star, so it is the goal. A weapon banner has two, and
      // which one the user wants is theirs to say -- picking for them would be the same guess
      // as deciding whose signature a weapon is.
      if (banner.featured_five.length === 1) {
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
    if (!item) return { label: '', ownedCopies: 0 };
    const owned = item.owned_copies === null || item.owned_copies === undefined
      ? 0
      : item.owned_copies + 1;
    return { label: item.name, ownedCopies: owned };
  }

  /** The featured 5-stars a row may name its goal after. */
  protected rowUnits(entry: CustomRow): WishFeaturedItem[] {
    return this.rowBanner(entry)?.featured_five ?? [];
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
    return this.banners().find((b) => b.slug === entry.bannerSlug) ?? null;
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
      if (plan.milestones.length !== (this.plan()?.milestones.length ?? -1)) {
        this.chartedIndex.set(null);
      }
      this.plan.set(plan);
      this.error.set(null);
    } catch (caught) {
      if (ticket !== this.latest) return;
      this.plan.set(null);
      this.chartedIndex.set(null);
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
    const label = banner === 'character' ? 'Character' : 'Weapon';
    this.rows.set([
      ...this.rows(),
      row(banner, `${label} ${this.rows().length + 1}`),
    ]);
  }

  protected removeRow(index: number): void {
    // Never leave the plan empty: a request with no targets is refused, and the page would
    // show an error rather than an empty state.
    if (this.rows().length === 1) return;
    this.rows.set(this.rows().filter((_, i) => i !== index));
  }

  protected moveRow(index: number, by: -1 | 1): void {
    const next = [...this.rows()];
    const to = index + by;
    if (!next[index] || to < 0 || to >= next.length) return;
    [next[index], next[to]] = [next[to], next[index]];
    this.rows.set(next);
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
    next[index].targetCopies = Math.min(next[index].targetCopies, cap);
    next[index].ownedCopies = Math.min(next[index].ownedCopies, cap - 1);
    if (next[index].targetCopies <= next[index].ownedCopies) {
      next[index].targetCopies = next[index].ownedCopies + 1;
    }
    this.rows.set(next);
  }

  protected copyOptions(banner: 'character' | 'weapon'): number[] {
    return Array.from({ length: MAX_COPIES[banner] }, (_, i) => i + 1);
  }

  protected ownedOptions(banner: 'character' | 'weapon'): number[] {
    return Array.from({ length: MAX_COPIES[banner] }, (_, i) => i);
  }

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
}
