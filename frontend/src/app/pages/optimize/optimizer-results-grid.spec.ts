import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import { Component } from '@angular/core';

import { OptimizerResultsGrid } from './optimizer-results-grid';
import type { OptimizerDiscBuildSchema } from './optimizer.service';
import { RankService } from '../rank/rank.service';
import type { TeamCalculateResponse } from '../rank/rank.service';

function makeBuild(
  totalDamage: number,
  stats: Record<string, number> = {},
): OptimizerDiscBuildSchema {
  return {
    total_damage: totalDamage,
    disc_ids: ['d1', 'd2', 'd3', 'd4', 'd5', 'd6'],
    set_counts: {},
    total_stats: stats,
    discs: [],
    per_combo_damage: {},
  } as unknown as OptimizerDiscBuildSchema;
}

const BUILDS: OptimizerDiscBuildSchema[] = [
  makeBuild(10000, { atk: 2000, crit_rate: 5000, crit_dmg: 10000, pen_ratio: 2400, anomaly_proficiency: 120 }),
  makeBuild(12000, { atk: 2200, crit_rate: 6000, crit_dmg: 12000, pen_ratio: 2400, anomaly_proficiency: 100 }),
  makeBuild(11000, { atk: 2100, crit_rate: 4800, crit_dmg: 11000, pen_ratio: 2400, anomaly_proficiency: 110 }),
];

