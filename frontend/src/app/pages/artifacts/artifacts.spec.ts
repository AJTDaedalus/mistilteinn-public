import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { ArtifactsPage, describePotential, formatStat } from './artifacts';
import { ArtifactsService } from './artifacts.service';

const OPTIONS = {
  stats: [
    { key: 'FIGHT_PROP_HP', display: 'HP', percentage: false },
    { key: 'FIGHT_PROP_CRITICAL_HURT', display: 'CRIT DMG', percentage: true },
    { key: 'FIGHT_PROP_CRITICAL', display: 'CRIT Rate', percentage: true },
  ],
  slots: [
    { key: 'equip_bracer', display: 'Flower' },
    { key: 'equip_dress', display: 'Circlet' },
  ],
  rarities: [
    { key: 'five_star', stars: 5 },
    { key: 'four_star', stars: 4 },
  ],
};

const CIRCLET = {
  id: 'a1', slot: 'equip_dress', rarity: 'five_star', level: 20,
  main_stat_type: 'FIGHT_PROP_CRITICAL_HURT', main_stat_value: 0.622,
  substats: [{ stat: 'FIGHT_PROP_CRITICAL', value: 0.109, rolls: 3 }],
  artifact_set_id: 's1', set_name: 'Blizzard Strayer', build_id: null,
};

function pageWith(service: Partial<ArtifactsService>) {
  TestBed.configureTestingModule({
    providers: [{ provide: ArtifactsService, useValue: service }],
  });
  return TestBed.runInInjectionContext(() => new ArtifactsPage());
}

function healthy(service: Partial<ArtifactsService> = {}) {
  return pageWith({
    options: vi.fn().mockResolvedValue(OPTIONS),
    list: vi.fn().mockResolvedValue({ items: [CIRCLET], total: 1, truncated: false }),
    ...service,
  } as unknown as ArtifactsService);
}

describe('formatStat', () => {
  it('renders a fraction as a percentage', () => {
    // `0.622` is 62.2% CRIT DMG. Rendered as an absolute it reads "0.6", which looks like a
    // terrible roll rather than a perfect one.
    expect(formatStat(0.622, true)).toBe('62.2%');
  });

  it('renders an absolute as itself', () => {
    // And `4780` flat HP as a percentage would read "478000%".
    expect(formatStat(4780, false)).toBe('4,780');
  });
});

