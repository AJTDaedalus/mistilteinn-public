import { describe, expect, it } from 'vitest';

import { BuffContextStore, buffContextForBuilds } from './buff-context.store';

describe('BuffContextStore', () => {
  it('defaults to the server defaults', () => {
    const store = new BuffContextStore();
    expect(store.context()).toEqual({
      active_conditions: ['always'],
      stack_counts: {},
      disabled_buffs: [],
      custom_buffs: [],
    });
  });

  describe('seed()', () => {
    it('populates the three signals from the given context', () => {
      const store = new BuffContextStore();
      store.seed({
        active_conditions: ['always', 'hp_above_50'],
        stack_counts: { 'agent:stack': 3 },
        disabled_buffs: ['1:core_a'],
      });

      expect(store.activeConditions()).toEqual(['always', 'hp_above_50']);
      expect(store.stackCounts()).toEqual({ 'agent:stack': 3 });
      expect(store.disabledBuffs()).toEqual(['1:core_a']);
    });

    it('does not call any API -- pure in-memory seed', () => {
      // No fetch mock is installed; if seed() ever performs a network call,
      // the test environment's real (unmocked) fetch would throw.
      const store = new BuffContextStore();
      expect(() =>
        store.seed({
          active_conditions: ['always'],
          stack_counts: {},
          disabled_buffs: ['1:core_a'],
        }),
      ).not.toThrow();
    });

    it('re-seeding replaces the previous context entirely', () => {
      const store = new BuffContextStore();
      store.seed({
        active_conditions: ['always', 'hp_above_50'],
        stack_counts: { a: 1 },
        disabled_buffs: ['x'],
      });

      store.seed({ active_conditions: ['always'], stack_counts: {}, disabled_buffs: [] });

      expect(store.context()).toEqual({
        active_conditions: ['always'],
        stack_counts: {},
        disabled_buffs: [],
        custom_buffs: [],
      });
    });
  });

  it('reset() restores the server defaults after edits', () => {
    const store = new BuffContextStore();
    store.seed({
      active_conditions: ['always', 'hp_above_50'],
      stack_counts: { a: 2 },
      disabled_buffs: ['x'],
    });

    store.reset();

    expect(store.context()).toEqual({
      active_conditions: ['always'],
      stack_counts: {},
      disabled_buffs: [],
      custom_buffs: [],
    });
  });

  describe('toggleCondition()', () => {
    it('adds a condition not currently active', () => {
      const store = new BuffContextStore();
      store.toggleCondition('hp_above_50');
      expect(store.activeConditions()).toContain('hp_above_50');
    });

    it('removes a condition currently active', () => {
      const store = new BuffContextStore();
      store.setActiveConditions(['always', 'hp_above_50']);
      store.toggleCondition('hp_above_50');
      expect(store.activeConditions()).toEqual(['always']);
    });
  });

  describe('setStack()', () => {
    it('sets a partial stack override', () => {
      const store = new BuffContextStore();
      store.setStack('agent:stack', 2, 4);
      expect(store.stackCounts()).toEqual({ 'agent:stack': 2 });
    });

    it('drops the override when clamped to maxStacks (fully stacked = default)', () => {
      const store = new BuffContextStore();
      store.setStack('agent:stack', 2, 4);
      store.setStack('agent:stack', 4, 4);
      expect(store.stackCounts()).toEqual({});
    });

    it('clamps below zero to zero', () => {
      const store = new BuffContextStore();
      store.setStack('agent:stack', -5, 4);
      expect(store.stackCounts()).toEqual({ 'agent:stack': 0 });
    });

    it('clamps above maxStacks down to maxStacks (dropping the override)', () => {
      const store = new BuffContextStore();
      store.setStack('agent:stack', 99, 4);
      expect(store.stackCounts()).toEqual({});
    });
  });

  describe('toggleBuff()', () => {
    it('disables an enabled buff', () => {
      const store = new BuffContextStore();
      store.toggleBuff('1:core_a', false);
      expect(store.disabledBuffs()).toEqual(['1:core_a']);
    });

    it('re-enables a disabled buff', () => {
      const store = new BuffContextStore();
      store.setDisabledBuffs(['1:core_a', '2:core_b']);
      store.toggleBuff('1:core_a', true);
      expect(store.disabledBuffs()).toEqual(['2:core_b']);
    });
  });

  it('context() reflects live edits without re-seeding', () => {
    const store = new BuffContextStore();
    store.toggleCondition('hp_above_50');
    store.setStack('agent:stack', 3, 4);
    store.toggleBuff('1:core_a', false);

    expect(store.context()).toEqual({
      active_conditions: ['always', 'hp_above_50'],
      stack_counts: { 'agent:stack': 3 },
      disabled_buffs: ['1:core_a'],
      custom_buffs: [],
    });
  });
});

