import {
  Component,
  computed,
  input,
  output,
  signal,
  viewChild,
  ElementRef,
} from '@angular/core';

import { type DiscSetSummary, buildIconUrl } from '../icon-url';

@Component({
  selector: 'set-picker',
  standalone: true,
  imports: [],
  templateUrl: './set-picker.html',
  styleUrl: './set-picker.scss',
})
export class SetPicker {
  allSets = input<DiscSetSummary[]>([]);
  selected = input<string[]>([]);
  label = input<string>('Set');
  hint = input<string>('');

  selectedChange = output<string[]>();

  protected dialogRef = viewChild<ElementRef<HTMLDialogElement>>('pickerDialog');
  protected search = signal('');
  protected readonly iconUrl = buildIconUrl;

  protected selectedSets = computed(() => {
    const sel = new Set(this.selected());
    return this.allSets().filter((s) => sel.has(s.id));
  });

  protected sortedSets = computed(() => {
    const q = this.search().toLowerCase().trim();
    const sel = new Set(this.selected());
    let sets = this.allSets();
    if (q) sets = sets.filter((s) => s.name.toLowerCase().includes(q));
    return [...sets].sort((a, b) => {
      const diff = (sel.has(a.id) ? 0 : 1) - (sel.has(b.id) ? 0 : 1);
      return diff !== 0 ? diff : a.name.localeCompare(b.name);
    });
  });

  protected isSelected(id: string): boolean {
    return this.selected().includes(id);
  }

  protected setTooltip(s: DiscSetSummary): string {
    const parts: string[] = [];
    if (s.two_piece_text) parts.push(`2pc: ${s.two_piece_text}`);
    if (s.four_piece_text) parts.push(`4pc: ${s.four_piece_text}`);
    return parts.join('\n\n');
  }

  protected openDialog(): void {
    this.dialogRef()?.nativeElement.showModal();
  }

  protected closeDialog(): void {
    this.dialogRef()?.nativeElement.close();
    this.search.set('');
  }

  protected toggle(id: string): void {
    const cur = this.selected();
    const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    this.selectedChange.emit(next);
  }

  protected clear(): void {
    this.selectedChange.emit([]);
  }
}
