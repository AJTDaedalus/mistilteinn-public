import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { BuffContextStore } from '../../shared/buff-context.store';
import { BuffTogglesPanel } from './buff-toggles';
import { BuildsService } from './builds.service';

function makeGroup(
  role: string,
  buffId: string,
  enabled = true,
  overrides: Partial<{
    stat: string;
    value: number;
    max_stacks: number;
    target: string;
    source_label: string;
  }> = {},
) {
  return {
    role,
    agent_name: 'Agent',
    group_key: `${role}_key`,
    name: `${role} ability`,
    description: '',
    buffs: [
      {
        id: buffId,
        role,
        agent_name: 'Agent',
        source: 'skill',
        source_label: 'Skill',
        stat: 'atk_pct',
        value: 1200,
        target: 'self',
        conditions: [],
        enabled,
        max_stacks: 1,
        ...overrides,
      },
    ],
  };
}

function setup(roleToBuildId: Record<string, string | null> = {}) {
  const svc = {
    listBuffs: vi.fn(async (_id: string) => ({
      groups: [
        makeGroup('dps', 'dps-buff-1'),
        makeGroup('support1', 's1-buff-1'),
        makeGroup('support2', 's2-buff-1'),
      ],
    })),
    get: vi.fn(async () => ({ active_conditions: [], stack_counts: {} })),
    listConditions: vi.fn(async () => []),
    update: vi.fn(async () => ({})),
  };

  TestBed.configureTestingModule({
    imports: [BuffTogglesPanel],
    providers: [{ provide: BuildsService, useValue: svc }],
  });

  const f = TestBed.createComponent(BuffTogglesPanel);
  f.componentRef.setInput('buildId', 'dps-id');
  f.componentRef.setInput('roleToBuildId', {
    dps: 'dps-id',
    support1: 's1-id',
    support2: 's2-id',
    ...roleToBuildId,
  });
  return { svc, f };
}

async function settle(fixture: ReturnType<typeof TestBed.createComponent>) {
  fixture.detectChanges();
  for (let i = 0; i < 4; i++) await Promise.resolve();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
}

describe('BuffTogglesPanel — toggle PATCH routing (T-E0)', () => {
  it('PATCHes the DPS build when toggling a DPS buff', async () => {
    const { svc, f } = setup();
    await settle(f);

    const panel = f.componentInstance as unknown as {
      toggle: (id: string, enabled: boolean) => Promise<void>;
    };
    await panel.toggle('dps-buff-1', true);

    expect(svc.update).toHaveBeenCalledWith('dps-id', expect.objectContaining({
      disabled_buffs: expect.arrayContaining(['dps-buff-1']),
    }));
    const call = (svc.update.mock.calls as unknown as [string, unknown][])[0];
    expect(call[0]).toBe('dps-id');
  });

  it('PATCHes the support1 build when toggling a support1 buff', async () => {
    const { svc, f } = setup();
    await settle(f);

    const panel = f.componentInstance as unknown as {
      toggle: (id: string, enabled: boolean) => Promise<void>;
    };
    await panel.toggle('s1-buff-1', true);

    expect(svc.update).toHaveBeenCalledWith('s1-id', expect.objectContaining({
      disabled_buffs: expect.arrayContaining(['s1-buff-1']),
    }));
    const call = (svc.update.mock.calls as unknown as [string, unknown][])[0];
    expect(call[0]).toBe('s1-id');
  });

  it('PATCHes the support2 build when toggling a support2 buff', async () => {
    const { svc, f } = setup();
    await settle(f);

    const panel = f.componentInstance as unknown as {
      toggle: (id: string, enabled: boolean) => Promise<void>;
    };
    await panel.toggle('s2-buff-1', true);

    const call = (svc.update.mock.calls as unknown as [string, unknown][])[0];
    expect(call[0]).toBe('s2-id');
  });

  it('does not PATCH the DPS build when a support buff is toggled', async () => {
    const { svc, f } = setup();
    await settle(f);

    const panel = f.componentInstance as unknown as {
      toggle: (id: string, enabled: boolean) => Promise<void>;
    };
    await panel.toggle('s1-buff-1', true);

    const calls = svc.update.mock.calls as unknown as [string, unknown][];
    expect(calls.every(([id]) => id !== 'dps-id')).toBe(true);
  });

  it('falls back to buildId() when roleToBuildId has no entry for the role', async () => {
    const { svc, f } = setup({ dps: null, support1: null, support2: null });
    await settle(f);

    const panel = f.componentInstance as unknown as {
      toggle: (id: string, enabled: boolean) => Promise<void>;
    };
    await panel.toggle('dps-buff-1', true);

    const call = (svc.update.mock.calls as unknown as [string, unknown][])[0];
    expect(call[0]).toBe('dps-id');
  });

  it('includes only the target role buffs in disabled_buffs', async () => {
    const { svc, f } = setup();
    await settle(f);

    const panel = f.componentInstance as unknown as {
      toggle: (id: string, enabled: boolean) => Promise<void>;
    };
    await panel.toggle('s1-buff-1', true);

    const call = (svc.update.mock.calls as unknown as [string, { disabled_buffs: string[] }][])[0];
    const disabled = call[1].disabled_buffs;
    expect(disabled).not.toContain('dps-buff-1');
    expect(disabled).not.toContain('s2-buff-1');
    expect(disabled).toContain('s1-buff-1');
  });
});

