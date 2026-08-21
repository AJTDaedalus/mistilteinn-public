import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { RankContextBar } from './rank-context-bar';
import { TeamsService } from '../teams/teams.service';
import { BuildsService } from '../builds/builds.service';
import { CombosService } from '../builds/combos.service';
import { CalculateService } from '../calculate/calculate.service';
import { DiscSetsService } from '../optimize/disc-sets.service';
import { API_BASE_URL } from '../../api/api.client';

const TEAMS = [
  {
    id: 't1', name: 'Team Alpha',
    build1_id: 'b1', build2_id: 'b2', build3_id: null,
    build1: null, build2: null, build3: null,
  },
  {
    id: 't2', name: 'Team Beta',
    build1_id: 'b3', build2_id: null, build3_id: null,
    build1: null, build2: null, build3: null,
  },
];

const COMBOS_T1 = [
  { id: 'c1', name: 'Combo A', team_id: 't1', sequence: [], description: '' },
  { id: 'c2', name: 'Combo B', team_id: 't1', sequence: [], description: '' },
];

const COMBOS_T2 = [
  { id: 'c3', name: 'Combo C', team_id: 't2', sequence: [], description: '' },
];

const ENEMIES = [
  { id: 'e1', name: 'Dummy', level: 60, defense: 953, rarity: 4 },
  { id: 'e2', name: 'Elite', level: 70, defense: 1200, rarity: 4 },
];

const ENEMIES_MIXED = [
  { id: 'e-trash', name: 'Notorious Assaulter', level: 60, defense: 60, rarity: 1 },
  { id: 'e-boss-1', name: 'Dead End Butcher', level: 60, defense: 60, rarity: 4,
    stun_dmg_taken_ratio: 5000 },
  { id: 'e-boss-2', name: 'Girtablullu - Stagnant Aberrant', level: 60, defense: 60,
    rarity: 4, stun_dmg_taken_ratio: 2500 },
];

const DISC_SETS = [
  { id: 'set-uuid-1', hakushin_id: 31100, name: 'Chaotic Metal', two_piece_text: '', four_piece_text: '', icon_path: '' },
  { id: 'set-uuid-2', hakushin_id: 31200, name: 'Branch & Blade Song', two_piece_text: '', four_piece_text: '', icon_path: '' },
  { id: 'set-uuid-3', hakushin_id: 31300, name: 'Fanged Metal', two_piece_text: '', four_piece_text: '', icon_path: '' },
];

function makeTeamsService() {
  return {
    list: vi.fn().mockResolvedValue(TEAMS),
  };
}

// Buff columns are the per-build *defaults* the client seeds from
// (DESIGN_buff_context.md §2.2/§2.5) — deliberately distinct per build so a
// seeding test can tell which one the bar actually read.
const BUILDS = [
  {
    id: 'b1', agent_id: 'a1', agent_specialty: 'attack',
    active_conditions: ['always', 'hp_above_50'],
    stack_counts: { 'b1:stack': 2 },
    disabled_buffs: ['1:core_a'],
  },
  {
    id: 'b2', agent_id: 'a2', agent_specialty: 'support',
    active_conditions: ['always', 'enemy_stunned'],
    stack_counts: { 'b2:stack': 3 },
    disabled_buffs: ['2:core_b'],
  },
  {
    id: 'b3', agent_id: 'a3', agent_specialty: 'stun',
    active_conditions: ['always'],
    stack_counts: {},
    disabled_buffs: [],
  },
];
const AGENTS = [
  { id: 'a1', name: 'Caesar' },
  { id: 'a2', name: 'Burnice' },
  { id: 'a3', name: 'Koleda' },
];

function makeBuildsService() {
  return {
    list: vi.fn().mockResolvedValue(BUILDS),
    listAgents: vi.fn().mockResolvedValue(AGENTS),
  };
}

function makeCombosService() {
  return {
    listForTeam: vi.fn().mockImplementation((teamId: string) =>
      Promise.resolve(teamId === 't1' ? COMBOS_T1 : COMBOS_T2),
    ),
  };
}

