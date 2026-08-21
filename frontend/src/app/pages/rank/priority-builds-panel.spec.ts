import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { BuildsService } from '../builds/builds.service';
import { CombosService } from '../builds/combos.service';
import { CalculateService } from '../calculate/calculate.service';
import { DiscSetsService } from '../optimize/disc-sets.service';
import type { RankContextInput } from './rank.service';
import { PriorityBuildsPanel } from './priority-builds-panel';

// Buff columns differ per build on purpose: a priority job ranks N unrelated
// builds, so a per-row seeding test has to be able to tell them apart
// (DESIGN_buff_context.md §2.5, #95).
const MOCK_BUILDS = [
  { id: 'b1', name: 'Build A', agent_id: 'a1', w_engine_id: null, mindscape_level: 0, support1_build_id: 'b2', support2_build_id: null,
    active_conditions: ['always', 'hp_above_50'], stack_counts: { 'b1:stack': 2 }, disabled_buffs: ['1:core_a'] },
  { id: 'b2', name: 'Build B', agent_id: 'a2', w_engine_id: null, mindscape_level: 0, support1_build_id: null, support2_build_id: null,
    active_conditions: ['always', 'enemy_stunned'], stack_counts: { 'b2:stack': 3 }, disabled_buffs: ['2:core_b'] },
];
const MOCK_ENEMIES = [{ id: 'e1', name: 'Enemy A', level: 60, rarity: 4 }];

const ENEMIES_MIXED = [
  { id: 'e-trash', name: 'Notorious Assaulter', level: 60, rarity: 1 },
  { id: 'e-boss-1', name: 'Dead End Butcher', level: 60, rarity: 4, stun_dmg_taken_ratio: 5000 },
  { id: 'e-boss-2', name: 'Girtablullu - Stagnant Aberrant', level: 60, rarity: 4,
    stun_dmg_taken_ratio: 2500 },
];
const MOCK_SETS = [
  { id: 's1', hakushin_id: 100, name: 'Set One', icon_path: '' },
  { id: 's2', hakushin_id: 200, name: 'Set Two', icon_path: '' },
];
const MOCK_COMBOS = [
  { id: 'c1', name: 'Combo A', build_id: 'b1' },
  { id: 'c2', name: 'Combo B', build_id: 'b1' },
];

function makeDiscs(setIds: string[]) {
  return setIds.map((disc_set_id, i) => ({ id: `d${i}`, disc_set_id } as any));
}

async function flush(fixture: ReturnType<typeof TestBed.createComponent>) {
  await fixture.whenStable();
  await new Promise((r) => setTimeout(r, 0));
  fixture.detectChanges();
}

async function setup(overrides?: {
  listDiscsForBuild?: (...args: any[]) => any;
  enemies?: unknown[];
}) {
  const buildsService = {
    list: vi.fn().mockResolvedValue(MOCK_BUILDS),
    listDiscsForBuild: overrides?.listDiscsForBuild ?? vi.fn().mockResolvedValue(makeDiscs(['s1'])),
  };
  const combosService = { listForBuild: vi.fn().mockResolvedValue(MOCK_COMBOS) };
  const calcService = { listEnemies: vi.fn().mockResolvedValue(overrides?.enemies ?? MOCK_ENEMIES) };
  const discSetsService = { listSets: vi.fn().mockResolvedValue(MOCK_SETS) };

  TestBed.configureTestingModule({
    providers: [
      { provide: BuildsService, useValue: buildsService },
      { provide: CombosService, useValue: combosService },
      { provide: CalculateService, useValue: calcService },
      { provide: DiscSetsService, useValue: discSetsService },
    ],
  });
  const fixture = TestBed.createComponent(PriorityBuildsPanel);
  fixture.detectChanges();
  await flush(fixture);
  return { fixture, buildsService, combosService };
}

