import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';

import { DiscsService } from '../builds/discs.service';
import { ImportPage } from './import-page';

interface DiscsStub {
  importZod: ReturnType<typeof vi.fn>;
}

function setup(result?: unknown, throws?: boolean) {
  const svc: DiscsStub = {
    importZod: vi.fn(async (_payload) => {
      if (throws) throw new Error('boom');
      return result ?? {
        imported: 5, skipped_duplicate: 0,
        skipped_unknown_set: 0, skipped_invalid: 0, errors: [],
      };
    }),
  };
  TestBed.configureTestingModule({
    imports: [ImportPage],
    providers: [
      provideRouter([]),
      { provide: DiscsService, useValue: svc },
    ],
  });
  return { svc };
}

function fixture() {
  return TestBed.createComponent(ImportPage);
}

async function settle(f: ReturnType<typeof TestBed.createComponent>) {
  f.detectChanges();
  for (let i = 0; i < 4; i++) await Promise.resolve();
  f.detectChanges();
  await f.whenStable();
  f.detectChanges();
}

const VALID_ZOD = JSON.stringify({
  format: 'ZOD', version: 1, source: 'test',
  discs: [
    { setKey: 'MoonlightLullaby', slotKey: '1', level: 15, rarity: 'S',
      mainStatKey: 'hp', substats: [{ key: 'crit_', upgrades: 9 }] },
  ],
});

const VALID_EZOD = JSON.stringify({
  format: 'eZOD', version: 1, source: 'test',
  characters: [{ key: 'Miyabi', level: 60 }],
  weapons: [],
  discs: [
    { setKey: 'MoonlightLullaby', slotKey: '1', level: 15, rarity: 'S',
      mainStatKey: 'hp', substats: [{ key: 'crit_', upgrades: 9 }] },
  ],
});

