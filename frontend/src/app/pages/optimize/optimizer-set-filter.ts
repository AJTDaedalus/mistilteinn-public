import { Component, computed, input, output } from '@angular/core';

import type { DiscSetSummary } from './disc-sets.service';
import type { SetFrameSchema } from './optimizer.service';
import { SetPicker } from '../../shared/set-picker/set-picker';

// Re-exported for backward compatibility — use shared/icon-url.ts for new code.
export {
  extractBasename,
  buildIconUrl,
  discSetIconUrl,
  wEngineIconUrl,
  agentIconUrl,
} from '../../shared/icon-url';

export interface SetFilterState {
  /** Sets selected as the 4-piece bonus candidate. */
  fourPieceSets: number[];
  /** Sets selected as the 2-piece bonus candidate. */
  twoPieceSets: number[];
  /** Derived frames sent to the backend. */
  frames: SetFrameSchema[];
}

@Component({
  selector: 'optimizer-set-filter',
  standalone: true,
  imports: [SetPicker],
  templateUrl: './optimizer-set-filter.html',
  styleUrl: './optimizer-set-filter.scss',
})
export class OptimizerSetFilter {
  allSets = input<DiscSetSummary[]>([]);
  state = input<SetFilterState>(emptySetFilterState());
  stateChange = output<SetFilterState>();

  protected count4pc = computed(() => this.state().fourPieceSets.length);
  protected count2pc = computed(() => this.state().twoPieceSets.length);
  protected frameCount = computed(() => this.state().frames.length);

  /** Convert hakushin_id numbers → string ids for the SetPicker. */
  protected fourPieceSelected = computed(() =>
    this._toIds(this.state().fourPieceSets),
  );
  protected twoPieceSelected = computed(() =>
    this._toIds(this.state().twoPieceSets),
  );

  protected onFourPieceChange(ids: string[]): void {
    const s = this.state();
    this._emit({ ...s, fourPieceSets: this._toHakushinIds(ids) });
  }

  protected onTwoPieceChange(ids: string[]): void {
    const s = this.state();
    this._emit({ ...s, twoPieceSets: this._toHakushinIds(ids) });
  }

  private _toIds(hids: number[]): string[] {
    return hids.map((hid) => {
      const s = this.allSets().find((x) => x.hakushin_id === hid);
      return s ? s.id : String(hid);
    });
  }

  private _toHakushinIds(ids: string[]): number[] {
    return ids.map((id) => {
      const s = this.allSets().find((x) => x.id === id);
      return s ? s.hakushin_id : Number(id);
    });
  }

  private _emit(partial: Omit<SetFilterState, 'frames'>): void {
    const frames = deriveFrames(partial.fourPieceSets, partial.twoPieceSets);
    this.stateChange.emit({ ...partial, frames });
  }
}

/** Build frames from 4pc + 2pc candidate sets. */
export function deriveFrames(fourPieceSets: number[], twoPieceSets: number[]): SetFrameSchema[] {
  const seen = new Set<string>();
  const frames: SetFrameSchema[] = [];

  const add = (counts: Record<string, number>) => {
    const key = JSON.stringify(counts);
    if (!seen.has(key)) { seen.add(key); frames.push({ counts: counts as Record<number, number> }); }
  };

  if (fourPieceSets.length === 0 || twoPieceSets.length === 0) return frames;

  for (const s4 of fourPieceSets) {
    for (const s2 of twoPieceSets) {
      if (s4 === s2) {
        add({ [s4]: 6 });
      } else {
        add({ [s4]: 4, [s2]: 2 });
      }
    }
  }
  return frames;
}

export function emptySetFilterState(): SetFilterState {
  return { fourPieceSets: [], twoPieceSets: [], frames: [] };
}
