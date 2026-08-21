import { TestBed } from '@angular/core/testing';
import { ComponentRef } from '@angular/core';
import { describe, expect, it, vi } from 'vitest';

import { ComboBuilder, ComboMemberRef } from './combo-builder';
import { CombosService } from './combos.service';

const DPS_ATTACKS = [
  { id: 'atk1', skill_key: 'Basic', name: 'Basic 1', hit_index: 0,
    element: 'physical', damage_base: 10000, damage_growth: 500,
    agent_id: 'a1', hakushin_skill_id: 1 },
  { id: 'atk2', skill_key: 'EXSpecial', name: 'EX Special', hit_index: 0,
    element: 'physical', damage_base: 30000, damage_growth: 1500,
    agent_id: 'a1', hakushin_skill_id: 3 },
  { id: 'atk3', skill_key: 'Ultimate', name: 'Ultimate', hit_index: 0,
    element: 'physical', damage_base: 60000, damage_growth: 3000,
    agent_id: 'a1', hakushin_skill_id: 5 },
];

const SUP_ATTACKS = [
  { id: 'satk1', skill_key: 'Special', name: 'Sup Special', hit_index: 0,
    element: 'fire', damage_base: 5000, damage_growth: 200,
    agent_id: 'sup1', hakushin_skill_id: 2 },
];

/** Team members for the owner picker — DPS in slot 1, support in slot 2. */
const DPS_MEMBER: ComboMemberRef = { buildId: 'b1', agentId: 'a1', agentName: 'Miyabi' };
const SUP_MEMBER: ComboMemberRef = { buildId: 'build-sup1', agentId: 'sup1', agentName: 'Soukaku' };

interface CombosStub {
  listForTeam: ReturnType<typeof vi.fn>;
  create: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
  getAgentAttacks: ReturnType<typeof vi.fn>;
}

function setup(combos: unknown[] = [], supAttacks = SUP_ATTACKS): { svc: CombosStub } {
  const svc: CombosStub = {
    listForTeam: vi.fn(async () => combos),
    create: vi.fn(async (p) => ({
      id: 'new-combo', description: '', ...(p as object),
    })),
    update: vi.fn(async (id, patch) => ({ id, team_id: 't1', ...(patch as object) })),
    remove: vi.fn(async () => undefined),
    getAgentAttacks: vi.fn(async (agentId: string) =>
      agentId === 'sup1' ? supAttacks : DPS_ATTACKS,
    ),
  };
  TestBed.configureTestingModule({
    imports: [ComboBuilder],
    providers: [{ provide: CombosService, useValue: svc }],
  });
  return { svc };
}

function withInputs(teamId: string | null, members: ComboMemberRef[] = []) {
  const fixture = TestBed.createComponent(ComboBuilder);
  const ref = fixture.componentRef as ComponentRef<ComboBuilder>;
  ref.setInput('teamId', teamId);
  ref.setInput('members', members);
  return fixture;
}

async function settle(fixture: ReturnType<typeof TestBed.createComponent>) {
  fixture.detectChanges();
  for (let i = 0; i < 4; i++) await Promise.resolve();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
}

