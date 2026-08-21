import { describe, it, expect } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { BuffRosterPanelComponent } from './buff-roster-panel.component';
import type { components } from '../../api/api.types';

type BuffRosterEntrySchema = components['schemas']['BuffRosterEntrySchema'];

function entry(
  overrides: Partial<BuffRosterEntrySchema> & { source_label: string },
): BuffRosterEntrySchema {
  return {
    source_category: null,
    source_kind: null,
    owner_agent_name: null,
    stat: 'dmg_bonus',
    zone: 'boost',
    value_bp: 500,
    magnitude_display: '+5.00%',
    condition: null,
    is_modeled: true,
    notes: null,
    ...overrides,
  };
}

async function render(agentLabel: string, roster: BuffRosterEntrySchema[]) {
  @Component({
    standalone: true,
    imports: [BuffRosterPanelComponent],
    template: `<app-buff-roster-panel [agentLabel]="agentLabel" [roster]="roster" />`,
  })
  class Host {
    agentLabel = agentLabel;
    roster = roster;
  }
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture.nativeElement as HTMLElement;
}

describe('BuffRosterPanelComponent', () => {
  it('shows the agent label heading', async () => {
    const el = await render('Ellen Joe', [entry({ source_label: 'Core F', source_category: 'agent' })]);
    expect(el.textContent).toContain('Ellen Joe');
  });

  it('shows an empty state when the roster has no entries', async () => {
    const el = await render('Ellen Joe', []);
    expect(el.textContent).toMatch(/no resolved buffs/i);
  });

  it('renders every entry once, grouped by category', async () => {
    const roster = [
      entry({ source_label: 'Core F', source_category: 'agent', stat: 'crit_dmg' }),
      entry({ source_label: 'Deep Sea', source_category: 'wengine', stat: 'atk_pct' }),
      entry({ source_label: 'Polar 4pc', source_category: 'disc_set', stat: 'fire_dmg' }),
    ];
    const el = await render('Ellen Joe', roster);
    const text = el.textContent ?? '';
    expect(text).toContain('Core F');
    expect(text).toContain('Deep Sea');
    expect(text).toContain('Polar 4pc');
  });

  it('uses in-game stat nomenclature, not the raw field key', async () => {
    const el = await render('Ellen Joe', [
      entry({ source_label: 'Frost Bite', stat: 'crit_dmg', magnitude_display: '+20.00%' }),
    ]);
    const text = el.textContent ?? '';
    expect(text).toContain('CRIT DMG');
    expect(text).not.toContain('crit_dmg');
  });

  it('shows a "not yet modeled" tag on is_modeled=false rows without hiding them', async () => {
    const el = await render('Ellen Joe', [
      entry({ source_label: 'Unbaked buff', is_modeled: false, magnitude_display: '+0.00%' }),
    ]);
    const text = el.textContent ?? '';
    expect(text).toContain('Unbaked buff');
    expect(text).toMatch(/not yet modeled/i);
  });

  it('does not show the tag for modeled rows', async () => {
    const el = await render('Ellen Joe', [entry({ source_label: 'Modeled buff', is_modeled: true })]);
    expect(el.textContent ?? '').not.toMatch(/not yet modeled/i);
  });

  it('shows the condition when present', async () => {
    const el = await render('Ellen Joe', [
      entry({ source_label: 'Conditional buff', condition: 'stun_active' }),
    ]);
    expect(el.textContent ?? '').toContain('stun_active');
  });

  it('puts notes in a tooltip title attribute rather than inline text', async () => {
    const el = await render('Ellen Joe', [
      entry({ source_label: 'Cited buff', notes: 'Per Leifa reference doc' }),
    ]);
    const row = el.querySelector('[title="Per Leifa reference doc"]');
    expect(row).not.toBeNull();
  });
});
