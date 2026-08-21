import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { CalculatePage } from './calculate';
import { CalculateService } from './calculate.service';

const TEAMS = [
  { id: 't1', name: 'Squad', build1_id: 'b1', build2_id: 'b2', build3_id: null },
];
const BUILDS = [
  { id: 'b1', agent_id: 'a1', agent_specialty: 'attack' },
  { id: 'b2', agent_id: 'a2', agent_specialty: 'support' },
];
const AGENTS = [
  { id: 'a1', name: 'Caesar' },
  { id: 'a2', name: 'Burnice' },
];
const ENEMIES = [{ id: 'e1', name: 'Dummy', level: 60, rarity: 1 }];

const ENEMIES_MIXED = [
  { id: 'e-trash', name: 'Notorious Assaulter', level: 60, rarity: 1 },
  { id: 'e-boss-1', name: 'Dead End Butcher', level: 60, rarity: 4 },
  { id: 'e-boss-2', name: 'Girtablullu - Stagnant Aberrant', level: 60, rarity: 4 },
];
const COMBO = {
  id: 'c1',
  name: 'Disorder opener',
  sequence: [
    { agent_id: 'b1', move_name: 'basic' },
    { agent_id: 'support1', move_name: 'special' },
    { step_type: 'stun_trigger' },
  ],
};
const SIM_RESULT = {
  events: [{ t: 1.0, kind: 'hit', damage: 1000 }, { t: 2.0, kind: 'hit', damage: 500 }],
  totals: { total: 1500 },
  per_agent_attribution: { Caesar: 900, Burnice: 600 },
  warnings: [],
  buff_roster: { b1: [{ buff_key: 'atk_', display_name: 'ATK %', value: 0.15, target: 'self' }], b2: [] },
};

function setup(combos: unknown[] = [COMBO], enemies: unknown[] = ENEMIES) {
  const svc = {
    listTeams: vi.fn(async () => TEAMS),
    listBuilds: vi.fn(async () => BUILDS),
    listEnemies: vi.fn(async () => enemies),
    listAgents: vi.fn(async () => AGENTS),
    listTeamCombos: vi.fn(async () => combos),
    simulate: vi.fn(async () => SIM_RESULT),
  };
  TestBed.configureTestingModule({
    imports: [CalculatePage],
    providers: [{ provide: CalculateService, useValue: svc }],
  });
  return svc;
}

async function awaitFixture(fixture: ReturnType<typeof TestBed.createComponent>) {
  fixture.detectChanges();
  for (let i = 0; i < 5; i++) await Promise.resolve();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
}

