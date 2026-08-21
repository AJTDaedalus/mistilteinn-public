import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';

import { BuildEditorPage } from './build-editor';
import { BuildsService } from './builds.service';
import { CalculateService } from '../calculate/calculate.service';

const AGENTS = [
  {
    id: 'a1', name: 'Caesar', specialty: 'stun',
    element: 'physical', rarity: 'S', faction: 'sons-of-calydon',
    full_name: 'Caesar', hakushin_id: 1011,
  },
];

const MOCK_BUILD = {
  id: 'b1',
  agent_id: 'a1',
  agent_specialty: 'stun',
  w_engine_id: null,
  w_engine_level: 60,
  w_engine_refinement: 1,
  mindscape_level: 0,
  core_skill_level: 5,
  agent_level: 60,
  skill_levels: '12,12,12,12,12',
  disabled_buffs: [],
  active_conditions: [],
  stack_counts: {},
  optimizer_priority: null,
  notes: '',
};

function setup(buildId: string | null = null, build: unknown = null) {
  const svc = {
    list: vi.fn(async () => []),
    get: vi.fn(async (_id: string) => build),
    create: vi.fn(async (b: object) => ({ ...b, id: 'new-id' })),
    update: vi.fn(async (_id: string, patch: object) => ({ ...MOCK_BUILD, ...patch })),
    remove: vi.fn(async () => undefined),
    listAgents: vi.fn(async () => AGENTS),
    listWEngines: vi.fn(async () => []),
    listDiscSets: vi.fn(async () => []),
    listDiscsForBuild: vi.fn(async () => []),
    listDiscs: vi.fn(async () => []),
    equipDisc: vi.fn(async () => undefined),
  };
  const calcSvc = {
    listEnemies: vi.fn(async () => []),
  };
  TestBed.configureTestingModule({
    imports: [BuildEditorPage],
    providers: [
      provideRouter([]),
      { provide: BuildsService, useValue: svc },
      { provide: CalculateService, useValue: calcSvc },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: {
            paramMap: convertToParamMap(buildId ? { id: buildId } : {}),
            queryParamMap: convertToParamMap({}),
          },
        },
      },
    ],
  });
  return { svc };
}

async function settle(fixture: ReturnType<typeof TestBed.createComponent>) {
  fixture.detectChanges();
  for (let i = 0; i < 4; i++) await Promise.resolve();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
}

describe('BuildEditorPage — reference data', () => {
  it('fetches agents, wEngines, and discSets on init (create mode)', async () => {
    const { svc } = setup(null);
    const f = TestBed.createComponent(BuildEditorPage);
    await settle(f);

    expect(svc.listAgents).toHaveBeenCalledOnce();
    expect(svc.listWEngines).toHaveBeenCalledOnce();
    expect(svc.listDiscSets).toHaveBeenCalledOnce();
    expect(svc.get).not.toHaveBeenCalled();

    const cmp = f.componentInstance as unknown as {
      agents: () => typeof AGENTS;
      isCreate: () => boolean;
    };
    expect(cmp.agents()).toHaveLength(1);
    expect(cmp.isCreate()).toBe(true);
  });

  it('fetches the build via get(id) and sets dpsBuildRead in edit mode', async () => {
    const { svc } = setup('b1', MOCK_BUILD);
    const f = TestBed.createComponent(BuildEditorPage);
    await settle(f);

    expect(svc.get).toHaveBeenCalledWith('b1');

    const cmp = f.componentInstance as unknown as {
      dpsBuildRead: () => typeof MOCK_BUILD | null;
      buildId: () => string | null;
      isCreate: () => boolean;
    };
    expect(cmp.dpsBuildRead()?.id).toBe('b1');
    expect(cmp.buildId()).toBe('b1');
    expect(cmp.isCreate()).toBe(false);
  });
});

describe('BuildEditorPage — onDpsSaved', () => {
  it('updates dpsBuildRead and buildId after form saves', async () => {
    setup(null);
    const f = TestBed.createComponent(BuildEditorPage);
    await settle(f);

    const page = f.componentInstance as unknown as {
      dpsBuildRead: () => typeof MOCK_BUILD | null;
      buildId: () => string | null;
      onDpsSaved: (b: unknown) => Promise<void>;
    };
    expect(page.buildId()).toBeNull();

    await page.onDpsSaved(MOCK_BUILD);
    expect(page.buildId()).toBe('b1');
    expect(page.dpsBuildRead()?.id).toBe('b1');
  });

  // B17 audit: `buff-toggles` refetches whenever `reloadKey` changes (any
  // bump, regardless of cause — see buff-toggles.spec's "reloadKey
  // reactivity" suite). Since every field on the form (W-Engine, refinement,
  // core skill level, agent level, mindscape) shares the single `save()` ->
  // `saved.emit()` -> `onDpsSaved()` path, proving `onDpsSaved` bumps
  // `reloadKey` on every call — not just the first — is the one assertion
  // that closes out every trigger in the backlog item at once.
  it('bumps reloadKey on every save, even with buildId unchanged', async () => {
    setup('b1', MOCK_BUILD);
    const f = TestBed.createComponent(BuildEditorPage);
    await settle(f);

    const page = f.componentInstance as unknown as {
      reloadKey: () => number;
      onDpsSaved: (b: unknown) => Promise<void>;
    };
    expect(page.reloadKey()).toBe(0);

    await page.onDpsSaved({ ...MOCK_BUILD, w_engine_refinement: 3 });
    expect(page.reloadKey()).toBe(1);

    await page.onDpsSaved({ ...MOCK_BUILD, core_skill_level: 6 });
    expect(page.reloadKey()).toBe(2);

    await page.onDpsSaved({ ...MOCK_BUILD, agent_level: 45 });
    expect(page.reloadKey()).toBe(3);
  });
});

describe('BuildEditorPage — disc refresh', () => {
  it('onDpsEquipped refreshes allDiscs via listDiscs exactly once', async () => {
    const { svc } = setup('b1', MOCK_BUILD);
    const f = TestBed.createComponent(BuildEditorPage);
    await settle(f);

    svc.listDiscs.mockClear();

    const page = f.componentInstance as unknown as {
      onDpsEquipped: (e: { slot: number; discId: string | null }) => Promise<void>;
    };
    await page.onDpsEquipped({ slot: 1, discId: 'disc-1' });

    expect(svc.listDiscs).toHaveBeenCalledOnce();
  });
});
