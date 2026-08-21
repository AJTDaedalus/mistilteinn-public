import {
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';

import { DiscsService, DiscImportResponse, ImportMode } from '../builds/discs.service';

interface ParsedPayload {
  ok: true;
  data: { format?: string; discs?: unknown[] } & Record<string, unknown>;
}

interface ParseError {
  ok: false;
  reason: string;
}

@Component({
  selector: 'page-import',
  imports: [RouterLink],
  templateUrl: './import-page.html',
  styleUrl: './import-page.scss',
})
export class ImportPage {
  private svc = inject(DiscsService);

  protected pasteText = signal('');
  protected dragging = signal(false);
  protected conflictMode = signal<'skip' | 'overwrite'>('skip');
  protected discMode = signal<ImportMode>('merge');
  protected buildMode = signal<ImportMode>('merge');

  /** True once the user has been shown — and accepted — the clean-mode warning. */
  protected confirming = signal(false);

  protected submitting = signal(false);
  protected submitError = signal<string | null>(null);
  protected result = signal<DiscImportResponse | null>(null);

  /** Discs the file contained that did not land, across every skip reason.
   *
   *  The per-reason lines below already itemise *why* something was dropped, but the
   *  question a user actually arrives with is "my file had 445 discs and I see fewer —
   *  where did the rest go?" (issue #81). Answering that needs one reconciling number,
   *  not three conditional lines they have to add up.
   */
  protected totalSkipped = computed(() => {
    const r = this.result();
    if (!r) return 0;
    return r.skipped_duplicate + r.skipped_unknown_set + r.skipped_invalid;
  });

  protected parsed = computed<ParsedPayload | ParseError | null>(() => {
    const txt = this.pasteText().trim();
    if (!txt) return null;
    try {
      const data = JSON.parse(txt);
      if (typeof data !== 'object' || data === null) {
        return { ok: false, reason: 'JSON must be an object.' };
      }
      return { ok: true, data };
    } catch (e) {
      return {
        ok: false,
        reason: `Could not parse JSON: ${e instanceof Error ? e.message : String(e)}`,
      };
    }
  });

  protected isEzod = computed<boolean>(() => {
    const p = this.parsed();
    return !!p?.ok && p.data['format'] === 'eZOD';
  });

  protected validation = computed<string | null>(() => {
    const p = this.parsed();
    if (!p) return null;
    if (!p.ok) return p.reason;
    const fmt = p.data['format'];
    if (fmt !== 'ZOD' && fmt !== 'eZOD') {
      return `Expected format=ZOD or eZOD, got ${fmt ?? 'none'}`;
    }
    if (!Array.isArray(p.data['discs'])) return 'Payload missing "discs" array';
    return null;
  });

  protected preview = computed(() => {
    const p = this.parsed();
    if (!p || !p.ok) return null;
    const discs = p.data['discs'];
    const src = p.data['source'];
    return {
      format: String(p.data['format'] ?? 'unknown'),
      discCount: Array.isArray(discs) ? discs.length : 0,
      source: src ? String(src) : null,
    };
  });

  protected canSubmit = computed(
    () => this.parsed()?.ok && this.validation() === null && !this.submitting(),
  );

  /** A ZOD file carries no builds, so its build mode is always a no-op merge. */
  protected effectiveBuildMode = computed<ImportMode>(() =>
    this.isEzod() ? this.buildMode() : 'merge',
  );

  /** `build_conflict` only decides anything when builds are being merged. */
  protected showConflict = computed(
    () => this.isEzod() && this.buildMode() === 'merge',
  );

  /**
   * Kept builds lose their equipped discs when the inventory is wiped from
   * under them — nothing re-attaches them. Allowed, but warned about.
   */
  protected hazard = computed(
    () => this.discMode() === 'clean' && this.effectiveBuildMode() === 'merge',
  );

  protected needsConfirm = computed(
    () => this.discMode() === 'clean' || this.effectiveBuildMode() === 'clean',
  );

  protected confirmMessage = computed(() => {
    const targets: string[] = [];
    if (this.discMode() === 'clean') targets.push('every disc in your inventory');
    if (this.effectiveBuildMode() === 'clean') targets.push('every saved build');
    let msg = `This permanently deletes ${targets.join(' and ')} before importing.`;
    if (this.effectiveBuildMode() === 'clean') {
      msg +=
        ' Team slots are re-pointed to the imported builds where the agent appears' +
        ' in this file, and any team whose agents are all absent from this file' +
        ' will be deleted, along with its combos.';
    }
    return `${msg} Continue?`;
  });

  protected onPasteInput(event: Event) {
    this.pasteText.set((event.target as HTMLTextAreaElement).value);
    this.submitError.set(null);
    this.result.set(null);
    this.confirming.set(false);
  }

  protected onConflictChange(event: Event) {
    const v = (event.target as HTMLSelectElement).value;
    this.conflictMode.set(v === 'overwrite' ? 'overwrite' : 'skip');
  }

  protected onDiscModeChange(event: Event) {
    this.discMode.set(toMode((event.target as HTMLSelectElement).value));
    this.confirming.set(false);
  }

  protected onBuildModeChange(event: Event) {
    this.buildMode.set(toMode((event.target as HTMLSelectElement).value));
    this.confirming.set(false);
  }

  /** Step one of the two-step confirm: a clean import re-asks before firing. */
  protected onImportClick() {
    if (this.needsConfirm() && !this.confirming()) {
      this.confirming.set(true);
      return;
    }
    void this.submit();
  }

  protected cancelConfirm() {
    this.confirming.set(false);
  }

  protected onDragOver(event: DragEvent) {
    event.preventDefault();
    this.dragging.set(true);
  }

  protected onDragLeave() {
    this.dragging.set(false);
  }

  protected async onDrop(event: DragEvent) {
    event.preventDefault();
    this.dragging.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) await this.loadFile(file);
  }

  protected async onFileInput(event: Event) {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (file) await this.loadFile(file);
  }

  private async loadFile(file: File) {
    // A new payload invalidates any confirm the user already gave, so a wipe
    // approved for one file can never fire against another.
    this.confirming.set(false);
    try {
      this.pasteText.set(await file.text());
      this.submitError.set(null);
      this.result.set(null);
    } catch (e) {
      this.submitError.set(
        e instanceof Error ? e.message : 'Could not read file.',
      );
    }
  }

  protected async submit() {
    const p = this.parsed();
    if (!p || !p.ok || this.validation() !== null) return;
    // Guard the destructive path here as well as in `onImportClick`, so no
    // caller can reach a wipe without passing the confirm.
    if (this.needsConfirm() && !this.confirming()) return;
    this.confirming.set(false);
    this.submitting.set(true);
    this.submitError.set(null);
    this.result.set(null);
    try {
      const r = await this.svc.importZod(
        p.data,
        this.showConflict() ? this.conflictMode() : undefined,
        this.discMode(),
        this.isEzod() ? this.buildMode() : undefined,
      );
      this.result.set(r);
    } catch (e) {
      this.submitError.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.submitting.set(false);
    }
  }

  protected reset() {
    this.pasteText.set('');
    this.result.set(null);
    this.submitError.set(null);
    this.conflictMode.set('skip');
    this.discMode.set('merge');
    this.buildMode.set('merge');
    this.confirming.set(false);
  }
}

function toMode(value: string): ImportMode {
  return value === 'clean' ? 'clean' : 'merge';
}
