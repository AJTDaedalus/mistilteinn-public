import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { CONTRACT } from '../../api/contract';
import { BuildsService } from '../builds/builds.service';
import { TeamsPage } from './teams';
import { TEAM_SLOTS, TeamsService } from './teams.service';

const AYAKA = { id: 'char-ayaka', name: 'Kamisato Ayaka' };
const BARBARA = { id: 'char-barbara', name: 'Barbara' };

const AYAKA_C0 = {
  id: 'b-ayaka-c0', character_id: 'char-ayaka', constellation_level: 0,
  character: AYAKA, weapon: null,
};
const AYAKA_C6 = {
  id: 'b-ayaka-c6', character_id: 'char-ayaka', constellation_level: 6,
  character: AYAKA, weapon: null,
};
const BARBARA_B = {
  id: 'b-barbara', character_id: 'char-barbara', constellation_level: 0,
  character: BARBARA, weapon: null,
};

function pageWith(teams: Partial<TeamsService>, builds: Partial<BuildsService>) {
  TestBed.configureTestingModule({
    providers: [
      { provide: TeamsService, useValue: teams },
      { provide: BuildsService, useValue: builds },
    ],
  });
  return TestBed.runInInjectionContext(() => new TeamsPage());
}

function healthy(teams: Partial<TeamsService> = {}, builds: Partial<BuildsService> = {}) {
  return pageWith(
    { list: vi.fn().mockResolvedValue([]), ...teams } as unknown as TeamsService,
    {
      list: vi.fn().mockResolvedValue([AYAKA_C0, AYAKA_C6, BARBARA_B]),
      ...builds,
    } as unknown as BuildsService,
  );
}

describe('TEAM_SLOTS', () => {
  it('is the slot list the API publishes', () => {
    // Mirrored from the server's own `TEAM_SLOTS`, which is itself one definition replacing
    // four hand-written lists — the fork carried ZZZ's three-agent squad into a game with
    // four-character parties and every copy had to be found. Checked against the committed
    // contract rather than trusted, so a fifth slot cannot be added server-side and silently
    // go unoffered here.
    const props = CONTRACT.components.schemas['TeamCreate'].properties ?? {};

    expect(Object.keys(props).filter((k) => k.endsWith('_id')).sort()).toEqual(
      [...TEAM_SLOTS].sort(),
    );
  });
});

describe('TeamsPage', () => {
  it('reports a failed load instead of rendering it as "you have no teams"', async () => {
    const page = healthy({ list: vi.fn().mockRejectedValue(new Error('boom')) });

    await page['load']();

    expect(page['error']()).not.toBeNull();
    expect(page['teams']()).toEqual([]);
    expect(page['loading']()).toBe(false);
  });

  it('offers every build to an empty team', async () => {
    // Guards the guard: every assertion below is about something being *excluded*.
    const page = healthy();
    await page['load']();

    expect(page['availableFor']('build1_id').map((b) => b.id)).toEqual([
      'b-ayaka-c0', 'b-ayaka-c6', 'b-barbara',
    ]);
  });

  it('will not offer a build already in another slot', async () => {
    // `assert_slots_distinct`. The same build twice has no defined meaning — every
    // index-based support selection hands the primary back to itself.
    const page = healthy();
    await page['load']();

    page['pick']('build1_id', 'b-barbara');

    expect(page['availableFor']('build2_id').map((b) => b.id)).not.toContain('b-barbara');
  });

  it('will not offer a second build of a character already on the team', async () => {
    // T.1a. A user may own a C0 and a C6 of one character; gcsim refuses a party holding
    // both, so the picker must not offer the second one.
    const page = healthy();
    await page['load']();

    page['pick']('build1_id', 'b-ayaka-c0');

    const offered = page['availableFor']('build2_id').map((b) => b.id);
    expect(offered).not.toContain('b-ayaka-c6');
    expect(offered).toContain('b-barbara');
  });

  it('a slot that already holds a conflicting build still shows it', async () => {
    // The state the `b.id === current` clause exists for, and the one the first version of
    // this test did not reach: a *saved* team holding two builds of one character. The API
    // refuses to create one, so it can only arrive by being written directly — but if it
    // does, dropping the current value would leave the `<select>` with no option matching
    // its value, and a filled slot would render as empty. The picker would be disagreeing
    // with the state it exists to display.
    const conflicted = {
      id: 't1', name: 'Impossible', build1_id: 'b-ayaka-c0', build2_id: 'b-ayaka-c6',
      build3_id: null, build4_id: null,
    };
    const page = healthy({ list: vi.fn().mockResolvedValue([conflicted]) });
    await page['load']();

    page['edit'](conflicted as never);

    expect(page['availableFor']('build1_id').map((b) => b.id)).toContain('b-ayaka-c0');
    expect(page['availableFor']('build2_id').map((b) => b.id)).toContain('b-ayaka-c6');
    // …and still refuses to offer either as a *new* pick for the empty slots.
    expect(page['availableFor']('build3_id').map((b) => b.id)).toEqual(['b-barbara']);
  });

  it('will not save an unnamed or empty team', async () => {
    const create = vi.fn();
    const page = healthy({ create });
    await page['load']();

    page['name'] = 'Freeze';
    expect(page['canSave']()).toBe(false);
    await page['save']();
    expect(create).not.toHaveBeenCalled();

    page['pick']('build1_id', 'b-ayaka-c0');
    expect(page['canSave']()).toBe(true);
  });

  it('sends every slot, including the empty ones as null', async () => {
    // An omitted slot means "leave it as it was" on a patch, which is a different
    // instruction from "empty it". Sent explicitly so clearing a slot actually clears it.
    const create = vi.fn().mockResolvedValue({ id: 't1' });
    const page = healthy({ create });
    await page['load']();
    page['name'] = 'Freeze';
    page['pick']('build1_id', 'b-ayaka-c0');

    await page['save']();

    expect(create.mock.calls[0][0]).toEqual({
      name: 'Freeze',
      build1_id: 'b-ayaka-c0',
      build2_id: null,
      build3_id: null,
      build4_id: null,
    });
  });

  it('shows the API refusal verbatim rather than inventing its own', async () => {
    // The 422 names the character it saw twice and which slots hold it.
    const detail = 'this team holds Kamisato Ayaka twice (b-ayaka-c0 and b-ayaka-c6).';
    const page = healthy({ create: vi.fn().mockRejectedValue({ detail }) });
    await page['load']();
    page['name'] = 'Two Ayakas';
    page['pick']('build1_id', 'b-ayaka-c0');

    await page['save']();

    expect(page['actionError']()).toBe(detail);
  });

  it('stays in the team it just saved', async () => {
    const saved = { id: 't1', name: 'Freeze', build1_id: 'b-ayaka-c0' };
    const page = healthy({
      update: vi.fn().mockResolvedValue(saved),
      list: vi.fn().mockResolvedValue([saved]),
    });
    await page['load']();
    page['edit'](saved as never);
    page['name'] = 'Renamed';

    await page['save']();

    expect(page['editing']()?.id).toBe('t1');
  });

  it('lists a saved team by who is on it', async () => {
    const team = {
      id: 't1', name: 'Freeze', build1_id: 'b-ayaka-c0', build2_id: 'b-barbara',
      build3_id: null, build4_id: null,
    };
    const page = healthy({ list: vi.fn().mockResolvedValue([team]) });
    await page['load']();

    expect(page['members'](team as never)).toEqual(['Kamisato Ayaka', 'Barbara']);
  });
});