describe('PriorityBuildsPanel', () => {
  it('starts with zero rows', async () => {
    const { fixture } = await setup();
    expect(fixture.componentInstance.rowCount).toBe(0);
  });

  it('addRow() adds a row', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    comp['addRow']();
    expect(comp.rowCount).toBe(1);
  });

  it('removeRow() removes the matching row', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    comp['addRow']();
    comp['addRow']();
    expect(comp.rowCount).toBe(2);
    const id = comp['rows']()[0].id;
    comp['removeRow'](id);
    expect(comp.rowCount).toBe(1);
    expect(comp['rows']()[0].id).not.toBe(id);
  });

  it('each row carries its own allowedSetIds after build change', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;

    comp['addRow']();
    const rowId = comp['rows']()[0].id;
    await comp['onBuildChange'](rowId, 'b1');
    await flush(fixture);

    const row = comp['rows']().find((r) => r.id === rowId)!;
    // Pre-populated from disc s1 → hakushin_id 100
    expect(row.allowedSetIds).toEqual([100]);
  });

  it('two rows carry independent allowedSetIds', async () => {
    const { fixture } = await setup({
      listDiscsForBuild: vi.fn()
        .mockResolvedValueOnce(makeDiscs(['s1']))  // row 0 → set 100
        .mockResolvedValueOnce(makeDiscs(['s2'])), // row 1 → set 200
    });
    const comp = fixture.componentInstance;

    comp['addRow']();
    comp['addRow']();
    const [r0, r1] = comp['rows']();
    await comp['onBuildChange'](r0.id, 'b1');
    await flush(fixture);
    await comp['onBuildChange'](r1.id, 'b2');
    await flush(fixture);

    const rows = comp['rows']();
    expect(rows.find((r) => r.id === r0.id)!.allowedSetIds).toEqual([100]);
    expect(rows.find((r) => r.id === r1.id)!.allowedSetIds).toEqual([200]);
  });

  it('emits null when a row is incomplete', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;

    const emitted: (RankContextInput[] | null)[] = [];
    comp.contextsChange.subscribe((v) => emitted.push(v));

    comp['addRow'](); // row has no build chosen
    expect(emitted.at(-1)).toBeNull();
  });

  it('emits full context list once all rows are complete', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;

    comp['addRow']();
    const rowId = comp['rows']()[0].id;

    const emitted: (RankContextInput[] | null)[] = [];
    comp.contextsChange.subscribe((v) => emitted.push(v));

    await comp['onBuildChange'](rowId, 'b1');
    await flush(fixture);

    const nonNull = emitted.filter((e) => e !== null);
    expect(nonNull.length).toBeGreaterThan(0);
    const last = nonNull.at(-1)!;
    expect(last[0].build_id).toBe('b1');
    expect(last[0].combo_id).toBe('c1');
    expect(last[0].enemy_profile_id).toBe('e1');
  });

  it('emits contexts with correct weight', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;

    comp['addRow']();
    const rowId = comp['rows']()[0].id;
    await comp['onBuildChange'](rowId, 'b1');
    await flush(fixture);

    const emitted: (RankContextInput[] | null)[] = [];
    comp.contextsChange.subscribe((v) => emitted.push(v));
    comp['onWeightChange'](rowId, 3);

    const nonNull = emitted.filter((e) => e !== null);
    expect(nonNull.length).toBeGreaterThan(0);
    expect(nonNull.at(-1)![0].weight).toBe(3);
  });

  // DESIGN_buff_context.md §2.5 (#95). Before this, every context in a priority
  // job carried the same shared BuffContextStore value, so N unrelated builds
  // were all ranked against one arbitrary buff state.
  it('seeds each row from its own build, not one shared value (#95)', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;

    comp['addRow']();
    const first = comp['rows']()[0].id;
    await comp['onBuildChange'](first, 'b1');
    await flush(fixture);

    comp['addRow']();
    const second = comp['rows']()[1].id;

    const emitted: (RankContextInput[] | null)[] = [];
    comp.contextsChange.subscribe((v) => emitted.push(v));
    await comp['onBuildChange'](second, 'b2');
    await flush(fixture);

    const contexts = emitted.filter((e) => e !== null).at(-1)!;
    expect(contexts).toHaveLength(2);

    expect(contexts[0].active_conditions).toEqual(['always', 'hp_above_50']);
    expect(contexts[0].stack_counts).toEqual({ 'b1:stack': 2 });
    expect(contexts[0].disabled_buffs).toEqual(['1:core_a']);

    expect(contexts[1].active_conditions).toEqual(['always', 'enemy_stunned']);
    expect(contexts[1].stack_counts).toEqual({ 'b2:stack': 3 });
    expect(contexts[1].disabled_buffs).toEqual(['2:core_b']);
  });

  it('toggleSet adds/removes a set id from the correct row', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;

    comp['addRow']();
    const rowId = comp['rows']()[0].id;
    await comp['onBuildChange'](rowId, 'b1');
    await flush(fixture);

    // Row pre-filled with set 100. Toggle 200 on.
    comp['toggleSet'](rowId, 200);
    expect(comp['rows']()[0].allowedSetIds).toContain(200);

    // Toggle 200 off.
    comp['toggleSet'](rowId, 200);
    expect(comp['rows']()[0].allowedSetIds).not.toContain(200);
  });

  it('clearSets sets allowedSetIds to null', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;

    comp['addRow']();
    const rowId = comp['rows']()[0].id;
    await comp['onBuildChange'](rowId, 'b1');
    await flush(fixture);
    comp['clearSets'](rowId);
    expect(comp['rows']()[0].allowedSetIds).toBeNull();
  });

  it('rank() payload matches RankRequest shape', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;

    comp['addRow']();
    const rowId = comp['rows']()[0].id;

    const emitted: (RankContextInput[] | null)[] = [];
    comp.contextsChange.subscribe((v) => emitted.push(v));

    await comp['onBuildChange'](rowId, 'b1');
    await flush(fixture);

    const nonNull = emitted.filter((e) => e !== null);
    expect(nonNull.length).toBeGreaterThan(0);
    const contexts = nonNull.at(-1)!;
    expect(contexts).toHaveLength(1);
    expect(contexts[0]).toMatchObject({
      build_id: 'b1',
      combo_id: 'c1',
      enemy_profile_id: 'e1',
      weight: 1,
    });
  });

  it('toggleRowMainStat adds/removes a main stat key for that row', () => {
    const { fixture } = { fixture: TestBed.createComponent(PriorityBuildsPanel) };
    const comp = fixture.componentInstance;
    comp['addRow']();
    const rowId = comp['rows']()[0].id;

    comp['toggleRowMainStat'](rowId, 'atk_pct');
    expect(comp['rows']()[0].mainStats).toContain('atk_pct');

    comp['toggleRowMainStat'](rowId, 'atk_pct');
    expect(comp['rows']()[0].mainStats).not.toContain('atk_pct');
  });

  it('toggleRowRarity adds/removes a rarity for that row', () => {
    const { fixture } = { fixture: TestBed.createComponent(PriorityBuildsPanel) };
    const comp = fixture.componentInstance;
    comp['addRow']();
    const rowId = comp['rows']()[0].id;

    comp['toggleRowRarity'](rowId, 'S');
    expect(comp['rows']()[0].rarities).toContain('S');

    comp['toggleRowRarity'](rowId, 'S');
    expect(comp['rows']()[0].rarities).not.toContain('S');
  });

  it('filtersChange emits union of rows mainStats', () => {
    const { fixture } = { fixture: TestBed.createComponent(PriorityBuildsPanel) };
    const comp = fixture.componentInstance;
    comp['addRow']();
    comp['addRow']();
    const [r1, r2] = comp['rows']();

    const emitted: { mainStats: string[]; rarities: string[] }[] = [];
    comp.filtersChange.subscribe((v) => emitted.push(v));

    comp['toggleRowMainStat'](r1.id, 'atk_pct');
    comp['toggleRowMainStat'](r2.id, 'crit_rate');

    const last = emitted.at(-1)!;
    expect(last.mainStats).toContain('atk_pct');
    expect(last.mainStats).toContain('crit_rate');
  });

  it('filtersChange emits mainStats=[] if any row has no main stat filter', () => {
    const { fixture } = { fixture: TestBed.createComponent(PriorityBuildsPanel) };
    const comp = fixture.componentInstance;
    comp['addRow']();
    comp['addRow']();
    const [r1] = comp['rows']();

    const emitted: { mainStats: string[] }[] = [];
    comp.filtersChange.subscribe((v) => emitted.push(v));

    comp['toggleRowMainStat'](r1.id, 'atk_pct');

    expect(emitted.at(-1)!.mainStats).toEqual([]);
  });

  it('scoreRequested emits when requestScore is called with ready rows', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;
    comp['addRow']();
    const rowId = comp['rows']()[0].id;
    await comp['onBuildChange'](rowId, 'b1');
    await flush(fixture);

    const fired: number[] = [];
    comp.scoreRequested.subscribe(() => fired.push(1));
    comp['requestScore']();
    expect(fired).toHaveLength(1);
  });

  it('scoreRequested does not emit when rows are empty', async () => {
    const { fixture } = await setup();
    const comp = fixture.componentInstance;

    const fired: number[] = [];
    comp.scoreRequested.subscribe(() => fired.push(1));
    comp['requestScore']();
    expect(fired).toHaveLength(0);
  });

  describe('support-slot selector', () => {
    it('availableSupportSlots is always empty (support-build relationships removed)', async () => {
      const { fixture } = await setup();
      const comp = fixture.componentInstance;

      comp['addRow']();
      const rowId = comp['rows']()[0].id;
      await comp['onBuildChange'](rowId, 'b1');
      await flush(fixture);

      expect(comp['rows']()[0].availableSupportSlots).toEqual([]);
    });

    it('build with no supports has empty availableSupportSlots', async () => {
      const { fixture } = await setup();
      const comp = fixture.componentInstance;

      comp['addRow']();
      const rowId = comp['rows']()[0].id;
      // b2 has no support builds
      await comp['onBuildChange'](rowId, 'b2');
      await flush(fixture);

      expect(comp['rows']()[0].availableSupportSlots).toEqual([]);
    });

    it('onSupportSlotChange sets supportSlot and emits it in context', async () => {
      const { fixture } = await setup();
      const comp = fixture.componentInstance;

      comp['addRow']();
      const rowId = comp['rows']()[0].id;
      await comp['onBuildChange'](rowId, 'b1');
      await flush(fixture);

      const emitted: (RankContextInput[] | null)[] = [];
      comp.contextsChange.subscribe((v) => emitted.push(v));

      comp['onSupportSlotChange'](rowId, '1');

      const nonNull = emitted.filter((e) => e !== null);
      expect(nonNull.at(-1)![0].support_slot).toBe(1);
    });

    it('onSupportSlotChange with empty string sets supportSlot to null', async () => {
      const { fixture } = await setup();
      const comp = fixture.componentInstance;

      comp['addRow']();
      const rowId = comp['rows']()[0].id;
      await comp['onBuildChange'](rowId, 'b1');
      await flush(fixture);

      comp['onSupportSlotChange'](rowId, '1');
      comp['onSupportSlotChange'](rowId, '');

      expect(comp['rows']().find((r) => r.id === rowId)!.supportSlot).toBeNull();
    });

    it('context payload includes support_slot when set', async () => {
      const { fixture } = await setup();
      const comp = fixture.componentInstance;

      comp['addRow']();
      const rowId = comp['rows']()[0].id;
      await comp['onBuildChange'](rowId, 'b1');
      await flush(fixture);
      comp['onSupportSlotChange'](rowId, '1');

      const emitted: (RankContextInput[] | null)[] = [];
      comp.contextsChange.subscribe((v) => emitted.push(v));
      comp['onSupportSlotChange'](rowId, '1');

      const nonNull = emitted.filter((e) => e !== null);
      expect(nonNull.at(-1)![0]).toMatchObject({ build_id: 'b1', support_slot: 1 });
    });
  });

  describe('loadContexts()', () => {
    const CONTEXTS: import('./rank.service').RankContextInput[] = [
      { build_id: 'b1', combo_id: 'c2', enemy_profile_id: 'e1', weight: 2, allowed_set_ids: [100] },
      { build_id: 'b2', combo_id: 'c1', enemy_profile_id: 'e1', weight: 3, allowed_set_ids: null },
    ];

    const COMBOS_B2 = [{ id: 'c1', name: 'Combo X', build_id: 'b2' }];

    it('rebuilds rows from a 2-context input', async () => {
      const { fixture, combosService } = await setup();
      combosService.listForBuild
        .mockResolvedValueOnce(MOCK_COMBOS)   // b1
        .mockResolvedValueOnce(COMBOS_B2);    // b2

      await fixture.componentInstance.loadContexts(CONTEXTS);
      await flush(fixture);

      expect(fixture.componentInstance.rowCount).toBe(2);
    });

    it('calls listForBuild for each context build', async () => {
      const { fixture, combosService } = await setup();
      combosService.listForBuild
        .mockResolvedValueOnce(MOCK_COMBOS)
        .mockResolvedValueOnce(COMBOS_B2);

      await fixture.componentInstance.loadContexts(CONTEXTS);

      expect(combosService.listForBuild).toHaveBeenCalledWith('b1');
      expect(combosService.listForBuild).toHaveBeenCalledWith('b2');
    });

    it('sets comboId / enemyProfileId / weight / allowedSetIds from context', async () => {
      const { fixture, combosService } = await setup();
      combosService.listForBuild
        .mockResolvedValueOnce(MOCK_COMBOS)
        .mockResolvedValueOnce(COMBOS_B2);

      await fixture.componentInstance.loadContexts(CONTEXTS);
      await flush(fixture);

      const rows = fixture.componentInstance['rows']();
      expect(rows[0].buildId).toBe('b1');
      expect(rows[0].comboId).toBe('c2');
      expect(rows[0].enemyProfileId).toBe('e1');
      expect(rows[0].weight).toBe(2);
      expect(rows[0].allowedSetIds).toEqual([100]);

      expect(rows[1].buildId).toBe('b2');
      expect(rows[1].comboId).toBe('c1');
      expect(rows[1].weight).toBe(3);
      expect(rows[1].allowedSetIds).toBeNull();
    });

    it('populates combos on each row', async () => {
      const { fixture, combosService } = await setup();
      combosService.listForBuild
        .mockResolvedValueOnce(MOCK_COMBOS)
        .mockResolvedValueOnce(COMBOS_B2);

      await fixture.componentInstance.loadContexts(CONTEXTS);
      await flush(fixture);

      const rows = fixture.componentInstance['rows']();
      expect(rows[0].combos).toEqual(MOCK_COMBOS);
      expect(rows[1].combos).toEqual(COMBOS_B2);
    });

    it('emits the contexts after loading', async () => {
      const { fixture, combosService } = await setup();
      combosService.listForBuild
        .mockResolvedValueOnce(MOCK_COMBOS)
        .mockResolvedValueOnce(COMBOS_B2);

      const emitted: (import('./rank.service').RankContextInput[] | null)[] = [];
      fixture.componentInstance.contextsChange.subscribe((v) => emitted.push(v));

      await fixture.componentInstance.loadContexts(CONTEXTS);
      await flush(fixture);

      const nonNull = emitted.filter((e) => e !== null);
      expect(nonNull.length).toBeGreaterThan(0);
      const last = nonNull.at(-1)!;
      expect(last).toHaveLength(2);
      expect(last[0]).toMatchObject({ build_id: 'b1', combo_id: 'c2', weight: 2 });
      expect(last[1]).toMatchObject({ build_id: 'b2', combo_id: 'c1', weight: 3 });
    });

    it('replaces existing rows when called again', async () => {
      const { fixture, combosService } = await setup();
      combosService.listForBuild.mockResolvedValue(MOCK_COMBOS);

      // Load 2 contexts, then reload with 1.
      await fixture.componentInstance.loadContexts(CONTEXTS);
      await flush(fixture);
      expect(fixture.componentInstance.rowCount).toBe(2);

      await fixture.componentInstance.loadContexts([CONTEXTS[0]]);
      await flush(fixture);
      expect(fixture.componentInstance.rowCount).toBe(1);
    });

    it('restores supportSlot from context on load (availableSupportSlots always empty)', async () => {
      const { fixture, combosService } = await setup();
      combosService.listForBuild.mockResolvedValue(MOCK_COMBOS);

      const ctx: RankContextInput = {
        build_id: 'b1', combo_id: 'c1', enemy_profile_id: 'e1',
        weight: 1, allowed_set_ids: null, support_slot: 1,
      };
      await fixture.componentInstance.loadContexts([ctx]);
      await flush(fixture);

      const row = fixture.componentInstance['rows']()[0];
      expect(row.availableSupportSlots).toEqual([]);
      expect(row.supportSlot).toBe(1);
    });

    it('availableSupportSlots is empty when build has no support builds', async () => {
      // b2 has no support builds.
      const { fixture, combosService } = await setup();
      combosService.listForBuild.mockResolvedValue(MOCK_COMBOS);

      const ctx: RankContextInput = {
        build_id: 'b2', combo_id: 'c1', enemy_profile_id: 'e1',
        weight: 1, allowed_set_ids: null, support_slot: null,
      };
      await fixture.componentInstance.loadContexts([ctx]);
      await flush(fixture);

      expect(fixture.componentInstance['rows']()[0].availableSupportSlots).toEqual([]);
    });
  });

  describe('enemy picker tabs (#55)', () => {
    it('addRow() defaults a new row to the first rarity-4 enemy, not enemies[0]', async () => {
      const { fixture } = await setup({ enemies: ENEMIES_MIXED });
      const comp = fixture.componentInstance;
      comp['addRow']();
      expect(comp['rows']()[0].enemyProfileId).toBe('e-boss-1');
    });

    it('filteredEnemies() lists only rarity-4 profiles under the default tab', async () => {
      const { fixture } = await setup({ enemies: ENEMIES_MIXED });
      const comp = fixture.componentInstance;
      expect(comp['filteredEnemies']().map((e: { id: string }) => e.id))
        .toEqual(['e-boss-1', 'e-boss-2']);
    });

    it('"All Enemies" tab surfaces the trash mob for every row', async () => {
      const { fixture } = await setup({ enemies: ENEMIES_MIXED });
      const comp = fixture.componentInstance;
      comp['onEnemyTabChange']('all');
      expect(comp['filteredEnemies']().map((e: { id: string }) => e.id)).toContain('e-trash');
    });

    it('switching tabs re-defaults any row whose enemy gets filtered out', async () => {
      const { fixture } = await setup({ enemies: ENEMIES_MIXED });
      const comp = fixture.componentInstance;
      comp['addRow']();
      comp['onEnemyTabChange']('all');
      comp['onEnemyChange'](comp['rows']()[0].id, 'e-trash');
      expect(comp['rows']()[0].enemyProfileId).toBe('e-trash');

      comp['onEnemyTabChange']('bosses');
      expect(comp['rows']()[0].enemyProfileId).toBe('e-boss-1');
    });

    it('a row whose enemy is still visible under the new tab is left untouched', async () => {
      const { fixture } = await setup({ enemies: ENEMIES_MIXED });
      const comp = fixture.componentInstance;
      comp['addRow']();
      comp['onEnemyChange'](comp['rows']()[0].id, 'e-boss-2');
      comp['onEnemyTabChange']('all');
      expect(comp['rows']()[0].enemyProfileId).toBe('e-boss-2');
    });
  });
});
