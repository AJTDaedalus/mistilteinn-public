import {
  Component,
  computed,
  input,
  output,
} from '@angular/core';

import type { ComboRead } from '../builds/combos.service';

@Component({
  selector: 'optimizer-combo-selector',
  templateUrl: './optimizer-combo-selector.html',
  styleUrl: './optimizer-combo-selector.scss',
})
export class OptimizerComboSelector {
  combos = input<ComboRead[]>([]);
  selectedIds = input<Set<string>>(new Set());
  selectionChange = output<Set<string>>();

  protected allSelected = computed(() =>
    this.combos().length > 0 &&
    this.combos().every((c) => this.selectedIds().has(c.id)),
  );

  protected isSelected(id: string) {
    return this.selectedIds().has(id);
  }

  protected toggle(id: string) {
    const next = new Set(this.selectedIds());
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    this.selectionChange.emit(next);
  }

  protected selectAll() {
    this.selectionChange.emit(new Set(this.combos().map((c) => c.id)));
  }

  protected clearAll() {
    this.selectionChange.emit(new Set());
  }
}