describe('BuffContextStore.seedFromBuilds()', () => {
  const dps = {
    id: 'b1',
    active_conditions: ['always', 'hp_above_50'],
    stack_counts: { 'agent:stack': 2 },
    disabled_buffs: ['1:core_a'],
  };
  const support = {
    id: 'b2',
    active_conditions: ['enemy_stunned'],
    stack_counts: { 'other:stack': 1 },
    disabled_buffs: ['2:core_b'],
  };

  it('takes conditions and stacks from the head build only', () => {
    const store = new BuffContextStore();
    store.seedFromBuilds([dps, support]);

    expect(store.activeConditions()).toEqual(['always', 'hp_above_50']);
    expect(store.stackCounts()).toEqual({ 'agent:stack': 2 });
  });

  it('merges disabled_buffs across every team member', () => {
    const store = new BuffContextStore();
    store.seedFromBuilds([dps, support]);

    expect(store.disabledBuffs().sort()).toEqual(['1:core_a', '2:core_b']);
  });

  it('de-duplicates a buff id shared by two members', () => {
    const store = new BuffContextStore();
    store.seedFromBuilds([dps, { ...support, disabled_buffs: ['1:core_a'] }]);

    expect(store.disabledBuffs()).toEqual(['1:core_a']);
  });

  it('tolerates null columns', () => {
    const store = new BuffContextStore();
    store.seedFromBuilds([
      { id: 'b1', active_conditions: null, stack_counts: null, disabled_buffs: null },
    ]);

    expect(store.context()).toEqual({
      active_conditions: [],
      stack_counts: {},
      disabled_buffs: [],
      custom_buffs: [],
    });
  });

  it('is a no-op for an empty list', () => {
    const store = new BuffContextStore();
    store.setActiveConditions(['always', 'hp_above_50']);
    store.seedFromBuilds([]);

    expect(store.activeConditions()).toEqual(['always', 'hp_above_50']);
  });

  it('does not clobber this run edits when the same target is re-seeded', () => {
    const store = new BuffContextStore();
    store.seedFromBuilds([dps]);
    store.toggleCondition('enemy_stunned');

    store.seedFromBuilds([dps]);

    expect(store.activeConditions()).toEqual(['always', 'hp_above_50', 'enemy_stunned']);
  });

  it('reseeds when the target builds change, so build A does not leak into build B', () => {
    const store = new BuffContextStore();
    store.seedFromBuilds([dps]);
    store.seedFromBuilds([support]);

    expect(store.activeConditions()).toEqual(['enemy_stunned']);
    expect(store.stackCounts()).toEqual({ 'other:stack': 1 });
    expect(store.disabledBuffs()).toEqual(['2:core_b']);
  });

  it('lets a later target seed over an explicit seed() from the defaults editor', () => {
    const store = new BuffContextStore();
    store.seedFromBuilds([dps]);
    // buff-toggles.ts seeds directly when its panel loads a different build.
    store.seed({ active_conditions: ['always'], stack_counts: {}, disabled_buffs: [] });

    store.seedFromBuilds([dps]);

    expect(store.activeConditions()).toEqual(['always', 'hp_above_50']);
  });

  it('context() hands out copies, so a mutated request body cannot reach back in', () => {
    const store = new BuffContextStore();
    store.seedFromBuilds([dps]);

    const body = store.context();
    body.active_conditions.push('mutated');
    body.stack_counts['injected'] = 9;
    body.disabled_buffs.push('9:nope');

    expect(store.context()).toEqual({
      active_conditions: ['always', 'hp_above_50'],
      stack_counts: { 'agent:stack': 2 },
      disabled_buffs: ['1:core_a'],
      custom_buffs: [],
    });
  });
});

