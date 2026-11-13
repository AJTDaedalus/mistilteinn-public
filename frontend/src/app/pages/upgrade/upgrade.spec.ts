import { computed, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { ArtifactsService } from '../artifacts/artifacts.service';
import { ArtifactsContextService } from '../artifacts/artifacts-context.service';
import { CalibrationCancelled } from '../optimize/recipe-optimize.service';
import { ArtifactRankingService, type UpgradeSlotRow } from '../artifacts/artifact-ranking.service';
import { OptimizeService } from '../optimize/optimize.service';
import { FormulaEstimateService } from '../optimize/formula-estimate.service';
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
  // Math-fallback P1, task 8: gcsim or the formula estimate, shared with Rank.
  const mode = signal<'gcsim' | 'formula'>('gcsim');
  const formulaRequest = signal<unknown>(null);
  return {
    rotationId, buildId, mode, formulaRequest,
    rotationChoices: signal([{ id: 'r1', label: 'R' }]),
    buildChoices: signal([{ id: 'b1', label: 'B', detail: '' }]),
    ready: computed(() => (mode() === 'formula' || rotationId() === 'r1') && buildId() === 'b1'),
    load: vi.fn().mockResolvedValue(undefined),
    chooseRotation: (id: string) => rotationId.set(id),
    teams: signal([]),
    formulaTeamId: signal(''),
    formulaHits: signal([]),
    formulaRefused: signal([]),
    formulaGroups: signal([]),
    gcsimBlocked: signal<string[]>([]),
    chooseMode: (m: 'gcsim' | 'formula') => mode.set(m),
    chooseFormulaTeam: vi.fn(),
    useFormulaEstimate: () => mode.set('formula'),
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

  // ── Math-fallback P1, task 8 ────────────────────────────────────────────────────────────

  it('turns a 422 naming a member gcsim cannot run into a choice', async () => {
    const detail = "gcsim has no character key for 'Kachina' (normalised 'kachina') at pin x.";
    const p = page(vi.fn().mockRejectedValue({ detail }));
    p['rotationId'].set('r1');
    p['buildId'].set('b1');
    await p['run']();
    expect(p['error']()).toBe('');
    expect(p['gcsimRefused']()?.name).toBe('Kachina');
    p['useFormulaEstimate']();
    expect(p['mode']()).toBe('formula');
  });

  it('in formula mode needs a target, sends the formula request and labels the rows', async () => {
    const upgradeEstimate = vi.fn().mockResolvedValue({
      rows: [], baseline: 1, gain: 0.01, threshold: 1.01, resinPerRun: 20,
      weightsCaveat: '', caveats: { unstable: [], staleConversions: [] }, formula: ['x'],
    });
    const p = page(upgradeEstimate);
    const ctx = TestBed.inject(ArtifactsContextService) as unknown as ReturnType<typeof context>;
    ctx.mode.set('formula');
    p['buildId'].set('b1');
    // No target for this build yet: Estimate stays off.
    expect(p['canRun']()).toBe(false);
    TestBed.inject(FormulaEstimateService).ensureTarget('b1', [{
      talent: 'elemental_skill', label: 'Skill DMG', index: 0, multiplier: 1, hits: 1,
      exclusive: false, scaling_stat: 'atk', extra_terms: [],
    }] as never);
    expect(p['canRun']()).toBe(true);

    const request = { build: { id: 'b1' }, team: [], channel: 'geo', scope: 'normal', enemyLevel: 90 };
    ctx.formulaRequest.set(request);
    await p['run']();
    expect(upgradeEstimate.mock.calls[0][0].formula).toEqual(request);
    expect(p['ranFormula']()).toBe(true);
    // No simulator loads, so the status line never claimed one did.
    expect(p['progress']()).toBeNull();
  });
});
