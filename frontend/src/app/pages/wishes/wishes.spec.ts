import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { WishesService, type WishLimits, type WishPlanRead } from './wishes.service';
import { WishesPage } from './wishes';

const LIMITS: WishLimits = {
  account_refund: 'account',
  primogems_per_wish: 160,
  max_constellation: 6,
  max_refinement: 5,
  max_lost_fifty_fifties: 3,
  banner_page: 8,
  strategies: ['r1_first', 'c0_first', 'c1_first', 'c6_first'],
  starglitter_refund_tiers: { none: 0, low: 0.041667, average: 0.075269, high: 0.111111 },
  banners: {
    character: { hard_pity: 90, published_worst_case: 180, capturing_radiance: true },
    weapon: { hard_pity: 80, published_worst_case: 160, capturing_radiance: false },
  },
};

const INCOME = {
  fetched_at: '2026-09-22T12:00:00Z',
  versions: [
    { version: '7.0', is_estimate: false, f2p: 101.6, welkin: 127.9, welkin_bp: 136.1 },
    { version: '7.1', is_estimate: true, f2p: 88.0, welkin: 114.3, welkin_bp: 122.5 },
  ],
};

const PLAN: WishPlanRead = {
  budget: 0,
  wallet_wishes: 0,
  refunded_wishes: 0,
  refund_source: 'tier',
  published_worst_case: 180,
  milestones: [
    {
      copies: 1, label: 'Furina C0', success_chance: 1, average_wishes: 93.45, budget: 0,
      median_wishes: 80,
      histogram: [
        { start: 60, end: 70, probability: 0.2 },
        { start: 70, end: 80, probability: 0.5 },
        { start: 80, end: 90, probability: 0.3 },
      ],
    },
  ],
};

const BANNERS = {
  total: 20,
  fetched_at: '2026-09-22T12:00:00Z',
  banners: [
    {
      slug: 'When Warm Winds Cavort/2026-09-23', name: 'When Warm Winds Cavort',
      kind: 'character', starts_at: '2026-09-23 11:00:00', ends_at: '2026-10-13 17:59:59',
      featured_five: [{ name: 'Vesna', icon: 'UI_Vesna', owned_copies: null }],
      featured_four: [
        { name: 'Diona', icon: 'UI_Diona', owned_copies: 3 },
        { name: 'Faruzan', icon: null, owned_copies: null },
        { name: 'Chongyun', icon: 'UI_Chongyun', owned_copies: 0 },
      ],
      alongside: ['Epitome Invocation/2026-09-23'],
      signature_banner: 'Epitome Invocation/2026-09-23',
    },
    {
      slug: 'Epitome Invocation/2026-09-23', name: 'Epitome Invocation',
      kind: 'weapon', starts_at: '2026-09-23 11:00:00', ends_at: '2026-10-13 17:59:59',
      featured_five: [{ name: 'Splendor', icon: 'UI_Splendor', owned_copies: null }],
      featured_four: [{ name: 'New Bough', icon: null, owned_copies: null }],
      alongside: ['When Warm Winds Cavort/2026-09-23'],
      signature_banner: null,
    },
  ],
};

/** Access a protected member without widening the component's real surface. */
function open(page: WishesPage): any {
  return page as any;
}

function makePage(over: Partial<WishesService> = {}) {
  const service = {
    limits: vi.fn().mockResolvedValue(LIMITS),
    income: vi.fn().mockResolvedValue(INCOME),
    banners: vi.fn().mockResolvedValue(BANNERS),
    plan: vi.fn().mockResolvedValue(PLAN),
    ...over,
  };
  TestBed.configureTestingModule({
    providers: [{ provide: WishesService, useValue: service }],
  });
  const page = TestBed.runInInjectionContext(() => new WishesPage());
  return { page: open(page), service };
}