// The derivation `seedFromBuilds` delegates to, exercised directly because
// rank calls it N times per submit without going through the store
// (DESIGN_buff_context.md §2.5, #95) — the store's idempotent-per-target guard
// is correct for a single-target page and wrong for N contexts in one job.
describe('buffContextForBuilds', () => {
  const dps = {
    id: 'b1',
    active_conditions: ['always', 'hp_above_50'],
    stack_counts: { 'agent:stack': 2 },
    disabled_buffs: ['1:core_a'],
  };
  const support = {
    id: 'b2',
    active_conditions: ['enemy_stunned'],
    stack_counts: { 'other:stack': 1 },
    disabled_buffs: ['2:core_b'],
  };

  it('takes conditions and stacks from the head build only', () => {
    const ctx = buffContextForBuilds([dps, support]);
    expect(ctx.active_conditions).toEqual(['always', 'hp_above_50']);
    expect(ctx.stack_counts).toEqual({ 'agent:stack': 2 });
  });

  it('unions disabled_buffs across every member, de-duplicated', () => {
    expect(buffContextForBuilds([dps, support]).disabled_buffs.sort()).toEqual([
      '1:core_a',
      '2:core_b',
    ]);
    expect(
      buffContextForBuilds([dps, { ...support, disabled_buffs: ['1:core_a'] }]).disabled_buffs,
    ).toEqual(['1:core_a']);
  });

  it('degenerates to the single build for a build-only context', () => {
    expect(buffContextForBuilds([dps])).toEqual({
      active_conditions: ['always', 'hp_above_50'],
      stack_counts: { 'agent:stack': 2 },
      disabled_buffs: ['1:core_a'],
    });
  });

  it('returns the server defaults for an empty list', () => {
    expect(buffContextForBuilds([])).toEqual({
      active_conditions: ['always'],
      stack_counts: {},
      disabled_buffs: [],
    });
  });

  it('never carries custom_buffs — a build cannot seed or clear a stage buff', () => {
    // #64: rank's per-context producers spread this straight into a request context
    // (DESIGN §2.5). A `custom_buffs: []` in that spread would strip the stage buffs
    // from every ranked context, silently, so the derivation must not have the key at
    // all rather than have it empty.
    expect(buffContextForBuilds([dps])).not.toHaveProperty('custom_buffs');
    expect(buffContextForBuilds([])).not.toHaveProperty('custom_buffs');
  });

  it('tolerates null columns', () => {
    expect(
      buffContextForBuilds([
        { id: 'b1', active_conditions: null, stack_counts: null, disabled_buffs: null },
      ]),
    ).toEqual({ active_conditions: [], stack_counts: {}, disabled_buffs: [] });
  });

  it('copies rather than aliasing the build rows', () => {
    const ctx = buffContextForBuilds([dps]);
    ctx.active_conditions.push('mutated');
    ctx.stack_counts['agent:stack'] = 99;
    ctx.disabled_buffs.push('mutated');

    expect(dps.active_conditions).toEqual(['always', 'hp_above_50']);
    expect(dps.stack_counts).toEqual({ 'agent:stack': 2 });
    expect(dps.disabled_buffs).toEqual(['1:core_a']);
  });

  it('gives each call its own arrays, so N contexts cannot share state', () => {
    const a = buffContextForBuilds([dps]);
    const b = buffContextForBuilds([dps]);
    a.disabled_buffs.push('only-in-a');

    expect(b.disabled_buffs).toEqual(['1:core_a']);
  });
});

describe('BuffContextStore — stage buffs (#64)', () => {
  const iceDmg = {
    label: 'DA Stage 3: Ice DMG',
    stat: 'ice_dmg',
    value: 2500,
    target: 'team' as const,
    conditions: ['always'],
    scopes: ['all'],
    max_stacks: 1,
  };

  it('carries custom_buffs into the serialized context', () => {
    const store = new BuffContextStore();
    store.addCustomBuff(iceDmg);
    expect(store.context().custom_buffs).toEqual([iceDmg]);
  });

  it('hands out copies, so a request body cannot mutate the store', () => {
    const store = new BuffContextStore();
    store.addCustomBuff(iceDmg);
    const body = store.context();
    body.custom_buffs[0].value = 9999;
    expect(store.customBuffs()[0].value).toBe(2500);
  });

  it('setCustomBuffs replaces the list — what applying a preset does', () => {
    const store = new BuffContextStore();
    store.addCustomBuff(iceDmg);
    store.setCustomBuffs([{ ...iceDmg, label: 'Shiyu Node 2', stat: 'fire_dmg' }]);
    expect(store.customBuffs().map((b) => b.label)).toEqual(['Shiyu Node 2']);
  });

  it('copies on apply, so editing the source list afterwards changes nothing', () => {
    // DESIGN §2.4: applying a preset is a copy, not a live reference.
    const store = new BuffContextStore();
    const presetBuffs = [{ ...iceDmg }];
    store.setCustomBuffs(presetBuffs);
    presetBuffs[0].value = 9999;
    expect(store.customBuffs()[0].value).toBe(2500);
  });

  it('updateCustomBuff replaces one row and ignores out-of-range indices', () => {
    const store = new BuffContextStore();
    store.addCustomBuff(iceDmg);
    store.updateCustomBuff(0, { ...iceDmg, value: 3000 });
    store.updateCustomBuff(7, { ...iceDmg, value: 1 });
    expect(store.customBuffs()).toEqual([{ ...iceDmg, value: 3000 }]);
  });

  it('removing a buff also drops its disabled_buffs entry', () => {
    // Otherwise the id lingers invisibly and a later buff with the same label
    // arrives switched off for no reason the user can see.
    const store = new BuffContextStore();
    store.addCustomBuff(iceDmg);
    store.toggleBuff('custom:da_stage_3_ice_dmg', false);
    store.removeCustomBuff(0);
    expect(store.disabledBuffs()).toEqual([]);
  });

  it('seeding from a build leaves stage buffs alone', () => {
    // A stage buff belongs to the encounter, not to a build — switching build or
    // navigating must not silently clear the encounter being evaluated.
    const store = new BuffContextStore();
    store.addCustomBuff(iceDmg);
    store.seed({ active_conditions: ['always'], stack_counts: {}, disabled_buffs: [] });
    expect(store.customBuffs()).toEqual([iceDmg]);
  });

  it('reset() does clear them — the one explicit way out', () => {
    const store = new BuffContextStore();
    store.addCustomBuff(iceDmg);
    store.reset();
    expect(store.customBuffs()).toEqual([]);
  });
});

