import { describe, expect, it } from 'vitest';

import { teamBuildsTargetFirst, teamMemberSlots } from './team-member-slots';

const NAMES: Record<string, string> = { b1: 'Caesar', b2: 'Burnice', b3: 'Nicole' };
const nameForBuild = (id: string): string | null => NAMES[id] ?? null;

describe('teamMemberSlots', () => {
  it('labels each filled slot by agent name', () => {
    const slots = teamMemberSlots(
      { build1_id: 'b1', build2_id: 'b2', build3_id: 'b3' },
      nameForBuild,
    );
    expect(slots).toEqual([
      { index: 0, label: 'Caesar' },
      { index: 1, label: 'Burnice' },
      { index: 2, label: 'Nicole' },
    ]);
  });

  it('omits empty optional slots', () => {
    const slots = teamMemberSlots(
      { build1_id: 'b1', build2_id: null, build3_id: null },
      nameForBuild,
    );
    expect(slots).toEqual([{ index: 0, label: 'Caesar' }]);
  });

  // build1_id became nullable when Build deletes started SET NULL-ing team
  // slots (D-IM1), so slot 0 can be empty while later slots are filled.
  it('omits an empty slot 0 but keeps the later slots at their own index', () => {
    const slots = teamMemberSlots(
      { build1_id: null, build2_id: 'b2', build3_id: null },
      nameForBuild,
    );
    expect(slots).toEqual([{ index: 1, label: 'Burnice' }]);
  });

  it('returns no slots for a team whose slots are all empty', () => {
    const slots = teamMemberSlots(
      { build1_id: null, build2_id: null, build3_id: null },
      nameForBuild,
    );
    expect(slots).toEqual([]);
  });

  it('falls back to Member N when the agent is unresolved', () => {
    const slots = teamMemberSlots(
      { build1_id: 'unknown', build2_id: 'b2', build3_id: null },
      nameForBuild,
    );
    expect(slots).toEqual([
      { index: 0, label: 'Member 1' },
      { index: 1, label: 'Burnice' },
    ]);
  });
});

describe('teamBuildsTargetFirst', () => {
  const b1 = { id: 'b1' };
  const b2 = { id: 'b2' };
  const b3 = { id: 'b3' };
  const team = { build1_id: 'b1', build2_id: 'b2', build3_id: 'b3' };
  const all = [b3, b1, b2]; // deliberately not in slot order

  it('puts the active member first and the rest in slot order', () => {
    expect(teamBuildsTargetFirst(team, 1, all)).toEqual([b2, b1, b3]);
  });

  it('returns the whole team in slot order when the active member is slot 0', () => {
    expect(teamBuildsTargetFirst(team, 0, all)).toEqual([b1, b2, b3]);
  });

  it('returns [] when the active slot is empty', () => {
    expect(teamBuildsTargetFirst({ build1_id: 'b1', build2_id: null }, 1, all)).toEqual([]);
  });

  it('returns [] when the target build row has not loaded yet', () => {
    expect(teamBuildsTargetFirst(team, 0, [b2, b3])).toEqual([]);
  });

  it('skips members whose rows have not loaded rather than faking them', () => {
    expect(teamBuildsTargetFirst(team, 0, [b1, b3])).toEqual([b1, b3]);
  });

  it('handles a one-member team', () => {
    expect(teamBuildsTargetFirst({ build1_id: 'b1' }, 0, all)).toEqual([b1]);
  });
});