async function settled(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe('WishesPage', () => {
  describe('simple mode builds one character’s campaign', () => {
    it('sends the character, the weapon and the strategy', async () => {
      const { page } = makePage();
      await settled();
      const request = page.request();
      expect(request.character.banner).toBe('character');
      expect(request.weapon.banner).toBe('weapon');
      expect(request.strategy).toBe('c0_first');
      expect(request.targets).toBeUndefined();
    });

    it('drops the weapon when it is not being planned', async () => {
      const { page } = makePage();
      await settled();
      page.planWeapon.set(false);
      expect(page.request().weapon).toBeNull();
    });

    /** Capturing Radiance is the character banner's alone. */
    it('never sends banked losses on the weapon', async () => {
      const { page } = makePage();
      await settled();
      page.patch('weapon', { lostFiftyFifties: 3 });
      expect(page.request().weapon.lost_fifty_fifties).toBe(0);
    });
  });

  describe('custom mode builds an explicit list', () => {
    it('sends targets in order with their goals', async () => {
      const { page } = makePage();
      await settled();
      page.mode.set('custom');
      page.patchRow(0, { label: 'Furina', targetCopies: 3 });
      page.addRow('weapon');
      page.patchRow(1, { label: 'Splendor', targetCopies: 1 });
      page.addRow('character');
      page.patchRow(2, { label: 'Neuvillette', targetCopies: 1 });

      const request = page.request();
      expect(request.character).toBeUndefined();
      expect(request.targets.map((t: any) => [t.label, t.banner, t.target_copies])).toEqual([
        ['Furina', 'character', 3],
        ['Splendor', 'weapon', 1],
        ['Neuvillette', 'character', 1],
      ]);
    });

    /** One account, one counter — the backend refuses a later row that sets it. */
    it('lets only the first row carry the loss counter', async () => {
      const { page } = makePage();
      await settled();
      page.mode.set('custom');
      page.addRow('character');
      page.patchRow(0, { lostFiftyFifties: 2 });
      page.patchRow(1, { lostFiftyFifties: 3 });
      const targets = page.request().targets;
      expect(targets[0].lost_fifty_fifties).toBe(2);
      expect(targets[1].lost_fifty_fifties).toBe(0);
    });

    it('reorders rows', async () => {
      const { page } = makePage();
      await settled();
      page.mode.set('custom');
      page.patchRow(0, { label: 'first' });
      page.addRow('weapon');
      page.patchRow(1, { label: 'second' });
      page.moveRow(1, -1);
      expect(page.rows().map((r: any) => r.label)).toEqual(['second', 'first']);
    });

    it('will not move a row off either end', async () => {
      const { page } = makePage();
      await settled();
      page.mode.set('custom');
      page.addRow('weapon');
      page.moveRow(0, -1);
      page.moveRow(1, 1);
      expect(page.rows()).toHaveLength(2);
      expect(page.rows()[0].banner).toBe('character');
    });

    /** An empty plan is refused by the backend, so the page must not be able to build one. */
    it('refuses to remove the last row', async () => {
      const { page } = makePage();
      await settled();
      page.mode.set('custom');
      page.removeRow(0);
      expect(page.rows()).toHaveLength(1);
    });

    it('clamps a goal that the new banner cannot reach', async () => {
      const { page } = makePage();
      await settled();
      page.mode.set('custom');
      page.patchRow(0, { targetCopies: 7 });
      page.patchRow(0, { banner: 'weapon' });
      expect(page.rows()[0].targetCopies).toBe(5);
    });

    it('keeps the goal above what is already owned', async () => {
      const { page } = makePage();
      await settled();
      page.mode.set('custom');
      page.patchRow(0, { ownedCopies: 4, targetCopies: 1 });
      expect(page.rows()[0].targetCopies).toBe(5);
    });
  });

  describe('the wallet', () => {
    it('adds only the patches that were ticked, at the chosen tier', async () => {
      const { page } = makePage();
      await settled();
      page.toggleVersion('7.1');
      expect(page.projectedWishes()).toBe(88);
      page.tier.set('welkin_bp');
      expect(page.projectedWishes()).toBe(122);
      page.toggleVersion('7.1');
      expect(page.projectedWishes()).toBe(0);
    });

    it('sends the refund tier so the backend applies the cited rate', async () => {
      const { page } = makePage();
      await settled();
      page.refund.set('average');
      expect(page.request().starglitter_refund).toBe('average');
    });

    it('labels the refund tiers from the backend rather than hardcoding them', async () => {
      const { page } = makePage();
      await settled();
      expect(page.refundLabel('none')).toBe('None');
      expect(page.refundLabel('average')).toContain('7.5');
      expect(page.refundTiers()).toEqual(['none', 'low', 'average', 'high']);
    });
  });

  describe('Capturing Radiance', () => {
    /** Arming the guarantee requires losing a 50/50, which increments the counter. */
    it('cannot express guaranteed with no losses', async () => {
      const { page } = makePage();
      await settled();
      page.setGuaranteed('character', true);
      expect(page.character().lostFiftyFifties).toBe(1);
    });

    it('drops the guarantee when the losses go back to zero', async () => {
      const { page } = makePage();
      await settled();
      page.setGuaranteed('character', true);
      page.setLosses(0);
      expect(page.character().guaranteed).toBe(false);
    });

    /** The weapon banner has Epitomized Path, which arms without any counter. */
    it('does not touch the counter when the weapon is guaranteed', async () => {
      const { page } = makePage();
      await settled();
      page.setGuaranteed('weapon', true);
      expect(page.weapon().guaranteed).toBe(true);
      expect(page.character().lostFiftyFifties).toBe(0);
    });

    it('says when three losses already amount to a guarantee', async () => {
      const { page } = makePage();
      await settled();
      expect(page.radianceIsCertain()).toBe(false);
      page.setLosses(3);
      expect(page.radianceIsCertain()).toBe(true);
    });
  });

  describe('numeric inputs', () => {
    /** `Number('')` is 0, so an emptied box would read as "I hold none". */
    it('ignores an emptied box rather than reading it as zero', async () => {
      const { page } = makePage();
      await settled();
      page.primogems.set(1600);
      page.setNumber({ value: '' } as HTMLInputElement, page.primogems.set);
      expect(page.primogems()).toBe(1600);
    });

    it('ignores a value that is not a number', async () => {
      const { page } = makePage();
      await settled();
      page.primogems.set(1600);
      page.setNumber({ value: 'abc' } as HTMLInputElement, page.primogems.set);
      expect(page.primogems()).toBe(1600);
    });

    it('clamps to the maximum it was given', async () => {
      const { page } = makePage();
      await settled();
      page.setNumber({ value: '500' } as HTMLInputElement,
        (v: number) => page.patch('character', { pity: v }), 89);
      expect(page.character().pity).toBe(89);
    });

    it('refuses a negative', async () => {
      const { page } = makePage();
      await settled();
      page.primogems.set(1600);
      page.setNumber({ value: '-5' } as HTMLInputElement, page.primogems.set);
      expect(page.primogems()).toBe(1600);
    });
  });

  describe('presentation', () => {
    it('grades the bar from sure to none', async () => {
      const { page } = makePage();
      await settled();
      expect(page.barClass(1)).toContain('sure');
      expect(page.barClass(0.7)).toContain('likely');
      expect(page.barClass(0.3)).toContain('even');
      expect(page.barClass(0.05)).toContain('unlikely');
      expect(page.barClass(0)).toContain('none');
    });

    it('keeps one decimal of a percentage', async () => {
      const { page } = makePage();
      await settled();
      expect(page.percent(0.4908)).toBe(49.1);
    });

    it('names rungs the way a player says them', async () => {
      const { page } = makePage();
      await settled();
      expect(page.rung('character', 1)).toBe('C0');
      expect(page.rung('character', 7)).toBe('C6');
      expect(page.rung('weapon', 1)).toBe('R1');
      expect(page.rung('weapon', 5)).toBe('R5');
    });

    it('labels strategies readably', async () => {
      const { page } = makePage();
      await settled();
      expect(page.strategyLabel('r1_first')).toBe('R1 first');
      expect(page.strategyLabel('c6_first')).toBe('C6 first');
    });
  });

  describe('when the backend refuses', () => {
    it('shows the reason rather than a blank table', async () => {
      const { page } = makePage({
        plan: vi.fn().mockRejectedValue({ detail: 'guaranteed with no 50/50s lost' }),
      });
      await settled();
      await page.recompute(page.request());
      expect(page.error()).toContain('guaranteed');
      expect(page.plan()).toBeNull();
    });

    it('reports a failure to load reference data', async () => {
      const { page } = makePage({ limits: vi.fn().mockRejectedValue(new Error('nope')) });
      await settled();
      expect(page.error()).toBeTruthy();
    });
  });

  describe('income', () => {
    it('keeps the workbook’s estimate marker', async () => {
      const { page } = makePage();
      await settled();
      expect(page.upcoming().find((v: any) => v.version === '7.1').is_estimate).toBe(true);
    });

    // The "Refreshed …" line was removed at the owner's request, and with it the only reader
    // of `fetched_at` — so the signal and the `DatePipe` went with it rather than staying
    // tested and rendered nowhere.
  });
});

describe('owning copies is not the same as reaching a rung', () => {
  /**
   * A character you have never pulled is not a C0 character. Labelling `owned = 0` as "C0"
   * made a fresh custom row read "from C0 to C0" — self-contradictory, and a goal the
   * backend refuses. Found by looking at the page, not by a test.
   */
  it('calls holding none "None" on both banners', async () => {
    const { page } = makePage();
    await settled();
    expect(page.ownedLabel('character', 0)).toBe('None');
    expect(page.ownedLabel('weapon', 0)).toBe('None');
  });

  it('calls the first copy C0 on a character and R1 on a weapon', async () => {
    const { page } = makePage();
    await settled();
    expect(page.ownedLabel('character', 1)).toBe('C0');
    expect(page.ownedLabel('weapon', 1)).toBe('R1');
    expect(page.ownedLabel('character', 7)).toBe('C6');
  });
});

describe('a custom plan cannot exceed what the backend accepts', () => {
  /**
   * `WishPlanRequest.targets` caps at 12. A page that builds a thirteenth row gets a 422 the
   * user reads as "that combination could not be planned" — a refusal about a limit nothing
   * on screen mentioned. Found by comparing the two caps, not by anything failing.
   */
  it('stops adding rows at twelve', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    for (let i = 0; i < 20; i++) page.addRow('character');
    expect(page.rows()).toHaveLength(12);
    expect(page.canAddRow()).toBe(false);
  });

  it('allows adding again once a row is removed', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    for (let i = 0; i < 20; i++) page.addRow('weapon');
    page.removeRow(0);
    expect(page.canAddRow()).toBe(true);
    page.addRow('weapon');
    expect(page.rows()).toHaveLength(12);
  });
});

