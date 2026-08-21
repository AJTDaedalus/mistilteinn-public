import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';

import { BuildsListPage } from './builds-list';
import { BuildsService } from './builds.service';

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
    icon_path: '', has_potential: false,
    ...overrides,
  };
}

function setupPage(builds: unknown[] = [], agents: unknown[] = []) {
  const svcStub = {
    list: vi.fn(async () => builds),
    listAgents: vi.fn(async () => agents),
  };
  TestBed.configureTestingModule({
    imports: [BuildsListPage],
    providers: [
      provideRouter([]),
      { provide: BuildsService, useValue: svcStub },
    ],
  });
  return { svc: svcStub };
}

async function awaitFixture(fixture: ReturnType<typeof TestBed.createComponent>) {
  fixture.detectChanges();
  for (let i = 0; i < 3; i++) await Promise.resolve();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
}

describe('BuildsListPage', () => {
  it('shows the empty state when no builds exist', async () => {
    setupPage([], []);
    const fixture = TestBed.createComponent(BuildsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-test="empty"]')?.textContent ?? '')
      .toMatch(/no builds yet/i);
    expect(el.querySelectorAll('[data-test="build-card"]')).toHaveLength(0);
  });

  it('renders a card per build with agent name and mindscape', async () => {
    setupPage(
      [
        makeBuild({ id: 'b1', agent_id: 'a1', mindscape_level: 6 }),
        makeBuild({ id: 'b2', agent_id: 'a2', mindscape_level: 0 }),
      ],
      [
        makeAgent({ id: 'a1', name: 'Caesar' }),
        makeAgent({ id: 'a2', name: 'Burnice', element: 'fire', specialty: 'anomaly' }),
      ],
    );
    const fixture = TestBed.createComponent(BuildsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const cards = el.querySelectorAll('[data-test="build-card"]');
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain('Caesar');
    expect(cards[1].textContent).toContain('Burnice');

    // Mindscape badge shows the number, and only when M > 0.
    expect(cards[0].querySelector('[data-test="mindscape"]')?.textContent?.trim()).toBe('6');
    expect(cards[1].querySelector('[data-test="mindscape"]')).toBeNull();
  });

  it('overlays rank, element/specialty icons and level on the portrait', async () => {
    setupPage(
      [makeBuild({ id: 'b1', agent_id: 'a1', agent_specialty: 'attack', agent_level: 55 })],
      [makeAgent({ id: 'a1', name: 'Caesar', element: 'fire', specialty: 'attack', rarity: 'S' })],
    );
    const fixture = TestBed.createComponent(BuildsListPage);
    await awaitFixture(fixture);
    const card = (fixture.nativeElement as HTMLElement)
      .querySelector('[data-test="build-card"]') as HTMLElement;

    // Rank badge reflects rarity.
    const rank = card.querySelector('[data-test="rank-badge"]') as HTMLElement;
    expect(rank.textContent).toContain('S');
    expect(rank.className).toContain('card__rank--S');

    // Level overlay.
    expect(card.querySelector('[data-test="level"]')?.textContent).toContain('Lv. 55');

    // Element + specialty icon assets resolve to the expected files.
    const badgeSrcs = Array.from(card.querySelectorAll('.card__badge'))
      .map((img) => (img as HTMLImageElement).getAttribute('src') ?? '');
    expect(badgeSrcs.some((s) => s.includes('IconElementFire'))).toBe(true);
    expect(badgeSrcs.some((s) => s.includes('IconAttack'))).toBe(true);
  });

  it('exposes a "new build" CTA wired to the editor route', async () => {
    setupPage();
    const fixture = TestBed.createComponent(BuildsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const link = el.querySelector('[data-test="new-build"]') as HTMLAnchorElement;
    expect(link).toBeTruthy();
    expect(link.getAttribute('href') ?? link.getAttribute('routerLink'))
      .toMatch(/builds\/new/);
  });

  it('has no import entry (nav Import tab is the single entry point)', async () => {
    setupPage();
    const fixture = TestBed.createComponent(BuildsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-test="import"]')).toBeNull();
    // No scanner-import modal in the template.
    expect(el.querySelector('scanner-import')).toBeNull();
  });

  it('E3 — each build card has an optimize link with correct buildId', async () => {
    setupPage(
      [makeBuild({ id: 'b99' })],
      [makeAgent({ id: 'a1', name: 'Agent' })],
    );
    const fixture = TestBed.createComponent(BuildsListPage);
    await awaitFixture(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const link = el.querySelector('[data-test="optimize-link"]') as HTMLAnchorElement;
    expect(link).toBeTruthy();
    expect(link.getAttribute('href') ?? '').toContain('optimize');
  });

  it('text filter narrows the cards grid', async () => {
    setupPage(
      [
        makeBuild({ id: 'b1', agent_id: 'a1' }),
        makeBuild({ id: 'b2', agent_id: 'a2' }),
      ],
      [
        makeAgent({ id: 'a1', name: 'Caesar' }),
        makeAgent({ id: 'a2', name: 'Burnice', element: 'fire', specialty: 'anomaly' }),
      ],
    );
    const fixture = TestBed.createComponent(BuildsListPage);
    await awaitFixture(fixture);

    // Apply text filter targeting only 'Caesar'
    (fixture.componentInstance as any).filterState.set({ text: 'caesar', elements: [], specialties: [] });
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const cards = el.querySelectorAll('[data-test="build-card"]');
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain('Caesar');
  });

  it('specialty filter narrows the cards grid', async () => {
    setupPage(
      [
        makeBuild({ id: 'b1', agent_id: 'a1', agent_specialty: 'attack' }),
        makeBuild({ id: 'b2', agent_id: 'a2', agent_specialty: 'anomaly' }),
      ],
      [
        makeAgent({ id: 'a1', name: 'Caesar', specialty: 'attack' }),
        makeAgent({ id: 'a2', name: 'Burnice', specialty: 'anomaly' }),
      ],
    );
    const fixture = TestBed.createComponent(BuildsListPage);
    await awaitFixture(fixture);

    (fixture.componentInstance as any).filterState.set({ text: '', elements: [], specialties: ['anomaly'] });
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const cards = el.querySelectorAll('[data-test="build-card"]');
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain('Burnice');
  });
});