describe('BuffTogglesPanel — stack count chip (Task 5)', () => {
  it('shows a ×N chip and effective total for a stackable buff (Astra M1 shape)', async () => {
    const svc = {
      listBuffs: vi.fn(async () => ({
        groups: [
          makeGroup('dps', 'astra-m1', true, {
            stat: 'res_reduction',
            value: 600,
            max_stacks: 3,
          }),
        ],
      })),
      get: vi.fn(async () => ({ active_conditions: [], stack_counts: {} })),
      listConditions: vi.fn(async () => []),
      update: vi.fn(async () => ({})),
    };

    TestBed.configureTestingModule({
      imports: [BuffTogglesPanel],
      providers: [{ provide: BuildsService, useValue: svc }],
    });
    const f = TestBed.createComponent(BuffTogglesPanel);
    f.componentRef.setInput('buildId', 'dps-id');
    f.componentRef.setInput('roleToBuildId', { dps: 'dps-id', support1: null, support2: null });
    await settle(f);

    const text = (f.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('×3');
    expect(text).toContain('+6.00%');
    expect(text).toContain('+18.00%');
  });

  it('shows no chip for a max_stacks: 1 buff', async () => {
    const svc = {
      listBuffs: vi.fn(async () => ({
        groups: [makeGroup('dps', 'single-buff', true, { max_stacks: 1 })],
      })),
      get: vi.fn(async () => ({ active_conditions: [], stack_counts: {} })),
      listConditions: vi.fn(async () => []),
      update: vi.fn(async () => ({})),
    };

    TestBed.configureTestingModule({
      imports: [BuffTogglesPanel],
      providers: [{ provide: BuildsService, useValue: svc }],
    });
    const f = TestBed.createComponent(BuffTogglesPanel);
    f.componentRef.setInput('buildId', 'dps-id');
    f.componentRef.setInput('roleToBuildId', { dps: 'dps-id', support1: null, support2: null });
    await settle(f);

    expect((f.nativeElement as HTMLElement).querySelector('.buff__stacks')).toBeNull();
  });
});

describe('BuffTogglesPanel — reloadKey reactivity (issue #61)', () => {
  it('re-fetches when reloadKey changes even though buildId is unchanged', async () => {
    const { svc, f } = setup();
    await settle(f);

    expect(svc.listBuffs).toHaveBeenCalledTimes(1);

    f.componentRef.setInput('reloadKey', 1);
    await settle(f);

    expect(svc.listBuffs).toHaveBeenCalledTimes(2);
    expect(svc.listBuffs).toHaveBeenLastCalledWith('dps-id');
  });

  it('does not re-fetch on an unrelated re-render when reloadKey is unchanged', async () => {
    const { svc, f } = setup();
    await settle(f);

    expect(svc.listBuffs).toHaveBeenCalledTimes(1);

    f.componentRef.setInput('roleToBuildId', {
      dps: 'dps-id',
      support1: 's1-id',
      support2: 's2-id',
    });
    await settle(f);

    expect(svc.listBuffs).toHaveBeenCalledTimes(1);
  });
});

describe('BuffTogglesPanel — stack overrides', () => {
  function stackableSvc(stackCounts: Record<string, number>) {
    return {
      listBuffs: vi.fn(async () => ({
        groups: [
          makeGroup('dps', 'astra-m1', true, {
            stat: 'res_reduction',
            value: 600,
            max_stacks: 3,
            source_label: 'M1: RES Reduction stacks',
          }),
        ],
      })),
      get: vi.fn(async () => ({ active_conditions: [], stack_counts: stackCounts })),
      listConditions: vi.fn(async () => []),
      update: vi.fn(async () => ({})),
    };
  }

  async function mount(svc: ReturnType<typeof stackableSvc>) {
    TestBed.configureTestingModule({
      imports: [BuffTogglesPanel],
      providers: [{ provide: BuildsService, useValue: svc }],
    });
    const f = TestBed.createComponent(BuffTogglesPanel);
    f.componentRef.setInput('buildId', 'dps-id');
    f.componentRef.setInput('roleToBuildId', { dps: 'dps-id', support1: null, support2: null });
    await settle(f);
    return f;
  }

  it('renders a saved override instead of the max, and totals against it', async () => {
    const f = await mount(stackableSvc({ 'M1: RES Reduction stacks': 2 }));

    const text = (f.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('×2');
    expect(text).toContain('+12.00%'); // 600bp × 2 stacks, not the ×3 max
    expect(text).not.toContain('+18.00%');
  });

  it('PATCHes an override keyed by source_label — the key the engine resolves by', async () => {
    const svc = stackableSvc({});
    const f = await mount(svc);

    const input = (f.nativeElement as HTMLElement).querySelector(
      '.buff__stack-edit-input',
    ) as HTMLInputElement;
    expect(input.value).toBe('3'); // defaults to fully stacked

    input.value = '1';
    input.dispatchEvent(new Event('change'));
    await settle(f);

    expect(svc.update).toHaveBeenCalledWith('dps-id', {
      stack_counts: { 'M1: RES Reduction stacks': 1 },
    });
    expect((f.nativeElement as HTMLElement).textContent).toContain('×1');
  });

  it('clears the override when the user sets it back to max', async () => {
    const svc = stackableSvc({ 'M1: RES Reduction stacks': 1 });
    const f = await mount(svc);

    const input = (f.nativeElement as HTMLElement).querySelector(
      '.buff__stack-edit-input',
    ) as HTMLInputElement;
    input.value = '3';
    input.dispatchEvent(new Event('change'));
    await settle(f);

    expect(svc.update).toHaveBeenCalledWith('dps-id', { stack_counts: {} });
  });
});

describe('BuffTogglesPanel — save-as-defaults / BuffContextStore sync (Task A11)', () => {
  it('seeds the store from the build on load, merging disabled_buffs across all roles', async () => {
    const { f } = setup();
    const store = TestBed.inject(BuffContextStore);

    // makeGroup() defaults every buff to enabled=true, so nothing should be
    // disabled yet -- this exercises the "no-op merge" path before any edit.
    await settle(f);

    expect(store.context()).toEqual({
      active_conditions: [],
      stack_counts: {},
      disabled_buffs: [],
      custom_buffs: [],
    });
  });

  it('mirrors a support2 buff being disabled into the store, without touching the build write scope', async () => {
    const { svc, f } = setup();
    await settle(f);
    const store = TestBed.inject(BuffContextStore);

    const panel = f.componentInstance as unknown as {
      toggle: (id: string, enabled: boolean) => Promise<void>;
    };
    await panel.toggle('s2-buff-1', true);

    // The store gets the full merged list (Task A6's flat, agent-qualified
    // list covers all roles) even though the PATCH itself only targets the
    // support2 build.
    expect(store.disabledBuffs()).toContain('s2-buff-1');
    const call = (svc.update.mock.calls as unknown as [string, unknown][])[0];
    expect(call[0]).toBe('s2-id');
  });

  it('mirrors an active-condition toggle into the store', async () => {
    const svc = {
      listBuffs: vi.fn(async () => ({ groups: [makeGroup('dps', 'dps-buff-1')] })),
      get: vi.fn(async () => ({ active_conditions: [], stack_counts: {} })),
      listConditions: vi.fn(async () => [
        { condition: 'hp_above_50', label: 'HP > 50%', sources: [] },
      ]),
      update: vi.fn(async () => ({})),
    };
    TestBed.configureTestingModule({
      imports: [BuffTogglesPanel],
      providers: [{ provide: BuildsService, useValue: svc }],
    });
    const f = TestBed.createComponent(BuffTogglesPanel);
    f.componentRef.setInput('buildId', 'dps-id');
    f.componentRef.setInput('roleToBuildId', { dps: 'dps-id', support1: null, support2: null });
    await settle(f);
    const store = TestBed.inject(BuffContextStore);

    const panel = f.componentInstance as unknown as {
      toggleCondition: (cond: string) => Promise<void>;
    };
    await panel.toggleCondition('hp_above_50');

    expect(store.activeConditions()).toEqual(['hp_above_50']);
  });

  it('mirrors a stack override into the store', async () => {
    const svc = {
      listBuffs: vi.fn(async () => ({
        groups: [
          makeGroup('dps', 'astra-m1', true, {
            stat: 'res_reduction',
            value: 600,
            max_stacks: 3,
            source_label: 'M1: RES Reduction stacks',
          }),
        ],
      })),
      get: vi.fn(async () => ({ active_conditions: [], stack_counts: {} })),
      listConditions: vi.fn(async () => []),
      update: vi.fn(async () => ({})),
    };
    TestBed.configureTestingModule({
      imports: [BuffTogglesPanel],
      providers: [{ provide: BuildsService, useValue: svc }],
    });
    const f = TestBed.createComponent(BuffTogglesPanel);
    f.componentRef.setInput('buildId', 'dps-id');
    f.componentRef.setInput('roleToBuildId', { dps: 'dps-id', support1: null, support2: null });
    await settle(f);
    const store = TestBed.inject(BuffContextStore);

    const input = (f.nativeElement as HTMLElement).querySelector(
      '.buff__stack-edit-input',
    ) as HTMLInputElement;
    input.value = '1';
    input.dispatchEvent(new Event('change'));
    await settle(f);

    expect(store.stackCounts()).toEqual({ 'M1: RES Reduction stacks': 1 });
  });

  it('does not call the build-write API when only reading the store', async () => {
    // Task A8's acceptance criterion, exercised end-to-end through the real
    // editor component: loading a build populates the store; nothing about
    // that alone should PATCH the build.
    const { svc, f } = setup();
    await settle(f);

    expect(svc.update).not.toHaveBeenCalled();
  });
});
