import { TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { provideRouter } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';

import { TeamEditorPage } from './team-editor';
import { TeamsService } from './teams.service';
import { BuildsService } from '../builds/builds.service';
import { defaultMemberFilters } from './team-member-filters';

function makeBuild(overrides: Record<string, unknown> = {}) {
  return {
    id: 'b1',
    agent_id: 'a1',
    agent_specialty: 'attack',
    w_engine_id: null,
    w_engine_level: 60,
    w_engine_refinement: 1,
    mindscape_level: 0,
    core_skill_level: 5,
    agent_level: 60,
    skill_levels: '12,12,12,12,12',
    notes: '',
    disabled_buffs: [],
    active_conditions: [],
    stack_counts: {},
    optimizer_priority: null,
    ...overrides,
  };
}

function makeAgent(overrides: Record<string, unknown> = {}) {
  return {
    id: 'a1',
    hakushin_id: 1,
    name: 'Caesar',
    full_name: 'Caesar',
    element: 'fire',
    specialty: 'attack',
    rarity: 'S',
    faction: 'Victoria Housekeeping',
    icon_path: '/icons/Caesar.webp', has_potential: false,
    ...overrides,
  };
}

function setupPage(
  builds: unknown[] = [],
  agents: unknown[] = [],
  routeId: string | null = null,
  existingTeam: unknown = null,
) {
  const teamsSvcStub = {
    get: vi.fn(async () => existingTeam),
    create: vi.fn(async (payload: unknown) => ({ id: 't-new', name: (payload as any).name, ...(payload as any) })),
    update: vi.fn(async (_id: string, payload: unknown) => ({ id: routeId, name: (payload as any).name, ...(payload as any) })),
  };
  const buildsSvcStub = {
    list: vi.fn(async () => builds),
    listAgents: vi.fn(async () => agents),
  };
  TestBed.configureTestingModule({
    imports: [TeamEditorPage],
    providers: [
      provideRouter([]),
      { provide: TeamsService, useValue: teamsSvcStub },
      { provide: BuildsService, useValue: buildsSvcStub },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: { get: () => routeId } } },
      },
    ],
  });
  return { teamsSvc: teamsSvcStub, buildsSvc: buildsSvcStub };
}

async function awaitFixture(fixture: ReturnType<typeof TestBed.createComponent>) {
  fixture.detectChanges();
  for (let i = 0; i < 5; i++) await Promise.resolve();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
}