describe('ArtifactsPage', () => {
  it('reports a failed load instead of rendering it as "you have no artifacts"', async () => {
    const page = healthy({ options: vi.fn().mockRejectedValue(new Error('boom')) });

    await page['load']();

    expect(page['error']()).not.toBeNull();
    expect(page['artifacts']()).toEqual([]);
    expect(page['loading']()).toBe(false);
  });

  it('draws a row from the published vocabulary, not from its own tables', async () => {
    // `equip_dress`, `five_star` and `FIGHT_PROP_CRITICAL_HURT` are all source spellings.
    // Translating them here would be a third copy of `ArtifactSlot.display`, `Rarity.stars`
    // and `StatType.display`.
    const page = healthy();

    await page['load']();

    const [row] = page['rows']();
    expect(row.setName).toBe('Blizzard Strayer');
    expect(row.slot).toBe('Circlet');
    expect(row.stars).toBe(5);
    expect(row.mainStat).toBe('CRIT DMG 62.2%');
    expect(row.substats).toEqual(['CRIT Rate 10.9%']);
  });

  it('reads each piece\'s rarity from the vocabulary rather than assuming', async () => {
    // The five-star fixture above cannot tell a lookup from a hardcoded 5 — a mutation
    // hardcoding it survived until this test existed.
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [CIRCLET, { ...CIRCLET, id: 'a2', rarity: 'four_star' }],
        total: 2, truncated: false,
      }),
    } as unknown as ArtifactsService);

    await page['load']();

    expect(page['rows']().map((r) => r.stars)).toEqual([5, 4]);
  });

  it('shows a stat the vocabulary does not know rather than dropping it', async () => {
    // A piece carrying something unrecognised is worth seeing. Silently omitting it would
    // make the row look complete while a substat is missing from it.
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [{ ...CIRCLET, main_stat_type: 'FIGHT_PROP_MYSTERY', main_stat_value: 7 }],
        total: 1,
        truncated: false,
      }),
    });

    await page['load']();

    expect(page['rows']()[0].mainStat).toContain('FIGHT_PROP_MYSTERY');
  });

  it('names a setless piece rather than leaving the row blank', async () => {
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [{ ...CIRCLET, artifact_set_id: null, set_name: null }],
        total: 1, truncated: false,
      }),
    });

    await page['load']();

    expect(page['rows']()[0].setName).toBe('No set');
  });

  // ── the import ─────────────────────────────────────────────────────────────

  it('will not import without a mode being chosen', async () => {
    // `replace` and `append` are different intentions and GOOD has no stable per-artifact id
    // to merge on, so a default would be this page deciding whether to delete an inventory.
    const importGood = vi.fn();
    const page = healthy({ importGood } as unknown as ArtifactsService);
    await page['load']();
    page['payloadText'] = '{"format":"GOOD"}';

    expect(page['mode']).toBe('');
    expect(page['canImport']()).toBe(false);
    await page['runImport']();

    expect(importGood).not.toHaveBeenCalled();
  });

  it('sends the mode the user chose', async () => {
    const importGood = vi.fn().mockResolvedValue({
      inserted: 2, deleted: 0, rejected: [], ok: true, source: 'GO', version: 2,
    });
    const page = healthy({ importGood } as unknown as ArtifactsService);
    await page['load']();
    page['mode'] = 'replace';
    page['payloadText'] = '{"format":"GOOD"}';

    await page['runImport']();

    expect(importGood).toHaveBeenCalledWith('replace', { format: 'GOOD' });
  });

  it('keeps every rejection, not just the count', async () => {
    // The endpoint refuses individual artifacts rather than failing the file — someone with
    // 800 pieces and two odd ones wants the 798. Showing only "imported 798" throws away the
    // only record of the two.
    const rejected = [
      { index: 3, reason: 'unknown set "Mystery"' },
      { index: 9, reason: 'level 25 is beyond a 4-star cap of 16' },
    ];
    const page = healthy({
      importGood: vi.fn().mockResolvedValue({
        inserted: 798, deleted: 0, rejected, ok: true, source: 'GO', version: 2,
      }),
    } as unknown as ArtifactsService);
    await page['load']();
    page['mode'] = 'append';
    page['payloadText'] = '{}';

    await page['runImport']();

    expect(page['importResult']()?.rejected).toEqual(rejected);
  });

  it('blames the file, not the server, for malformed JSON', async () => {
    // A `SyntaxError` from `JSON.parse` never reached the API. Reporting it as an API error
    // would send someone looking in the wrong place.
    const importGood = vi.fn();
    const page = healthy({ importGood } as unknown as ArtifactsService);
    await page['load']();
    page['mode'] = 'append';
    page['payloadText'] = 'not json';

    await page['runImport']();

    expect(importGood).not.toHaveBeenCalled();
    expect(page['actionError']()).toContain('not valid JSON');
  });

  it('shows the API refusal verbatim', async () => {
    // A `replace` that resolved nothing is a 409 that deletes nothing, and its message says
    // so better than anything this page could invent.
    const detail = 'refusing to replace: 0 of 812 artifacts resolved.';
    const page = healthy({
      importGood: vi.fn().mockRejectedValue({ detail }),
    } as unknown as ArtifactsService);
    await page['load']();
    page['mode'] = 'replace';
    page['payloadText'] = '{}';

    await page['runImport']();

    expect(page['actionError']()).toBe(detail);
  });

  // ── filtering ──────────────────────────────────────────────────────────────

  it('filters by slot on the server, so the total matches the list', async () => {
    // Client-side filtering would page over an unfiltered list and print a total that
    // disagrees with what is on screen — the same reasoning as the catalogue pages.
    const list = vi.fn().mockResolvedValue({ items: [], total: 0, truncated: false });
    const page = healthy({ list } as unknown as ArtifactsService);
    await page['load']();

    await page['filterBySlot']('equip_bracer');

    expect(list).toHaveBeenLastCalledWith({ slot: 'equip_bracer' });
  });

  it('omits the filter entirely when showing everything', async () => {
    const list = vi.fn().mockResolvedValue({ items: [], total: 0, truncated: false });
    const page = healthy({ list } as unknown as ArtifactsService);
    await page['load']();

    await page['filterBySlot']('');

    expect(list).toHaveBeenLastCalledWith({});
  });

  it('says when the list is shorter than the total', async () => {
    const page = healthy({
      list: vi.fn().mockResolvedValue({ items: [CIRCLET], total: 900, truncated: true }),
    } as unknown as ArtifactsService);

    await page['load']();

    expect(page['truncated']()).toBe(true);
    expect(page['total']()).toBe(900);
  });
});

