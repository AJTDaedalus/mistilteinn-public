import { Component, computed, model, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { elementIconUrl, specialtyIconUrl } from '../../shared/icon-url';

export interface BuildFilterState {
  text: string;
  elements: string[];
  specialties: string[];
}

export function defaultBuildFilters(): BuildFilterState {
  return { text: '', elements: [], specialties: [] };
}

export const ELEMENTS = ['physical', 'fire', 'ice', 'electric', 'ether'] as const;
export const SPECIALTIES = ['attack', 'stun', 'anomaly', 'support', 'defense', 'rupture'] as const;

@Component({
  selector: 'build-filters',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './build-filters.html',
  styleUrl: './build-filters.scss',
})
export class BuildFilters {
  filters = model<BuildFilterState>(defaultBuildFilters());
  filtersChange = output<BuildFilterState>();

  protected readonly elementIcon = elementIconUrl;
  protected readonly specialtyIcon = specialtyIconUrl;
  protected readonly elements = ELEMENTS;
  protected readonly specialties = SPECIALTIES;

  protected activeElements = computed(() => new Set(this.filters().elements));
  protected activeSpecialties = computed(() => new Set(this.filters().specialties));

  protected get hasActiveFilters(): boolean {
    const f = this.filters();
    return f.text.length > 0 || f.elements.length > 0 || f.specialties.length > 0;
  }

  protected setText(text: string): void {
    this.update(f => ({ ...f, text }));
  }

  protected toggleElement(e: string): void {
    this.update(f => ({ ...f, elements: toggle(f.elements, e) }));
  }

  protected toggleSpecialty(s: string): void {
    this.update(f => ({ ...f, specialties: toggle(f.specialties, s) }));
  }

  protected reset(): void {
    const next = defaultBuildFilters();
    this.filters.set(next);
    this.filtersChange.emit(next);
  }

  private update(fn: (f: BuildFilterState) => BuildFilterState): void {
    const next = fn(this.filters());
    this.filters.set(next);
    this.filtersChange.emit(next);
  }
}

function toggle(arr: string[], key: string): string[] {
  return arr.includes(key) ? arr.filter(x => x !== key) : [...arr, key];
}
