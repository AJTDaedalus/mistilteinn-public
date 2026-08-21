import { TestBed } from '@angular/core/testing';
import { ComponentRef } from '@angular/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WEnginePicker, type WEngineSummary } from './wengine-picker';

const WENGINES: WEngineSummary[] = [
  { id: 'w1', hakushin_id: 1, name: 'Tusks of Fury', rarity: 'S', specialty: 'stun', base_atk: 48, secondary_stat_type: 'impact', secondary_stat_value: 480, icon_path: '' },
  { id: 'w2', hakushin_id: 2, name: 'Lunar Decoration', rarity: 'A', specialty: 'stun', base_atk: 38, secondary_stat_type: 'atk_pct', secondary_stat_value: 1200, icon_path: '' },
  { id: 'w3', hakushin_id: 3, name: 'Sharpened Stinger', rarity: 'S', specialty: 'attack', base_atk: 46, secondary_stat_type: 'crit_rate', secondary_stat_value: 960, icon_path: '' },
  { id: 'w4', hakushin_id: 4, name: 'Reverb Mark I', rarity: 'B', specialty: 'support', base_atk: 32, secondary_stat_type: 'energy_regen', secondary_stat_value: 1600, icon_path: '' },
  { id: 'w5', hakushin_id: 5, name: 'Fusion Compiler', rarity: 'S', specialty: 'anomaly', base_atk: 46, secondary_stat_type: 'pen_ratio', secondary_stat_value: 960, icon_path: '' },
  { id: 'w6', hakushin_id: 6, name: 'Practiced Perfection', rarity: 'S', specialty: 'anomaly', base_atk: 48, secondary_stat_type: 'anomaly_mastery', secondary_stat_value: 480, icon_path: '' },
];

function setup(selectedId: string | null = null, agentSpecialty: string | null = null, disabled = false) {
  TestBed.configureTestingModule({ imports: [WEnginePicker] });
  const f = TestBed.createComponent(WEnginePicker);
  const ref = f.componentRef as ComponentRef<WEnginePicker>;
  ref.setInput('allWEngines', WENGINES);
  ref.setInput('selectedId', selectedId);
  ref.setInput('agentSpecialty', agentSpecialty);
  ref.setInput('disabled', disabled);
  f.detectChanges();
  return f;
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn();
  HTMLDialogElement.prototype.close = vi.fn();
});