describe('ComboBuilder', () => {
  it('shows a "save the build first" hint when teamId is null', async () => {
    setup();
    const f = withInputs(null, []);
    await settle(f);
    const el = f.nativeElement as HTMLElement;
    expect(el.textContent).toMatch(/save.*build first/i);
  });

  it('loads combos and member attacks when teamId + members are present', async () => {
    const { svc } = setup([{
      id: 'c1', name: 'BA1 → EX', team_id: 't1',
      sequence: [{ attack_id: 'atk1', label: 'BA1' }], description: '',
    }]);
    const f = withInputs('t1', [DPS_MEMBER]);
    await settle(f);
    expect(svc.listForTeam).toHaveBeenCalledWith('t1');
    expect(svc.getAgentAttacks).toHaveBeenCalledWith('a1');
    const el = f.nativeElement as HTMLElement;
    expect(el.textContent).toContain('BA1 → EX');
  });

  it('loads each member\'s moves and exposes them per owner build id', async () => {
    const { svc } = setup([]);
    const f = withInputs('t1', [DPS_MEMBER, SUP_MEMBER]);
    const cmp = f.componentInstance as unknown as {
      getMoveOptionsForOwner: (buildId: string) => { value: string }[];
    };
    await settle(f);
    expect(svc.getAgentAttacks).toHaveBeenCalledWith('a1');
    expect(svc.getAgentAttacks).toHaveBeenCalledWith('sup1');
    const supOpts = cmp.getMoveOptionsForOwner('build-sup1');
    expect(supOpts.map(o => o.value)).toContain('Sup Special');
    const dpsOpts = cmp.getMoveOptionsForOwner('b1');
    expect(dpsOpts.map(o => o.value)).toContain('Basic 1');
  });

  it('renders the owner picker with member agent names, not role labels', async () => {
    setup([]);
    const f = withInputs('t1', [DPS_MEMBER, SUP_MEMBER]);
    const cmp = f.componentInstance as unknown as { startNew: () => void; addStep: () => void };
    await settle(f);
    cmp.startNew();
    cmp.addStep();
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    const optionText = Array.from(el.querySelectorAll('.agent-select option'))
      .map(o => o.textContent?.trim());
    expect(optionText).toEqual(['Miyabi', 'Soukaku']);
    expect(el.textContent).not.toMatch(/Support 1|Support 2/);
  });

  it('saves combo steps as move_name owned by the primary build id', async () => {
    const { svc } = setup([]);
    const f = withInputs('t1', [DPS_MEMBER]);
    const cmp = f.componentInstance as unknown as {
      startNew: () => void;
      addStep: () => void;
      updateStep: (i: number, moveName: string, label?: string) => void;
      draftName: { set: (v: string) => void };
      saveDraft: () => Promise<void>;
    };
    await settle(f);

    cmp.startNew();
    cmp.draftName.set('My Combo');
    cmp.addStep();
    cmp.updateStep(0, 'Basic 1', 'BA1');
    cmp.addStep();
    cmp.updateStep(1, 'Ultimate', 'ULT');
    await cmp.saveDraft();

    expect(svc.create).toHaveBeenCalledOnce();
    const arg = svc.create.mock.calls[0][0];
    expect(arg.team_id).toBe('t1');
    expect(arg.name).toBe('My Combo');
    expect(arg.sequence[0].move_name).toBe('Basic 1');
    expect(arg.sequence[0].agent_id).toBe('b1');
  });

  it('tags a step with the support member\'s build id when reassigned', async () => {
    const { svc } = setup([]);
    const f = withInputs('t1', [DPS_MEMBER, SUP_MEMBER]);
    const cmp = f.componentInstance as unknown as {
      startNew: () => void;
      addStep: () => void;
      updateStep: (i: number, moveName: string, label?: string, ownerId?: string) => void;
      updateStepAgent: (i: number, ownerId: string) => void;
      draftName: { set: (v: string) => void };
      saveDraft: () => Promise<void>;
    };
    await settle(f);

    cmp.startNew();
    cmp.draftName.set('Team Combo');
    cmp.addStep();
    cmp.updateStep(0, 'Basic 1', 'BA1');
    // Reassign step 0 to the support member by build id.
    cmp.updateStepAgent(0, 'build-sup1');
    cmp.updateStep(0, 'Sup Special', 'SS');
    await cmp.saveDraft();

    const arg = svc.create.mock.calls[0][0];
    expect(arg.sequence[0].agent_id).toBe('build-sup1');
  });

  it('normalises a legacy support1 role string to the slot-2 build id on edit', async () => {
    const { svc } = setup([{
      id: 'c-legacy', name: 'Legacy', team_id: 't1', description: '',
      sequence: [{ move_name: 'Sup Special', label: 'SS', agent_id: 'support1' }],
    }]);
    const f = withInputs('t1', [DPS_MEMBER, SUP_MEMBER]);
    const cmp = f.componentInstance as unknown as {
      startEdit: (c: unknown) => void;
      draftSteps: () => { agent_id?: string }[];
    };
    await settle(f);
    cmp.startEdit((await svc.listForTeam.mock.results[0].value)[0]);
    expect(cmp.draftSteps()[0].agent_id).toBe('build-sup1');
  });

  it('issue #56 repro: a legacy support1 step loaded before members settle ' +
    'still resolves to the right owner everywhere, including on save (B13/B15)', async () => {
    const { svc } = setup([{
      id: 'c-race', name: 'Race', team_id: 't1', description: '',
      sequence: [{ move_name: 'Sup Special', label: 'SS', agent_id: 'support1' }],
    }]);
    // Members start empty — the team's own data hasn't arrived yet when the
    // combo is opened for editing (DESIGN hypothesis 1: a load-time race).
    const f = withInputs('t1', []);
    const cmp = f.componentInstance as unknown as {
      startEdit: (c: unknown) => void;
      draftSteps: () => { agent_id?: string }[];
      getMoveOptionsForOwner: (buildId: string | undefined) => { value: string }[];
      saveDraft: () => Promise<void>;
    };
    await settle(f);
    cmp.startEdit((await svc.listForTeam.mock.results[0].value)[0]);

    // Team data arrives late, after the combo was already opened. The raw
    // stored agent_id stays the un-resolved 'support1' literal baked in
    // while members() was empty — that alone is fine, since every consumer
    // (display, move list, save) re-resolves it live off ownerBuildId().
    const ref = f.componentRef as ComponentRef<ComboBuilder>;
    ref.setInput('members', [DPS_MEMBER, SUP_MEMBER]);
    await settle(f);

    const step = cmp.draftSteps()[0];
    expect(step.agent_id).toBe('support1');

    // The move list resolves live off members() and correctly shows
    // Soukaku's (the support member's) moves.
    const opts = cmp.getMoveOptionsForOwner(step.agent_id);
    expect(opts.map((o) => o.value)).toContain('Sup Special');

    // Saving without touching this step must not re-persist the raw
    // 'support1' literal — it has to migrate to the real build id (B15).
    await cmp.saveDraft();
    const saved = svc.update.mock.calls[0][1] as { sequence: { agent_id?: string }[] };
    expect(saved.sequence[0].agent_id).toBe(SUP_MEMBER.buildId);
  });

  it('B14: the owner <select> and the move list always resolve to the same ' +
    'member, even for a raw legacy role string baked in before members settled', async () => {
    const { svc } = setup([{
      id: 'c-race2', name: 'Race2', team_id: 't1', description: '',
      sequence: [{ move_name: 'Sup Special', label: 'SS', agent_id: 'support1' }],
    }]);
    const f = withInputs('t1', []);
    const cmp = f.componentInstance as unknown as {
      startEdit: (c: unknown) => void;
      draftSteps: () => { agent_id?: string }[];
      getMoveOptionsForOwner: (buildId: string | undefined) => { value: string }[];
      ownerBuildId: (agentId: string | undefined) => string;
    };
    await settle(f);
    cmp.startEdit((await svc.listForTeam.mock.results[0].value)[0]);
    const ref = f.componentRef as ComponentRef<ComboBuilder>;
    ref.setInput('members', [DPS_MEMBER, SUP_MEMBER]);
    await settle(f);

    const step = cmp.draftSteps()[0];
    // The resolver behind the <select>'s [value] binding...
    const displayedOwner = cmp.ownerBuildId(step.agent_id);
    // ...must name the same member as the move list actually shown.
    const opts = cmp.getMoveOptionsForOwner(step.agent_id);
    expect(opts.map((o) => o.value)).toContain('Sup Special');
    expect(displayedOwner).toBe(SUP_MEMBER.buildId);

    // And the rendered DOM select genuinely shows that member selected —
    // not silently falling back to the first option.
    const el = f.nativeElement as HTMLElement;
    const select = el.querySelector('.agent-select') as HTMLSelectElement;
    expect(select.value).toBe(SUP_MEMBER.buildId);
  });

  it('removes a combo via service.remove and refreshes the list', async () => {
    const { svc } = setup([{
      id: 'c1', name: 'A', team_id: 't1', sequence: [], description: '',
    }]);
    const f = withInputs('t1', [DPS_MEMBER]);
    const cmp = f.componentInstance as unknown as {
      removeCombo: (id: string) => Promise<void>;
    };
    await settle(f);
    await cmp.removeCombo('c1');
    expect(svc.remove).toHaveBeenCalledWith('c1');
    expect(svc.listForTeam).toHaveBeenCalledTimes(2);
  });

  it('new step defaults to the previous step\'s owner; first step to the primary', async () => {
    setup([]);
    const f = withInputs('t1', [DPS_MEMBER, SUP_MEMBER]);
    const cmp = f.componentInstance as unknown as {
      startNew: () => void;
      addStep: () => void;
      updateStepAgent: (i: number, ownerId: string) => void;
      draftSteps: () => { agent_id?: string }[];
    };
    await settle(f);

    cmp.startNew();
    cmp.addStep(); // first step → primary member
    expect(cmp.draftSteps()[0].agent_id).toBe('b1');

    cmp.addStep(); // inherits previous owner (primary)
    expect(cmp.draftSteps()[1].agent_id).toBe('b1');

    cmp.updateStepAgent(1, 'build-sup1'); // reassign step 1 to support
    cmp.addStep(); // inherits the support owner now
    expect(cmp.draftSteps()[2].agent_id).toBe('build-sup1');
  });

  it('reorders steps with moveStep()', async () => {
    setup([]);
    const f = withInputs('t1', [DPS_MEMBER]);
    const cmp = f.componentInstance as unknown as {
      startNew: () => void;
      addStep: () => void;
      updateStep: (i: number, moveName: string, label?: string) => void;
      moveStep: (from: number, to: number) => void;
      draftSteps: () => { label: string }[];
    };
    await settle(f);
    cmp.startNew();
    cmp.addStep(); cmp.updateStep(0, 'Basic 1', 'A');
    cmp.addStep(); cmp.updateStep(1, 'EX Special', 'B');
    cmp.addStep(); cmp.updateStep(2, 'Ultimate', 'C');
    cmp.moveStep(0, 2);
    expect(cmp.draftSteps().map((s) => s.label)).toEqual(['B', 'C', 'A']);
  });

  it('exposes distinct moves derived from the owner\'s attacks', async () => {
    setup([]);
    const f = withInputs('t1', [DPS_MEMBER]);
    const cmp = f.componentInstance as unknown as {
      getMoveOptionsForOwner: (buildId: string) => { value: string; label: string; group?: string }[];
    };
    await settle(f);
    const opts = cmp.getMoveOptionsForOwner('b1');
    expect(opts.map((o) => o.value).sort()).toEqual(
      ['Basic 1', 'EX Special', 'Ultimate'],
    );
    expect(new Set(opts.map((o) => o.group))).toEqual(
      new Set(['Basic', 'EXSpecial', 'Ultimate']),
    );
  });
});