describe('PR #331 review findings', () => {
  /**
   * Finding 3. `income().slice(-8)` was the last eight rows of the *whole* history, and six
   * of those had already shipped — so ticking 6.5 added ~88 wishes the player had already
   * earned and already counted in their primogem box, inflating every success chance.
   */
  it('offers only patches that have not finished', async () => {
    const { page } = makePage();
    await settled();
    expect(page.upcoming().map((v: any) => v.version)).toEqual(['7.1']);
    expect(page.upcoming().every((v: any) => v.is_estimate)).toBe(true);
  });

  it('adds nothing when a finished patch cannot be ticked', async () => {
    const { page } = makePage();
    await settled();
    page.toggleVersion('7.0');
    expect(page.projectedWishes()).toBe(0);
  });

  /**
   * Finding 4/9's frontend half: the loss options come from the backend's advertised ceiling
   * rather than a literal `[0, 1, 2, 3]`, so a change to the radiance table cannot leave the
   * control behind.
   */
  it('builds the loss options from the backend ceiling', async () => {
    const { page } = makePage();
    await settled();
    expect(page.lossOptions()).toEqual([0, 1, 2, 3]);
  });

  it('follows a different ceiling if the backend reports one', async () => {
    const { page } = makePage({
      limits: vi.fn().mockResolvedValue({ ...LIMITS, max_lost_fifty_fifties: 2 }),
    });
    await settled();
    expect(page.lossOptions()).toEqual([0, 1, 2]);
  });

  /**
   * Finding 6. Debouncing cancels a pending timer, not a request already in flight. A slow
   * request A and a fast request B could land out of order, leaving the table showing A's
   * answer for B's inputs — no error, no cue.
   */
  it('ignores a slow earlier request that lands after a faster later one', async () => {
    let release: ((value: WishPlanRead) => void) | null = null;
    const slow = new Promise<WishPlanRead>((resolve) => { release = resolve; });
    const planFn = vi.fn()
      .mockReturnValueOnce(slow)
      .mockResolvedValueOnce({ ...PLAN, budget: 999 });
    const { page } = makePage({ plan: planFn });
    await settled();

    const first = page.recompute(page.request());
    const second = page.recompute(page.request());
    await second;
    expect(page.plan().budget).toBe(999);

    release!({ ...PLAN, budget: 111 });
    await first;
    expect(page.plan().budget).toBe(999);
  });

  it('still reports an error from the newest request', async () => {
    const { page } = makePage({
      plan: vi.fn().mockRejectedValue({ detail: 'nope' }),
    });
    await settled();
    await page.recompute(page.request());
    expect(page.error()).toBe('nope');
  });
});


