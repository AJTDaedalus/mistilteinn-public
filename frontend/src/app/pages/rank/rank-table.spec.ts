import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { CdkVirtualScrollViewport } from '@angular/cdk/scrolling';
import { Component } from '@angular/core';
import { describe, expect, it, vi } from 'vitest';

import { RankTable } from './rank-table';
import { defaultRankFilters } from './rank-filters';
import type { RankFilterState } from './rank-filters';
import { RankService } from './rank.service';
import type { DiscScoreSchema, DiscRankSchema, TeamCalculateResponse } from '../rank/rank.service';
import type { DiscRead } from '../builds/discs.service';

function makeScore(overrides: Partial<DiscScoreSchema> = {}): DiscScoreSchema {
  return {
    disc_id: 'd1',
    rolls_used: 5,
    remaining_rolls: 4,
    current_damage: 95000,
    baseline_damage: 100000,
    mean_improvement: 5000,
    max_improvement: 10000,
    stddev_improvement: 2000,
    p10: 2000,
    p50: 5000,
    p90: 8000,
    ...overrides,
  };
}

function makeDisc(overrides: Partial<DiscRead> = {}): DiscRead {
  return {
    id: 'd1',
    disc_set_id: 'set1',
    slot: 1 as any,
    rarity: 'S' as any,
    level: 10,
    main_stat_type: 'hp' as any,
    main_stat_value: 1000,
    substats: [],
    build_id: null,
    build_slot: null,
    ...overrides,
  };
}

function makeRankResult(overrides: Partial<DiscRankSchema> = {}): DiscRankSchema {
  return {
    disc_id: 'd1',
    per_build: [],
    best_build_avg: 5.0,
    best_build_avg_build_id: 'b1',
    best_build_max: 10.0,
    portfolio_avg: 4.0,
    ...overrides,
  };
}

interface RenderOpts {
  scores?: DiscScoreSchema[];
  discMap?: Record<string, DiscRead>;
  filters?: RankFilterState;
  rankResults?: DiscRankSchema[] | null;
  buildNames?: Record<string, string>;
  supportBuildIds?: Set<string>;
  providers?: unknown[];
}

