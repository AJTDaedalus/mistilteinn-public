import { Component, computed, input, signal } from '@angular/core';

import type { components } from '../../api/api.types';
import { equationTerms, type EquationTermKey } from './equation-terms';
import { BuffDrawerComponent } from './buff-drawer.component';

type StepAttribution = components['schemas']['StepAttributionSchema'];
type ComboStepResultSchema = components['schemas']['ComboStepResultSchema'];

@Component({
  selector: 'app-step-detail',
  imports: [BuffDrawerComponent],
  templateUrl: './step-detail.component.html',
  styleUrl: './step-detail.component.scss',
})
export class StepDetailComponent {
  readonly step = input.required<ComboStepResultSchema>();
  readonly attribution = input<StepAttribution | null>(null);
  readonly activeAgentName = input<string>('');

  protected activeChipKey = signal<EquationTermKey | null>(null);

  protected readonly termList = computed(() => equationTerms(this.step()));

  protected readonly activeTerm = computed(() => {
    const key = this.activeChipKey();
    if (!key) return null;
    return this.termList().find((t) => t.key === key) ?? null;
  });

  protected toggleChip(key: EquationTermKey) {
    this.activeChipKey.update((cur) => (cur === key ? null : key));
  }
}