/**
 * Issue #80 — a combo step whose owning build has left the team.
 *
 * Team membership is editable while combos exist, and the edit is LIVE: the team
 * editor's `removeMember` writes a signal, `comboMembers` is a computed off it, and it
 * feeds this component's `members()` input. So an owner can vanish mid-draft with no
 * save in between, leaving a step tagged with a build id that matches no member.
 *
 * The maintainer's ruling: such steps are DROPPED, not re-pointed. Re-pointing them at
 * the primary — what the old fallback and the backend resolver both effectively do —
 * keeps a `move_name` belonging to the removed agent, which may not exist on the
 * primary's kit. The drop happens at SAVE, not at removal, because `removeMember` is a
 * single click with no undo.
 */
describe('ComboBuilder — owner left the team (#80)', () => {
  const GONE_STEP = { move_name: 'Sup Special', label: 'SUP', agent_id: 'build-sup1' };
  const KEPT_STEP = { move_name: 'Basic 1', label: 'BA1', agent_id: 'b1' };

  /** Open the combo for editing with both members, then drop the support. */
  async function draftAfterSupportLeaves(sequence: unknown[]) {
    const { svc } = setup([{
      id: 'c1', name: 'Combo', team_id: 't1', sequence, description: '',
    }]);
    const fixture = TestBed.createComponent(ComboBuilder);
    const ref = fixture.componentRef as ComponentRef<ComboBuilder>;
    ref.setInput('teamId', 't1');
    ref.setInput('members', [DPS_MEMBER, SUP_MEMBER]);
    await settle(fixture);

    const cmp = fixture.componentInstance as unknown as {
      startEdit: (c: unknown) => void;
      saveDraft: () => Promise<void>;
      draftSteps: () => unknown[];
      orphanedSteps: () => unknown[];
    };
    cmp.startEdit({ id: 'c1', name: 'Combo', team_id: 't1', sequence, description: '' });
    await settle(fixture);

    // The support leaves — exactly what team-editor's removeMember does.
    ref.setInput('members', [DPS_MEMBER]);
    await settle(fixture);

    return { svc, fixture, cmp };
  }

  it('renders a distinguishable owner state instead of falling back to option[0]', async () => {
    const { fixture } = await draftAfterSupportLeaves([KEPT_STEP, GONE_STEP]);
    const el = fixture.nativeElement as HTMLElement;

    expect(el.textContent).toMatch(/owner left the team/i);

    // The bug was that no <option> matched, so the browser selected the primary and the
    // step silently read as belonging to Miyabi.
    const selects = Array.from(el.querySelectorAll('select.agent-select'));
    const orphanSelect = selects[1] as HTMLSelectElement;
    expect(orphanSelect.selectedOptions[0]?.textContent).toMatch(/owner left the team/i);
    expect(orphanSelect.selectedOptions[0]?.textContent).not.toContain('Miyabi');
  });

  it('warns before saving that the steps will be dropped', async () => {
    const { fixture } = await draftAfterSupportLeaves([KEPT_STEP, GONE_STEP]);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toMatch(/will be dropped when you save/i);
  });

  it('does not drop them merely because the member was removed', async () => {
    // The whole reason the drop is deferred to save: removeMember is one click, no undo.
    const { svc, cmp } = await draftAfterSupportLeaves([KEPT_STEP, GONE_STEP]);
    expect(cmp.draftSteps()).toHaveLength(2);
    expect(cmp.orphanedSteps()).toHaveLength(1);
    expect(svc.update).not.toHaveBeenCalled();
  });

  it('drops the orphaned step on save, and never re-persists the stale id', async () => {
    const { svc, cmp } = await draftAfterSupportLeaves([KEPT_STEP, GONE_STEP]);
    await cmp.saveDraft();

    expect(svc.update).toHaveBeenCalledTimes(1);
    const sequence = (svc.update.mock.calls[0][1] as { sequence: { agent_id?: string }[] })
      .sequence;
    expect(sequence).toHaveLength(1);
    expect(sequence[0].agent_id).toBe('b1');
    expect(sequence.some((s) => s.agent_id === 'build-sup1')).toBe(false);
  });

  it('re-adding the member keeps the step — the drop is not latched', async () => {
    const { svc, fixture, cmp } = await draftAfterSupportLeaves([KEPT_STEP, GONE_STEP]);
    const ref = fixture.componentRef as ComponentRef<ComboBuilder>;
    ref.setInput('members', [DPS_MEMBER, SUP_MEMBER]);
    await settle(fixture);

    expect(cmp.orphanedSteps()).toHaveLength(0);
    await cmp.saveDraft();
    const sequence = (svc.update.mock.calls[0][1] as { sequence: unknown[] }).sequence;
    expect(sequence).toHaveLength(2);
  });

  it('refuses to save a combo whose every step was orphaned, and says why', async () => {
    // The draft is visibly showing a step, so "needs at least one step" would be
    // contradicted by the screen it appears on. The message has to name the reason.
    const { svc, cmp, fixture } = await draftAfterSupportLeaves([GONE_STEP]);
    await cmp.saveDraft();
    await settle(fixture);

    expect(svc.update).not.toHaveBeenCalled();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toMatch(/every step belongs to a build that has left the team/i);
    expect(text).not.toMatch(/needs a name and at least one step/i);
  });

  it('still reports a genuinely empty draft as empty', async () => {
    // The other side of the branch above: no steps at all is not an owner problem.
    setup([]);
    const fixture = TestBed.createComponent(ComboBuilder);
    const ref = fixture.componentRef as ComponentRef<ComboBuilder>;
    ref.setInput('teamId', 't1');
    ref.setInput('members', [DPS_MEMBER]);
    await settle(fixture);

    const cmp = fixture.componentInstance as unknown as {
      startNew: () => void;
      onNameInput: (e: Event) => void;
      saveDraft: () => Promise<void>;
    };
    cmp.startNew();
    cmp.onNameInput({ target: { value: 'Empty' } } as unknown as Event);
    await cmp.saveDraft();
    await settle(fixture);

    expect((fixture.nativeElement as HTMLElement).textContent)
      .toMatch(/needs a name and at least one step/i);
  });

  it('treats a legacy support role on a short team as orphaned too', async () => {
    // The issue's second case: `support1`/`support2` on a team with fewer members used
    // to resolve to the literal role string and re-persist it forever.
    const { svc } = setup([]);
    const fixture = TestBed.createComponent(ComboBuilder);
    const ref = fixture.componentRef as ComponentRef<ComboBuilder>;
    ref.setInput('teamId', 't1');
    ref.setInput('members', [DPS_MEMBER]);
    await settle(fixture);

    const cmp = fixture.componentInstance as unknown as {
      startEdit: (c: unknown) => void;
      saveDraft: () => Promise<void>;
      orphanedSteps: () => unknown[];
    };
    cmp.startEdit({
      id: 'c1', name: 'Legacy', team_id: 't1', description: '',
      sequence: [KEPT_STEP, { move_name: 'Sup Special', label: 'S', agent_id: 'support2' }],
    });
    await settle(fixture);

    expect(cmp.orphanedSteps()).toHaveLength(1);
    await cmp.saveDraft();
    const sequence = (svc.update.mock.calls[0][1] as { sequence: { agent_id?: string }[] })
      .sequence;
    expect(sequence.some((s) => s.agent_id === 'support2')).toBe(false);
  });

  it('does not flag steps while members() is still empty during load', async () => {
    // The load-order trap the issue calls out: an empty members() must not make every
    // step look orphaned and wipe the combo on the next save.
    setup([]);
    const fixture = TestBed.createComponent(ComboBuilder);
    const ref = fixture.componentRef as ComponentRef<ComboBuilder>;
    ref.setInput('teamId', 't1');
    ref.setInput('members', []);
    await settle(fixture);

    const cmp = fixture.componentInstance as unknown as {
      startEdit: (c: unknown) => void;
      orphanedSteps: () => unknown[];
    };
    cmp.startEdit({
      id: 'c1', name: 'Loading', team_id: 't1', sequence: [KEPT_STEP], description: '',
    });
    await settle(fixture);

    expect(cmp.orphanedSteps()).toHaveLength(0);
  });
});
