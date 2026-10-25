import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { AuthService } from '../../api/auth.service';
import { BuildsService } from '../builds/builds.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService } from '../teams/teams.service';
import { ArtifactsContextService } from './artifacts-context.service';

function setup() {
  const token = signal<string | null>('first-user');
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      { provide: AuthService, useValue: { token } },
      { provide: BuildsService, useValue: { list: vi.fn().mockResolvedValue([]) } },
      {
        provide: RotationsService,
        useValue: { list: vi.fn().mockResolvedValue({ items: [{ id: 'r1', name: 'R', team_id: 't1' }] }) },
      },
      { provide: TeamsService, useValue: { list: vi.fn().mockResolvedValue([]) } },
    ],
  });
  return { token, context: TestBed.inject(ArtifactsContextService) };
}

/** `DESIGN_upgrade_estimator.md` §11 — the picker shared by Rank and Upgrade. */
describe('ArtifactsContextService', () => {
  it('forgets the selection when the signed-in account changes', async () => {
    const { token, context } = setup();
    await context.load();
    context.rotationId.set('r1');
    context.buildId.set('b1');
    TestBed.tick();

    token.set('second-user');
    TestBed.tick();

    // The next account must not inherit an enabled Estimate button for ids it does not own.
    expect(context.rotationId()).toBe('');
    expect(context.buildId()).toBe('');
    expect(context.rotationChoices()).toEqual([]);
  });

  it('loads once, however many tabs ask', async () => {
    const { context } = setup();
    await Promise.all([context.load(), context.load()]);
    expect(TestBed.inject(RotationsService).list).toHaveBeenCalledTimes(1);
    expect(context.rotationChoices()).toEqual([{ id: 'r1', label: 'R' }]);
  });

  it('is not ready for a choice outside its own list', async () => {
    const { context } = setup();
    await context.load();
    context.rotationId.set('not-mine');
    expect(context.ready()).toBe(false);
  });
});