describe('BuffContextStore — a stage-buff toggle survives seeding (#64)', () => {
  const buff = {
    label: 'DA Stage 3',
    stat: 'ice_dmg',
    value: 2500,
    target: 'team' as const,
    conditions: ['always'],
    scopes: ['all'],
    max_stacks: 1,
  };

  it('keeps custom: entries when a build seeds disabled_buffs over them', () => {
    // Stage buffs are exempt from seeding, so the buff itself survives a build change.
    // If its off-switch did not, the next run would silently apply it.
    const store = new BuffContextStore();
    store.addCustomBuff(buff);
    store.toggleBuff('custom:da_stage_3', false);

    store.seed({
      active_conditions: ['always'],
      stack_counts: {},
      disabled_buffs: ['1:core_a'],
    });

    expect(store.disabledBuffs()).toContain('custom:da_stage_3');
    expect(store.disabledBuffs()).toContain('1:core_a');
  });

  it('keeps them when the Builds page rewrites the kit toggles', () => {
    // buff-toggles.ts recomputes the whole list from kit-buff groups, which can never
    // contain a custom: id — so a plain replace erased every stage-buff toggle whenever
    // the user flipped an unrelated kit buff.
    const store = new BuffContextStore();
    store.addCustomBuff(buff);
    store.toggleBuff('custom:da_stage_3', false);

    store.setDisabledBuffs(['1:core_a', '2:core_b']);

    expect(store.disabledBuffs().sort()).toEqual(['1:core_a', '2:core_b', 'custom:da_stage_3']);
  });

  it('drops a kit toggle that the new list omits — the kit half still replaces', () => {
    const store = new BuffContextStore();
    store.setDisabledBuffs(['1:core_a']);
    store.setDisabledBuffs(['2:core_b']);

    expect(store.disabledBuffs()).toEqual(['2:core_b']);
  });

  it('reset() drops the custom: toggles too, since it drops the buffs', () => {
    const store = new BuffContextStore();
    store.addCustomBuff(buff);
    store.toggleBuff('custom:da_stage_3', false);

    store.reset();

    expect(store.disabledBuffs()).toEqual([]);
    expect(store.customBuffs()).toEqual([]);
  });
});

describe('BuffContextStore — a stale stage-buff toggle cannot outlive its buff (#64)', () => {
  const buff = {
    label: 'DA Stage 3',
    stat: 'ice_dmg',
    value: 2500,
    target: 'team' as const,
    conditions: ['always'],
    scopes: ['all'],
    max_stacks: 1,
  };

  function offSwitched(): BuffContextStore {
    const store = new BuffContextStore();
    store.addCustomBuff(buff);
    store.toggleBuff('custom:da_stage_3', false);
    return store;
  }

  it('clearing the list drops the off-switch with it', () => {
    // Otherwise applying a preset containing a buff of the same name later would copy
    // it in already switched off, with nothing on screen explaining why.
    const store = offSwitched();
    store.setCustomBuffs([]);
    expect(store.disabledBuffs()).toEqual([]);
  });

  it('applying a preset that omits the buff drops its off-switch', () => {
    const store = offSwitched();
    store.setCustomBuffs([{ ...buff, label: 'Shiyu Node 2' }]);
    expect(store.disabledBuffs()).toEqual([]);
  });

  it('applying a preset that still contains it keeps the off-switch', () => {
    const store = offSwitched();
    store.setCustomBuffs([buff, { ...buff, label: 'Shiyu Node 2' }]);
    expect(store.disabledBuffs()).toEqual(['custom:da_stage_3']);
  });

  it('renaming a buff does not leave its old id behind', () => {
    const store = offSwitched();
    store.updateCustomBuff(0, { ...buff, label: 'DA Stage 4' });
    expect(store.disabledBuffs()).not.toContain('custom:da_stage_3');
  });

  it('leaves kit ids alone — they name buffs on builds this store knows nothing about', () => {
    const store = offSwitched();
    store.toggleBuff('1:core_a', false);
    store.setCustomBuffs([]);
    expect(store.disabledBuffs()).toEqual(['1:core_a']);
  });
});
