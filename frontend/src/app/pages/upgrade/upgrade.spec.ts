import { computed, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { ArtifactsService } from '../artifacts/artifacts.service';
import { ArtifactsContextService } from '../artifacts/artifacts-context.service';
import { CalibrationCancelled } from '../optimize/recipe-optimize.service';
import { ArtifactRankingService, type UpgradeSlotRow } from '../artifacts/artifact-ranking.service';
import { OptimizeService } from '../optimize/optimize.service';
import { resinToUpgrade } from '../../sim/resin-to-upgrade';
import { UpgradePage } from './upgrade';

const CLAIM = { fiveStarPerRun: 1.065, setShare: 0.5, slotShare: 0.2, resinPerRun: 20 };

function row(pBeat: number, factor = 0.5): UpgradeSlotRow {
  return {
    slot: 'equip_dress', pieceId: 'a1', setId: 15003, level: 20, mainStat: 'FIGHT_PROP_CRITICAL_HURT',
    factor, domainless: factor === 0, pBeat, byMain: [],
    estimate: resinToUpgrade(pBeat, factor, CLAIM),
    sensitivity: {
      cheap: resinToUpgrade(pBeat * 1.2, factor, CLAIM),
      dear: resinToUpgrade(pBeat * 0.8, factor, CLAIM),
    },
    evaluations: 0,
  };
}

/** The shared picker, stubbed: `ready` is what the page gates Estimate on. */
function context() {
  const rotationId = signal('');
  const buildId = signal('');
  return {
    rotationId, buildId,
    rotationChoices: signal([{ id: 'r1', label: 'R' }]),
    buildChoices: signal([{ id: 'b1', label: 'B', detail: '' }]),
    ready: computed(() => rotationId() === 'r1' && buildId() === 'b1'),
    load: vi.fn().mockResolvedValue(undefined),
    chooseRotation: (id: string) => rotationId.set(id),
  };
}

function page(upgradeEstimate = vi.fn()) {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      { provide: ArtifactsContextService, useValue: context() },
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
  it('will not run without a rotation and a build this account can ask about', () => {
    const p = page();
    expect(p['canRun']()).toBe(false);
    // A selection left over from another session is not one of this account's choices.
    p['rotationId'].set('someone-elses');
    p['buildId'].set('b1');
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

  it('keeps the last gain when the box is emptied or negative, and puts it back in the box', () => {
    const p = page();
    const box = document.createElement('input');
    box.value = '2.5';
    p['setGain'](box);
    expect(p['gainPercent']()).toBe(2.5);
    // `Number('')` is 0: an emptied box must not silently become "any gain counts".
    box.value = '';
    p['setGain'](box);
    expect(p['gainPercent']()).toBe(2.5);
    expect(box.value).toBe('2.5');
    box.value = '-1';
    p['setGain'](box);
    expect(p['gainPercent']()).toBe(2.5);
    expect(box.value).toBe('2.5');
  });

  it('treats a cancelled calibration as a cancel, not an error', async () => {
    const p = page(vi.fn().mockRejectedValue(new CalibrationCancelled()));
    p['rotationId'].set('r1');
    p['buildId'].set('b1');
    await p['run']();
    expect(p['error']()).toBe('');
    expect(p['running']()).toBe(false);
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