describe('TeamEditorPage', () => {
  it('save button is disabled when name is empty and no members selected', async () => {
    setupPage(
      [makeBuild({ id: 'b1', agent_id: 'a1' })],
      [makeAgent({ id: 'a1', name: 'Caesar' })],
      null,
    );
    const fixture = TestBed.createComponent(TeamEditorPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const btn = el.querySelector('[data-test="save-btn"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('save button is disabled when name is set but no members selected', async () => {
    setupPage(
      [makeBuild({ id: 'b1', agent_id: 'a1' })],
      [makeAgent({ id: 'a1', name: 'Caesar' })],
    );
    const fixture = TestBed.createComponent(TeamEditorPage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;
    comp.teamName.set('My Team');
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const btn = el.querySelector('[data-test="save-btn"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('save button is enabled with 1 member and non-empty name', async () => {
    setupPage(
      [makeBuild({ id: 'b1', agent_id: 'a1' })],
      [makeAgent({ id: 'a1', name: 'Caesar' })],
    );
    const fixture = TestBed.createComponent(TeamEditorPage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;
    comp.teamName.set('Solo Squad');
    comp.selectedBuilds.set([makeBuild({ id: 'b1', agent_id: 'a1' })]);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const btn = el.querySelector('[data-test="save-btn"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it('save button is enabled with exactly 3 members and a name', async () => {
    const builds = [
      makeBuild({ id: 'b1', agent_id: 'a1' }),
      makeBuild({ id: 'b2', agent_id: 'a2' }),
      makeBuild({ id: 'b3', agent_id: 'a3' }),
    ];
    setupPage(builds, [
      makeAgent({ id: 'a1', name: 'Caesar' }),
      makeAgent({ id: 'a2', name: 'Burnice' }),
      makeAgent({ id: 'a3', name: 'Nicole' }),
    ]);
    const fixture = TestBed.createComponent(TeamEditorPage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;
    comp.teamName.set('Full Squad');
    comp.selectedBuilds.set(builds);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const btn = el.querySelector('[data-test="save-btn"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it('create mode calls teamsSvc.create with correct build1/2/3_id mapping', async () => {
    const builds = [
      makeBuild({ id: 'b1', agent_id: 'a1' }),
      makeBuild({ id: 'b2', agent_id: 'a2' }),
    ];
    const { teamsSvc } = setupPage(builds, [
      makeAgent({ id: 'a1', name: 'Caesar' }),
      makeAgent({ id: 'a2', name: 'Burnice' }),
    ]);
    const fixture = TestBed.createComponent(TeamEditorPage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;
    comp.teamName.set('Duo Squad');
    comp.selectedBuilds.set(builds);
    fixture.detectChanges();

    await comp.save();

    expect(teamsSvc.create).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Duo Squad',
        build1_id: 'b1',
        build2_id: 'b2',
        build3_id: null,
      }),
    );
  });

  it('edit mode calls teamsSvc.update with patched payload', async () => {
    const builds = [makeBuild({ id: 'b1', agent_id: 'a1' })];
    const existingTeam = {
      id: 't42',
      name: 'Old Name',
      build1_id: 'b1',
      build2_id: null,
      build3_id: null,
    };
    const { teamsSvc } = setupPage(builds, [makeAgent({ id: 'a1', name: 'Caesar' })], 't42', existingTeam);
    const fixture = TestBed.createComponent(TeamEditorPage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;
    comp.teamName.set('New Name');
    fixture.detectChanges();

    await comp.save();

    expect(teamsSvc.update).toHaveBeenCalledWith(
      't42',
      expect.objectContaining({ name: 'New Name', build1_id: 'b1' }),
    );
  });

  it('preview row shows 3 slots; slots fill as members are selected', async () => {
    setupPage(
      [
        makeBuild({ id: 'b1', agent_id: 'a1' }),
        makeBuild({ id: 'b2', agent_id: 'a2' }),
      ],
      [
        makeAgent({ id: 'a1', name: 'Caesar' }),
        makeAgent({ id: 'a2', name: 'Burnice' }),
      ],
    );
    const fixture = TestBed.createComponent(TeamEditorPage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;
    const el = fixture.nativeElement as HTMLElement;

    expect(el.querySelectorAll('.slot--empty')).toHaveLength(3);

    comp.selectedBuilds.set([makeBuild({ id: 'b1', agent_id: 'a1' })]);
    fixture.detectChanges();
    expect(el.querySelectorAll('.slot--filled')).toHaveLength(1);
    expect(el.querySelectorAll('.slot--empty')).toHaveLength(2);
  });

  describe('filters (A2)', () => {
    it('empty filter shows all builds in grid', async () => {
      setupPage(
        [makeBuild({ id: 'b1', agent_id: 'a1' }), makeBuild({ id: 'b2', agent_id: 'a2' })],
        [makeAgent({ id: 'a1', name: 'Caesar' }), makeAgent({ id: 'a2', name: 'Burnice' })],
      );
      const fixture = TestBed.createComponent(TeamEditorPage);
      await awaitFixture(fixture);
      const el = fixture.nativeElement as HTMLElement;
      expect(el.querySelectorAll('[data-test^="pick-"]')).toHaveLength(2);
    });

    it('name filter hides non-matching builds', async () => {
      setupPage(
        [makeBuild({ id: 'b1', agent_id: 'a1' }), makeBuild({ id: 'b2', agent_id: 'a2' })],
        [makeAgent({ id: 'a1', name: 'Caesar' }), makeAgent({ id: 'a2', name: 'Burnice' })],
      );
      const fixture = TestBed.createComponent(TeamEditorPage);
      await awaitFixture(fixture);
      const comp = fixture.componentInstance as any;
      comp.filters.set({ ...defaultMemberFilters(), name: 'caes' });
      fixture.detectChanges();
      const cards = fixture.nativeElement.querySelectorAll('[data-test^="pick-"]');
      expect(cards).toHaveLength(1);
      expect(cards[0].getAttribute('data-test')).toBe('pick-b1');
    });

    it('element filter hides builds whose agent element does not match', async () => {
      setupPage(
        [makeBuild({ id: 'b1', agent_id: 'a1' }), makeBuild({ id: 'b2', agent_id: 'a2' })],
        [
          makeAgent({ id: 'a1', name: 'Caesar', element: 'fire' }),
          makeAgent({ id: 'a2', name: 'Burnice', element: 'fire' }),
        ],
      );
      setupPage(
        [makeBuild({ id: 'b1', agent_id: 'a1' }), makeBuild({ id: 'b2', agent_id: 'a2' })],
        [
          makeAgent({ id: 'a1', name: 'Caesar', element: 'fire' }),
          makeAgent({ id: 'a2', name: 'Burnice', element: 'electric' }),
        ],
      );
      const fixture = TestBed.createComponent(TeamEditorPage);
      await awaitFixture(fixture);
      const comp = fixture.componentInstance as any;
      comp.filters.set({ ...defaultMemberFilters(), elements: ['fire'] });
      fixture.detectChanges();
      const cards = fixture.nativeElement.querySelectorAll('[data-test^="pick-"]');
      expect(cards).toHaveLength(1);
      expect(cards[0].getAttribute('data-test')).toBe('pick-b1');
    });

    it('specialty filter hides builds with non-matching specialty', async () => {
      setupPage(
        [
          makeBuild({ id: 'b1', agent_id: 'a1', agent_specialty: 'attack' }),
          makeBuild({ id: 'b2', agent_id: 'a2', agent_specialty: 'stun' }),
        ],
        [makeAgent({ id: 'a1', name: 'Caesar' }), makeAgent({ id: 'a2', name: 'Burnice' })],
      );
      const fixture = TestBed.createComponent(TeamEditorPage);
      await awaitFixture(fixture);
      const comp = fixture.componentInstance as any;
      comp.filters.set({ ...defaultMemberFilters(), specialties: ['attack'] });
      fixture.detectChanges();
      const cards = fixture.nativeElement.querySelectorAll('[data-test^="pick-"]');
      expect(cards).toHaveLength(1);
      expect(cards[0].getAttribute('data-test')).toBe('pick-b1');
    });

    it('no-match shows empty-state element', async () => {
      setupPage(
        [makeBuild({ id: 'b1', agent_id: 'a1' })],
        [makeAgent({ id: 'a1', name: 'Caesar' })],
      );
      const fixture = TestBed.createComponent(TeamEditorPage);
      await awaitFixture(fixture);
      const comp = fixture.componentInstance as any;
      comp.filters.set({ ...defaultMemberFilters(), name: 'zzz-no-match' });
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('[data-test="picker-empty"]')).toBeTruthy();
    });

    it('selected build stays in preview row when filtered out of grid', async () => {
      setupPage(
        [makeBuild({ id: 'b1', agent_id: 'a1' }), makeBuild({ id: 'b2', agent_id: 'a2' })],
        [makeAgent({ id: 'a1', name: 'Caesar' }), makeAgent({ id: 'a2', name: 'Burnice' })],
      );
      const fixture = TestBed.createComponent(TeamEditorPage);
      await awaitFixture(fixture);
      const comp = fixture.componentInstance as any;
      comp.selectedBuilds.set([makeBuild({ id: 'b1', agent_id: 'a1' })]);
      comp.filters.set({ ...defaultMemberFilters(), name: 'Burnice' });
      fixture.detectChanges();
      const el = fixture.nativeElement as HTMLElement;
      // Grid shows only Burnice
      const cards = el.querySelectorAll('[data-test^="pick-"]');
      expect(cards).toHaveLength(1);
      expect(cards[0].getAttribute('data-test')).toBe('pick-b2');
      // Preview slot still has the selected Caesar
      expect(el.querySelectorAll('.slot--filled')).toHaveLength(1);
    });
  });


  it('picker cards are disabled once 3 members are selected', async () => {
    const builds = [
      makeBuild({ id: 'b1', agent_id: 'a1' }),
      makeBuild({ id: 'b2', agent_id: 'a2' }),
      makeBuild({ id: 'b3', agent_id: 'a3' }),
      makeBuild({ id: 'b4', agent_id: 'a4' }),
    ];
    setupPage(builds, [
      makeAgent({ id: 'a1', name: 'Caesar' }),
      makeAgent({ id: 'a2', name: 'Burnice' }),
      makeAgent({ id: 'a3', name: 'Nicole' }),
      makeAgent({ id: 'a4', name: 'Ellen' }),
    ]);
    const fixture = TestBed.createComponent(TeamEditorPage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;
    comp.selectedBuilds.set(builds.slice(0, 3));
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const cards = el.querySelectorAll<HTMLButtonElement>('[data-test^="pick-"]');
    const disabledCards = Array.from(cards).filter(c => c.disabled);
    expect(disabledCards.length).toBeGreaterThan(0);
  });
});
