import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { BuffContextStore } from '../buff-context.store';
import { BuffPresetsService } from '../buff-presets.service';
import { StageBuffsPanelComponent } from './stage-buffs-panel';

const STAGE_BUFF = {
  label: 'DA Stage 3: Ice DMG',
  stat: 'ice_dmg',
  value: 2500,
  target: 'team' as const,
  conditions: ['always'],
  scopes: ['all'],
  max_stacks: 1,
};

function setup(presets: { id: string; name: string; buffs: (typeof STAGE_BUFF)[] }[] = []) {
  const svc = {
    // The picker is served, never hardcoded — `atk` is absent because the resolver
    // never reads it (Task B2), and the component must not invent it.
    statOptions: vi.fn(async () => ['ice_dmg', 'crit_rate', 'flat_atk']),
    list: vi.fn(async () => presets),
    create: vi.fn(async (name: string, buffs: unknown[]) => ({
      id: 'new-preset',
      name,
      buffs,
      created_at: '2026-08-17T00:00:00Z',
      updated_at: '2026-08-17T00:00:00Z',
    })),
    update: vi.fn(async (id: string, patch: { buffs?: unknown[] }) => ({
      id,
      name: 'Updated',
      buffs: patch.buffs ?? [],
      created_at: '2026-08-17T00:00:00Z',
      updated_at: '2026-08-17T00:00:00Z',
    })),
    remove: vi.fn(async () => undefined),
  };

  TestBed.configureTestingModule({
    imports: [StageBuffsPanelComponent],
    providers: [{ provide: BuffPresetsService, useValue: svc }],
  });

  const f = TestBed.createComponent(StageBuffsPanelComponent);
  const store = TestBed.inject(BuffContextStore);
  store.reset();
  return { svc, f, store };
}

async function settle(fixture: ReturnType<typeof TestBed.createComponent>) {
  fixture.detectChanges();
  for (let i = 0; i < 4; i++) await Promise.resolve();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
}

interface Panel {
  addBuff: () => void;
  removeBuff: (i: number) => void;
  setLabel: (row: { index: number; buff: typeof STAGE_BUFF; id: string; enabled: boolean }, label: string) => void;
  setValue: (row: { index: number; buff: typeof STAGE_BUFF; isPercent: boolean }, v: number) => void;
  toggleEnabled: (row: { id: string }, enabled: boolean) => void;
  applyPreset: () => Promise<void>;
  saveAsPreset: () => Promise<void>;
  selectedPresetId: { set: (v: string) => void };
  newPresetName: { set: (v: string) => void };
  statOptions: () => { stat: string; label: string }[];
  rows: () => {
    index: number;
    buff: typeof STAGE_BUFF;
    id: string;
    statLabel: string;
    inputValue: number;
    isPercent: boolean;
    contribution: string;
    enabled: boolean;
    problem: string | null;
  }[];
  hasProblems: () => boolean;
}

