import { Injectable } from '@angular/core';

import { injectApi } from '../../api/api.client';
import type { components } from '../../api/api.types';

export type WishPlanRequest = components['schemas']['WishPlanRequest'];
export type WishStrategy = components['schemas']['Strategy'];
export type WishPlanRead = components['schemas']['WishPlanRead'];
export type WishMilestoneRead = components['schemas']['WishMilestoneRead'];
export type WishIncomeRead = components['schemas']['WishIncomeRead'];
export type WishIncomeVersionRead = components['schemas']['WishIncomeVersionRead'];
export type WishTarget = components['schemas']['WishTarget'];
export type Strategy = components['schemas']['Strategy'];
export type WishBannerRead = components['schemas']['WishBannerRead'];
export type WishBannerList = components['schemas']['WishBannerList'];
export type WishHistogramBin = components['schemas']['WishHistogramBin'];
export type WishFeaturedItem = components['schemas']['WishFeaturedItem'];
export type WishCustomBanner = components['schemas']['WishCustomBanner'];
export type CustomFeaturedItem = components['schemas']['CustomFeaturedItem'];

/** What `/wishes/banners` narrows by. Absent means "any". */
export interface WishBannerFilter {
  q?: string;
  kind?: 'character' | 'weapon';
  element?: components['schemas']['Element'];
  weapon_type?: components['schemas']['WeaponType'];
}

/** What `/wishes/limits` answers — the page builds its controls from this, not from constants. */
export interface WishLimits {
  primogems_per_wish: number;
  max_constellation: number;
  max_refinement: number;
  max_lost_fifty_fifties: number;
  banner_page: number;
  strategies: string[];
  starglitter_refund_tiers: Record<string, number>;
  /** The refund choice meaning "price it from my roster" — the page does not spell it. */
  account_refund: string;
  banners: Record<string, { hard_pity: number; published_worst_case: number; capturing_radiance: boolean }>;
}

/**
 * The wish planner's three calls.
 *
 * Every type comes from `api.types`, generated from the committed `openapi.json`. Nothing
 * here describes the API by hand.
 */
@Injectable({ providedIn: 'root' })
export class WishesService {
  private api = injectApi();

  async plan(body: WishPlanRequest): Promise<WishPlanRead> {
    const { data, error } = await this.api.POST('/api/v1/wishes/plan', { body });
    if (error) throw error;
    return data;
  }

  async income(): Promise<WishIncomeRead> {
    const { data, error } = await this.api.GET('/api/v1/wishes/income', {});
    if (error) throw error;
    return data;
  }

  /** Banners newest first. `total` is what lets the page say how many more there are. */
  /** Banners newest first. The filters are the server's, so they search the whole table. */
  async banners(
    offset: number, limit: number, filter: WishBannerFilter = {},
  ): Promise<WishBannerList> {
    const { data, error } = await this.api.GET('/api/v1/wishes/banners', {
      params: { query: { offset, limit, ...filter } },
    });
    if (error) throw error;
    return data;
  }

  async limits(): Promise<WishLimits> {
    const { data, error } = await this.api.GET('/api/v1/wishes/limits', {});
    if (error) throw error;
    return data as unknown as WishLimits;
  }
}