describe('the banner picker', () => {
  it('loads a page of banners and knows there are more', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    expect(page.banners()).toHaveLength(2);
    expect(page.bannerTotal()).toBe(20);
    expect(page.hasMoreBanners()).toBe(true);
  });

  it('appends rather than replaces when showing more', async () => {
    const service = {
      banners: vi.fn()
        .mockResolvedValueOnce(BANNERS)
        .mockResolvedValueOnce({ ...BANNERS, banners: [{ ...BANNERS.banners[0], slug: 'x/1' }] }),
    };
    const { page } = makePage(service as never);
    await settled();
    await settled();
    page.showMoreBanners();
    await settled();
    await settled();
    expect(page.banners().map((b: any) => b.slug)).toContain('x/1');
    expect(page.banners().length).toBe(3);
  });

  /** The banner knows who is featured. It cannot know your pity, so it must not clear it. */
  it('fills the name but leaves typed state alone', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    page.patch('character', { pity: 62, ownedCopies: 2 });
    page.chooseBanner(BANNERS.banners[0]);
    expect(page.character().label).toBe('Vesna');
    expect(page.character().pity).toBe(62);
    expect(page.character().ownedCopies).toBe(2);
  });

  /** The banner rides on the TARGET, not on the plan — a custom plan spans banners. */
  it('sends the chosen banner on each simple-mode target', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    page.chooseBanner(BANNERS.banners[0]);
    const request = page.request();
    expect(request.banner_slug).toBeUndefined();
    expect(request.character.banner_slug).toBe('When Warm Winds Cavort/2026-09-23');
    // A character banner now *keeps* the weapon leg and prices it on the paired weapon
    // banner. Turning it off here was the defect: the same click lit that banner in brass and
    // captioned it "Signature" while sending `weapon: null`.
    expect(request.weapon.banner_slug).toBe('Epitome Invocation/2026-09-23');

    page.chooseBanner(BANNERS.banners[1]);
    expect(page.request().weapon.banner_slug).toBe('Epitome Invocation/2026-09-23');

    page.chooseBanner(null);
    expect(page.request().character.banner_slug).toBeNull();
  });

  it('plans the weapon when a weapon banner is picked', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    page.chooseBanner(BANNERS.banners[1]);
    expect(page.planWeapon()).toBe(true);
    expect(page.weapon().label).toBe('Splendor');
  });

  /**
   * The planner works without a banner — it just cannot read the refund from the account.
   * Blanking the page over a failed banner fetch would be the worse trade.
   */
  it('survives a banner fetch that fails', async () => {
    const { page } = makePage({ banners: vi.fn().mockRejectedValue(new Error('nope')) });
    await settled();
    await settled();
    expect(page.banners()).toEqual([]);
    expect(page.error()).toBeNull();
  });

  it('formats a banner date for scanning', async () => {
    const { page } = makePage();
    await settled();
    expect(page.bannerWhen(BANNERS.banners[0])).toMatch(/2026/);
    expect(page.bannerWhen({ ...BANNERS.banners[0], starts_at: null })).toBe('');
  });
});

describe('the exact distribution', () => {
  it('charts the first rung that carries a histogram', async () => {
    const { page } = makePage();
    await settled();
    await page.recompute(page.request());
    expect(page.charted().label).toBe('Furina C0');
  });

  it('scales to the tallest bar rather than to one', async () => {
    const { page } = makePage();
    await settled();
    await page.recompute(page.request());
    expect(page.chartPeak()).toBe(0.5);
  });

  it('charts nothing when no rung carries a histogram', async () => {
    const { page } = makePage({
      plan: vi.fn().mockResolvedValue({
        ...PLAN, milestones: [{ ...PLAN.milestones[0], histogram: [] }],
      }),
    });
    await settled();
    await page.recompute(page.request());
    expect(page.charted()).toBeNull();
  });
});