async function renderGrid(
  results: OptimizerDiscBuildSchema[] = BUILDS,
  currentBuildDamage: number | null = null,
  deepLink: {
    teamId?: string | null;
    comboId?: string | null;
    enemyProfileId?: string | null;
    activeIndex?: number;
  } = {},
  rankServiceMock?: Partial<RankService>,
) {
  @Component({
    template: `
      <optimizer-results-grid
        [results]="results"
        [currentBuildDamage]="cbd"
        [teamId]="teamId"
        [comboId]="comboId"
        [enemyProfileId]="enemyProfileId"
        [activeIndex]="activeIndex"
      />
    `,
    imports: [OptimizerResultsGrid],
    standalone: true,
  })
  class Host {
    results = results;
    cbd = currentBuildDamage;
    teamId = deepLink.teamId ?? null;
    comboId = deepLink.comboId ?? null;
    enemyProfileId = deepLink.enemyProfileId ?? null;
    activeIndex = deepLink.activeIndex ?? 0;
  }

  TestBed.configureTestingModule({
    providers: rankServiceMock ? [{ provide: RankService, useValue: rankServiceMock }] : [],
  });
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('OptimizerResultsGrid', () => {
  describe('D1 — stat columns', () => {
    it('renders ATK, CR, CD, PR, AP column headers', async () => {
      const fixture = await renderGrid();
      const headers = Array.from(
        fixture.nativeElement.querySelectorAll('th'),
      ).map((th: any) => th.textContent.trim());
      expect(headers).toContain('ATK');
      expect(headers).toContain('CR');
      expect(headers).toContain('CD');
      expect(headers).toContain('PR');
      expect(headers).toContain('AP');
    });

    it('formats crit_rate as percent', async () => {
      // Single-build fixture to avoid sort ambiguity.
      const fixture = await renderGrid([
        makeBuild(10000, { atk: 2000, crit_rate: 5000, crit_dmg: 10000, pen_ratio: 2400, anomaly_proficiency: 120 }),
      ]);
      // Row cells order: #, total_damage, Δ%, ATK, CR, CD, PR, AP, sets, equip
      const cells = fixture.nativeElement.querySelectorAll('tbody tr:first-child td');
      const crCell = cells[4]; // CR is index 4
      expect(crCell.textContent.trim()).toBe('50.0%');
    });

    it('formats ATK as flat integer', async () => {
      const fixture = await renderGrid();
      const cells = fixture.nativeElement.querySelectorAll('tbody tr:first-child td');
      // ATK is index 3
      const atkCell = cells[3];
      // First row by default sort (total_damage desc) = build[1] with atk=2200
      expect(atkCell.textContent.trim()).toBe('2200');
    });

    it('shows — for missing stats', async () => {
      const fixture = await renderGrid([makeBuild(5000)]);
      const cells = fixture.nativeElement.querySelectorAll('tbody tr:first-child td');
      // CR cell (index 4) should be — since total_stats = {}
      expect(cells[4].textContent.trim()).toBe('—');
    });
  });

  describe('D2 — sortable stat columns', () => {
    it('sorts rows by crit_rate descending when CR header clicked', async () => {
      const fixture = await renderGrid();

      // Find the CR sort button in the controls bar
      const sortBtns = fixture.nativeElement.querySelectorAll('.results-grid__controls .link-btn');
      const crBtn = Array.from(sortBtns).find(
        (b: any) => b.textContent.trim() === 'CR',
      ) as HTMLElement;
      crBtn.click();
      fixture.detectChanges();

      // Rows should now be sorted by crit_rate desc: build[1]=6000, build[0]=5000, build[2]=4800
      const cells = fixture.nativeElement.querySelectorAll('tbody tr td:nth-child(5)');
      const values = Array.from(cells).map((c: any) => c.textContent.trim());
      expect(values[0]).toBe('60.0%'); // 6000 bp
      expect(values[1]).toBe('50.0%'); // 5000 bp
      expect(values[2]).toBe('48.0%'); // 4800 bp
    });

    it('CR header has sorted class when active', async () => {
      const fixture = await renderGrid();
      const crBtn = Array.from(
        fixture.nativeElement.querySelectorAll('.results-grid__controls .link-btn'),
      ).find((b: any) => b.textContent.trim() === 'CR') as HTMLElement;
      crBtn.click();
      fixture.detectChanges();

      const crTh = Array.from(fixture.nativeElement.querySelectorAll('th.sortable')).find(
        (th: any) => th.textContent.trim() === 'CR',
      ) as HTMLElement;
      expect(crTh?.classList).toContain('sorted');
    });
  });

  describe('F3 — keystone deep-link + delta breakdown', () => {
    it('enables the breakdown button when team/combo/enemy context is provided', async () => {
      const fixture = await renderGrid(BUILDS, null, {
        teamId: 't1',
        comboId: 'c1',
        enemyProfileId: 'e1',
      });
      const btn = fixture.nativeElement.querySelector(
        'tbody tr:first-child .btn-breakdown',
      ) as HTMLButtonElement;
      expect(btn).toBeTruthy();
      expect(btn.disabled).toBe(false);
    });

    it('disables the breakdown button when deep-link context is missing', async () => {
      const fixture = await renderGrid(BUILDS, null, {});
      const btn = fixture.nativeElement.querySelector(
        'tbody tr:first-child .btn-breakdown',
      ) as HTMLButtonElement;
      expect(btn).toBeTruthy();
      expect(btn.disabled).toBe(true);
    });

    it('clicking breakdown calls RankService.evaluateDiscs with the row disc_ids and opens the panel', async () => {
      const response = {
        dps_agent_name: 'Zhu Yuan',
        combo_name: 'Rotation A',
        enemy_name: 'Cyclops',
        total_damage: 99999,
        delta: null,
      } as unknown as TeamCalculateResponse;
      const evaluateDiscs = vi.fn().mockResolvedValue(response);
      const fixture = await renderGrid(
        [makeBuild(10000, { atk: 2000 })],
        null,
        { teamId: 't1', comboId: 'c1', enemyProfileId: 'e1', activeIndex: 2 },
        { evaluateDiscs },
      );

      const btn = fixture.nativeElement.querySelector(
        'tbody tr:first-child .btn-breakdown',
      ) as HTMLButtonElement;
      btn.click();
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();

      expect(evaluateDiscs).toHaveBeenCalledWith('t1', {
        comboId: 'c1',
        enemyProfileId: 'e1',
        activeIndex: 2,
        discIds: ['d1', 'd2', 'd3', 'd4', 'd5', 'd6'],
      });
      expect(fixture.nativeElement.querySelector('rank-breakdown-panel')).toBeTruthy();
      expect(fixture.nativeElement.textContent).toContain('99,999');
    });

    it('closing the panel clears the breakdown response', async () => {
      const response = {
        dps_agent_name: 'Zhu Yuan',
        combo_name: 'Rotation A',
        enemy_name: 'Cyclops',
        total_damage: 99999,
        delta: null,
      } as unknown as TeamCalculateResponse;
      const evaluateDiscs = vi.fn().mockResolvedValue(response);
      const fixture = await renderGrid(
        [makeBuild(10000, { atk: 2000 })],
        null,
        { teamId: 't1', comboId: 'c1', enemyProfileId: 'e1' },
        { evaluateDiscs },
      );

      const btn = fixture.nativeElement.querySelector(
        'tbody tr:first-child .btn-breakdown',
      ) as HTMLButtonElement;
      btn.click();
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();

      const closeBtn = fixture.nativeElement.querySelector('.close-btn') as HTMLButtonElement;
      closeBtn.click();
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector('rank-breakdown-panel')).toBeFalsy();
    });
  });
});
