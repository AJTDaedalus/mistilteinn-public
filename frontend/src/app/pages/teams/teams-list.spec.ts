import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';

import { TeamsListPage } from './teams-list';
import { TeamsService } from './teams.service';
import { BuildsService } from '../builds/builds.service';

function makeTeam(overrides: Record<string, unknown> = {}) {
  return {
    id: 't1',
    name: 'Alpha Squad',
    build1_id: 'b1',
    build2_id: null,
    build3_id: null,
    ...overrides,
  };
}

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
  teams: unknown[] = [],
  builds: unknown[] = [],
  agents: unknown[] = [],
) {
  const teamsSvcStub = {
    list: vi.fn(async () => teams),
    remove: vi.fn(async () => undefined),
  };
  const buildsSvcStub = {
    list: vi.fn(async () => builds),
    listAgents: vi.fn(async () => agents),
  };
  TestBed.configureTestingModule({
    imports: [TeamsListPage],
    providers: [
      provideRouter([]),
      { provide: TeamsService, useValue: teamsSvcStub },
      { provide: BuildsService, useValue: buildsSvcStub },
    ],
  });
  return { teamsSvc: teamsSvcStub, buildsSvc: buildsSvcStub };
}

async function awaitFixture(fixture: ReturnType<typeof TestBed.createComponent>) {
  fixture.detectChanges();
  for (let i = 0; i < 3; i++) await Promise.resolve();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
}

describe('TeamsListPage', () => {
  it('shows the empty state when no teams exist', async () => {
    setupPage([], [], []);
    const fixture = TestBed.createComponent(TeamsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-test="empty"]')?.textContent ?? '')
      .toMatch(/no teams yet/i);
    expect(el.querySelectorAll('[data-test="team-card"]')).toHaveLength(0);
  });

  it('renders a card per team with team name', async () => {
    setupPage(
      [
        makeTeam({ id: 't1', name: 'Alpha Squad', build1_id: 'b1' }),
        makeTeam({ id: 't2', name: 'Beta Squad', build1_id: 'b2' }),
      ],
      [
        makeBuild({ id: 'b1', agent_id: 'a1' }),
        makeBuild({ id: 'b2', agent_id: 'a2' }),
      ],
      [
        makeAgent({ id: 'a1', name: 'Caesar' }),
        makeAgent({ id: 'a2', name: 'Burnice' }),
      ],
    );
    const fixture = TestBed.createComponent(TeamsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const cards = el.querySelectorAll('[data-test="team-card"]');
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain('Alpha Squad');
    expect(cards[1].textContent).toContain('Beta Squad');
  });

  it('renders mini-portraits for each team member', async () => {
    setupPage(
      [makeTeam({ build1_id: 'b1', build2_id: 'b2', build3_id: 'b3' })],
      [
        makeBuild({ id: 'b1', agent_id: 'a1' }),
        makeBuild({ id: 'b2', agent_id: 'a2' }),
        makeBuild({ id: 'b3', agent_id: 'a3' }),
      ],
      [
        makeAgent({ id: 'a1', name: 'Caesar', icon_path: '/icons/Caesar.webp' }),
        makeAgent({ id: 'a2', name: 'Burnice', icon_path: '/icons/Burnice.webp' }),
        makeAgent({ id: 'a3', name: 'Nicole', icon_path: '/icons/Nicole.webp' }),
      ],
    );
    const fixture = TestBed.createComponent(TeamsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const card = el.querySelector('[data-test="team-card"]')!;
    const portraits = card.querySelectorAll('[data-test="member-portraits"] .portrait');
    expect(portraits).toHaveLength(3);
  });

  it('renders only 1 portrait for a 1-member team', async () => {
    setupPage(
      [makeTeam({ build1_id: 'b1', build2_id: null, build3_id: null })],
      [makeBuild({ id: 'b1', agent_id: 'a1' })],
      [makeAgent({ id: 'a1', name: 'Caesar' })],
    );
    const fixture = TestBed.createComponent(TeamsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const portraits = el.querySelectorAll('[data-test="member-portraits"] .portrait');
    expect(portraits).toHaveLength(1);
  });

  it('delete removes the team card', async () => {
    const { teamsSvc } = setupPage(
      [makeTeam({ id: 't1', name: 'Solo', build1_id: 'b1' })],
      [makeBuild({ id: 'b1', agent_id: 'a1' })],
      [makeAgent({ id: 'a1', name: 'Caesar' })],
    );
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const fixture = TestBed.createComponent(TeamsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('[data-test="team-card"]')).toHaveLength(1);

    const btn = el.querySelector('[data-test="delete-team"]') as HTMLButtonElement;
    btn.click();
    fixture.detectChanges();
    for (let i = 0; i < 3; i++) await Promise.resolve();
    fixture.detectChanges();

    expect(teamsSvc.remove).toHaveBeenCalledWith('t1');
    expect(el.querySelectorAll('[data-test="team-card"]')).toHaveLength(0);
  });

  it('exposes a "new team" CTA linked to /teams/new', async () => {
    setupPage();
    const fixture = TestBed.createComponent(TeamsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const link = el.querySelector('[data-test="new-team"]') as HTMLAnchorElement;
    expect(link).toBeTruthy();
    expect(link.getAttribute('href') ?? link.getAttribute('routerLink'))
      .toMatch(/teams\/new/);
  });
});