describe('a custom plan spans banners', () => {
  /**
   * The picker used to set one banner for the whole plan, which was wrong the moment a
   * second row existed: each character is on its own banner with its own featured 4-stars,
   * and those are two thirds of every 4-star pulled, so they decide that leg's refund.
   */
  it('gives each row its own banner', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    page.mode.set('custom');
    page.addRow('weapon');
    page.chooseRowBanner(0, BANNERS.banners[0]);
    page.chooseRowBanner(1, BANNERS.banners[1]);

    const targets = page.request().targets;
    expect(targets[0].banner_slug).toBe('When Warm Winds Cavort/2026-09-23');
    expect(targets[1].banner_slug).toBe('Epitome Invocation/2026-09-23');
  });

  it('fills the row from the banner it was given', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    page.mode.set('custom');
    page.chooseRowBanner(0, BANNERS.banners[1]);
    expect(page.rows()[0].banner).toBe('weapon');
    expect(page.rows()[0].label).toBe('Splendor');
  });

  it('leaves the other rows alone', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    page.mode.set('custom');
    page.addRow('character');
    page.patchRow(1, { label: 'Kept' });
    page.chooseRowBanner(0, BANNERS.banners[0]);
    expect(page.rows()[1].label).toBe('Kept');
    expect(page.rows()[1].bannerSlug).toBeNull();
  });

  /**
   * **A second row of the same kind cannot hold pity, so it is not left holding one.**
   * `plan_campaign` applies pity only to the first leg on each banner, so a value here was
   * accepted, validated and thrown away -- measured, row 2 at pity 89 gave the same averages
   * as row 2 at pity 0.
   */
  it('clears pity on a row that does not lead its banner kind', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    page.addRow('character');
    page.patchRow(1, { pity: 40 });
    expect(page.leadsItsBanner(1)).toBe(false);
    expect(page.rows()[1].pity).toBe(0);
  });

  /** But the first row of a *different* kind does lead, and keeps it. */
  it('keeps pity on the first row of each kind', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    page.addRow('weapon');
    page.patchRow(1, { pity: 40 });
    expect(page.leadsItsBanner(1)).toBe(true);
    expect(page.rows()[1].pity).toBe(40);
  });

  it('opens one picker at a time', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    page.addRow('character');
    page.togglePicker(1);
    expect(page.pickingFor()).toBe(1);
    page.togglePicker(1);
    expect(page.pickingFor()).toBeNull();
  });

  it('closes the picker once a banner is chosen', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    page.mode.set('custom');
    page.togglePicker(0);
    page.chooseRowBanner(0, BANNERS.banners[0]);
    expect(page.pickingFor()).toBeNull();
  });
});

describe('a row that does not exist', () => {
  /**
   * `patchRow` spread `next[index]` without checking it. For an out-of-range index that
   * spread `undefined`, so the change *became* the row: `ownedCopies` was missing, the clamp
   * turned it into `NaN`, and it serialised as `null`. The user saw a 422 naming a field
   * they never touched, on a row they never added — and the plan vanished.
   */
  it('is not created by patching it', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    page.patchRow(7, { label: 'ghost' });
    expect(page.rows()).toHaveLength(1);
  });

  it('is not created by choosing a banner for it', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    page.mode.set('custom');
    page.chooseRowBanner(5, BANNERS.banners[0]);
    expect(page.rows()).toHaveLength(1);
  });

  it('never sends a null owned_copies', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    page.patchRow(3, { banner: 'weapon' });
    for (const target of page.request().targets) {
      expect(target.owned_copies).toEqual(expect.any(Number));
      expect(Number.isNaN(target.owned_copies)).toBe(false);
    }
  });

  it('is not moved', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    page.moveRow(9, -1);
    expect(page.rows()).toHaveLength(1);
  });
});

describe('no constellation data', () => {
  /**
   * The one case worth a word: the account was asked and could not answer, because the
   * roster carries no constellations — every account imported before that column existed.
   *
   * **Keyed off `refund_source: 'none'`, which only that case produces.** The earlier version
   * reassembled the rule here from "a banner is picked and the source is not roster", which
   * also caught an empty wallet and told a fully-scanned account its roster was blank.
   */
  it('is reported when the account was asked and declined', async () => {
    const { page } = makePage({
      plan: vi.fn().mockResolvedValue({ ...PLAN, refund_source: 'none', wallet_wishes: 180 }),
    });
    await settled();
    await settled();
    page.chooseBanner(BANNERS.banners[0]);
    await page.recompute(page.request());
    expect(page.noConstellationData()).toBe(true);
  });

  /** Not picking a banner is not a problem to warn about; the dropdown is right there. */
  it('is silent when no banner is picked', async () => {
    const { page } = makePage();
    await settled();
    await page.recompute(page.request());
    expect(page.noConstellationData()).toBe(false);
  });

  it('is silent when the roster answered', async () => {
    const { page } = makePage({
      plan: vi.fn().mockResolvedValue({ ...PLAN, refund_source: 'roster' }),
    });
    await settled();
    await settled();
    page.chooseBanner(BANNERS.banners[0]);
    await page.recompute(page.request());
    expect(page.noConstellationData()).toBe(false);
  });

  /**
   * The warning no longer reconstructs *why* the account declined, so there is nothing
   * mode-specific left to assert here. What matters instead is that a custom row's banner
   * actually reaches the request — the per-row slug is the whole point of this mode, and it
   * was silently dropped once already.
   */
  it('sends each custom row’s own banner', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const { page } = makePage({ plan });
    await settled();
    await settled();
    page.mode.set('custom');
    page.chooseRowBanner(0, BANNERS.banners[0]);
    await page.recompute(page.request());
    const sent = plan.mock.calls.at(-1)?.[0];
    expect(sent.targets[0].banner_slug).toBe(BANNERS.banners[0].slug);
  });
});


describe('the account is a refund choice, not an override', () => {
  /**
   * The exact refund used to win silently whenever the roster could answer, so this control
   * read "8.7% (Average)" while nothing it said was in use. The owner read it exactly that
   * way: "having 'Starglitter refund' makes users assume that controls it."
   */
  it('defaults to the account and offers it first', async () => {
    const { page } = makePage();
    await settled();
    expect(page.refund()).toBe('account');
    expect(page.refundOptions()[0]).toBe('account');
    expect(page.refundLabel('account')).toBe('Calculate with my account');
  });

  it('sends whichever choice is selected', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const { page } = makePage({ plan });
    await settled();
    page.refund.set('average');
    await page.recompute(page.request());
    expect(plan.mock.calls.at(-1)?.[0].starglitter_refund).toBe('average');
  });

  /** A declined account is the backend's verdict, not a guess reassembled here. */
  it('warns only when the account was asked and declined on a real wallet', async () => {
    const { page } = makePage({
      plan: vi.fn().mockResolvedValue({ ...PLAN, refund_source: 'none', wallet_wishes: 180 }),
    });
    await settled();
    await page.recompute(page.request());
    expect(page.noConstellationData()).toBe(true);
  });

  it('stays quiet when the wallet is empty', async () => {
    const { page } = makePage({
      plan: vi.fn().mockResolvedValue({ ...PLAN, refund_source: 'none', wallet_wishes: 0 }),
    });
    await settled();
    await page.recompute(page.request());
    expect(page.noConstellationData()).toBe(false);
  });
});

