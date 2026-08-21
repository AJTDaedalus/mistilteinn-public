import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';

import { BuildEditorFormComponent } from './build-editor-form';
import { BuildsService, BuildRead } from './builds.service';

const AGENTS = [
  {
    id: 'a1', name: 'Caesar', specialty: 'stun',
    element: 'physical', rarity: 'S', faction: 'sons-of-calydon',
    full_name: 'Caesar', hakushin_id: 1011, has_potential: false,
  },
  {
    id: 'a2', name: 'Burnice', specialty: 'anomaly',
    element: 'fire', rarity: 'S', faction: 'belobog',
    full_name: 'Burnice', hakushin_id: 1316, has_potential: true,
  },
];

const WENGINES = [
  { id: 'w1', name: 'Sharpened Stinger', specialty: 'attack', rarity: 'S' },
  { id: 'w2', name: 'Lunar Decoration', specialty: 'stun', rarity: 'S' },
  { id: 'w3', name: 'Tusks of Fury',    specialty: 'stun', rarity: 'A' },
];

const MOCK_BUILD: BuildRead = {
  id: 'b1',
  agent_id: 'a2',
  agent_specialty: 'anomaly',
  w_engine_id: 'w2',
  w_engine_level: 55,
  w_engine_refinement: 2,
  mindscape_level: 4,
  core_skill_level: 3,
  agent_level: 50,
  skill_levels: '10,11,12,11,10',
  disabled_buffs: [],
  active_conditions: [],
  stack_counts: {},
  optimizer_priority: null,
  notes: '',
} as unknown as BuildRead;