function makeCalcService(enemies: unknown[] = ENEMIES) {
  return { listEnemies: vi.fn().mockResolvedValue(enemies) };
}

function makeDiscSetsService() {
  return { listSets: vi.fn().mockResolvedValue(DISC_SETS) };
}

async function flush(fixture: ReturnType<typeof TestBed.createComponent>) {
  await fixture.whenStable();
  await new Promise((r) => setTimeout(r, 0));
  fixture.detectChanges();
}

async function setup(enemies: unknown[] = ENEMIES) {
  TestBed.configureTestingModule({
    providers: [
      { provide: API_BASE_URL, useValue: 'http://test' },
      { provide: TeamsService, useValue: makeTeamsService() },
      { provide: BuildsService, useValue: makeBuildsService() },
      { provide: CombosService, useValue: makeCombosService() },
      { provide: CalculateService, useValue: makeCalcService(enemies) },
      { provide: DiscSetsService, useValue: makeDiscSetsService() },
    ],
  });
  const fixture = TestBed.createComponent(RankContextBar);
  fixture.detectChanges();
  await flush(fixture);
  return fixture;
}

describe('RankContextBar', () => {
  it('loads teams and enemies on init', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;
    expect(comp['teams']().length).toBe(2);
    expect(comp['enemies']().length).toBe(2);
  });

  it('loads disc sets on init', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;
    expect(comp['allSets']().length).toBe(3);
  });

  it('auto-selects first enemy after init', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;
    expect(comp['selectedEnemyId']()).toBe('e1');
  });

  it('loads combos for selected team and auto-selects first', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);

    expect(comp['combos']().length).toBe(2);
    expect(comp['selectedComboId']()).toBe('c1');
  });

  it('refreshes combos when team changes', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);
    expect(comp['combos']().map((c) => c.id)).toEqual(['c1', 'c2']);

    await comp['onTeamChange']('t2');
    await flush(fixture);
    expect(comp['combos']().map((c) => c.id)).toEqual(['c3']);
    expect(comp['selectedComboId']()).toBe('c3');
  });

  it('resets combo and active_index when team changes', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);
    comp['onComboChange']('c2');
    comp['onMemberChange'](1);

    await comp['onTeamChange']('t2');
    await flush(fixture);
    expect(comp['selectedComboId']()).toBe('c3');
    expect(comp['selectedActiveIndex']()).toBe(0);
  });

  it('starts with an empty set picker on team change', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);
    expect(comp['selectedSetIds']()).toEqual([]);
  });

  it('clears set selection when team changes', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);
    comp['toggleSet'](31100);
    expect(comp['selectedSetIds']().length).toBeGreaterThan(0);

    await comp['onTeamChange']('t2');
    await flush(fixture);
    expect(comp['selectedSetIds']()).toEqual([]);
  });

  it('toggles individual set chips', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);

    comp['toggleSet'](31100);
    expect(comp['selectedSetIds']()).toContain(31100);

    comp['toggleSet'](31100);
    expect(comp['selectedSetIds']()).not.toContain(31100);

    comp['toggleSet'](31300);
    expect(comp['selectedSetIds']()).toContain(31300);
  });

  it('clearSets() resets to empty (all sets)', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);
    comp['toggleSet'](31100);
    comp['toggleSet'](31200);
    expect(comp['selectedSetIds']().length).toBeGreaterThan(0);

    comp['clearSets']();
    expect(comp['selectedSetIds']()).toEqual([]);
  });

  it('emits selectionChange with teamId and activeIndex when team, combo, and enemy are selected', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    const emitted: unknown[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));

    await comp['onTeamChange']('t1');
    await flush(fixture);

    expect(emitted).toHaveLength(1);
    const ev = emitted[0] as {
      teamId: string; activeIndex: number; comboId: string;
      enemyProfileId: string; allowedSetIds: number[] | null;
    };
    expect(ev.teamId).toBe('t1');
    expect(ev.activeIndex).toBe(0);
    expect(ev.comboId).toBe('c1');
    expect(ev.enemyProfileId).toBe('e1');
    expect(ev.allowedSetIds).toBeNull();
  });

  // DESIGN_buff_context.md §2.5 (#95). Rank used to send whatever was in the
  // shared BuffContextStore, which no rank component ever seeded — so a rank
  // job ran against defaults, or against state left behind by Calculate.
  it('emits a buffContext seeded from the selected member (#95)', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    const emitted: { buffContext: unknown }[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));

    await comp['onTeamChange']('t1');
    await flush(fixture);

    // Slot 0 is b1: its own conditions/stacks, disabled_buffs unioned with b2's
    // because the backend snapshots the supports for this context too.
    expect(emitted.at(-1)!.buffContext).toEqual({
      active_conditions: ['always', 'hp_above_50'],
      stack_counts: { 'b1:stack': 2 },
      disabled_buffs: ['1:core_a', '2:core_b'],
    });
  });

  it('re-seeds the buffContext when the active member changes (#95)', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);

    const emitted: { buffContext: unknown }[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));
    comp['onMemberChange'](1);

    // Now b2 is the target: its conditions/stacks win, and the union is
    // unchanged because it spans the same team either way.
    expect(emitted.at(-1)!.buffContext).toEqual({
      active_conditions: ['always', 'enemy_stunned'],
      stack_counts: { 'b2:stack': 3 },
      disabled_buffs: ['2:core_b', '1:core_a'],
    });
  });

  it('emits a null buffContext when the target build row is unknown (#95)', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;
    // Simulate builds not having loaded — the caller must then keep the store
    // fallback rather than send an empty context that reads as "nothing off".
    comp['builds'].set([]);

    const emitted: { buffContext: unknown }[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));

    await comp['onTeamChange']('t1');
    await flush(fixture);

    expect(emitted.at(-1)!.buffContext).toBeNull();
  });

  it('emits updated activeIndex when member changes', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);

    const emitted: unknown[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));

    comp['onMemberChange'](1);

    const ev = emitted[0] as { teamId: string; activeIndex: number };
    expect(ev.teamId).toBe('t1');
    expect(ev.activeIndex).toBe(1);
  });

  it('member selector shows when team has >1 member', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);

    expect(comp['teamMemberIndices']().length).toBe(2);
  });

  it('member selector labels slots by agent name', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);

    expect(comp['teamMemberIndices']().map((m) => m.label)).toEqual(['Caesar', 'Burnice']);
  });

  it('member selector hidden when team has 1 member', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t2');
    await flush(fixture);

    expect(comp['teamMemberIndices']().length).toBe(1);
  });

  it('emits allowedSetIds=null when set picker is cleared', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);

    const emitted: unknown[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));

    comp['clearSets']();

    const ev = emitted[0] as { allowedSetIds: number[] | null };
    expect(ev.allowedSetIds).toBeNull();
  });

  it('emits allowedSetIds with selected set ids when some are chosen', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);

    comp['clearSets']();
    comp['toggleSet'](31300);

    const emitted: unknown[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));
    comp['toggleSet'](31100);

    const ev = emitted[0] as { allowedSetIds: number[] | null };
    expect(ev.allowedSetIds).toContain(31100);
    expect(ev.allowedSetIds).toContain(31300);
    expect(ev.allowedSetIds).not.toContain(31200);
  });

  it('emits updated selection when combo changes', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    const emitted: unknown[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));

    await comp['onTeamChange']('t1');
    await flush(fixture);
    comp['onComboChange']('c2');

    const ev = emitted.at(-1) as { teamId: string; comboId: string; enemyProfileId: string };
    expect(ev.teamId).toBe('t1');
    expect(ev.comboId).toBe('c2');
    expect(ev.enemyProfileId).toBe('e1');
  });

  it('does not emit when combo is cleared', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;

    await comp['onTeamChange']('t1');
    await flush(fixture);

    const emitted: unknown[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));

    comp['onComboChange']('');
    expect(emitted).toHaveLength(0);
  });

  it('emits mainStats in selection when toggleMainStat is called', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;
    await comp['onTeamChange']('t1');
    await flush(fixture);

    const emitted: unknown[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));
    comp['toggleMainStat']('atk_pct');

    const ev = emitted[0] as { mainStats: string[] };
    expect(ev.mainStats).toContain('atk_pct');
  });

  it('emits rarities in selection when toggleRarity is called', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;
    await comp['onTeamChange']('t1');
    await flush(fixture);

    const emitted: unknown[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));
    comp['toggleRarity']('A');

    const ev = emitted[0] as { rarities: string[] };
    expect(ev.rarities).toContain('A');
  });

  it('includes mainStats: [] and rarities: ["S"] when nothing is toggled', async () => {
    const fixture = await setup();
    const comp = fixture.componentInstance;
    await comp['onTeamChange']('t1');
    await flush(fixture);

    const emitted: unknown[] = [];
    comp.selectionChange.subscribe((v) => emitted.push(v));
    comp['onEnemyChange']('e1');

    const ev = emitted[0] as { mainStats: string[]; rarities: string[] };
    expect(ev.mainStats).toEqual([]);
    expect(ev.rarities).toEqual(['S']);
  });

  describe('enemy picker tabs (#55)', () => {
    it('marks the active tab with aria-selected, not colour alone', async () => {
      const fixture = await setup(ENEMIES_MIXED);
      const comp = fixture.componentInstance;
      await comp['onTeamChange']('t1');
      await flush(fixture);
      const tabs = () => Array.from(
        fixture.nativeElement.querySelectorAll('[role="tab"]') as NodeListOf<HTMLElement>,
      ).map((b) => b.getAttribute('aria-selected'));

      expect(tabs()).toEqual(['true', 'false']);

      comp['onEnemyTabChange']('all');
      fixture.detectChanges();
      expect(tabs()).toEqual(['false', 'true']);
    });

    it('defaults to "Endgame Bosses", selecting the first rarity-4 profile', async () => {
      const fixture = await setup(ENEMIES_MIXED);
      const comp = fixture.componentInstance;
      expect(comp['selectedEnemyId']()).toBe('e-boss-1');
    });

    it('lists only rarity-4 enemies under the default tab, once a team is selected', async () => {
      const fixture = await setup(ENEMIES_MIXED);
      const comp = fixture.componentInstance;
      await comp['onTeamChange']('t1');
      await flush(fixture);

      const select = fixture.nativeElement.querySelector('#rank-enemy') as HTMLSelectElement;
      const values = Array.from(select.querySelectorAll('option'))
        .map((o) => o.getAttribute('value'))
        .filter((v) => v);
      expect(values).toEqual(['e-boss-1', 'e-boss-2']);
    });

    it('"All Enemies" tab surfaces the trash mob too', async () => {
      const fixture = await setup(ENEMIES_MIXED);
      const comp = fixture.componentInstance;
      await comp['onTeamChange']('t1');
      await flush(fixture);

      comp['onEnemyTabChange']('all');
      fixture.detectChanges();
      const select = fixture.nativeElement.querySelector('#rank-enemy') as HTMLSelectElement;
      const values = Array.from(select.querySelectorAll('option'))
        .map((o) => o.getAttribute('value'))
        .filter((v) => v);
      expect(values).toContain('e-trash');
    });

    it('re-defaults selection when switching back to Bosses filters out the current pick', async () => {
      const fixture = await setup(ENEMIES_MIXED);
      const comp = fixture.componentInstance;
      await comp['onTeamChange']('t1');
      await flush(fixture);

      comp['onEnemyTabChange']('all');
      comp['onEnemyChange']('e-trash');
      comp['onEnemyTabChange']('bosses');
      expect(comp['selectedEnemyId']()).toBe('e-boss-1');
    });
  });
});
