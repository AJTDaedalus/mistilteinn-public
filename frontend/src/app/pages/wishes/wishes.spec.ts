import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { WishesService, type WishLimits, type WishPlanRead } from './wishes.service';
import { WishesPage } from './wishes';

const LIMITS: WishLimits = {
  primogems_per_wish: 160,
  max_constellation: 6,
  max_refinement: 5,
  max_lost_fifty_fifties: 3,
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
  published_worst_case: 180,
  milestones: [
    { copies: 1, label: 'C0', success_chance: 1, average_wishes: 93.45, median_wishes: 80 },
    { copies: 2, label: 'C1', success_chance: 0.49, average_wishes: 186.11, median_wishes: 182 },
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
  describe('the budget shows its own arithmetic', () => {
    it('turns primogems and fate into whole wishes', async () => {
      const { page } = makePage();
      await settled();
      page.primogems.set(24_000);
      page.intertwined.set(60);
      expect(page.walletWishes()).toBe(210);
      expect(page.budget()).toBe(210);
    });

    it('does not sell a partial wish', async () => {
      const { page } = makePage();
      await settled();
      page.primogems.set(159);
      expect(page.walletWishes()).toBe(0);
    });

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
  });

  describe('Capturing Radiance', () => {
    it('is offered on the character banner and hidden on the weapon banner', async () => {
      const { page } = makePage();
      await settled();
      expect(page.showsRadiance()).toBe(true);
      page.chooseBanner('weapon');
      expect(page.showsRadiance()).toBe(false);
    });

    /**
     * Arming the guarantee *requires* losing a 50/50, so guaranteed-with-zero-losses is a
     * state the game cannot produce and the backend refuses with a 422. The control raises
     * the counter instead of letting the user build it.
     */
    it('cannot express guaranteed with no losses', async () => {
      const { page } = makePage();
      await settled();
      page.setGuaranteed(true);
      expect(page.lostFiftyFifties()).toBe(1);
    });

    it('drops the guarantee when the losses go back to zero', async () => {
      const { page } = makePage();
      await settled();
      page.setGuaranteed(true);
      page.setLosses(0);
      expect(page.guaranteed()).toBe(false);
    });

    it('says when three losses already amount to a guarantee', async () => {
      const { page } = makePage();
      await settled();
      expect(page.radianceIsCertain()).toBe(false);
      page.setLosses(3);
      expect(page.radianceIsCertain()).toBe(true);
    });

    it('never sends banked losses for the weapon banner', async () => {
      const { page } = makePage();
      await settled();
      page.setLosses(2);
      page.chooseBanner('weapon');
      expect(page.request().lost_fifty_fifties).toBe(0);
    });
  });

  describe('switching banners', () => {
    it('clears pity, guarantee and losses together', async () => {
      const { page } = makePage();
      await settled();
      page.pity.set(70);
      page.setGuaranteed(true);
      page.ownedCopies.set(3);
      page.chooseBanner('weapon');
      expect(page.pity()).toBe(0);
      expect(page.guaranteed()).toBe(false);
      expect(page.lostFiftyFifties()).toBe(0);
      expect(page.ownedCopies()).toBe(0);
    });

    it('caps owned copies per banner', async () => {
      const { page } = makePage();
      await settled();
      expect(page.maxOwned()).toBe(6);
      page.chooseBanner('weapon');
      expect(page.maxOwned()).toBe(4);
    });
  });

  describe('numeric inputs', () => {
    /**
     * `Number('')` is 0, so an emptied box would silently read as "I hold none" — the defect
     * CLAUDE.md records from the materials editor. An empty box keeps the previous value.
     */
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
      page.setNumber({ value: '500' } as HTMLInputElement, page.pity.set, 89);
      expect(page.pity()).toBe(89);
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