describe('CalculatePage (team-centric)', () => {
  it('lists teams as options, not builds', async () => {
    setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;
    expect(comp.teamOptions()).toEqual([{ value: 't1', label: 'Squad' }]);
  });

  it('selecting a team loads that team\'s rotations', async () => {
    const svc = setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;

    comp.onTeamPick('t1');
    await awaitFixture(fixture);

    expect(svc.listTeamCombos).toHaveBeenCalledWith('t1');
    expect(comp.comboOptions().length).toBe(1);
  });

  it('evaluate keys team_builds by member build id and normalizes legacy owners', async () => {
    const svc = setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;

    comp.teamId.set('t1');
    comp.combos.set([COMBO]);
    comp.comboId.set('c1');
    comp.enemyId.set('e1');

    await comp.evaluate();

    expect(svc.simulate).toHaveBeenCalledTimes(1);
    const [teamBuilds, steps, enemyId] = svc.simulate.mock.calls[0] as unknown as [
      Record<string, string>,
      any[],
      string,
    ];
    // team_builds keyed by build id (matches what team combo steps store)
    expect(teamBuilds).toEqual({ b1: 'b1', b2: 'b2' });
    // bare build-id owner kept; legacy 'support1' → second member; marker → first member
    expect(steps.map((s: any) => s.agent_id)).toEqual(['b1', 'b2', 'b1']);
    expect(steps[2].move_name).toBe('stun_trigger');
    expect(enemyId).toBe('e1');
  });

  it('resolves simulation owner build ids back to agent names', async () => {
    setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;
    comp.teamId.set('t1');

    const nameFor = comp.agentRoleToName();
    expect(nameFor('b1')).toBe('Caesar');
    expect(nameFor('support1')).toBe('Burnice');
    expect(nameFor(null)).toBe('—');
  });

  // ---- collapse / de-busy tests (Tasks 8-11) --------------------------------

  it('buff rosters are collapsed by default after evaluate()', async () => {
    setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;

    comp.teamId.set('t1');
    comp.combos.set([COMBO]);
    comp.comboId.set('c1');
    comp.enemyId.set('e1');
    await comp.evaluate();
    fixture.detectChanges();

    expect(comp.buffsOpen()).toBe(false);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-test="buffs-body"]')).toBeNull();
    expect(el.querySelector('[data-test="buffs-summary"]')).toBeTruthy();
  });

  it('buff rosters expand when toggle is clicked', async () => {
    setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;

    comp.teamId.set('t1');
    comp.combos.set([COMBO]);
    comp.comboId.set('c1');
    comp.enemyId.set('e1');
    await comp.evaluate();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    (el.querySelector('[data-test="buffs-toggle"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(comp.buffsOpen()).toBe(true);
    expect(el.querySelector('[data-test="buffs-body"]')).toBeTruthy();
  });

  it('attribution is collapsed by default after evaluate()', async () => {
    setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;

    comp.teamId.set('t1');
    comp.combos.set([COMBO]);
    comp.comboId.set('c1');
    comp.enemyId.set('e1');
    await comp.evaluate();
    fixture.detectChanges();

    expect(comp.attributionOpen()).toBe(false);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-test="attribution-body"]')).toBeNull();
    expect(el.querySelector('[data-test="attribution-summary"]')).toBeTruthy();
  });

  it('attribution expands when toggle is clicked', async () => {
    setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;

    comp.teamId.set('t1');
    comp.combos.set([COMBO]);
    comp.comboId.set('c1');
    comp.enemyId.set('e1');
    await comp.evaluate();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    (el.querySelector('[data-test="attribution-toggle"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(comp.attributionOpen()).toBe(true);
    expect(el.querySelector('[data-test="attribution-body"]')).toBeTruthy();
  });

  it('timeline is collapsed by default after evaluate()', async () => {
    setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;

    comp.teamId.set('t1');
    comp.combos.set([COMBO]);
    comp.comboId.set('c1');
    comp.enemyId.set('e1');
    await comp.evaluate();
    fixture.detectChanges();

    expect(comp.timelineOpen()).toBe(false);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-test="timeline-body"]')).toBeNull();
    expect(el.querySelector('[data-test="timeline-summary"]')).toBeTruthy();
  });

  it('timeline expands when toggle is clicked', async () => {
    setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;

    comp.teamId.set('t1');
    comp.combos.set([COMBO]);
    comp.comboId.set('c1');
    comp.enemyId.set('e1');
    await comp.evaluate();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    (el.querySelector('[data-test="timeline-toggle"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(comp.timelineOpen()).toBe(true);
    expect(el.querySelector('[data-test="timeline-body"]')).toBeTruthy();
  });

  it('a second evaluate() re-collapses all three sections', async () => {
    setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;

    comp.teamId.set('t1');
    comp.combos.set([COMBO]);
    comp.comboId.set('c1');
    comp.enemyId.set('e1');
    await comp.evaluate();
    fixture.detectChanges();

    // Open all three.
    comp.buffsOpen.set(true);
    comp.attributionOpen.set(true);
    comp.timelineOpen.set(true);
    fixture.detectChanges();

    // Run a second calculation — should re-collapse.
    await comp.evaluate();
    fixture.detectChanges();

    expect(comp.buffsOpen()).toBe(false);
    expect(comp.attributionOpen()).toBe(false);
    expect(comp.timelineOpen()).toBe(false);
  });

  it('Totals panel is always visible (not collapsible)', async () => {
    setup();
    const fixture = TestBed.createComponent(CalculatePage);
    await awaitFixture(fixture);
    const comp = fixture.componentInstance as any;

    comp.teamId.set('t1');
    comp.combos.set([COMBO]);
    comp.comboId.set('c1');
    comp.enemyId.set('e1');
    await comp.evaluate();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.totals')).toBeTruthy();
  });

  describe('enemy picker tabs (#55)', () => {
    it('defaults to "Endgame Bosses", listing only rarity-4 enemy names', async () => {
      setup([COMBO], ENEMIES_MIXED);
      const fixture = TestBed.createComponent(CalculatePage);
      await awaitFixture(fixture);
      const comp = fixture.componentInstance as any;
      expect(comp.enemyNameOptions().map((o: { value: string }) => o.value)).toEqual([
        'Dead End Butcher',
        'Girtablullu - Stagnant Aberrant',
      ]);
    });

    it('"All Enemies" tab surfaces the trash mob too', async () => {
      setup([COMBO], ENEMIES_MIXED);
      const fixture = TestBed.createComponent(CalculatePage);
      await awaitFixture(fixture);
      const comp = fixture.componentInstance as any;

      comp.onEnemyTabChange('all');
      expect(comp.enemyNameOptions().map((o: { value: string }) => o.value))
        .toContain('Notorious Assaulter');
    });

    it('switching tabs clears the selected enemy once it is no longer in the list', async () => {
      setup([COMBO], ENEMIES_MIXED);
      const fixture = TestBed.createComponent(CalculatePage);
      await awaitFixture(fixture);
      const comp = fixture.componentInstance as any;

      comp.onEnemyTabChange('all');
      comp.onEnemyNamePick('Notorious Assaulter');
      expect(comp.enemyName()).toBe('Notorious Assaulter');

      comp.onEnemyTabChange('bosses');
      expect(comp.enemyName()).toBe('');
      expect(comp.enemyId()).toBe('');
    });

    it('switching tabs leaves a still-visible selection untouched', async () => {
      setup([COMBO], ENEMIES_MIXED);
      const fixture = TestBed.createComponent(CalculatePage);
      await awaitFixture(fixture);
      const comp = fixture.componentInstance as any;

      comp.onEnemyNamePick('Dead End Butcher');
      comp.onEnemyTabChange('all');
      expect(comp.enemyName()).toBe('Dead End Butcher');
    });
  });
});