function setup() {
  const svc = {
    get: vi.fn(async (id: string) => ({ ...MOCK_BUILD, id })),
    create: vi.fn(async (b: object) => ({ ...b, id: 'new-id' })),
    update: vi.fn(async (_id: string, _patch: object) => undefined),
    equipDisc: vi.fn(async () => undefined),
    listAgents: vi.fn(async () => AGENTS),
    listWEngines: vi.fn(async () => WENGINES),
    listDiscSets: vi.fn(async () => []),
    listDiscsForBuild: vi.fn(async () => []),
    listDiscs: vi.fn(async () => []),
  };
  TestBed.configureTestingModule({
    imports: [BuildEditorFormComponent],
    providers: [
      provideRouter([]),
      { provide: BuildsService, useValue: svc },
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

// Helper: cast component to access protected/private members in tests.
function cast(cmp: BuildEditorFormComponent) {
  return cmp as unknown as {
    buildId: () => string | null;
    agentId: () => string;
    wEngineId: () => string | null;
    mindscape: () => number;
    agentLevel: () => number;
    wEngineLevel: () => number;
    wEngineRefinement: () => number;
    coreSkillLevel: () => number;
    skillLevels: () => number[];
    saving: () => boolean;
    agentId_set: (v: string) => void;
    matchingWEngines: () => { name: string; specialty: string }[];
    otherWEngines: () => { name: string; specialty: string }[];
    setSkillLevel: (slot: number, level: number) => void;
    save: () => Promise<void>;
    pickDisc: (slot: number, discId: string | null) => Promise<void>;
  };
}

describe('BuildEditorFormComponent — field population', () => {
  it('populates all fields from the build input', async () => {
    setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', MOCK_BUILD);
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('wEngines', WENGINES);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const cmp = cast(f.componentInstance);
    expect(cmp.buildId()).toBe('b1');
    expect(cmp.agentId()).toBe('a2');
    expect(cmp.wEngineId()).toBe('w2');
    expect(cmp.wEngineLevel()).toBe(55);
    expect(cmp.wEngineRefinement()).toBe(2);
    expect(cmp.mindscape()).toBe(4);
    expect(cmp.coreSkillLevel()).toBe(3);
    expect(cmp.agentLevel()).toBe(50);
    expect(cmp.skillLevels()).toEqual([10, 11, 12, 11, 10]);
  });
});

describe('BuildEditorFormComponent — save (edit mode)', () => {
  it('calls svc.update then svc.get and emits saved', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', MOCK_BUILD);
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const savedValues: BuildRead[] = [];
    f.componentInstance.saved.subscribe((v) => savedValues.push(v));

    const cmp = cast(f.componentInstance);
    await cmp.save();

    expect(svc.update).toHaveBeenCalledOnce();
    const [id] = svc.update.mock.calls[0] as [string, object];
    expect(id).toBe('b1');
    expect(svc.create).not.toHaveBeenCalled();

    expect(svc.get).toHaveBeenCalledWith('b1');
    expect(savedValues).toHaveLength(1);
    expect(savedValues[0].id).toBe('b1');
  });

  it('does not save when no agent is selected', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    await cast(f.componentInstance).save();
    expect(svc.create).not.toHaveBeenCalled();
    expect(svc.update).not.toHaveBeenCalled();
  });
});

describe('BuildEditorFormComponent — save (create mode)', () => {
  it('calls svc.create and emits saved with the created build', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', null);
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('mode', 'create');
    await settle(f);

    const savedValues: BuildRead[] = [];
    f.componentInstance.saved.subscribe((v) => savedValues.push(v));

    const cmp = f.componentInstance as unknown as {
      agentId: { set: (v: string) => void };
      save: () => Promise<void>;
    };
    cmp.agentId.set('a1');
    await cmp.save();

    expect(svc.create).toHaveBeenCalledOnce();
    const arg = svc.create.mock.calls[0][0] as { agent_id: string };
    expect(arg).toMatchObject({ agent_id: 'a1' });
    expect(svc.update).not.toHaveBeenCalled();

    expect(savedValues).toHaveLength(1);
    expect(savedValues[0]).toMatchObject({ id: 'new-id', agent_id: 'a1' });

    // Internal buildId updated immediately so disc picker works without
    // waiting for parent to re-render.
    expect(cast(f.componentInstance).buildId()).toBe('new-id');
  });
});

describe('BuildEditorFormComponent — reload triggers (issue #61 / B17)', () => {
  // Each of these fields lives in the same flat `save()` payload as mindscape
  // (the field B16 fixed), so a single "Save changes" click always emits
  // `saved` regardless of which field moved — proving the parent's
  // `reloadKey` bump (wired off that one `saved` emission) fires for every
  // trigger below, not just mindscape.

  it('agent swap: emits saved with the new agent_id', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', MOCK_BUILD); // agent_id: 'a2'
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('wEngines', WENGINES);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const savedValues: BuildRead[] = [];
    f.componentInstance.saved.subscribe((v) => savedValues.push(v));

    const cmp = f.componentInstance as unknown as {
      onAgentPick: (v: string | null) => void;
      save: () => Promise<void>;
    };
    cmp.onAgentPick('a1');
    await cmp.save();

    const [, payload] = svc.update.mock.calls[0] as [string, { agent_id: string }];
    expect(payload.agent_id).toBe('a1');
    expect(savedValues).toHaveLength(1);
  });

  it('W-Engine swap: emits saved with the new w_engine_id', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', MOCK_BUILD); // w_engine_id: 'w2'
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('wEngines', WENGINES);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const savedValues: BuildRead[] = [];
    f.componentInstance.saved.subscribe((v) => savedValues.push(v));

    const cmp = f.componentInstance as unknown as {
      wEngineId: { set: (v: string | null) => void };
      save: () => Promise<void>;
    };
    cmp.wEngineId.set('w3');
    await cmp.save();

    const [, payload] = svc.update.mock.calls[0] as [string, { w_engine_id: string | null }];
    expect(payload.w_engine_id).toBe('w3');
    expect(savedValues).toHaveLength(1);
  });

  it('W-Engine refinement change: emits saved with the new w_engine_refinement', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', MOCK_BUILD); // w_engine_refinement: 2
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('wEngines', WENGINES);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const savedValues: BuildRead[] = [];
    f.componentInstance.saved.subscribe((v) => savedValues.push(v));

    const cmp = f.componentInstance as unknown as {
      wEngineRefinement: { set: (v: number) => void };
      save: () => Promise<void>;
    };
    cmp.wEngineRefinement.set(4);
    await cmp.save();

    const [, payload] = svc.update.mock.calls[0] as [string, { w_engine_refinement: number }];
    expect(payload.w_engine_refinement).toBe(4);
    expect(savedValues).toHaveLength(1);
  });

  it('core skill level change: emits saved with the new core_skill_level', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', MOCK_BUILD); // core_skill_level: 3
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('wEngines', WENGINES);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const savedValues: BuildRead[] = [];
    f.componentInstance.saved.subscribe((v) => savedValues.push(v));

    const cmp = f.componentInstance as unknown as {
      coreSkillLevel: { set: (v: number) => void };
      save: () => Promise<void>;
    };
    cmp.coreSkillLevel.set(6);
    await cmp.save();

    const [, payload] = svc.update.mock.calls[0] as [string, { core_skill_level: number }];
    expect(payload.core_skill_level).toBe(6);
    expect(savedValues).toHaveLength(1);
  });

  it('agent level change: emits saved with the new agent_level', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', MOCK_BUILD); // agent_level: 50
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('wEngines', WENGINES);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const savedValues: BuildRead[] = [];
    f.componentInstance.saved.subscribe((v) => savedValues.push(v));

    const cmp = f.componentInstance as unknown as {
      agentLevel: { set: (v: number) => void };
      save: () => Promise<void>;
    };
    cmp.agentLevel.set(35);
    await cmp.save();

    const [, payload] = svc.update.mock.calls[0] as [string, { agent_level: number }];
    expect(payload.agent_level).toBe(35);
    expect(savedValues).toHaveLength(1);
  });
});

