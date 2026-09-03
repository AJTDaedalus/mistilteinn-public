import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { RotationTimeline } from './timeline';
import type { RosterCharacter, RotationStep } from '../rotations.service';

const NAHIDA: RosterCharacter = {
  nanoka_id: '10000073', name: 'Nahida', element: 'Dendro', icon: 'UI_AvatarIcon_Nahida',
  abilities: {},
  actions: [
    { action: 'skill', base: 'skill', variant: null, name: 'All Schemes to Know',
      icon: 'Skill_S_Nahida_01' },
    { action: 'skill_hold', base: 'skill', variant: 'hold', name: 'All Schemes to Know',
      icon: 'Skill_S_Nahida_01' },
    { action: 'charge', base: 'charge', variant: null, name: 'charge', icon: null },
  ],
};

const XINGQIU: RosterCharacter = {
  nanoka_id: '10000025', name: 'Xingqiu', element: 'Hydro', icon: 'UI_AvatarIcon_Xingqiu',
  abilities: {},
  actions: [
    { action: 'burst', base: 'burst', variant: null, name: 'Raincutter',
      icon: 'Skill_E_Xingqiu_01' },
  ],
};

/**
 * Dahlia declares `short_hold` and no `hold`, which is why `VARIANT_PARAMS` has three entries
 * and not one — offering `hold` alone would leave her out. Read from gcsim's own generated
 * validation table, not invented for this fixture.
 */
const DAHLIA: RosterCharacter = {
  nanoka_id: '10000105', name: 'Dahlia', element: 'Hydro', icon: 'UI_AvatarIcon_Dahlia',
  abilities: {},
  actions: [
    { action: 'skill', base: 'skill', variant: null, name: 'Radiant Psalter', icon: null },
    { action: 'skill_short_hold', base: 'skill', variant: 'short_hold',
      name: 'Radiant Psalter', icon: null },
  ],
};

function step(character: string, action: string, extra: Partial<RotationStep> = {}) {
  return {
    character, action, repeat: 1, note: '', group: '', group_repeat: 1, group_condition: '', ...extra,
  } as RotationStep;
}

function render(steps: RotationStep[], options: {
  selection?: { start: number; end: number } | null;
  measured?: { character: number; key: string; start: number; end: number; actions: number }[]
    | null;
} = {}) {
  TestBed.configureTestingModule({ imports: [RotationTimeline] });
  const fixture = TestBed.createComponent(RotationTimeline);
  fixture.componentRef.setInput('steps', steps);
  fixture.componentRef.setInput('roster', [NAHIDA, XINGQIU, DAHLIA]);
  fixture.componentRef.setInput('selection', options.selection ?? null);
  fixture.componentRef.setInput('measured', options.measured ?? null);
  fixture.detectChanges();
  return fixture.nativeElement as HTMLElement;
}

