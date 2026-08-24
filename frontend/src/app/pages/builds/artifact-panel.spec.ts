import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { ArtifactsService } from '../artifacts/artifacts.service';
import { ArtifactPanel } from './artifact-panel';

const OPTIONS = {
  stats: [{ key: 'FIGHT_PROP_CRITICAL_HURT', display: 'CRIT DMG', percentage: true }],
  slots: [
    { key: 'equip_bracer', display: 'Flower' },
    { key: 'equip_dress', display: 'Circlet' },
  ],
  rarities: [{ key: 'five_star', stars: 5 }],
};

function piece(id: string, slot: string, buildId: string | null = null) {
  return {
    id, slot, rarity: 'five_star', level: 20,
    main_stat_type: 'FIGHT_PROP_CRITICAL_HURT', main_stat_value: 0.622,
    substats: [], artifact_set_id: 's1', set_name: 'Blizzard Strayer', build_id: buildId,
  };
}

function panelWith(service: Partial<ArtifactsService>, buildId: string | null = 'b1') {
  TestBed.configureTestingModule({
    providers: [{ provide: ArtifactsService, useValue: service }],
  });
  const fixture = TestBed.createComponent(ArtifactPanel);
  fixture.componentRef.setInput('buildId', buildId);
  return fixture;
}

function healthy(overrides: Partial<ArtifactsService> = {}, buildId: string | null = 'b1') {
  const list = vi.fn(async (filters: Record<string, unknown> = {}) => {
    if (filters['build_id']) {
      return { items: [piece('worn', 'equip_dress', 'b1')], total: 1, truncated: false };
    }
    return {
      items: [piece('spare-flower', 'equip_bracer'), piece('spare-circlet', 'equip_dress')],
      total: 2,
      truncated: false,
    };
  });
  return panelWith(
    {
      options: vi.fn().mockResolvedValue(OPTIONS),
      list,
      equip: vi.fn().mockResolvedValue(piece('spare-flower', 'equip_bracer', 'b1')),
      ...overrides,
    } as unknown as ArtifactsService,
    buildId,
  );
}

/**
 * Runs the effect and lets its awaits settle.
 *
 * `whenStable()` alone is not enough: the load is an `async` method fired from an `effect`,
 * so its promise chain is not something the fixture tracks. A macrotask turn flushes the
 * mocked promises, and a second `detectChanges` renders what they produced.
 */
async function settle(fixture: ReturnType<typeof panelWith>) {
  fixture.detectChanges();
  await new Promise((resolve) => setTimeout(resolve, 0));
  fixture.detectChanges();
}

describe('ArtifactPanel', () => {
  it('says to save the build rather than showing five inert slots', async () => {
    // A piece is equipped *to a build*, so there is nothing to attach it to yet.
    const fixture = healthy({}, null);

    await settle(fixture);

    expect(fixture.componentInstance['hasBuild']()).toBe(false);
    expect(fixture.componentInstance['slots']()).toEqual([]);
  });

  it('shows what the build already holds, per slot', async () => {
    const fixture = healthy();

    await settle(fixture);

    const slots = fixture.componentInstance['slots']();
    expect(slots.map((s) => s.display)).toEqual(['Flower', 'Circlet']);
    expect(slots[0].equipped).toBeNull();
    expect(slots[1].equipped?.id).toBe('worn');
  });

  it('offers only unequipped pieces, and only of that slot', async () => {
    // A.1 refuses a filled slot by name rather than swapping, so offering an equipped piece
    // would let a user pick one and be told their own choice is invalid. And a plume in the
    // flower slot is not a thing the API would take either.
    const fixture = healthy();

    await settle(fixture);

    const slots = fixture.componentInstance['slots']();
    expect(slots[0].candidates.map((c) => c.id)).toEqual(['spare-flower']);
    expect(slots[1].candidates.map((c) => c.id)).toEqual(['spare-circlet']);
  });

  it('asks the server for spare pieces rather than filtering everything client-side', async () => {
    const fixture = healthy();

    await settle(fixture);

    const list = fixture.componentInstance['service'].list as ReturnType<typeof vi.fn>;
    expect(list).toHaveBeenCalledWith({ build_id: 'b1' });
    expect(list).toHaveBeenCalledWith({ equipped: false });
  });

  it('equips through the API and reloads', async () => {
    const equip = vi.fn().mockResolvedValue(piece('spare-flower', 'equip_bracer', 'b1'));
    const fixture = healthy({ equip } as unknown as ArtifactsService);
    await settle(fixture);

    await fixture.componentInstance['equip']('spare-flower');

    expect(equip).toHaveBeenCalledWith('spare-flower', 'b1');
  });

  it('unequips with null rather than deleting', async () => {
    // `SET NULL`, not cascade: taking a piece off a build must not destroy the piece.
    const equip = vi.fn().mockResolvedValue(piece('worn', 'equip_dress', null));
    const fixture = healthy({ equip } as unknown as ArtifactsService);
    await settle(fixture);
    const circlet = fixture.componentInstance['slots']()[1];

    await fixture.componentInstance['unequip'](circlet);

    expect(equip).toHaveBeenCalledWith('worn', null);
  });

  it('does nothing when the picker is cleared rather than equipping nothing', async () => {
    const equip = vi.fn();
    const fixture = healthy({ equip } as unknown as ArtifactsService);
    await settle(fixture);

    await fixture.componentInstance['equip']('');

    expect(equip).not.toHaveBeenCalled();
  });

  it('shows the API refusal verbatim', async () => {
    // A.1's 422 names the piece already in the slot, which beats anything this panel could
    // invent.
    const detail = 'that build already has a Flower equipped (abc).';
    const fixture = healthy({
      equip: vi.fn().mockRejectedValue({ detail }),
    } as unknown as ArtifactsService);
    await settle(fixture);

    await fixture.componentInstance['equip']('spare-flower');

    expect(fixture.componentInstance['error']()).toBe(detail);
  });

  it('surfaces a failed load rather than showing five empty slots', async () => {
    // Five empty slots read as "you own nothing that fits" — a different and much more
    // discouraging statement than "this did not load".
    const fixture = healthy({
      list: vi.fn().mockRejectedValue(new Error('boom')),
    } as unknown as ArtifactsService);

    await settle(fixture);

    expect(fixture.componentInstance['error']()).not.toBeNull();
    expect(fixture.componentInstance['slots']()).toEqual([]);
  });

  it('renders a main stat through the published vocabulary', async () => {
    const fixture = healthy();
    await settle(fixture);

    const worn = fixture.componentInstance['slots']()[1].equipped!;

    expect(fixture.componentInstance['describe'](worn)).toBe('CRIT DMG 62.2%');
  });
});