describe('BuildEditorFormComponent — disc equip', () => {
  it('calls svc.equipDisc and emits equipped({slot, discId})', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', MOCK_BUILD);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const equipEvents: { slot: number; discId: string | null }[] = [];
    f.componentInstance.equipped.subscribe((e) => equipEvents.push(e));

    await cast(f.componentInstance).pickDisc(3, 'disc-42');

    expect(svc.equipDisc).toHaveBeenCalledWith('b1', 3, 'disc-42');
    expect(equipEvents).toHaveLength(1);
    expect(equipEvents[0]).toEqual({ slot: 3, discId: 'disc-42' });
  });

  it('unequips (null discId) and emits equipped with null', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', MOCK_BUILD);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const equipEvents: { slot: number; discId: string | null }[] = [];
    f.componentInstance.equipped.subscribe((e) => equipEvents.push(e));

    await cast(f.componentInstance).pickDisc(1, null);

    expect(svc.equipDisc).toHaveBeenCalledWith('b1', 1, null);
    expect(equipEvents[0]).toEqual({ slot: 1, discId: null });
  });
});

describe('BuildEditorFormComponent — W-Engine grouping', () => {
  it('groups W-Engines into matching vs others by agent specialty', async () => {
    setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('wEngines', WENGINES);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const cmp = f.componentInstance as unknown as {
      agentId: { set: (v: string) => void };
      matchingWEngines: () => { name: string }[];
      otherWEngines: () => { name: string }[];
    };
    cmp.agentId.set('a1'); // stun
    expect(cmp.matchingWEngines().map((w) => w.name)).toEqual([
      'Lunar Decoration', 'Tusks of Fury',
    ]);
    expect(cmp.otherWEngines().map((w) => w.name)).toEqual(['Sharpened Stinger']);

    cmp.agentId.set('a2'); // anomaly — no matching in fixture
    expect(cmp.matchingWEngines()).toHaveLength(0);
    expect(cmp.otherWEngines()).toHaveLength(3);
  });

  it('does not clear an off-spec W-Engine on agent change', async () => {
    setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', MOCK_BUILD); // agent=a2, w_engine=w2 (stun)
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('wEngines', WENGINES);
    f.componentRef.setInput('mode', 'edit');
    await settle(f);

    const cmp = f.componentInstance as unknown as {
      agentId: { set: (v: string) => void };
      wEngineId: () => string | null;
    };
    // Switch agent — cross-specialty W-Engine should be preserved.
    cmp.agentId.set('a1');
    expect(cmp.wEngineId()).toBe('w2');
  });
});