describe('one picker, two legs', () => {
  /**
   * Simple mode has one banner picker and up to two legs, and it used to send the same slug
   * to both. `_refund_from_account` reads the banner's kind off the row, so a character
   * banner priced the *weapon* leg's pulls with featured 4-star characters — a 50 % featured
   * rate against 75 % — and both legs collapsed onto one key, so the per-leg split this PR
   * adds did nothing at all in the default mode. Nothing caught it: the backend unit test
   * proves two *different* slugs work, which no client has ever sent.
   */
  it('never labels the weapon leg with a character banner', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const { page } = makePage({ plan });
    await settled();
    await settled();
    const character = BANNERS.banners.find((b) => b.kind === 'character')!;
    page.chooseBanner(character);
    page.planWeapon.set(true);
    await page.recompute(page.request());
    const sent = plan.mock.calls.at(-1)?.[0];
    expect(sent.character.banner_slug).toBe(character.slug);
    // The defect was the weapon leg inheriting the *character* banner, which priced its
    // pulls with featured 4-star characters. It now takes the paired weapon banner; what it
    // must never be is the character's.
    expect(sent.weapon.banner_slug).not.toBe(character.slug);
  });

  it('sends no weapon banner when none runs beside the character', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const lonely = {
      ...BANNERS,
      // `signature_banner` is what decides the pairing now, resolved server-side; an empty
      // `alongside` alone no longer means anything to the client.
      banners: [{ ...BANNERS.banners[0], alongside: [], signature_banner: null }],
    };
    const { page } = makePage({ plan, banners: vi.fn().mockResolvedValue(lonely) });
    await settled();
    await settled();
    page.chooseBanner(lonely.banners[0]);
    page.planWeapon.set(true);
    await page.recompute(page.request());
    expect(plan.mock.calls.at(-1)?.[0].weapon.banner_slug).toBeNull();
  });

  it('does not label the character leg with a weapon banner', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const { page } = makePage({ plan });
    await settled();
    await settled();
    const weapon = BANNERS.banners.find((b) => b.kind === 'weapon')!;
    page.chooseBanner(weapon);
    await page.recompute(page.request());
    const sent = plan.mock.calls.at(-1)?.[0];
    expect(sent.character.banner_slug).toBeNull();
    expect(sent.weapon.banner_slug).toBe(weapon.slug);
  });
});

describe('naming no banner is not a silent roster', () => {
  /**
   * The page's own default state — type a wallet, never open the picker — answered
   * `refund_source: "none"`, so a fully-imported account was told it had no constellation
   * data. `no_banner` is a separate verdict so this cannot claim it.
   *
   * The test that used to guard this could not: it used the default mock, whose fixture says
   * `tier`, so it passed for a reason unrelated to the code.
   */
  it('is silent when the backend says no banner was named', async () => {
    const { page } = makePage({
      plan: vi.fn().mockResolvedValue({
        ...PLAN, refund_source: 'no_banner', wallet_wishes: 200,
      }),
    });
    await settled();
    await page.recompute(page.request());
    expect(page.noConstellationData()).toBe(false);
  });
});

describe('the signature weapon runs on its own banner', () => {
  /**
   * The owner's ask: "the one character plan 'signature weapon' uses the character's
   * signature weapon banner. Selecting it should also select their weapon banner so both are
   * yellow and it's obvious."
   *
   * It is also the correct fix for #334's finding 4: the weapon leg was sent either the
   * character's slug (pricing it with featured 4-star *characters*) or nothing at all.
   */
  it('lights the paired weapon banner and prices the weapon leg on it', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const { page } = makePage({ plan });
    await settled();
    await settled();
    const character = BANNERS.banners.find((b) => b.kind === 'character')!;
    const weapon = BANNERS.banners.find((b) => b.kind === 'weapon')!;

    page.chooseBanner(character);
    page.planWeapon.set(true);
    expect(page.isPaired(weapon.slug)).toBe(true);

    await page.recompute(page.request());
    const sent = plan.mock.calls.at(-1)?.[0];
    expect(sent.character.banner_slug).toBe(character.slug);
    expect(sent.weapon.banner_slug).toBe(weapon.slug);
  });

  /**
   * **Not backwards.** A weapon banner runs beside *two* character banners and carries *two*
   * 5-star weapons, and nothing in the source says which is whose. Pairing in that direction
   * would be a guess presented as a fact.
   */
  it('does not infer a character from a weapon banner', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    const character = BANNERS.banners.find((b) => b.kind === 'character')!;
    page.chooseBanner(BANNERS.banners.find((b) => b.kind === 'weapon')!);
    expect(page.pairedWeaponBanner()).toBeNull();
    expect(page.isPaired(character.slug)).toBe(false);
  });
});

