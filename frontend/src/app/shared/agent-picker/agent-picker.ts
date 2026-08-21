import {
  Component,
  computed,
  input,
  output,
  signal,
  viewChild,
  ElementRef,
} from '@angular/core';

import { TitleCasePipe } from '@angular/common';
import type { components } from '../../api/api.types';
import { agentIconUrl, specialtyIconUrl, elementIconUrl, factionIconUrl } from '../icon-url';

export type AgentSummary = components['schemas']['AgentSummary'];

@Component({
  selector: 'agent-picker',
  standalone: true,
  imports: [TitleCasePipe],
  templateUrl: './agent-picker.html',
  styleUrl: './agent-picker.scss',
})
export class AgentPicker {
  allAgents = input<AgentSummary[]>([]);
  selectedId = input<string | null>(null);
  disabled = input<boolean>(false);
  placeholder = input<string>('Select agent…');

  selectedChange = output<string | null>();

  protected dialogRef = viewChild<ElementRef<HTMLDialogElement>>('pickerDialog');
  protected search = signal('');
  protected selectedElement = signal<string | null>(null);
  protected selectedSpecialty = signal<string | null>(null);
  protected selectedFaction = signal<string | null>(null);
  protected factionDropdownOpen = signal(false);
  protected activeRarities = signal<string[]>([]);

  protected readonly agentIcon = agentIconUrl;
  protected readonly specialtyIcon = specialtyIconUrl;
  protected readonly elementIcon = elementIconUrl;
  protected readonly factionIcon = factionIconUrl;

  protected selectedAgent = computed(() => {
    return this.allAgents().find((a) => a.id === this.selectedId()) ?? null;
  });

  protected elements = ['physical', 'fire', 'ice', 'electric', 'ether', 'wind'] as const;
  protected specialties = ['attack', 'stun', 'anomaly', 'support', 'defense', 'rupture'] as const;
  protected rarities = ['S', 'A'] as const;

  protected uniqueFactions = computed(() => {
    const list = this.allAgents()
      .map((a) => a.faction)
      .filter((f): f is string => !!f);
    return [...new Set(list)].sort();
  });

  protected filteredAgents = computed(() => {
    const q = this.search().toLowerCase().trim();
    const elem = this.selectedElement();
    const spec = this.selectedSpecialty();
    const fact = this.selectedFaction();
    const rars = this.activeRarities();

    let list = this.allAgents();

    // 1. Text filter
    if (q) {
      list = list.filter(
        (a) =>
          a.name.toLowerCase().includes(q) ||
          a.full_name?.toLowerCase().includes(q)
      );
    }

    // 2. Element filter
    if (elem) {
      list = list.filter((a) => a.element.toLowerCase() === elem.toLowerCase());
    }

    // 3. Specialty filter
    if (spec) {
      list = list.filter((a) => a.specialty.toLowerCase() === spec.toLowerCase());
    }

    // 4. Faction filter
    if (fact) {
      list = list.filter((a) => a.faction === fact);
    }

    // 5. Rarity filter
    if (rars.length > 0) {
      list = list.filter((a) => rars.includes(a.rarity));
    }

    // Sort: selected Agent first, then rarity S -> A, then alphabetical name
    const currentId = this.selectedId();

    return [...list].sort((a, b) => {
      // Selected first
      if (a.id === currentId && b.id !== currentId) return -1;
      if (b.id === currentId && a.id !== currentId) return 1;

      // Rarity sort (S -> A)
      const rarityRank: Record<string, number> = { S: 2, A: 1 };
      const aRank = rarityRank[a.rarity] ?? 0;
      const bRank = rarityRank[b.rarity] ?? 0;
      if (aRank !== bRank) return bRank - aRank;

      // Alphabetical name
      return a.name.localeCompare(b.name);
    });
  });

  protected openDialog(): void {
    if (this.disabled()) return;

    // Reset filters on open
    this.search.set('');
    this.selectedElement.set(null);
    this.selectedSpecialty.set(null);
    this.selectedFaction.set(null);
    this.factionDropdownOpen.set(false);
    this.activeRarities.set([]);

    this.dialogRef()?.nativeElement.showModal();
  }

  protected toggleFactionDropdown(): void {
    this.factionDropdownOpen.update((v) => !v);
  }

  protected selectFaction(fact: string | null): void {
    this.selectedFaction.set(fact);
    this.factionDropdownOpen.set(false);
  }

  protected closeDialog(): void {
    this.dialogRef()?.nativeElement.close();
  }

  protected selectAgent(id: string | null): void {
    this.selectedChange.emit(id);
    this.closeDialog();
  }

  protected toggleElement(elem: string): void {
    const current = this.selectedElement();
    if (current === elem) {
      this.selectedElement.set(null);
    } else {
      this.selectedElement.set(elem);
    }
  }

  protected toggleSpecialty(spec: string): void {
    const current = this.selectedSpecialty();
    if (current === spec) {
      this.selectedSpecialty.set(null);
    } else {
      this.selectedSpecialty.set(spec);
    }
  }

  protected toggleRarity(rarity: string): void {
    const cur = this.activeRarities();
    const next = cur.includes(rarity) ? cur.filter((r) => r !== rarity) : [...cur, rarity];
    this.activeRarities.set(next);
  }

  protected isRaritySelected(rarity: string): boolean {
    return this.activeRarities().includes(rarity);
  }

  protected formatFaction(fact: string): string {
    // Convert 'sons-of-calydon' -> 'Sons Of Calydon'
    return fact
      .split(/[-_]/)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ');
  }
}