describe('BuildEditorFormComponent — skill levels', () => {
  it('encodes 5 skill levels into comma-separated string on save', async () => {
    const { svc } = setup();
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('mode', 'create');
    await settle(f);

    const cmp = f.componentInstance as unknown as {
      agentId: { set: (v: string) => void };
      setSkillLevel: (slot: number, level: number) => void;
      save: () => Promise<void>;
    };
    cmp.agentId.set('a1');
    cmp.setSkillLevel(0, 12);
    cmp.setSkillLevel(1, 9);
    cmp.setSkillLevel(2, 12);
    cmp.setSkillLevel(3, 11);
    cmp.setSkillLevel(4, 10);
    await cmp.save();

    const arg = svc.create.mock.calls[0][0] as { skill_levels: string };
    expect(arg.skill_levels).toBe('12,9,12,11,10');
  });
});



// ---- Potential Vision level picker (#90 Track 2) ---------------------------
describe('BuildEditorFormComponent — Potential Vision level', () => {
  function mount(build: BuildRead) {
    const f = TestBed.createComponent(BuildEditorFormComponent);
    f.componentRef.setInput('build', build);
    f.componentRef.setInput('agents', AGENTS);
    f.componentRef.setInput('wEngines', WENGINES);
    f.componentRef.setInput('mode', 'edit');
    return f;
  }

  const picker = (f: ReturnType<typeof TestBed.createComponent>) =>
    (f.nativeElement as HTMLElement).querySelector(
      'select',
    ) as HTMLSelectElement | null;

  it('renders only for an agent that has a Potential tree', async () => {
    // a2 (Burnice) has_potential: true; a1 (Caesar) does not. An inert control on the
    // ~49 agents without Potential is a support question waiting to happen.
    setup();
    const withPotential = mount(MOCK_BUILD); // agent a2
    await settle(withPotential);
    expect(picker(withPotential)).toBeTruthy();

    const without = mount({ ...MOCK_BUILD, agent_id: 'a1' } as BuildRead);
    await settle(without);
    expect(picker(without)).toBeFalsy();
  });

  it('offers seven states: not-unlocked plus Levels I-VI', async () => {
    // Level I is a real state, not a synonym for locked: it buys the kit variant and
    // no value bonus. Collapsing the two is the off-by-one this picker replaced.
    setup();
    const f = mount(MOCK_BUILD);
    await settle(f);
    const options = Array.from(picker(f)!.options).map((o) => o.value);
    expect(options).toEqual(['0', '1', '2', '3', '4', '5', '6']);
  });

  it('defaults to Level VI and saves rank 6', async () => {
    const { svc } = setup();
    const f = mount(MOCK_BUILD);
    await settle(f);

    const cmp = f.componentInstance as unknown as { save: () => Promise<void> };
    await cmp.save();
    const [, payload] = svc.update.mock.calls[0] as [string, { potential_rank: number }];
    expect(payload.potential_rank).toBe(6);
  });

  it('saves the selected level', async () => {
    const { svc } = setup();
    const f = mount(MOCK_BUILD);
    await settle(f);

    const sel = picker(f)!;
    sel.value = '3';
    sel.dispatchEvent(new Event('change'));
    await settle(f);

    const cmp = f.componentInstance as unknown as { save: () => Promise<void> };
    await cmp.save();
    const [, payload] = svc.update.mock.calls[0] as [string, { potential_rank: number }];
    expect(payload.potential_rank).toBe(3);
  });

  it('reads a stored level back', async () => {
    setup();
    const f = mount({ ...MOCK_BUILD, potential_rank: 2 } as unknown as BuildRead);
    await settle(f);
    expect(picker(f)!.value).toBe('2');
  });

  it('reads rank 0 back as not unlocked', async () => {
    setup();
    const f = mount({ ...MOCK_BUILD, potential_rank: 0 } as unknown as BuildRead);
    await settle(f);
    expect(picker(f)!.value).toBe('0');
  });
});