async function render({
  scores = [], discMap = {}, filters = defaultRankFilters(), rankResults = null,
  buildNames = {}, supportBuildIds = new Set<string>(), providers = [],
}: RenderOpts = {}) {
  @Component({
    template: `<rank-table [scores]="scores" [discMap]="discMap" [filters]="filters" [rankResults]="rankResults" [buildNames]="buildNames" [supportBuildIds]="supportBuildIds" />`,
    imports: [RankTable],
    standalone: true,
  })
  class Host {
    scores = scores;
    discMap = discMap;
    filters = filters;
    rankResults = rankResults;
    buildNames = buildNames;
    supportBuildIds = supportBuildIds;
  }

  TestBed.configureTestingModule({ providers });
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();

  // jsdom has no layout engine — cdk-virtual-scroll-viewport reports clientHeight=0,
  // so *cdkVirtualFor renders nothing. Patch the height and trigger a size recheck
  // so all data rows are rendered before any assertion runs.
  const vpQuery = fixture.debugElement.query(By.directive(CdkVirtualScrollViewport));
  if (vpQuery) {
    Object.defineProperty(vpQuery.nativeElement, 'clientHeight', { value: 1000, configurable: true });
    (vpQuery.componentInstance as CdkVirtualScrollViewport).checkViewportSize();
  }

  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

function cellTexts(fixture: ReturnType<typeof TestBed.createComponent>, selector: string): string[] {
  return Array.from(fixture.nativeElement.querySelectorAll(selector)).map(
    (el: any) => el.textContent.trim(),
  );
}

function clickSortHeader(fixture: ReturnType<typeof TestBed.createComponent>, labelFragment: string): void {
  const headers = Array.from(fixture.nativeElement.querySelectorAll('[role="columnheader"].sortable')) as HTMLElement[];
  const header = headers.find((h) => h.textContent?.includes(labelFragment));
  if (!header) throw new Error(`Sort header not found: "${labelFragment}"`);
  header.click();
  fixture.detectChanges();
}

describe('RankTable', () => {
  describe('D1 — column headers', () => {
    it('renders Avg % and Max % column headers', async () => {
      const fixture = await render({ scores: [makeScore()] });
      const headers = cellTexts(fixture, '[role="columnheader"]');
      expect(headers.some((h) => h.includes('Avg %'))).toBe(true);
      expect(headers.some((h) => h.includes('Max %'))).toBe(true);
    });

    it('renders substat column headers', async () => {
      const fixture = await render({ scores: [makeScore()] });
      const headers = cellTexts(fixture, '[role="columnheader"]');
      expect(headers.some((h) => h.includes('HP%'))).toBe(true);
      expect(headers.some((h) => h.includes('ATK%'))).toBe(true);
      expect(headers.some((h) => h.includes('CR'))).toBe(true);
      expect(headers.some((h) => h.includes('CD'))).toBe(true);
      expect(headers.some((h) => h.includes('PEN'))).toBe(true);
      expect(headers.some((h) => h.includes('AP'))).toBe(true);
    });
  });

  describe('roll count display — total rolls, issue #65', () => {
    it('shows the total roll count, not upgrade-only, next to a substat value', async () => {
      const disc = makeDisc({
        id: 'd1',
        substats: [{ stat: 'crit_rate', value: 240, rolls: 3 } as never],
      });
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        discMap: { d1: disc },
      });
      const cells = cellTexts(fixture, '.substat-col.mono');
      expect(cells.some((c) => c.includes('(3)'))).toBe(true);
    });

    it('defaults to 1 when a substat has no rolls field', async () => {
      const disc = makeDisc({
        id: 'd1',
        substats: [{ stat: 'crit_rate', value: 240 } as never],
      });
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        discMap: { d1: disc },
      });
      const cells = cellTexts(fixture, '.substat-col.mono');
      expect(cells.some((c) => c.includes('(1)'))).toBe(true);
    });
  });

  describe('D2 — % computation', () => {
    it('computes Avg % as mean_improvement / baseline_damage * 100', async () => {
      const fixture = await render({ scores: [makeScore({ mean_improvement: 5000, baseline_damage: 100000 })] });
      const avgCells = cellTexts(fixture, '.avg-pct');
      expect(avgCells[0]).toBe('5.00%');
    });

    it('computes Max % as max_improvement / baseline_damage * 100', async () => {
      const fixture = await render({ scores: [makeScore({ max_improvement: 10000, baseline_damage: 100000 })] });
      const maxCells = cellTexts(fixture, '.max-pct');
      expect(maxCells[0]).toBe('10.00%');
    });

    it('level-15 employed disc renders ~0% for both Avg and Max', async () => {
      const maxed = makeScore({
        disc_id: 'd-maxed',
        remaining_rolls: 0,
        mean_improvement: 0,
        max_improvement: 0,
      });
      const fixture = await render({ scores: [maxed] });
      const avgCells = cellTexts(fixture, '.avg-pct');
      const maxCells = cellTexts(fixture, '.max-pct');
      expect(avgCells[0]).toBe('0.00%');
      expect(maxCells[0]).toBe('0.00%');
    });

    it('guards baseline_damage == 0 by showing —', async () => {
      const zeroBase = makeScore({ baseline_damage: 0, mean_improvement: 0, max_improvement: 0 });
      const fixture = await render({ scores: [zeroBase] });
      const avgCells = cellTexts(fixture, '.avg-pct');
      const maxCells = cellTexts(fixture, '.max-pct');
      expect(avgCells[0]).toBe('—');
      expect(maxCells[0]).toBe('—');
    });
  });

  describe('D3 — default sort', () => {
    it('defaults to Avg % descending — higher avgPct row appears first', async () => {
      const low = makeScore({ disc_id: 'low', mean_improvement: 1000, baseline_damage: 100000 });
      const high = makeScore({ disc_id: 'high', mean_improvement: 8000, baseline_damage: 100000 });
      const fixture = await render({ scores: [low, high] });
      const rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      const firstRowAvg = rows[0].querySelector('.avg-pct')?.textContent.trim();
      expect(firstRowAvg).toBe('8.00%');
    });
  });

  describe('D4 — empty state', () => {
    it('shows a hint when scores is empty', async () => {
      const fixture = await render();
      const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
      expect(text).toMatch(/no discs/i);
    });
  });

  describe('D5 — sort toggle', () => {
    it('clicking a sorted header reverses the sort direction', async () => {
      const low = makeScore({ disc_id: 'low', mean_improvement: 1000, baseline_damage: 100000 });
      const high = makeScore({ disc_id: 'high', mean_improvement: 8000, baseline_damage: 100000 });
      const fixture = await render({ scores: [low, high] });

      // Default: high first (desc)
      let rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows[0].querySelector('.avg-pct')?.textContent.trim()).toBe('8.00%');

      // Click Avg % header → toggle to asc → low first
      clickSortHeader(fixture, 'Avg %');
      rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows[0].querySelector('.avg-pct')?.textContent.trim()).toBe('1.00%');

      // Click again → back to desc
      clickSortHeader(fixture, 'Avg %');
      rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows[0].querySelector('.avg-pct')?.textContent.trim()).toBe('8.00%');
    });

    it('clicking a different header switches sort key to desc', async () => {
      const scores = [
        makeScore({ disc_id: 'd1', mean_improvement: 8000, max_improvement: 2000, baseline_damage: 100000 }),
        makeScore({ disc_id: 'd2', mean_improvement: 1000, max_improvement: 9000, baseline_damage: 100000 }),
      ];
      const fixture = await render({ scores });

      // Default: sorted by avg_pct desc → d1 first
      let rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows[0].querySelector('.avg-pct')?.textContent.trim()).toBe('8.00%');

      // Switch to Max % → d2 first (max 9%)
      clickSortHeader(fixture, 'Max %');
      rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows[0].querySelector('.max-pct')?.textContent.trim()).toBe('9.00%');
    });
  });

  describe('D6 — filter', () => {
    it('slot filter narrows rows', async () => {
      const scores = [
        makeScore({ disc_id: 'd1' }),
        makeScore({ disc_id: 'd2' }),
      ];
      const discMap: Record<string, DiscRead> = {
        d1: makeDisc({ id: 'd1', slot: 1 as any }),
        d2: makeDisc({ id: 'd2', slot: 2 as any }),
      };
      const filters: RankFilterState = { ...defaultRankFilters(), slot: 1 };
      const fixture = await render({ scores, discMap, filters });

      const rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows).toHaveLength(1);
    });

    it('rarity filter narrows rows', async () => {
      const scores = [
        makeScore({ disc_id: 'd1' }),
        makeScore({ disc_id: 'd2' }),
      ];
      const discMap: Record<string, DiscRead> = {
        d1: makeDisc({ id: 'd1', rarity: 'S' as any }),
        d2: makeDisc({ id: 'd2', rarity: 'A' as any }),
      };
      const filters: RankFilterState = { ...defaultRankFilters(), rarities: ['A'] };
      const fixture = await render({ scores, discMap, filters });

      const rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows).toHaveLength(1);
    });

    it('set filter narrows rows', async () => {
      const scores = [
        makeScore({ disc_id: 'd1' }),
        makeScore({ disc_id: 'd2' }),
      ];
      const discMap: Record<string, DiscRead> = {
        d1: makeDisc({ id: 'd1', disc_set_id: 'set-a' }),
        d2: makeDisc({ id: 'd2', disc_set_id: 'set-b' }),
      };
      const filters: RankFilterState = { ...defaultRankFilters(), sets: ['set-a'] };
      const fixture = await render({ scores, discMap, filters });

      const rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows).toHaveLength(1);
    });

    it('main stat filter narrows rows', async () => {
      const scores = [
        makeScore({ disc_id: 'd1' }),
        makeScore({ disc_id: 'd2' }),
      ];
      const discMap: Record<string, DiscRead> = {
        d1: makeDisc({ id: 'd1', main_stat_type: 'crit_rate' as any }),
        d2: makeDisc({ id: 'd2', main_stat_type: 'atk_pct' as any }),
      };
      const filters: RankFilterState = { ...defaultRankFilters(), mainStats: ['crit_rate'] };
      const fixture = await render({ scores, discMap, filters });

      const rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows).toHaveLength(1);
    });

    it('empty filters show all rows', async () => {
      const scores = [
        makeScore({ disc_id: 'd1' }),
        makeScore({ disc_id: 'd2' }),
        makeScore({ disc_id: 'd3' }),
      ];
      const fixture = await render({ scores, filters: defaultRankFilters() });
      const rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows).toHaveLength(3);
    });
  });

  describe('R2.9 — priority columns', () => {
    it('combined columns do NOT appear when rankResults is null', async () => {
      const fixture = await render({ scores: [makeScore()], rankResults: null });
      const headers = cellTexts(fixture, '[role="columnheader"]');
      expect(headers.some((h) => h.includes('Best Build Avg'))).toBe(false);
      expect(headers.some((h) => h.includes('Best Build Max'))).toBe(false);
      expect(headers.some((h) => h.includes('All Builds Avg'))).toBe(false);
    });

    it('Avg % and Max % columns are hidden when priority list is active', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({ disc_id: 'd1' })],
      });
      const headers = cellTexts(fixture, '[role="columnheader"]');
      expect(headers.some((h) => h.trim() === 'Avg %')).toBe(false);
      expect(headers.some((h) => h.trim() === 'Max %')).toBe(false);
      expect(fixture.nativeElement.querySelectorAll('.avg-pct').length).toBe(0);
      expect(fixture.nativeElement.querySelectorAll('.max-pct').length).toBe(0);
    });

    it('combined columns appear when rankResults is non-empty', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({ disc_id: 'd1' })],
      });
      const headers = cellTexts(fixture, '[role="columnheader"]');
      expect(headers.some((h) => h.includes('Best Build Avg'))).toBe(true);
      expect(headers.some((h) => h.includes('Best Build Max'))).toBe(true);
      expect(headers.some((h) => h.includes('All Builds Avg'))).toBe(true);
    });

    it('Best-build Avg % cell shows the correct value', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({ disc_id: 'd1', best_build_avg: 7.5 })],
      });
      const cells = cellTexts(fixture, '.best-build-avg-pct');
      expect(cells[0]).toBe('7.50%');
    });

    it('Best-build Max % cell shows the correct value', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({ disc_id: 'd1', best_build_max: 12.0 })],
      });
      const cells = cellTexts(fixture, '.best-build-max-pct');
      expect(cells[0]).toBe('12.00%');
    });

    it('Portfolio Avg % cell shows the correct value', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({ disc_id: 'd1', portfolio_avg: 3.2 })],
      });
      const cells = cellTexts(fixture, '.portfolio-avg-pct');
      expect(cells[0]).toBe('3.20%');
    });

    it('shows winner build label in Best-build Avg % cell', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({ disc_id: 'd1', best_build_avg_build_id: 'b-winner', best_build_avg: 5 })],
        buildNames: { 'b-winner': 'Zhu Yuan' },
      });
      const cell = fixture.nativeElement.querySelector('.best-build-avg-pct');
      expect(cell?.textContent).toContain('Zhu Yuan');
    });

    it('default sort is Best-build Avg % desc when rankResults provided', async () => {
      const scores = [
        makeScore({ disc_id: 'low' }),
        makeScore({ disc_id: 'high' }),
      ];
      const rankResults = [
        makeRankResult({ disc_id: 'low', best_build_avg: 2.0 }),
        makeRankResult({ disc_id: 'high', best_build_avg: 8.0 }),
      ];
      const fixture = await render({ scores, rankResults });
      const rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      const firstCell = rows[0].querySelector('.best-build-avg-pct')?.textContent.trim();
      expect(firstCell).toBe('8.00%');
    });

    it('Best-build Avg % column is sortable', async () => {
      const scores = [
        makeScore({ disc_id: 'low' }),
        makeScore({ disc_id: 'high' }),
      ];
      const rankResults = [
        makeRankResult({ disc_id: 'low', best_build_avg: 2.0 }),
        makeRankResult({ disc_id: 'high', best_build_avg: 8.0 }),
      ];
      const fixture = await render({ scores, rankResults });

      // Default desc: high first
      let rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows[0].querySelector('.best-build-avg-pct')?.textContent.trim()).toBe('8.00%');

      // Toggle to asc: low first
      clickSortHeader(fixture, 'Best Build Avg');
      rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows[0].querySelector('.best-build-avg-pct')?.textContent.trim()).toBe('2.00%');
    });

    it('Portfolio Avg % column is sortable', async () => {
      const scores = [
        makeScore({ disc_id: 'low' }),
        makeScore({ disc_id: 'high' }),
      ];
      const rankResults = [
        makeRankResult({ disc_id: 'low', portfolio_avg: 1.0 }),
        makeRankResult({ disc_id: 'high', portfolio_avg: 9.0 }),
      ];
      const fixture = await render({ scores, rankResults });

      clickSortHeader(fixture, 'All Builds Avg');
      // First click on a non-default column → desc → high first
      const rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      expect(rows[0].querySelector('.portfolio-avg-pct')?.textContent.trim()).toBe('9.00%');
    });
  });

  describe('R6 — reference mode label (DESIGN_ranker_discless.md D1/D2a)', () => {
    it('shows "vs equipped" when the winning context has equipped discs', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({
          disc_id: 'd1',
          best_build_avg_build_id: 'b-geared',
          best_build_avg: 5,
          per_build: [{ build_id: 'b-geared', avg_pct: 5, max_pct: 8, reference_mode: 'equipped' }],
        })],
      });
      const cell = fixture.nativeElement.querySelector('.best-build-avg-pct');
      expect(cell?.textContent).toContain('vs equipped');
    });

    it('shows "vs best" when the winning context is disc-less', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({
          disc_id: 'd1',
          best_build_avg_build_id: 'b-discless',
          best_build_avg: 0,
          per_build: [{ build_id: 'b-discless', avg_pct: 0, max_pct: 0, reference_mode: 'best' }],
        })],
      });
      const cell = fixture.nativeElement.querySelector('.best-build-avg-pct');
      expect(cell?.textContent).toContain('vs best');
    });

    it('shows no reference-mode label when the winning per_build entry has none', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({
          disc_id: 'd1',
          best_build_avg_build_id: 'b1',
          best_build_avg: 5,
          per_build: [{ build_id: 'b1', avg_pct: 5, max_pct: 8 }],
        })],
      });
      const cell = fixture.nativeElement.querySelector('.best-build-avg-pct');
      expect(cell?.textContent).not.toMatch(/vs (equipped|best)/);
    });

    it('mixed disc-less/geared table: sort order follows best_build_avg, not the label', async () => {
      // Two discs whose winning contexts have opposite reference modes and
      // opposite label-vs-value framing — a naive label-based sort would put
      // "vs best" before "vs equipped" alphabetically; the real value says
      // the geared disc (5.0) should sort above the disc-less one (-2.0).
      const scores = [
        makeScore({ disc_id: 'discless-loser' }),
        makeScore({ disc_id: 'geared-winner' }),
      ];
      const rankResults = [
        makeRankResult({
          disc_id: 'discless-loser',
          best_build_avg_build_id: 'b-discless',
          best_build_avg: -2.0,
          per_build: [{ build_id: 'b-discless', avg_pct: -2.0, max_pct: -1.0, reference_mode: 'best' }],
        }),
        makeRankResult({
          disc_id: 'geared-winner',
          best_build_avg_build_id: 'b-geared',
          best_build_avg: 5.0,
          per_build: [{ build_id: 'b-geared', avg_pct: 5.0, max_pct: 8.0, reference_mode: 'equipped' }],
        }),
      ];
      const fixture = await render({ scores, rankResults });

      const rows = fixture.nativeElement.querySelectorAll('.rank-grid__row');
      const firstAvg = rows[0].querySelector('.best-build-avg-pct')?.textContent ?? '';
      expect(firstAvg).toContain('5.00%');
      expect(firstAvg).toContain('vs equipped');
    });
  });

  describe('R3.21 — support-context badge', () => {
    it('shows support badge when winning build is a support context', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({ disc_id: 'd1', best_build_avg_build_id: 'b-support', best_build_avg: 5 })],
        buildNames: { 'b-support': 'Nicole' },
        supportBuildIds: new Set(['b-support']),
      });
      const cell = fixture.nativeElement.querySelector('.best-build-avg-pct');
      expect(cell?.querySelector('.support-badge')).not.toBeNull();
    });

    it('does NOT show support badge when winning build is a DPS context', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({ disc_id: 'd1', best_build_avg_build_id: 'b-dps', best_build_avg: 5 })],
        buildNames: { 'b-dps': 'Zhu Yuan' },
        supportBuildIds: new Set(),
      });
      const cell = fixture.nativeElement.querySelector('.best-build-avg-pct');
      expect(cell?.querySelector('.support-badge')).toBeNull();
    });

    it('does NOT show support badge when supportBuildIds is absent (default)', async () => {
      const fixture = await render({
        scores: [makeScore({ disc_id: 'd1' })],
        rankResults: [makeRankResult({ disc_id: 'd1', best_build_avg_build_id: 'b1', best_build_avg: 5 })],
        buildNames: { 'b1': 'Anby' },
      });
      const cell = fixture.nativeElement.querySelector('.best-build-avg-pct');
      expect(cell?.querySelector('.support-badge')).toBeNull();
    });
  });

  describe('B6 — keystone deep-link', () => {
    function fakeResponse(): TeamCalculateResponse {
      return {
        team_id: 't1', team_name: 'T', dps_build_id: 'b1', dps_agent_name: 'DPS',
        combo_id: 'combo-1', combo_name: 'R', enemy_name: 'Dummy',
        auto_conditions: [], applied_team_buffs: [], by_agent: [],
        total_damage: 120000, standard_total: 120000, anomaly_total: 0,
        steps: [], by_category: [], by_element: [],
        total_atk: 3000, total_crit_rate: 500, total_crit_dmg: 5000, total_pen_ratio: 0,
        delta: {
          from_total: 100000, to_total: 120000, pct_change: 20,
          zone_deltas: [{ zone: 'boost', from_bp: 16200, to_bp: 17100, ratio: 10555, gain_share_pct: 100 }],
        },
      } as unknown as TeamCalculateResponse;
    }

    it('renders a "Full breakdown" button per row', async () => {
      const fixture = await render({ scores: [makeScore({ disc_id: 'd1' })] });
      const btn = fixture.nativeElement.querySelector('.breakdown-btn');
      expect(btn?.textContent).toContain('Full breakdown');
    });

    it('swaps the candidate into the target build\'s equipped six and calls evaluateDiscs', async () => {
      const evaluateDiscs = vi.fn().mockResolvedValue(fakeResponse());
      const fixture = await render({
        scores: [makeScore({ disc_id: 'candidate' })],
        discMap: {
          candidate: makeDisc({ id: 'candidate', slot: 3 as any, build_id: null }),
          equipped1: makeDisc({ id: 'equipped1', slot: 1 as any, build_id: 'b1' }),
          equipped3: makeDisc({ id: 'equipped3', slot: 3 as any, build_id: 'b1' }),
        },
        rankResults: [makeRankResult({
          disc_id: 'candidate',
          best_build_avg_build_id: 'b1',
          per_build: [{
            build_id: 'b1', avg_pct: 5, max_pct: 10,
            team_id: 'team-1', combo_id: 'combo-1', enemy_profile_id: 'enemy-1', active_index: 0,
          }],
        })],
        providers: [{ provide: RankService, useValue: { evaluateDiscs } }],
      });

      const btn = fixture.nativeElement.querySelector('.breakdown-btn') as HTMLButtonElement;
      btn.click();
      fixture.detectChanges();
      await fixture.whenStable();

      expect(evaluateDiscs).toHaveBeenCalledTimes(1);
      const [teamId, params] = evaluateDiscs.mock.calls[0];
      expect(teamId).toBe('team-1');
      expect(params.comboId).toBe('combo-1');
      expect(params.enemyProfileId).toBe('enemy-1');
      expect(params.activeIndex).toBe(0);
      // slot 1 keeps the equipped disc; slot 3 is overridden by the candidate.
      expect(new Set(params.discIds)).toEqual(new Set(['equipped1', 'candidate']));
    });

    it('shows the evaluated total damage once evaluateDiscs resolves', async () => {
      const evaluateDiscs = vi.fn().mockResolvedValue(fakeResponse());
      const fixture = await render({
        scores: [makeScore({ disc_id: 'candidate' })],
        discMap: { candidate: makeDisc({ id: 'candidate', slot: 3 as any, build_id: null }) },
        rankResults: [makeRankResult({
          disc_id: 'candidate',
          best_build_avg_build_id: 'b1',
          per_build: [{
            build_id: 'b1', avg_pct: 5, max_pct: 10,
            team_id: 'team-1', combo_id: 'combo-1', enemy_profile_id: 'enemy-1', active_index: 0,
          }],
        })],
        providers: [{ provide: RankService, useValue: { evaluateDiscs } }],
      });

      const btn = fixture.nativeElement.querySelector('.breakdown-btn') as HTMLButtonElement;
      btn.click();
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();

      expect(fixture.nativeElement.textContent).toContain('120,000');
    });

    it('shows an error when the context has no team/combo/enemy to evaluate against', async () => {
      const evaluateDiscs = vi.fn();
      const fixture = await render({
        scores: [makeScore({ disc_id: 'candidate' })],
        discMap: { candidate: makeDisc({ id: 'candidate' }) },
        rankResults: [makeRankResult({
          disc_id: 'candidate',
          best_build_avg_build_id: 'b1',
          per_build: [{ build_id: 'b1', avg_pct: 5, max_pct: 10 }],
        })],
        providers: [{ provide: RankService, useValue: { evaluateDiscs } }],
      });

      const btn = fixture.nativeElement.querySelector('.breakdown-btn') as HTMLButtonElement;
      btn.click();
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();

      expect(evaluateDiscs).not.toHaveBeenCalled();
      expect(fixture.nativeElement.textContent).toContain('no team/combo/enemy');
    });
  });
});
