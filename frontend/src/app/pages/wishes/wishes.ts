import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CatalogueIcon } from '../../shared/icon/icon';

import {
  WishesService,
  type WishBannerRead,
  type WishIncomeVersionRead,
  type WishLimits,
  type WishPlanRead,
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
  protected readonly strategy = signal('c0_first');

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
  protected readonly banner = computed(() =>
    this.banners().find((b) => b.slug === this.chosenBanner()) ?? null,
  );

  protected readonly hasMoreBanners = computed(
    () => this.banners().length < this.bannerTotal(),
  );

  /** The first rung that carries a histogram — what the chart draws. */
  protected readonly charted = computed(
    () => this.plan()?.milestones.find((m) => (m.histogram ?? []).length) ?? null,
  );

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

  protected request() {
    const wallet = {
      primogems: this.primogems(),
      intertwined_fate: this.intertwined(),
      extra_wishes: this.projectedWishes(),
      starglitter_refund: this.refund(),
    };

    if (this.mode() === 'custom') {
      return {
        ...wallet,
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
      character: { ...this.target(this.character(), 'character'),
                   banner_slug: this.chosenBanner() },
      weapon: this.planWeapon()
        ? { ...this.target(this.weapon(), 'weapon'), banner_slug: this.chosenBanner() }
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
      change.label = banner.featured_five[0]?.name ?? '';
    }
    this.patchRow(index, change);
    this.pickingFor.set(null);
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
      const plan = await this.service.plan(request as never);
      if (ticket !== this.latest) return;
      this.plan.set(plan);
      this.error.set(null);
    } catch (caught) {
      if (ticket !== this.latest) return;
      this.plan.set(null);
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
