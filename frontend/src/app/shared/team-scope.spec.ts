import { describe, expect, it } from 'vitest';

import type { BuildRead } from '../pages/builds/builds.service';
import type { TeamRead } from '../pages/teams/teams.service';
import { buildOptions, buildsInTeam, teamOptions } from './team-scope';

/**
 * The "start from a team" projection, shared by Optimize and Compare.
 *
 * Extracted at the second use rather than the fourth. The functions are small; the decisions
 * in them are what would drift between copies, so those are what these tests pin.
 */

const build = (id: string, name: string, icon = `art-${name}`) => ({
  id,
  constellation_level: 2,
  weapon_display: 'Mistsplitter Reforged · R1 · Lv90',
  character: { id: `c-${id}`, name, icon },
  weapon: { id: 'w1', name: 'Mistsplitter Reforged' },
}) as unknown as BuildRead;

const BUILDS = [build('b1', 'Ayaka'), build('b2', 'Ganyu'), build('b3', 'Xingqiu')];

const team = (over: Partial<TeamRead> = {}) => ({
  id: 't1', name: 'Freeze',
  build1_id: 'b2', build2_id: 'b3', build3_id: null, build4_id: null,
  ...over,
}) as TeamRead;

describe('buildsInTeam', () => {
  it('returns the whole list when no team is chosen', () => {
    // Clearing the team widens the grid back to everything rather than emptying it: a build in
    // no team would otherwise be unreachable, which on the owner's account is most of them.
    expect(buildsInTeam(null, BUILDS)).toEqual(BUILDS);
  });

  it('keeps the team in slot order, not in the build list order', () => {
    // A team's first slot is its first slot. Sorting by anything else would silently reorder
    // the party a user arranged.
    expect(buildsInTeam(team(), BUILDS).map((b) => b.character?.name))
      .toEqual(['Ganyu', 'Xingqiu']);
  });

  it('skips a slot pointing at a build that no longer exists', () => {
    // Rendering it as a gap would put an empty card in a party of four and invite the reader
    // to wonder which character it was.
    expect(buildsInTeam(team({ build3_id: 'deleted' }), BUILDS)).toHaveLength(2);
  });
});

describe('teamOptions', () => {
  it('carries all four faces rather than electing one to stand for the team', () => {
    const [card] = teamOptions([team()], BUILDS);

    expect(card.icons).toEqual(['art-Ganyu', 'art-Xingqiu']);
  });

  it('puts the party in the searchable line', () => {
    // "Which of my teams has Nahida" is how anyone looks for a team they named "Bloom 2", and
    // `CardPicker` searches label plus detail.
    const [card] = teamOptions([team()], BUILDS);

    expect(card.label).toBe('Freeze');
    expect(card.detail).toBe('Ganyu · Xingqiu');
  });
});

describe('buildOptions', () => {
  it('shows the loadout as the second line', () => {
    const [card] = buildOptions([BUILDS[0]]);

    expect(card).toEqual({
      value: 'b1',
      label: 'Ayaka',
      icon: 'art-Ayaka',
      detail: 'C2 · Mistsplitter Reforged · R1 · Lv90',
    });
  });

  it('says "no weapon" rather than leaving the line half-written', () => {
    const weaponless = { ...BUILDS[0], weapon_display: null, weapon: null } as BuildRead;

    expect(buildOptions([weaponless])[0].detail).toBe('C2 · no weapon');
  });

  it('names a build whose character is missing rather than showing an empty card', () => {
    const orphan = { ...BUILDS[0], character: null } as BuildRead;

    expect(buildOptions([orphan])[0].label).toBe('No character');
  });
});