describe('ImportPage', () => {
  it('renders page shell with Import heading', async () => {
    setup();
    const f = fixture();
    await settle(f);
    const el = f.nativeElement as HTMLElement;
    expect(el.querySelector('h1')?.textContent?.trim()).toBe('Import');
  });

  it('parses + validates a pasted ZOD payload before submitting', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as {
      pasteText: { set: (v: string) => void };
      preview: () => { discCount: number; format: string } | null;
      submit: () => Promise<void>;
    };
    await settle(f);

    cmp.pasteText.set(VALID_ZOD);
    expect(cmp.preview()?.discCount).toBe(1);
    expect(cmp.preview()?.format).toBe('ZOD');
    await cmp.submit();
    expect(svc.importZod).toHaveBeenCalledOnce();
  });

  it('parses + accepts an eZOD payload and submits with conflict mode', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as {
      pasteText: { set: (v: string) => void };
      validation: () => string | null;
      preview: () => { discCount: number; format: string } | null;
      submit: () => Promise<void>;
    };
    await settle(f);

    cmp.pasteText.set(VALID_EZOD);
    expect(cmp.validation()).toBeNull();
    expect(cmp.preview()?.format).toBe('eZOD');
    await cmp.submit();
    expect(svc.importZod).toHaveBeenCalledOnce();
    expect(svc.importZod.mock.calls[0][1]).toBe('skip');
  });

  it('does not forward a conflict mode for plain ZOD', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as {
      pasteText: { set: (v: string) => void };
      submit: () => Promise<void>;
    };
    await settle(f);

    cmp.pasteText.set(VALID_ZOD);
    await cmp.submit();
    expect(svc.importZod).toHaveBeenCalledOnce();
    expect(svc.importZod.mock.calls[0][1]).toBeUndefined();
  });

  it('rejects an unknown format locally before hitting the API', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as {
      pasteText: { set: (v: string) => void };
      validation: () => string | null;
      submit: () => Promise<void>;
    };
    await settle(f);

    cmp.pasteText.set(JSON.stringify({ format: 'GOOD', discs: [] }));
    expect(cmp.validation()).toMatch(/format/i);
    await cmp.submit();
    expect(svc.importZod).not.toHaveBeenCalled();
  });

  it('rejects malformed JSON locally', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as {
      pasteText: { set: (v: string) => void };
      validation: () => string | null;
      submit: () => Promise<void>;
    };
    await settle(f);

    cmp.pasteText.set('not json {');
    expect(cmp.validation()).toMatch(/json|parse/i);
    await cmp.submit();
    expect(svc.importZod).not.toHaveBeenCalled();
  });

  it('exposes the import result after a successful submit', async () => {
    setup({
      imported: 1500, skipped_duplicate: 100,
      skipped_unknown_set: 0, skipped_invalid: 0, errors: [],
    });
    const f = fixture();
    const cmp = f.componentInstance as unknown as {
      pasteText: { set: (v: string) => void };
      result: () => { imported: number } | null;
      submit: () => Promise<void>;
    };
    await settle(f);
    cmp.pasteText.set(VALID_ZOD);
    await cmp.submit();
    expect(cmp.result()?.imported).toBe(1500);
  });

  it('shows View discs link after successful import', async () => {
    setup({ imported: 3, skipped_duplicate: 0, skipped_unknown_set: 0, skipped_invalid: 0, errors: [] });
    const f = fixture();
    const cmp = f.componentInstance as unknown as {
      pasteText: { set: (v: string) => void };
      submit: () => Promise<void>;
    };
    await settle(f);
    cmp.pasteText.set(VALID_ZOD);
    await cmp.submit();
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    expect(el.querySelector('[data-test="view-discs"]')).toBeTruthy();
  });

  it('shows View builds link when builds were created', async () => {
    setup({
      imported: 1, skipped_duplicate: 0, skipped_unknown_set: 0, skipped_invalid: 0,
      errors: [], builds_created: 2,
    });
    const f = fixture();
    const cmp = f.componentInstance as unknown as {
      pasteText: { set: (v: string) => void };
      submit: () => Promise<void>;
    };
    await settle(f);
    cmp.pasteText.set(VALID_EZOD);
    await cmp.submit();
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    expect(el.querySelector('[data-test="view-builds"]')).toBeTruthy();
  });

  it('captures the API error in submitError when the import fails', async () => {
    setup(undefined, true);
    const f = fixture();
    const cmp = f.componentInstance as unknown as {
      pasteText: { set: (v: string) => void };
      submit: () => Promise<void>;
      submitError: () => string | null;
    };
    await settle(f);
    cmp.pasteText.set(VALID_ZOD);
    await cmp.submit();
    expect(cmp.submitError()).toContain('boom');
  });

  it('reset() clears paste text, result, conflict mode, and import modes', async () => {
    setup({
      imported: 1, skipped_duplicate: 0, skipped_unknown_set: 0, skipped_invalid: 0, errors: [],
    });
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    cmp.pasteText.set(VALID_ZOD);
    cmp.conflictMode.set('overwrite');
    cmp.discMode.set('clean');
    cmp.buildMode.set('clean');
    cmp.confirming.set(true);
    await cmp.submit();
    expect(cmp.result()).not.toBeNull();

    cmp.reset();
    expect(cmp.pasteText()).toBe('');
    expect(cmp.result()).toBeNull();
    expect(cmp.conflictMode()).toBe('skip');
    expect(cmp.discMode()).toBe('merge');
    expect(cmp.buildMode()).toBe('merge');
    expect(cmp.confirming()).toBe(false);
  });
});

// ---------------------------------------------------------------- Task 9 ---

/** The protected surface of ImportPage the mode tests reach into. */
interface Cmp {
  pasteText: { set: (v: string) => void; (): string };
  conflictMode: { set: (v: 'skip' | 'overwrite') => void; (): string };
  discMode: { set: (v: 'merge' | 'clean') => void; (): string };
  buildMode: { set: (v: 'merge' | 'clean') => void; (): string };
  confirming: { set: (v: boolean) => void; (): boolean };
  result: () => unknown;
  submit: () => Promise<void>;
  reset: () => void;
  onFileInput: (event: Event) => Promise<void>;
}