describe('a custom row is named by its banner, not by typing', () => {
  /**
   * The owner's point: "Free text entry characters/weapons don't give us the benefit of the
   * roster we've given ourselves." A typed name cannot be looked up, so the constellation
   * data the refund already reads went unused for the thing actually being pulled for.
   */
  it('takes the name and the owned copies from a one-five-star banner', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    page.mode.set('custom');
    const character = BANNERS.banners.find((b) => b.kind === 'character')!;
    page.chooseRowBanner(0, character);
    expect(page.rows()[0].label).toBe('Vesna');
    expect(page.rows()[0].banner).toBe('character');
  });

  /**
   * **Constellation on the wire, copies in the row.** C3 is four copies and holding none is
   * 0, so reading `owned_copies` straight across would make a C3 account read as "from C2".
   */
  it('converts a constellation into copies held', async () => {
    const owned = {
      ...BANNERS,
      banners: [{
        ...BANNERS.banners[0],
        featured_five: [{ name: 'Diona', icon: 'UI_Diona', owned_copies: 3 }],
      }],
    };
    const { page } = makePage({ banners: vi.fn().mockResolvedValue(owned) });
    await settled();
    await settled();
    page.mode.set('custom');
    page.chooseRowBanner(0, owned.banners[0]);
    expect(page.rows()[0].ownedCopies).toBe(4);
  });

  it('leaves an unknown constellation at none rather than guessing C0', async () => {
    const { page } = makePage();
    await settled();
    await settled();
    page.mode.set('custom');
    page.chooseRowBanner(0, BANNERS.banners.find((b) => b.kind === 'character')!);
    expect(page.rows()[0].ownedCopies).toBe(0);
  });

  /** A weapon banner has two 5-stars; the user says which, we do not infer it. */
  it('does not name a goal for a two-five-star banner until one is picked', async () => {
    const two = {
      ...BANNERS,
      banners: [{
        ...BANNERS.banners[1],
        featured_five: [
          { name: 'Splendor', icon: null, owned_copies: null },
          { name: 'Hymn', icon: null, owned_copies: null },
        ],
      }],
    };
    const { page } = makePage({ banners: vi.fn().mockResolvedValue(two) });
    await settled();
    await settled();
    page.mode.set('custom');
    page.chooseRowBanner(0, two.banners[0]);
    expect(page.rows()[0].label).toBe('');
    expect(page.rowUnits(page.rows()[0]).length).toBe(2);

    page.chooseRowUnit(0, two.banners[0].featured_five[1]);
    expect(page.rows()[0].label).toBe('Hymn');
  });
});

describe('a custom row carries pity, guarantee and losses', () => {
  /**
   * All three were already in `CustomRow` and already sent by `target()`, with no UI at all —
   * so every custom plan was silently computed at 0 pity with no guarantee. The owner hit it
   * directly: "I turned off my 50/50 losses since I can't edit them on custom right now."
   */
  it('sends the row’s pity and guarantee', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const { page } = makePage({ plan });
    await settled();
    page.mode.set('custom');
    page.patchRow(0, { pity: 42 });
    page.setRowGuaranteed(0, true);
    await page.recompute(page.request());
    const sent = plan.mock.calls.at(-1)?.[0].targets[0];
    expect(sent.pity).toBe(42);
    expect(sent.guaranteed).toBe(true);
  });

  /**
   * Guaranteed with zero losses is a state the game cannot produce and the backend answers
   * 422 for. Arming it raises the counter instead of sending the contradiction.
   */
  it('raises the loss counter rather than arming an impossible guarantee', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    page.setRowGuaranteed(0, true);
    expect(page.rows()[0].lostFiftyFifties).toBe(1);
    page.setRowLosses(0, 0);
    expect(page.rows()[0].guaranteed).toBe(false);
  });
});

describe('the histogram follows a chosen rung', () => {
  const laddered = {
    ...PLAN,
    milestones: [
      { ...PLAN.milestones[0], label: 'C0', histogram: [{ start: 0, end: 10, probability: 1 }] },
      { ...PLAN.milestones[0], label: 'C1', histogram: [{ start: 0, end: 20, probability: 1 }] },
    ],
  };

  /** It was pinned to the first rung with a histogram, and nothing said which that was. */
  it('defaults to the first rung that has one', async () => {
    const { page } = makePage({ plan: vi.fn().mockResolvedValue(laddered) });
    await settled();
    await page.recompute(page.request());
    expect(page.charted()?.label).toBe('C0');
    expect(page.isCharted(laddered.milestones[0])).toBe(true);
  });

  /**
   * Milestones are cumulative, so charting C1 shows the odds of C0 *and* C1 — which is the
   * owner's own example, along with "the second character in a custom plan to see the
   * probability of both".
   */
  it('charts the rung that was clicked', async () => {
    const { page } = makePage({ plan: vi.fn().mockResolvedValue(laddered) });
    await settled();
    await page.recompute(page.request());
    page.chart(1);
    expect(page.charted()?.label).toBe('C1');
    expect(page.isCharted(laddered.milestones[1])).toBe(true);
  });

  it('refuses a rung with no distribution to draw', async () => {
    const partial = {
      ...laddered,
      milestones: [laddered.milestones[0], { ...laddered.milestones[1], histogram: [] }],
    };
    const { page } = makePage({ plan: vi.fn().mockResolvedValue(partial) });
    await settled();
    await page.recompute(page.request());
    page.chart(1);
    expect(page.charted()?.label).toBe('C0');
  });

  /** A recompute of the same goals must not throw the selection away on every keystroke. */
  it('keeps the chosen rung across a recompute of the same ladder', async () => {
    const plan = vi.fn().mockResolvedValue(laddered);
    const { page } = makePage({ plan });
    await settled();
    await page.recompute(page.request());
    page.chart(1);
    await page.recompute(page.request());
    expect(page.charted()?.label).toBe('C1');
  });

  /** But index 3 of a different ladder is a different goal, so a shape change resets it. */
  it('drops the chosen rung when the ladder changes shape', async () => {
    const plan = vi.fn().mockResolvedValue(laddered);
    const { page } = makePage({ plan });
    await settled();
    await page.recompute(page.request());
    page.chart(1);
    plan.mockResolvedValue({ ...laddered, milestones: [laddered.milestones[0]] });
    await page.recompute(page.request());
    expect(page.chartedIndex()).toBeNull();
    expect(page.charted()?.label).toBe('C0');
  });
});

