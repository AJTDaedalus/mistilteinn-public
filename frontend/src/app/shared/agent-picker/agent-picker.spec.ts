import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { AgentPicker, AgentSummary } from './agent-picker';

const MOCK_AGENTS: AgentSummary[] = [
  {
    id: 'a1',
    name: 'Caesar',
    full_name: 'Caesar King',
    element: 'physical',
    specialty: 'defense',
    rarity: 'S',
    faction: 'sons-of-calydon',
    icon_path: 'caesar.webp', has_potential: false,
    hakushin_id: 1011,
  },
  {
    id: 'a2',
    name: 'Burnice',
    full_name: 'Burnice White',
    element: 'fire',
    specialty: 'anomaly',
    rarity: 'S',
    faction: 'sons-of-calydon',
    icon_path: 'burnice.webp', has_potential: false,
    hakushin_id: 1316,
  },
  {
    id: 'a3',
    name: 'Lucy',
    full_name: 'Luciana Auxesis',
    element: 'fire',
    specialty: 'support',
    rarity: 'A',
    faction: 'sons-of-calydon',
    icon_path: 'lucy.webp', has_potential: false,
    hakushin_id: 1111,
  },
  {
    id: 'a4',
    name: 'Seth',
    full_name: 'Seth Lowell',
    element: 'electric',
    specialty: 'defense',
    rarity: 'A',
    faction: 'pubsec',
    icon_path: 'seth.webp', has_potential: false,
    hakushin_id: 1121,
  },
];

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn();
  HTMLDialogElement.prototype.close = vi.fn();
});

function setup() {
  TestBed.configureTestingModule({
    imports: [AgentPicker],
  });
  const fixture = TestBed.createComponent(AgentPicker);
  const comp = fixture.componentInstance;
  return { fixture, comp };
}

describe('AgentPicker', () => {
  describe('trigger button', () => {
    it('shows placeholder when nothing is selected', () => {
      const { fixture } = setup();
      fixture.componentRef.setInput('placeholder', 'Choose character…');
      fixture.detectChanges();

      const btn = fixture.nativeElement.querySelector('.cb-trigger');
      expect(btn.textContent).toContain('Choose character…');
    });

    it('shows agent name when selected', () => {
      const { fixture } = setup();
      fixture.componentRef.setInput('allAgents', MOCK_AGENTS);
      fixture.componentRef.setInput('selectedId', 'a2');
      fixture.detectChanges();

      const btn = fixture.nativeElement.querySelector('.cb-trigger');
      expect(btn.textContent).toContain('Burnice');
    });

    it('is disabled when disabled input is set to true', () => {
      const { fixture } = setup();
      fixture.componentRef.setInput('disabled', true);
      fixture.detectChanges();

      const btn = fixture.nativeElement.querySelector('.cb-trigger');
      expect(btn.disabled).toBe(true);
    });
  });

  describe('dialog filtering', () => {
    it('resets search and filtering states on open', () => {
      const { comp } = setup();
      comp['search'].set('Burnice');
      comp['selectedElement'].set('fire');
      comp['selectedSpecialty'].set('anomaly');
      comp['selectedFaction'].set('sons-of-calydon');
      comp['activeRarities'].set(['S']);

      comp['openDialog']();

      expect(comp['search']()).toBe('');
      expect(comp['selectedElement']()).toBeNull();
      expect(comp['selectedSpecialty']()).toBeNull();
      expect(comp['selectedFaction']()).toBeNull();
      expect(comp['activeRarities']()).toEqual([]);
    });

    it('filters list by element when selectedElement is set', () => {
      const { comp, fixture } = setup();
      fixture.componentRef.setInput('allAgents', MOCK_AGENTS);
      fixture.detectChanges();

      comp['selectedElement'].set('fire');
      fixture.detectChanges();

      const filtered = comp['filteredAgents']();
      expect(filtered).toHaveLength(2);
      expect(filtered.map((a) => a.name)).toContain('Burnice');
      expect(filtered.map((a) => a.name)).toContain('Lucy');
    });

    it('filters list by specialty when selectedSpecialty is set', () => {
      const { comp, fixture } = setup();
      fixture.componentRef.setInput('allAgents', MOCK_AGENTS);
      fixture.detectChanges();

      comp['selectedSpecialty'].set('defense');
      fixture.detectChanges();

      const filtered = comp['filteredAgents']();
      expect(filtered).toHaveLength(2);
      expect(filtered.map((a) => a.name)).toContain('Caesar');
      expect(filtered.map((a) => a.name)).toContain('Seth');
    });

    it('filters list by faction when selectedFaction is set', () => {
      const { comp, fixture } = setup();
      fixture.componentRef.setInput('allAgents', MOCK_AGENTS);
      fixture.detectChanges();

      comp['selectedFaction'].set('pubsec');
      fixture.detectChanges();

      const filtered = comp['filteredAgents']();
      expect(filtered).toHaveLength(1);
      expect(filtered[0].name).toBe('Seth');
    });

    it('filters list by search text (case insensitive name or full name)', () => {
      const { comp, fixture } = setup();
      fixture.componentRef.setInput('allAgents', MOCK_AGENTS);
      fixture.detectChanges();

      comp['search'].set('lowell');
      fixture.detectChanges();

      const filtered = comp['filteredAgents']();
      expect(filtered).toHaveLength(1);
      expect(filtered[0].name).toBe('Seth');
    });

    it('filters list by active rarities', () => {
      const { comp, fixture } = setup();
      fixture.componentRef.setInput('allAgents', MOCK_AGENTS);
      fixture.detectChanges();

      comp['activeRarities'].set(['S']);
      fixture.detectChanges();

      const filtered = comp['filteredAgents']();
      expect(filtered).toHaveLength(2);
      expect(filtered.map((a) => a.name)).toEqual(['Burnice', 'Caesar']);
    });
  });

  describe('selection', () => {
    it('emits selectedChange with id and closes when an Agent card is clicked', () => {
      const { comp, fixture } = setup();
      fixture.componentRef.setInput('allAgents', MOCK_AGENTS);
      fixture.detectChanges();

      const emitted: (string | null)[] = [];
      comp.selectedChange.subscribe((id) => emitted.push(id));

      comp['selectAgent']('a2');

      expect(emitted).toEqual(['a2']);
      expect(HTMLDialogElement.prototype.close).toHaveBeenCalledOnce();
    });
  });

  describe('sorting priority', () => {
    it('sorts currently selected Agent first', () => {
      const { comp, fixture } = setup();
      fixture.componentRef.setInput('allAgents', MOCK_AGENTS);
      fixture.componentRef.setInput('selectedId', 'a3'); // Lucy
      fixture.detectChanges();

      const sorted = comp['filteredAgents']();
      expect(sorted[0].name).toBe('Lucy');
    });

    it('sorts S-Rank before A-Rank (when selected is not active)', () => {
      const { comp, fixture } = setup();
      fixture.componentRef.setInput('allAgents', MOCK_AGENTS);
      fixture.detectChanges();

      const sorted = comp['filteredAgents']();
      // Burnice and Caesar are S-Rank, Lucy and Seth are A-Rank. Alphabetical S-ranks: Burnice, Caesar
      expect(sorted[0].name).toBe('Burnice');
      expect(sorted[1].name).toBe('Caesar');
      expect(sorted[2].name).toBe('Lucy');
      expect(sorted[3].name).toBe('Seth');
    });
  });
});