describe('a row the data does not fit', () => {
  it('renders a malformed substat instead of taking the page down with it', async () => {
    // `substats` is a JSONB column with no schema behind it, so a row written by an older
    // importer or by hand can hold anything. `.toFixed` on that is a TypeError inside a
    // computed — which takes out the **entire** inventory rather than one substat.
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [
          { ...CIRCLET, id: 'bad', substats: [{ stat: 'FIGHT_PROP_CRITICAL' }, null] },
          { ...CIRCLET, id: 'good' },
        ],
        total: 2,
        truncated: false,
      }),
    } as unknown as ArtifactsService);

    await page['load']();

    const rows = page['rows']();
    expect(rows).toHaveLength(2);
    expect(rows[1].substats).toEqual(['CRIT Rate 10.9%']);
    expect(rows[0].substats[0]).toContain('CRIT Rate');
  });

  it('does not throw on a non-numeric value', () => {
    expect(formatStat('oops', true)).toBe('oops');
    expect(formatStat(undefined, false)).toBe('undefined');
    expect(formatStat(Number.NaN, true)).toBe('NaN');
  });
});

describe('describePotential', () => {
  const full = {
    rolls_remaining: 3, rolls_total: 5, level: 9, max_level: 20,
    levels_to_max: 11,
  };

  it('shows the working, not just the headline', () => {
    // "3 rolls left" alone is something a reader takes on trust. "of 5 · +9 of +20" is
    // something they can check — the repo's rule that a number must explain itself applies
    // to a two-digit figure as much as to a damage total.
    expect(describePotential(full)).toEqual({
      headline: '3 rolls left',
      detail: 'of 5 · +9 of +20',
    });
  });

  it('says a maxed piece is finished rather than "0 rolls left"', () => {
    const maxed = describePotential({ ...full, rolls_remaining: 0, level: 20, levels_to_max: 0 });
    expect(maxed?.headline).toBe('Fully upgraded');
  });

  it('reads as singular for one roll', () => {
    expect(describePotential({ ...full, rolls_remaining: 1 })?.headline).toBe('1 roll left');
  });

  it('returns null when the schedule could not answer', () => {
    // Not zero. Zero is the honest answer for a maxed piece; null means the row is at a level
    // its rarity cannot reach, and "0 rolls left" would hide that behind a plausible number.
    expect(describePotential(null)).toBeNull();
  });
});

describe('ArtifactsPage potential', () => {
  it('carries potential onto the row', async () => {
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [{
          ...CIRCLET,
          potential: {
            rolls_remaining: 2, rolls_total: 5, level: 12, max_level: 20,
    levels_to_max: 8,
          },
        }],
        total: 1, truncated: false,
      }),
    } as unknown as ArtifactsService);

    await page['load']();

    expect(page['rows']()[0].potential?.headline).toBe('2 rolls left');
  });

  it('leaves an unanswerable piece null rather than inventing a zero', async () => {
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [{ ...CIRCLET, potential: null }], total: 1, truncated: false,
      }),
    } as unknown as ArtifactsService);

    await page['load']();

    expect(page['rows']()[0].potential).toBeNull();
  });
});