describe('StageBuffsPanelComponent — the editor (Task B8)', () => {
  it('offers only the served stats, labelled with their in-game names', async () => {
    const { f, svc } = setup();
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    expect(svc.statOptions).toHaveBeenCalled();
    expect(panel.statOptions().map((o) => o.stat).sort()).toEqual([
      'crit_rate',
      'flat_atk',
      'ice_dmg',
    ]);
    // In-game names, not field keys (the #62 rule).
    expect(panel.statOptions().map((o) => o.label)).toContain('Ice DMG %');
    expect(panel.statOptions().map((o) => o.label)).not.toContain('ice_dmg');
  });

  it('shows the resolved contribution for each buff', async () => {
    const { f, store } = setup();
    store.addCustomBuff(STAGE_BUFF);
    await settle(f);

    const [row] = (f.componentInstance as unknown as Panel).rows();
    expect(row.statLabel).toBe('Ice DMG %');
    expect(row.contribution).toBe('+25.00%');
    expect(row.id).toBe('custom:da_stage_3_ice_dmg');
  });

  it('edits percentages in display units and stores basis points', async () => {
    const { f, store } = setup();
    store.addCustomBuff(STAGE_BUFF);
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    expect(panel.rows()[0].inputValue).toBe(25);
    panel.setValue(panel.rows()[0], 30);
    expect(store.customBuffs()[0].value).toBe(3000);
  });

  it('edits flat stats in raw units', async () => {
    const { f, store } = setup();
    store.addCustomBuff({ ...STAGE_BUFF, stat: 'flat_atk', value: 500 });
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    expect(panel.rows()[0].inputValue).toBe(500);
    expect(panel.rows()[0].isPercent).toBe(false);
  });

  it('flags a label the server would reject rather than letting it 422 on submit', async () => {
    const { f, store } = setup();
    store.addCustomBuff({ ...STAGE_BUFF, label: '!!!' });
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    expect(panel.rows()[0].problem).toMatch(/letter or digit/);
    expect(panel.hasProblems()).toBe(true);
  });

  it('flags two buffs whose labels resolve to one id', async () => {
    const { f, store } = setup();
    store.setCustomBuffs([STAGE_BUFF, { ...STAGE_BUFF, label: 'da stage 3 — ice dmg' }]);
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    expect(panel.rows()[0].problem).toBeNull();
    expect(panel.rows()[1].problem).toMatch(/distinguishable/);
  });

  it('toggling a row off writes the custom: id into disabled_buffs', async () => {
    const { f, store } = setup();
    store.addCustomBuff(STAGE_BUFF);
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    panel.toggleEnabled(panel.rows()[0], false);
    expect(store.disabledBuffs()).toEqual(['custom:da_stage_3_ice_dmg']);
  });

  it('renaming a switched-off buff keeps it switched off under its new id', async () => {
    // The id is derived from the label, so a rename would otherwise silently
    // re-enable the buff — a toggle that comes undone on an unrelated edit.
    const { f, store } = setup();
    store.addCustomBuff(STAGE_BUFF);
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    panel.toggleEnabled(panel.rows()[0], false);
    panel.setLabel(panel.rows()[0], 'DA Stage 4: Ice DMG');

    expect(store.disabledBuffs()).toEqual(['custom:da_stage_4_ice_dmg']);
    expect(panel.rows()[0].enabled).toBe(false);
  });

  it('a new row is born addressable, so adding one cannot 422 the next calculation', () => {
    // The label IS the id, and the server rejects one that slugifies to nothing — an
    // empty new row would break every calculation until the user named it.
    const { f, store } = setup();
    const panel = f.componentInstance as unknown as Panel;
    panel.addBuff();
    panel.addBuff();

    expect(store.customBuffs().map((b) => b.label)).toEqual(['Stage buff 1', 'Stage buff 2']);
    expect(panel.rows().every((r) => r.problem === null)).toBe(true);
  });

  it('skips a placeholder whose SLUG is taken, not just its exact label', () => {
    // The server rejects duplicates by slug, so "stage buff 2" already owns the id
    // "Stage buff 2" would take — exact-label matching would hand out a name that 422s
    // the next calculation.
    const { f, store } = setup();
    store.setCustomBuffs([{ ...STAGE_BUFF, label: 'stage buff 2' }]);
    const panel = f.componentInstance as unknown as Panel;
    panel.addBuff();

    expect(store.customBuffs().map((b) => b.label)).toEqual(['stage buff 2', 'Stage buff 3']);
    expect(panel.hasProblems()).toBe(false);
  });

  it('skips a placeholder name already taken rather than colliding with it', () => {
    const { f, store } = setup();
    store.setCustomBuffs([{ ...STAGE_BUFF, label: 'Stage buff 2' }]);
    const panel = f.componentInstance as unknown as Panel;
    panel.addBuff();

    expect(store.customBuffs().map((b) => b.label)).toEqual(['Stage buff 2', 'Stage buff 3']);
    expect(panel.hasProblems()).toBe(false);
  });

  it('removing a row drops it from the run', async () => {
    const { f, store } = setup();
    store.addCustomBuff(STAGE_BUFF);
    await settle(f);

    (f.componentInstance as unknown as Panel).removeBuff(0);
    expect(store.customBuffs()).toEqual([]);
  });
});

describe('StageBuffsPanelComponent — presets (Task B9)', () => {
  it('applying a preset copies its buffs into the run', async () => {
    const { f, store } = setup([{ id: 'p1', name: 'DA 2.1 Stage 3', buffs: [STAGE_BUFF] }]);
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    panel.selectedPresetId.set('p1');
    await panel.applyPreset();

    expect(store.customBuffs()).toEqual([STAGE_BUFF]);
  });

  it('the copy is not a live reference — mutating the preset row changes nothing', async () => {
    // DESIGN §2.4. If this were a reference, editing a preset would retroactively
    // change results the user already calculated with it.
    const presetBuffs = [{ ...STAGE_BUFF }];
    const { f, store } = setup([{ id: 'p1', name: 'DA 2.1 Stage 3', buffs: presetBuffs }]);
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    panel.selectedPresetId.set('p1');
    await panel.applyPreset();
    presetBuffs[0].value = 9999;

    expect(store.customBuffs()[0].value).toBe(2500);
  });

  it('saving sends the run’s current buffs under the given name', async () => {
    const { f, store, svc } = setup();
    store.addCustomBuff(STAGE_BUFF);
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    panel.newPresetName.set('DA 2.1 Stage 3');
    await panel.saveAsPreset();

    expect(svc.create).toHaveBeenCalledWith('DA 2.1 Stage 3', [STAGE_BUFF]);
  });

  it('refuses to save an unnamed preset instead of creating an untitled row', async () => {
    const { f, svc } = setup();
    await settle(f);

    const panel = f.componentInstance as unknown as Panel;
    panel.newPresetName.set('   ');
    await panel.saveAsPreset();

    expect(svc.create).not.toHaveBeenCalled();
  });
});