describe('RotationTimeline — authored', () => {
  it('draws one tile per step', () => {
    const el = render([
      step('10000073', 'skill'), step('10000073', 'charge'), step('10000025', 'burst'),
    ]);

    expect(el.querySelectorAll('.tile')).toHaveLength(3);
  });

  it('breaks a run where the character changes, which is where the swap is', () => {
    // gcsim emits no swap actions — naming a different character swaps to them implicitly
    // (`DESIGN_rotation.md` §3.3) — so the compiled config does not show them anywhere. The
    // run boundary is the only place a user can see one.
    const el = render([
      step('10000073', 'skill'), step('10000073', 'charge'),
      step('10000025', 'burst'),
      step('10000073', 'skill'),
    ]);

    expect(el.querySelectorAll('.run')).toHaveLength(3);
  });

  it('names the character on every run, not only colours it', () => {
    // Seven Genshin element hues include two blues and two greens, and `ElementChip`'s rule
    // is that colour is never the only channel.
    const el = render([step('10000073', 'skill'), step('10000025', 'burst')]);

    const names = [...el.querySelectorAll('.run__name')].map((n) => n.textContent?.trim());
    expect(names).toEqual(['Nahida', 'Xingqiu']);
  });

  it('colours a run by its element', () => {
    const el = render([step('10000073', 'skill')]);

    expect((el.querySelector('.run') as HTMLElement).style.getPropertyValue('--element'))
      .toBe('var(--element-dendro)');
  });

  it('falls back rather than colouring an element it does not know', () => {
    const el = render([step('nobody', 'skill')]);

    expect((el.querySelector('.run') as HTMLElement).style.getPropertyValue('--element'))
      .toBe('var(--element-none)');
  });

  it('draws the ability sprite, and the word where there is none', () => {
    // Owner ruling: the actions that are not talents are words, not glyphs — and they keep
    // their key rather than borrowing the normal attack's name. The key is *formatted*
    // though: the letter a rotation is written with, and no underscores.
    const el = render([step('10000073', 'skill'), step('10000073', 'charge')]);

    const tiles = el.querySelectorAll('.tile');
    expect(tiles[0].querySelector('img')).not.toBeNull();
    expect(tiles[1].querySelector('.tile__word')?.textContent?.trim()).toBe('C - Charge');
  });

  it('badges a variant and still says the word in the label', () => {
    // The owner chose the compact badge. It is never the only channel: the accessible name
    // spells the variant out, which is also what find-in-page and a screen reader get.
    const el = render([step('10000073', 'skill_hold')]);

    const tile = el.querySelector('.tile') as HTMLElement;
    expect(tile.querySelector('.tile__badge')?.textContent?.trim()).toBe('h');
    expect(tile.getAttribute('aria-label')).toContain('(hold)');
  });

  it('badges a short hold with an s, not an h', () => {
    // `short_hold` and `hold` are different parameters and gcsim refuses the wrong one. Two
    // moves sharing a badge would be the compact form losing the distinction it exists for.
    // One render per test: `TestBed` cannot be reconfigured once a component is instantiated.
    const el = render([step('10000105', 'skill_short_hold')]);

    expect(el.querySelector('.tile__badge')?.textContent?.trim()).toBe('s');
  });

  it('shows a repeat as a badge on one tile, not as several tiles', () => {
    // One step is one tile. `attack:3` is a single gcsim token and a single thing to drag.
    const el = render([step('10000073', 'skill', { repeat: 3 })]);

    expect(el.querySelectorAll('.tile')).toHaveLength(1);
    expect(el.querySelector('.tile__repeat')?.textContent?.trim()).toBe('×3');
  });

  it('marks the selected span and nothing else', () => {
    const el = render(
      [step('10000073', 'skill'), step('10000073', 'charge'), step('10000073', 'skill')],
      { selection: { start: 1, end: 2 } },
    );

    const pressed = [...el.querySelectorAll('.tile')]
      .map((t) => t.getAttribute('aria-pressed'));
    expect(pressed).toEqual(['false', 'true', 'true']);
  });

  it('draws a group as one run with its repeat', () => {
    const el = render([
      step('10000073', 'skill', { group: 'g', group_repeat: 3, group_condition: '' }),
      step('10000073', 'charge', { group: 'g', group_repeat: 3, group_condition: '' }),
    ]);

    expect(el.querySelectorAll('.run')).toHaveLength(1);
    expect(el.querySelector('.run__group')?.textContent?.trim()).toBe('×3');
  });

  it('breaks a run at a group boundary even for the same character', () => {
    // A bracket drawn across the boundary would say the repeat covered the ungrouped step.
    const el = render([
      step('10000073', 'skill', { group: 'g', group_repeat: 2, group_condition: '' }),
      step('10000073', 'charge'),
    ]);

    expect(el.querySelectorAll('.run')).toHaveLength(2);
  });

  it('says so rather than drawing nothing when there are no steps', () => {
    expect(render([]).textContent).toContain('No steps yet');
  });
});

describe('RotationTimeline — measured', () => {
  const TRACE = [
    { character: 2, key: 'nicole', start: 1, end: 117, actions: 2 },
    { character: 1, key: 'chevreuse', start: 160, end: 245, actions: 4 },
    { character: 2, key: 'nicole', start: 280, end: 345, actions: 4 },
  ];

  it('draws the measured stretches instead of the authored tiles', () => {
    // One component, two states. A user pressing Run watches their rotation become the real
    // one; two components would drift into a second renderer that agreed by accident.
    const el = render([step('10000073', 'skill')], { measured: TRACE });

    expect(el.querySelectorAll('.tile')).toHaveLength(0);
    expect(el.querySelectorAll('.band__run')).toHaveLength(3);
  });

  it('counts the cycles by how often the opener comes round', () => {
    const el = render([step('10000073', 'skill')], { measured: TRACE });

    expect(el.textContent).toContain('2 cycles');
  });

  it('counts swaps as transitions, not as stretches', () => {
    // Three stretches are two swaps: the first stretch is where the rotation started, not
    // somewhere it swapped to. Checked against a real run — gcsim logged 26 explicit swap
    // actions for the 27 stretches this derives from the four-character config.
    const el = render([step('10000073', 'skill')], { measured: TRACE });

    expect(el.textContent).toContain('3 stretches');
    expect(el.textContent).toContain('2 swaps');
  });

  it('says nothing executed rather than drawing an empty band', () => {
    // A rotation whose every gate stayed closed is a real answer, and it is the answer the
    // measured timeline exists to make visible.
    const el = render([step('10000073', 'skill')], { measured: [] });

    expect(el.textContent).toContain('Nothing executed');
  });

  it('gives a one-action stretch a visible width', () => {
    const el = render([step('10000073', 'skill')], {
      measured: [{ character: 0, key: 'nahida', start: 10, end: 10, actions: 1 }],
    });

    const run = el.querySelector('.band__run') as HTMLElement;
    expect(parseFloat(run.style.width)).toBeGreaterThan(0);
  });
});