function q(f: ReturnType<typeof fixture>, sel: string) {
  return (f.nativeElement as HTMLElement).querySelector(`[data-test="${sel}"]`);
}

/** Paste a payload and flush it into the DOM. */
async function paste(f: ReturnType<typeof fixture>, json: string) {
  (f.componentInstance as unknown as Cmp).pasteText.set(json);
  await settle(f);
}

describe('ImportPage — import modes (Task 9)', () => {
  it('renders the discs mode control for a plain ZOD payload', async () => {
    setup();
    const f = fixture();
    await settle(f);
    await paste(f, VALID_ZOD);

    expect(q(f, 'disc-mode')).toBeTruthy();
  });

  it('gates the builds mode control to eZOD payloads', async () => {
    setup();
    const f = fixture();
    await settle(f);

    await paste(f, VALID_ZOD);
    expect(q(f, 'build-mode')).toBeNull();

    await paste(f, VALID_EZOD);
    expect(q(f, 'build-mode')).toBeTruthy();
  });

  it('hides the build-conflict select when builds mode is clean', async () => {
    setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    await paste(f, VALID_EZOD);
    expect(q(f, 'conflict-select')).toBeTruthy();

    cmp.buildMode.set('clean');
    await settle(f);
    expect(q(f, 'conflict-select')).toBeNull();
  });

  it('requires an explicit confirm before POSTing a clean import', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    await paste(f, VALID_ZOD);
    cmp.discMode.set('clean');
    await settle(f);

    (q(f, 'submit') as HTMLButtonElement).click();
    await settle(f);
    expect(svc.importZod).not.toHaveBeenCalled();
    expect(q(f, 'confirm')).toBeTruthy();

    (q(f, 'confirm-yes') as HTMLButtonElement).click();
    await settle(f);
    expect(svc.importZod).toHaveBeenCalledOnce();
  });

  it('will not submit a clean import that was never confirmed', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    await paste(f, VALID_ZOD);
    cmp.discMode.set('clean');
    await cmp.submit();
    expect(svc.importZod).not.toHaveBeenCalled();
  });

  it('cancelling the confirm leaves the inventory alone', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    await paste(f, VALID_EZOD);
    cmp.buildMode.set('clean');
    await settle(f);

    (q(f, 'submit') as HTMLButtonElement).click();
    await settle(f);
    (q(f, 'confirm-cancel') as HTMLButtonElement).click();
    await settle(f);

    expect(svc.importZod).not.toHaveBeenCalled();
    expect(q(f, 'confirm')).toBeNull();
    expect(q(f, 'submit')).toBeTruthy();
  });

  it('names teams in the confirm copy for a clean build import', async () => {
    setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    await paste(f, VALID_EZOD);
    cmp.buildMode.set('clean');
    await settle(f);
    (q(f, 'submit') as HTMLButtonElement).click();
    await settle(f);

    expect(q(f, 'confirm')?.textContent).toMatch(/team/i);
  });

  it('submits merge/merge without a confirm step', async () => {
    const { svc } = setup();
    const f = fixture();
    await settle(f);

    await paste(f, VALID_ZOD);
    (q(f, 'submit') as HTMLButtonElement).click();
    await settle(f);

    expect(q(f, 'confirm')).toBeNull();
    expect(svc.importZod).toHaveBeenCalledOnce();
  });

  it('warns about the clean-discs + merge-builds hazard', async () => {
    setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    await paste(f, VALID_EZOD);
    expect(q(f, 'hazard-warning')).toBeNull();

    cmp.discMode.set('clean');
    await settle(f);
    expect(q(f, 'hazard-warning')).toBeTruthy();

    cmp.buildMode.set('clean');
    await settle(f);
    expect(q(f, 'hazard-warning')).toBeNull();
  });

  it('forwards both modes to the service on an eZOD import', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    await paste(f, VALID_EZOD);
    cmp.discMode.set('clean');
    cmp.buildMode.set('clean');
    cmp.confirming.set(true);
    await cmp.submit();

    const [, conflict, discMode, buildMode] = svc.importZod.mock.calls[0];
    expect(discMode).toBe('clean');
    expect(buildMode).toBe('clean');
    // build_conflict is meaningless under a clean build — don't send it.
    expect(conflict).toBeUndefined();
  });

  it('never forwards a build mode for a plain ZOD payload', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    await paste(f, VALID_ZOD);
    // Stale from an earlier eZOD paste — must not leak into a ZOD import.
    cmp.buildMode.set('clean');
    cmp.confirming.set(true);
    await cmp.submit();

    const [, , discMode, buildMode] = svc.importZod.mock.calls[0];
    expect(discMode).toBe('merge');
    expect(buildMode).toBeUndefined();
  });

  it('renders deletion counters, team fallout, and slot re-mapping', async () => {
    setup({
      imported: 4, skipped_duplicate: 0, skipped_unknown_set: 0, skipped_invalid: 0,
      errors: [], builds_created: 2,
      discs_deleted: 300, builds_deleted: 7,
      teams_deleted: 1, combos_deleted: 3, team_slots_remapped: 5,
    });
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    await paste(f, VALID_EZOD);
    cmp.discMode.set('clean');
    cmp.buildMode.set('clean');
    cmp.confirming.set(true);
    await cmp.submit();
    await settle(f);

    expect(q(f, 'discs-deleted')?.textContent).toContain('300');
    expect(q(f, 'builds-deleted')?.textContent).toContain('7');
    expect(q(f, 'teams-deleted')?.textContent).toContain('1');
    expect(q(f, 'combos-deleted')?.textContent).toContain('3');
    expect(q(f, 'slots-remapped')?.textContent).toContain('5');
  });

  it('omits team fallout from the result when nothing was deleted', async () => {
    setup({
      imported: 4, skipped_duplicate: 0, skipped_unknown_set: 0, skipped_invalid: 0,
      errors: [], discs_deleted: 0, builds_deleted: 0,
      teams_deleted: 0, combos_deleted: 0, team_slots_remapped: 0,
    });
    const f = fixture();
    await settle(f);
    await paste(f, VALID_ZOD);
    (q(f, 'submit') as HTMLButtonElement).click();
    await settle(f);

    expect(q(f, 'teams-deleted')).toBeNull();
    expect(q(f, 'combos-deleted')).toBeNull();
    expect(q(f, 'slots-remapped')).toBeNull();
    expect(q(f, 'discs-deleted')).toBeNull();
  });

  it('loading a file clears a pending confirm, so a wipe cannot fire on it', async () => {
    const { svc } = setup();
    const f = fixture();
    const cmp = f.componentInstance as unknown as Cmp;
    await settle(f);

    // The user confirms a clean import of one payload...
    await paste(f, VALID_ZOD);
    cmp.discMode.set('clean');
    cmp.confirming.set(true);

    // ...then loads a different file before pressing the confirm button.
    const file = new File([VALID_EZOD], 'other.json', { type: 'application/json' });
    await cmp.onFileInput({ target: { files: [file] } } as unknown as Event);
    await settle(f);

    expect(cmp.confirming()).toBe(false);
    // submit() re-guards, so the stale approval imports nothing.
    await cmp.submit();
    expect(svc.importZod).not.toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  // Issue #81 — import transparency.
  //
  // The issue's premise ("none of it reaches the UI") was already stale when
  // filed: the per-reason skip lines and the collapsed error list all shipped in
  // Task 1 (838e54d, 2026-07-05), 23 days before #81 was opened. Task 9
  // (5e49bd2) touched this template but added the *deletion* counters, not
  // these. What was genuinely missing is what these specs cover —
  // the reconciling total that answers "my file had N discs, where did the rest
  // go?", and any spec at all asserting that the skip lines and errors actually
  // *render*. Every pre-existing spec set the skip counts to 0.
  // -------------------------------------------------------------------------

  /** Drive a successful import and return the rendered page element. */
  async function importWith(result: Record<string, unknown>): Promise<HTMLElement> {
    setup({
      imported: 0, skipped_duplicate: 0, skipped_unknown_set: 0,
      skipped_invalid: 0, errors: [], ...result,
    });
    const f = fixture();
    const cmp = f.componentInstance as unknown as {
      pasteText: { set: (v: string) => void };
      submit: () => Promise<void>;
    };
    await settle(f);
    cmp.pasteText.set(VALID_ZOD);
    await cmp.submit();
    f.detectChanges();
    return f.nativeElement as HTMLElement;
  }

  /** Summary text with runs of whitespace collapsed, so assertions can be exact. */
  function summaryText(el: HTMLElement): string {
    return (el.querySelector('[data-test="summary"]')?.textContent ?? '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  it('totals the skip reasons: N imported, M skipped', async () => {
    const el = await importWith({
      imported: 400, skipped_duplicate: 30, skipped_unknown_set: 10, skipped_invalid: 5,
    });

    // Asserted as exact text, not /45/ — a substring match also accepts 145 or 450,
    // so it would pass against a totalSkipped() that is simply wrong. 30 + 10 + 5.
    expect(summaryText(el)).toBe('400 disc(s) imported, 45 skipped. Reasons below.');
  });

  it('does not nag when nothing was skipped', async () => {
    const el = await importWith({ imported: 445 });

    expect(summaryText(el)).toBe('445 disc(s) imported, 0 skipped.');
    expect(summaryText(el)).not.toMatch(/reasons below/i);
  });

  it('distinguishes an unknown set from a malformed row', async () => {
    // The issue's point: a new patch the DB has not seeded must not look like
    // corrupt data. Both reasons have to be separately visible.
    const el = await importWith({
      imported: 10, skipped_unknown_set: 7, skipped_invalid: 3,
    });

    const text = el.textContent ?? '';
    expect(text).toMatch(/unknown set/i);
    expect(text).toMatch(/7/);
    expect(text).toMatch(/invalid/i);
    expect(text).toMatch(/3/);
  });

  it('shows the duplicate count separately again', async () => {
    const el = await importWith({ imported: 10, skipped_duplicate: 12 });

    expect(el.textContent).toMatch(/already in inventory/i);
    expect(el.textContent).toMatch(/12/);
  });

  it('surfaces error rows rather than swallowing them', async () => {
    const el = await importWith({
      imported: 2,
      skipped_invalid: 2,
      errors: ["disc[4]: bad substat key 'wat'", "disc[9]: missing slotKey"],
    });

    const details = el.querySelector('.result__errors');
    expect(details).toBeTruthy();
    expect(details?.textContent).toMatch(/2 error rows/);
    expect(details?.textContent).toMatch(/bad substat key/);
    expect(details?.textContent).toMatch(/missing slotKey/);
  });

  it('renders no error block when there were no errors', async () => {
    const el = await importWith({ imported: 5 });

    expect(el.querySelector('.result__errors')).toBeNull();
  });

  // Issue #141 follow-up: `builds_created` now means *created*, so the "View builds"
  // link can no longer gate on it alone — a pure overwrite re-import is the most
  // common flow and would have hidden the link from a user who just imported builds.

  it('offers View builds after an overwrite re-import, not just a first import', async () => {
    const el = await importWith({ imported: 0, builds_created: 0, builds_overwritten: 3 });

    expect(el.querySelector('[data-test="view-builds"]')).toBeTruthy();
  });

  it('still hides View builds when the import touched no builds at all', async () => {
    const el = await importWith({ imported: 5, builds_created: 0, builds_overwritten: 0 });

    expect(el.querySelector('[data-test="view-builds"]')).toBeNull();
  });
});
