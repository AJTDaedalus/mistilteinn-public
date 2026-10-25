import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { BuildsService } from '../builds/builds.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService } from '../teams/teams.service';
import { ArtifactsService } from '../artifacts/artifacts.service';
import { ArtifactRankingService, type UpgradeSlotRow } from '../artifacts/artifact-ranking.service';
import { OptimizeService } from '../optimize/optimize.service';
import { resinToUpgrade } from '../../sim/resin-to-upgrade';
import { UpgradePage } from './upgrade';

const CLAIM = { fiveStarPerRun: 1.065, setShare: 0.5, slotShare: 0.2, resinPerRun: 20 };

function row(pBeat: number, factor = 0.5): UpgradeSlotRow {
  return {
    slot: 'equip_dress', pieceId: 'a1', setId: 15003, level: 20, mainStat: 'FIGHT_PROP_CRITICAL_HURT',
    factor, pBeat, byMain: [],
    estimate: resinToUpgrade(pBeat, factor, CLAIM),
    sensitivity: {
      cheap: resinToUpgrade(pBeat * 1.2, factor, CLAIM),
      dear: resinToUpgrade(pBeat * 0.8, factor, CLAIM),
    },
    evaluations: 0,
  };
}

function page(upgradeEstimate = vi.fn()) {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      { provide: BuildsService, useValue: { list: vi.fn().mockResolvedValue([]) } },
      { provide: RotationsService, useValue: { list: vi.fn().mockResolvedValue({ items: [] }) } },
      { provide: TeamsService, useValue: { list: vi.fn().mockResolvedValue([]) } },
      {
        provide: ArtifactsService,
        useValue: { options: vi.fn().mockResolvedValue({ stats: [], slots: [], rarities: [] }) },
      },
      { provide: OptimizeService, useValue: { artifactSets: vi.fn().mockResolvedValue(new Map()) } },
      { provide: ArtifactRankingService, useValue: { upgradeEstimate } },
    ],
  });
  return TestBed.runInInjectionContext(() => new UpgradePage());
}

/** `docs/TASKS_upgrade_estimator.md` Task 8 — the page's own logic, not the math beneath it. */
describe('UpgradePage', () => {
  it('will not run without a rotation and a build', () => {
    const p = page();
    expect(p['canRun']()).toBe(false);
    p['rotationId'].set('r1');
    p['buildId'].set('b1');
    expect(p['canRun']()).toBe(true);
  });

  it('defaults the minimum gain to 1%, and sends it as a fraction', async () => {
    const upgradeEstimate = vi.fn().mockResolvedValue({
      rows: [], baseline: 1, gain: 0.01, threshold: 1.01, resinPerRun: 20,
      weightsCaveat: '', caveats: { unstable: [], staleConversions: [] },
    });
    const p = page(upgradeEstimate);
    p['rotationId'].set('r1');
    p['buildId'].set('b1');
    expect(p['gainPercent']()).toBe(1);
    await p['run']();
    expect(upgradeEstimate.mock.calls[0][0].gain).toBeCloseTo(0.01, 12);
  });

  it('keeps the last gain when the box is emptied, because Number("") is 0', () => {
    const p = page();
    p['setGain']('2.5');
    expect(p['gainPercent']()).toBe(2.5);
    p['setGain']('');
    expect(p['gainPercent']()).toBe(2.5);
    p['setGain']('-1');
    expect(p['gainPercent']()).toBe(2.5);
  });

  it('says "never" for a piece no drop can beat, and a real ratio otherwise', () => {
    const p = page();
    expect(p['oneIn'](row(0).estimate)).toBe('never');
    // ½ · ⅕ · 0.01 = 1 in 1,000.
    expect(p['oneIn'](row(0.01).estimate)).toBe('1 in 1,000');
  });

  it('shows the weight spread as a resin range, cheap end first', () => {
    const p = page();
    const r = row(0.01);
    expect(p['spread'](r)).toBe(
      `${Math.round(r.sensitivity.cheap.median!).toLocaleString()}–`
      + `${Math.round(r.sensitivity.dear.median!).toLocaleString()}`,
    );
  });

  it('shows the error rather than a blank table when the estimate fails', async () => {
    const p = page(vi.fn().mockRejectedValue(new Error('no drop model')));
    p['rotationId'].set('r1');
    p['buildId'].set('b1');
    await p['run']();
    expect(p['error']()).toContain('no drop model');
    expect(p['running']()).toBe(false);
  });
});
