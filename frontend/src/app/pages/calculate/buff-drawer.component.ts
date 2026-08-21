import { Component, computed, input } from '@angular/core';

import { CATEGORY_ORDER, groupContributions, type SourceCategory } from './group-contributions';
import { ZONE_FORMAT, ZONE_LABELS, fmtContribution, type ZoneFormatType } from './format-helpers';
import type { EquationTerm } from './equation-terms';
import type { components } from '../../api/api.types';
import { FormulaCardComponent } from './formula-card.component';

type StepAttribution = components['schemas']['StepAttributionSchema'];
type ComboStepResult = components['schemas']['ComboStepResultSchema'];

const CATEGORY_LABELS: Record<SourceCategory, string> = {
  agent: 'Agent',
  wengine: 'W-Engine',
  disc_set: 'Disc Set',
  discs: 'Discs',
  base: 'Base',
  external: 'External',
};

interface ZoneSection {
  key: keyof StepAttribution;
  label: string;
  formatType: ZoneFormatType;
  total: number;
  groups: ReturnType<typeof groupContributions>;
  hasContent: boolean;
}

@Component({
  selector: 'app-buff-drawer',
  imports: [FormulaCardComponent],
  templateUrl: './buff-drawer.component.html',
  styleUrl: './buff-drawer.component.scss',
})
export class BuffDrawerComponent {
  readonly term = input.required<EquationTerm>();
  readonly step = input.required<ComboStepResult>();
  readonly attribution = input<StepAttribution | null>(null);
  readonly activeAgentName = input<string>('');

  protected readonly CATEGORY_ORDER = CATEGORY_ORDER;
  protected readonly CATEGORY_LABELS = CATEGORY_LABELS;
  protected readonly fmtContribution = fmtContribution;

  protected readonly zones = computed<ZoneSection[]>(() => {
    const attr = this.attribution();
    if (!attr) return [];
    return this.term().zones.map((zoneKey) => {
      const zone = attr[zoneKey] ?? null;
      const contributions = zone?.contributions ?? [];
      const groups = groupContributions(contributions, this.activeAgentName());
      const hasContent = CATEGORY_ORDER.some((cat) => groups[cat].length > 0);
      return {
        key: zoneKey,
        label: ZONE_LABELS[zoneKey],
        formatType: ZONE_FORMAT[zoneKey],
        total: zone?.total ?? 0,
        groups,
        hasContent,
      };
    });
  });

  protected readonly multiZone = computed(() => this.term().zones.length > 1);
}