describe('WEnginePicker', () => {
  describe('trigger button', () => {
    it('shows placeholder when nothing is selected', () => {
      const f = setup(null);
      const label = f.nativeElement.querySelector('.cb-trigger__label') as HTMLElement;
      expect(label?.textContent?.trim()).toBe('Select W-Engine…');
    });

    it('shows W-Engine name when selected', () => {
      const f = setup('w1');
      const label = f.nativeElement.querySelector('.cb-trigger__label') as HTMLElement;
      expect(label?.textContent?.trim()).toBe('Tusks of Fury');
    });

    it('is disabled when disabled input is set to true', () => {
      const f = setup(null, null, true);
      const btn = f.nativeElement.querySelector('.cb-trigger') as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
      expect(btn.classList.contains('cb-trigger--disabled')).toBe(true);
    });

    it('calls showModal when clicked and not disabled', () => {
      const f = setup(null);
      const btn = f.nativeElement.querySelector('.cb-trigger') as HTMLButtonElement;
      btn.click();
      expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();
    });
  });

  describe('dialog filtering', () => {
    it('defaults selectedSpecialty to agentSpecialty on open', () => {
      const f = setup(null, 'stun');
      const cmp = f.componentInstance as any;
      cmp.openDialog();
      f.detectChanges();
      expect(cmp.selectedSpecialty()).toBe('stun');
    });

    it('resets search and activeRarities on open', () => {
      const f = setup(null, null);
      const cmp = f.componentInstance as any;
      cmp.search.set('some search');
      cmp.activeRarities.set(['S']);
      
      cmp.openDialog();
      f.detectChanges();
      
      expect(cmp.search()).toBe('');
      expect(cmp.activeRarities()).toEqual([]);
    });

    it('filters list by specialty when selectedSpecialty is set', () => {
      const f = setup(null, null);
      const cmp = f.componentInstance as any;
      cmp.selectedSpecialty.set('stun');
      f.detectChanges();
      const filtered = cmp.filteredWEngines();
      expect(filtered.length).toBe(2);
      expect(filtered.every((w: any) => w.specialty === 'stun')).toBe(true);
    });

    it('filters list by search text (case insensitive)', () => {
      const f = setup(null, null);
      const cmp = f.componentInstance as any;
      cmp.search.set('STINGER');
      f.detectChanges();
      const filtered = cmp.filteredWEngines();
      expect(filtered.length).toBe(1);
      expect(filtered[0].name).toBe('Sharpened Stinger');
    });

    it('filters list by active rarities', () => {
      const f = setup(null, null);
      const cmp = f.componentInstance as any;
      cmp.activeRarities.set(['S', 'A']);
      f.detectChanges();
      const filtered = cmp.filteredWEngines();
      // Should show 'w1' (S), 'w2' (A), 'w3' (S), 'w5' (S), 'w6' (S). w4 (B) should be filtered out.
      expect(filtered.length).toBe(5);
      expect(filtered.every((w: any) => w.rarity !== 'B')).toBe(true);
    });
  });

  describe('selection', () => {
    it('emits selectedChange with id and closes when a W-Engine is clicked', () => {
      const f = setup(null);
      const emitted: (string | null)[] = [];
      f.componentInstance.selectedChange.subscribe((id) => emitted.push(id));

      const cards = f.nativeElement.querySelectorAll('.wengine-card') as NodeListOf<HTMLButtonElement>;
      cards[0].click(); // click first card in grid

      expect(emitted.length).toBe(1);
      expect(emitted[0]).toBeTruthy(); // should be first sorted id
      expect(HTMLDialogElement.prototype.close).toHaveBeenCalled();
    });

    it('emits null when unequip is clicked', () => {
      const f = setup('w1');
      f.detectChanges();
      const emitted: (string | null)[] = [];
      f.componentInstance.selectedChange.subscribe((id) => emitted.push(id));

      const unequipBtn = f.nativeElement.querySelector('.wp-header-actions .link-btn') as HTMLButtonElement;
      unequipBtn.click();

      expect(emitted.length).toBe(1);
      expect(emitted[0]).toBeNull();
      expect(HTMLDialogElement.prototype.close).toHaveBeenCalled();
    });
  });

  describe('sorting priority', () => {
    it('sorts currently selected W-Engine first', () => {
      const f = setup('w3', 'stun'); // selected w3, agent spec stun
      f.detectChanges();
      const cmp = f.componentInstance as any;
      const sorted = cmp.filteredWEngines();
      expect(sorted[0].id).toBe('w3'); // selected w3 is first despite stun filter preference
    });

    it('sorts agent specialty matches before other specialties', () => {
      const f = setup(null, 'stun'); // agent spec stun
      f.detectChanges();
      const cmp = f.componentInstance as any;
      const sorted = cmp.filteredWEngines();
      // Stun weapons (w1, w2) should be sorted before attack/support (w3, w4)
      expect(sorted[0].specialty).toBe('stun');
      expect(sorted[1].specialty).toBe('stun');
    });

    it('sorts higher rarities first for matching specialties', () => {
      const f = setup(null, 'stun'); // agent spec stun
      f.detectChanges();
      const cmp = f.componentInstance as any;
      const sorted = cmp.filteredWEngines();
      // w1 (S) should sort before w2 (A)
      expect(sorted[0].id).toBe('w1');
      expect(sorted[1].id).toBe('w2');
    });

    it('sorts agent signature W-Engine to the absolute top of matches', () => {
      TestBed.configureTestingModule({ imports: [WEnginePicker] });
      const f = TestBed.createComponent(WEnginePicker);
      const ref = f.componentRef as ComponentRef<WEnginePicker>;
      ref.setInput('allWEngines', WENGINES);
      ref.setInput('agentSpecialty', 'stun');
      ref.setInput('agentName', 'Caesar');
      f.detectChanges();

      const cmp = f.componentInstance as any;
      const sorted = cmp.filteredWEngines();
      // w1 is 'Tusks of Fury' (Caesar's signature). It should sort first.
      expect(sorted[0].id).toBe('w1');
    });

    it('sorts agent signature W-Engine case-insensitively with trailing whitespace', () => {
      TestBed.configureTestingModule({ imports: [WEnginePicker] });
      const f = TestBed.createComponent(WEnginePicker);
      const ref = f.componentRef as ComponentRef<WEnginePicker>;
      ref.setInput('allWEngines', WENGINES);
      ref.setInput('agentSpecialty', 'stun'); // agent is stun, but signature is attack (w3)
      ref.setInput('agentName', '  jAnE  '); // Case and whitespace variation of 'jane'
      f.detectChanges();

      const cmp = f.componentInstance as any;
      const sorted = cmp.filteredWEngines();
      // w3 is 'Sharpened Stinger' (Jane's signature). It should sort first despite different specialty.
      expect(sorted[0].id).toBe('w3');
    });

    it('sorts Alice signature W-Engine to the top of anomaly matching list', () => {
      TestBed.configureTestingModule({ imports: [WEnginePicker] });
      const f = TestBed.createComponent(WEnginePicker);
      const ref = f.componentRef as ComponentRef<WEnginePicker>;
      ref.setInput('allWEngines', WENGINES);
      ref.setInput('agentSpecialty', 'anomaly'); // agent is anomaly
      ref.setInput('agentName', 'Alice'); // Agent is Alice
      f.detectChanges();

      const cmp = f.componentInstance as any;
      const sorted = cmp.filteredWEngines();
      // w6 is 'Practiced Perfection' (Alice's signature). It should sort first.
      expect(sorted[0].id).toBe('w6');
    });
  });
});
