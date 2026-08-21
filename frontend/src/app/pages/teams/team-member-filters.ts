import { Component, computed, model, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ELEMENTS, SPECIALTIES } from '../builds/build-filters';
import { elementIconUrl, specialtyIconUrl } from '../../shared/icon-url';

export interface MemberFilterState {
  elements: string[];
  specialties: string[];
  rarities: string[];
  name: string;
}

export function defaultMemberFilters(): MemberFilterState {
  return { elements: [], specialties: [], rarities: [], name: '' };
}

const RARITIES = ['S', 'A'] as const;

@Component({
  selector: 'team-member-filters',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './team-member-filters.html',
  styleUrl: './team-member-filters.scss',
})
export class TeamMemberFilters {
  filters = model<MemberFilterState>(defaultMemberFilters());
  filtersChange = output<MemberFilterState>();

  protected readonly elementIcon = elementIconUrl;
  protected readonly specialtyIcon = specialtyIconUrl;
  protected readonly elements = ELEMENTS;
  protected readonly specialties = SPECIALTIES;
  protected readonly rarities = RARITIES;

  protected activeElements = computed(() => new Set(this.filters().elements));
  protected activeSpecialties = computed(() => new Set(this.filters().specialties));
  protected activeRarities = computed(() => new Set(this.filters().rarities));

  protected get hasActiveFilters(): boolean {
    const f = this.filters();
    return f.name.length > 0 || f.elements.length > 0 || f.specialties.length > 0 || f.rarities.length > 0;
  }

  protected setName(name: string): void {
    this.update(f => ({ ...f, name }));
  }

  protected toggleElement(e: string): void {
    this.update(f => ({ ...f, elements: toggle(f.elements, e) }));
  }

  protected toggleSpecialty(s: string): void {
    this.update(f => ({ ...f, specialties: toggle(f.specialties, s) }));
  }

  protected toggleRarity(r: string): void {
    this.update(f => ({ ...f, rarities: toggle(f.rarities, r) }));
  }

  protected reset(): void {
    const next = defaultMemberFilters();
    this.filters.set(next);
    this.filtersChange.emit(next);
  }

  private update(fn: (f: MemberFilterState) => MemberFilterState): void {
    const next = fn(this.filters());
    this.filters.set(next);
    this.filtersChange.emit(next);
  }
}

function toggle(arr: string[], key: string): string[] {
  return arr.includes(key) ? arr.filter(x => x !== key) : [...arr, key];
}
