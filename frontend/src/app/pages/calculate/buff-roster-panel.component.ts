import { Component, computed, input } from '@angular/core';

import { formatStatLabel } from '../../shared/stat-meta';
import { CATEGORY_ORDER, type SourceCategory } from './group-contributions';
import { groupBuffRoster } from './buff-roster-group';
import type { components } from '../../api/api.types';

type BuffRosterEntrySchema = components['schemas']['BuffRosterEntrySchema'];

const CATEGORY_LABELS: Record<SourceCategory, string> = {
  agent: 'Agent',
  wengine: 'W-Engine',
  disc_set: 'Disc Set',
  discs: 'Discs',
  base: 'Base',
  external: 'External',
};

interface RosterRow {
  entry: BuffRosterEntrySchema;
  statLabel: string;
}

/**
 * Build-level "every resolved buff, once" panel (DESIGN_explainability.md
 * §2.3). One instance per team_builds agent key -- `roster` is that agent's
 * `buff_roster` slice from the /simulate response.
 */
@Component({
  selector: 'app-buff-roster-panel',
  standalone: true,
  templateUrl: './buff-roster-panel.component.html',
  styleUrl: './buff-roster-panel.component.scss',
})
export class BuffRosterPanelComponent {
  readonly agentLabel = input.required<string>();
  readonly roster = input.required<BuffRosterEntrySchema[]>();

  protected readonly CATEGORY_ORDER = CATEGORY_ORDER;
  protected readonly CATEGORY_LABELS = CATEGORY_LABELS;

  protected readonly groups = computed<Record<SourceCategory, RosterRow[]>>(() => {
    const grouped = groupBuffRoster(this.roster());
    const out = {} as Record<SourceCategory, RosterRow[]>;
    for (const cat of CATEGORY_ORDER) {
      out[cat] = grouped[cat].map((entry) => ({ entry, statLabel: formatStatLabel(entry.stat) }));
    }
    return out;
  });

  protected readonly hasAny = computed(() => this.roster().length > 0);
}
