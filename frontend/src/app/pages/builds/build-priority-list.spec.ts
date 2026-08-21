import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { BuildPriorityList } from './build-priority-list';
import { BuildsService } from './builds.service';

const AGENT_ID: Record<string, string> = { b1: 'a1', b2: 'a2', b3: 'a3' };
const ALL_AGENTS = [
  { id: 'a1', name: 'Caesar', icon_path: null },
  { id: 'a2', name: 'Burnice', icon_path: null },
  { id: 'a3', name: 'Nicole', icon_path: null },
];

function build(id: string, priority: number | null = null) {
  return {
    id,
    agent_id: AGENT_ID[id] ?? 'a1',
    agent_specialty: 'attack',
    optimizer_priority: priority,
    mindscape_level: 0,
    agent_level: 60,
    skill_levels: '1,1,1,1,1',
    notes: '',
    disabled_buffs: [],
    active_conditions: [],
    stack_counts: {},
    w_engine_id: null,
    w_engine_level: 60,
    w_engine_refinement: 1,
    core_skill_level: 5,
  };
}

function setup(setPriorityOrder: ReturnType<typeof vi.fn> = vi.fn(async () => [])) {
  TestBed.configureTestingModule({
    imports: [BuildPriorityList],
    providers: [{ provide: BuildsService, useValue: { setPriorityOrder } }],
  });
  return { setPriorityOrder };
}

async function flush(fixture: ReturnType<typeof TestBed.createComponent>) {
  fixture.detectChanges();
  for (let i = 0; i < 3; i++) await Promise.resolve();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
}

describe('BuildPriorityList', () => {
  it('renders ranked builds in priority order', async () => {
    setup();
    const fixture = TestBed.createComponent(BuildPriorityList);
    fixture.componentRef.setInput('builds', [
      build('b1', 2),
      build('b2', 1),
      build('b3', 3),
    ]);
    fixture.componentRef.setInput('agents', ALL_AGENTS);
    await flush(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const rows = el.querySelectorAll('[data-test="ranked-row"]');
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toContain('Burnice');
    expect(rows[1].textContent).toContain('Caesar');
    expect(rows[2].textContent).toContain('Nicole');
  });

  it('shows empty ranked state when no builds have priority', async () => {
    setup();
    const fixture = TestBed.createComponent(BuildPriorityList);
    fixture.componentRef.setInput('builds', [build('b1'), build('b2')]);
    fixture.componentRef.setInput('agents', []);
    await flush(fixture);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-test="ranked-empty"]')).toBeTruthy();
    expect(el.querySelectorAll('[data-test="unranked-row"]')).toHaveLength(2);
  });

  it('moveUp swaps rows and enables save button', async () => {
    setup();
    const fixture = TestBed.createComponent(BuildPriorityList);
    fixture.componentRef.setInput('builds', [build('b1', 1), build('b2', 2)]);
    fixture.componentRef.setInput('agents', ALL_AGENTS);
    await flush(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const moveUpBtns = el.querySelectorAll<HTMLButtonElement>('[data-test="move-up"]');
    // Second row's up button
    moveUpBtns[1].click();
    fixture.detectChanges();
    const rows = el.querySelectorAll('[data-test="ranked-row"]');
    expect(rows[0].textContent).toContain('Burnice');
    expect(rows[1].textContent).toContain('Caesar');
    const saveBtn = el.querySelector<HTMLButtonElement>('[data-test="save-order"]');
    expect(saveBtn?.disabled).toBe(false);
  });

  it('promote moves a build from unranked to ranked', async () => {
    setup();
    const fixture = TestBed.createComponent(BuildPriorityList);
    fixture.componentRef.setInput('builds', [build('b1', 1), build('b2')]);
    fixture.componentRef.setInput('agents', []);
    await flush(fixture);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('[data-test="ranked-row"]')).toHaveLength(1);
    (el.querySelector('[data-test="promote"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelectorAll('[data-test="ranked-row"]')).toHaveLength(2);
    expect(el.querySelectorAll('[data-test="unranked-row"]')).toHaveLength(0);
  });

  it('demote moves a build from ranked to unranked', async () => {
    setup();
    const fixture = TestBed.createComponent(BuildPriorityList);
    fixture.componentRef.setInput('builds', [build('b1', 1)]);
    fixture.componentRef.setInput('agents', []);
    await flush(fixture);
    const el = fixture.nativeElement as HTMLElement;
    (el.querySelector('[data-test="demote"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelectorAll('[data-test="ranked-row"]')).toHaveLength(0);
    expect(el.querySelectorAll('[data-test="unranked-row"]')).toHaveLength(1);
  });

  it('save calls setPriorityOrder with ranked IDs in order', async () => {
    const setPriorityOrder = vi.fn(async () => [build('b1', 1), build('b2', 2)]);
    setup(setPriorityOrder);
    const fixture = TestBed.createComponent(BuildPriorityList);
    fixture.componentRef.setInput('builds', [build('b1', 1), build('b2', 2)]);
    fixture.componentRef.setInput('agents', []);
    await flush(fixture);

    // Make dirty first by promoting then demoting so there's a change
    const el = fixture.nativeElement as HTMLElement;
    const moveDownBtns = el.querySelectorAll<HTMLButtonElement>('[data-test="move-down"]');
    moveDownBtns[0].click();
    fixture.detectChanges();

    (el.querySelector('[data-test="save-order"]') as HTMLButtonElement).click();
    for (let i = 0; i < 5; i++) await Promise.resolve();
    fixture.detectChanges();

    expect(setPriorityOrder).toHaveBeenCalledWith(['b2', 'b1']);
  });
});