describe('a control never builds a state the backend refuses', () => {
  /**
   * **The dead end.** `setRowGuaranteed` raised the row's loss counter so the pair was not
   * contradictory, but `request()` zeroes that counter for every row after the first -- so
   * arming ✓ on row 2 sent `guaranteed: true, lost_fifty_fifties: 0`, the one state
   * `_validate_leg` refuses. Measured against the real API: 422. And the control that would
   * have fixed it is rendered only on row 0, so there was no way out.
   */
  it('never sends a guarantee with no losses behind it', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const { page } = makePage({ plan });
    await settled();
    page.mode.set('custom');
    page.addRow('character');
    page.setRowGuaranteed(1, true);
    await page.recompute(page.request());
    for (const target of plan.mock.calls.at(-1)?.[0].targets ?? []) {
      if (target.guaranteed) expect(target.lost_fifty_fifties).toBeGreaterThan(0);
    }
  });

  /** Reordering changes which row leads its kind, so the invariant is re-established. */
  it('does not leave a guarantee stranded by a move', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const { page } = makePage({ plan });
    await settled();
    page.mode.set('custom');
    page.addRow('character');
    page.setRowGuaranteed(0, true);
    page.moveRow(0, 1);
    await page.recompute(page.request());
    for (const target of plan.mock.calls.at(-1)?.[0].targets ?? []) {
      if (target.guaranteed) expect(target.lost_fifty_fifties).toBeGreaterThan(0);
    }
  });

  /** Character hard pity is 90 and the weapon banner's is 80. */
  it('re-clamps pity when the row changes banner kind', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    page.patchRow(0, { pity: 85 });
    expect(page.rows()[0].pity).toBe(85);
    page.patchRow(0, { banner: 'weapon' });
    expect(page.rows()[0].pity).toBeLessThanOrEqual(79);
  });
});

describe('holding the maximum is a real state', () => {
  /**
   * `ownedCopies` was clamped to `cap - 1`, so a C6 account read as **C5** and the plan priced
   * a copy they already hold. Seven copies is C6; the row then has no rung above it.
   */
  it('keeps a C6 holder at C6 rather than reporting C5', async () => {
    const { page } = makePage();
    await settled();
    page.mode.set('custom');
    page.patchRow(0, { ownedCopies: 7 });
    expect(page.rows()[0].ownedCopies).toBe(7);
    expect(page.rowIsComplete(page.rows()[0])).toBe(true);
  });

  it('offers the maximum as a choice at all', async () => {
    const { page } = makePage();
    await settled();
    expect(page.ownedOptions('character')).toContain(7);
    expect(page.ownedOptions('weapon')).toContain(5);
  });

  /** A goal already met is not sent: it would ask the backend to plan "from C6 to C6". */
  it('drops a complete row from the request', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const { page } = makePage({ plan });
    await settled();
    page.mode.set('custom');
    page.addRow('character');
    page.patchRow(0, { ownedCopies: 7 });
    await page.recompute(page.request());
    expect(plan.mock.calls.at(-1)?.[0].targets.length).toBe(1);
  });
});

describe('the signature pairing is resolved server-side', () => {
  /**
   * The click used to light the paired banner brass, caption it "Signature", and switch the
   * weapon goal *off* in the same gesture — measured `isPaired=true, planWeapon=false,
   * request().weapon=null`. Two halves of one screen asserting opposite things.
   */
  it('prices the weapon leg on the paired banner from the click alone', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const { page } = makePage({ plan });
    await settled();
    await settled();
    const character = BANNERS.banners.find((b) => b.kind === 'character')!;
    page.chooseBanner(character);          // and nothing else
    expect(page.planWeapon()).toBe(true);
    await page.recompute(page.request());
    const sent = plan.mock.calls.at(-1)?.[0];
    expect(sent.weapon.banner_slug).toBe('Epitome Invocation/2026-09-23');
  });

  /**
   * **The partner need not be on the loaded page.** The picker holds 8 banners and over the
   * committed table 2 of the 6 character banners on the first page have their partner at index
   * 8, so a client filtering its own page priced the weapon leg at zero refund and showed no
   * highlight — indistinguishable from a phase with no weapon banner, and no phase has none.
   */
  it('still prices the weapon leg when the partner is off the loaded page', async () => {
    const plan = vi.fn().mockResolvedValue(PLAN);
    const offPage = {
      ...BANNERS,
      banners: [BANNERS.banners[0]],   // the weapon banner is not loaded at all
    };
    const { page } = makePage({ plan, banners: vi.fn().mockResolvedValue(offPage) });
    await settled();
    await settled();
    page.chooseBanner(offPage.banners[0]);
    await page.recompute(page.request());
    expect(page.pairedWeaponBanner()).toBe('Epitome Invocation/2026-09-23');
    expect(page.pairedWeaponRow()).toBeNull();          // nothing to highlight
    expect(plan.mock.calls.at(-1)?.[0].weapon.banner_slug)
      .toBe('Epitome Invocation/2026-09-23');           // but it is still priced
  });
});
