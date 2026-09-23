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
      copies: 1, label: 'Furina C0', success_chance: 1, average_wishes: 93.45,
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
      featured_five: [{ name: 'Vesna', icon: 'UI_Vesna' }],
      featured_four: [
        { name: 'Diona', icon: 'UI_Diona' },
        { name: 'Faruzan', icon: null },
        { name: 'Chongyun', icon: 'UI_Chongyun' },
      ],
    },
    {
      slug: 'Epitome Invocation/2026-09-23', name: 'Epitome Invocation',
      kind: 'weapon', starts_at: '2026-09-23 11:00:00', ends_at: '2026-10-13 17:59:59',
      featured_five: [{ name: 'Splendor', icon: 'UI_Splendor' }],
      featured_four: [{ name: 'New Bough', icon: null }],
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

    it('records when the store was last refreshed', async () => {
      const { page } = makePage();
      await settled();
      expect(page.incomeFetchedAt()).toBe('2026-09-22T12:00:00Z');
    });
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
    // A character banner has no weapon on it, so `chooseBanner` turns the weapon leg off.
    expect(request.weapon).toBeNull();

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
    page.patchRow(1, { label: 'Kept', pity: 40 });
    page.chooseRowBanner(0, BANNERS.banners[0]);
    expect(page.rows()[1].label).toBe('Kept');
    expect(page.rows()[1].pity).toBe(40);
    expect(page.rows()[1].bannerSlug).toBeNull();
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
  it('does not label the weapon leg with a character banner', async () => {
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
    expect(sent.weapon.banner_slug).toBeNull();
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
