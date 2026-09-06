import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import type { ArtifactRow } from './artifacts';
import { ArtifactsPage, comparator, totalRollValue } from './artifacts';
import type { RankingRow } from './artifact-ranking.service';
import { formatStat } from '../../shared/stat-label';
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

/**
 * Import, stepping through the replace confirmation when the page raises one.
 *
 * `replace` is the default and it now asks before deleting a non-empty inventory, so a test
 * about *what the import sends* would otherwise assert against a press that deliberately did
 * nothing. The two tests that are about the confirmation itself call `runImport` directly.
 */
async function importPastConfirmation(page: ArtifactsPage): Promise<void> {
  await page['runImport']();
  if (page['confirmingReplace']()) await page['runImport']();
}

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
    expect(row.substats.map((x) => x.label)).toEqual(['CRIT Rate 10.9%']);
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

  it('asks before a replace that would delete an existing inventory', async () => {
    // The default is `replace` by owner ruling, which is right for a re-scan. But a scanner
    // that died half way through 2,370 pieces writes a **valid** GOOD file holding a
    // fraction of them, and paste-then-Import would delete the rest in one click.
    const importGood = vi.fn().mockResolvedValue({
      inserted: 1, deleted: 0, rejected: [], unequipped: [], ok: true,
    });
    const page = healthy({ importGood } as unknown as ArtifactsService);
    await page['load']();
    page['payloadText'] = '{"format":"GOOD","version":2,"artifacts":[]}';

    // Directly, not via the helper: this test is *about* the two presses.
    await page['runImport']();

    // First press arms, and imports nothing.
    expect(importGood).not.toHaveBeenCalled();
    expect(page['confirmingReplace']()).toBe(true);

    await page['runImport']();

    expect(importGood).toHaveBeenCalledTimes(1);
    expect(page['confirmingReplace']()).toBe(false);
  });

  it('does not ask when there is nothing to delete', async () => {
    // An empty inventory has nothing to lose, and a confirmation there is a click that
    // teaches people to dismiss confirmations.
    const importGood = vi.fn().mockResolvedValue({
      inserted: 1, deleted: 0, rejected: [], unequipped: [], ok: true,
    });
    const page = healthy({
      importGood,
      list: vi.fn().mockResolvedValue({ items: [], total: 0, truncated: false }),
    } as unknown as ArtifactsService);
    await page['load']();
    page['payloadText'] = '{"format":"GOOD","version":2,"artifacts":[]}';

    await importPastConfirmation(page);

    expect(importGood).toHaveBeenCalledTimes(1);
  });

  it('defaults the import mode to replace', () => {
    // Owner ruling, 2026-08-28. It was deliberately empty before, so that a default could
    // not decide whether to delete someone's inventory — but GOOD carries no stable
    // per-artifact id, so appending a second scan of the same account duplicates every
    // piece, which is what the empty default was steering people into. The destructive
    // reading is the *correct* one for a re-scan, and the page says so in a warning.
    const page = healthy();

    expect(page['mode']).toBe('replace');
    expect(page['canImport']()).toBe(false);
  });

  it('sends the mode the user chose', async () => {
    const importGood = vi.fn().mockResolvedValue({
      inserted: 2, deleted: 0, rejected: [], ok: true, source: 'GO', version: 2,
    });
    const page = healthy({ importGood } as unknown as ArtifactsService);
    await page['load']();
    page['mode'] = 'replace';
    page['payloadText'] = '{"format":"GOOD"}';

    await importPastConfirmation(page);

    // The third argument is the rebuild-builds flag, on by default — see the page.
    expect(importGood).toHaveBeenCalledWith('replace', { format: 'GOOD' }, true);
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

    await importPastConfirmation(page);

    expect(page['importResult']()?.rejected).toEqual(rejected);
  });

  it('keeps the list of build slots a replace could not refill', async () => {
    // N.3. A `replace` deletes every artifact and re-inserts from the export, re-equipping
    // what it can by matching stats — GOOD has no stable per-artifact id. A slot it cannot
    // refill is named, because one that empties silently is discovered later from a damage
    // number.
    const unequipped = ['build b1 lost its equip_bracer — no matching piece in the import'];
    const page = healthy({
      importGood: vi.fn().mockResolvedValue({
        inserted: 799, deleted: 800, rejected: [], ok: true, source: 'GO', version: 2,
        unequipped,
      }),
    } as unknown as ArtifactsService);
    await page['load']();
    page['mode'] = 'replace';
    page['payloadText'] = '{}';

    await importPastConfirmation(page);

    expect(page['importResult']()?.unequipped).toEqual(unequipped);
  });

  it('blames the file, not the server, for malformed JSON', async () => {
    // A `SyntaxError` from `JSON.parse` never reached the API. Reporting it as an API error
    // would send someone looking in the wrong place.
    const importGood = vi.fn();
    const page = healthy({ importGood } as unknown as ArtifactsService);
    await page['load']();
    page['mode'] = 'append';
    page['payloadText'] = 'not json';

    await importPastConfirmation(page);

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

    await importPastConfirmation(page);

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
    expect(rows[1].substats.map((x) => x.label)).toEqual(['CRIT Rate 10.9%']);
    // The label survives; the analysis is simply absent for a row the tables cannot read.
    expect(rows[0].substats[0].label).toContain('CRIT Rate');
    expect(rows[0].substats[0].rolls).toBeNull();
    expect(page['rollBars'](rows[0].substats[0])).toEqual([]);
  });

  it('does not throw on a non-numeric value', () => {
    expect(formatStat('oops', true)).toBe('oops');
    expect(formatStat(undefined, false)).toBe('undefined');
    expect(formatStat(Number.NaN, true)).toBe('NaN');
  });
});


describe('ArtifactsPage potential', () => {
  it('says a tie is one reading of several rather than shading it silently', async () => {
    // The change that put colour back on +20 pieces: several tier combinations of the same
    // length fit, one is read, and the bars are drawn. Genshin Optimizer stops there. The
    // tooltip is what keeps it truthful — without it the reading is indistinguishable from
    // a line where exactly one decomposition fits.
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [{
          ...CIRCLET,
          substats: [{ stat: 'FIGHT_PROP_CHARGE_EFFICIENCY', value: 0.11 }],
          substat_analysis: [
            { rolls: 2, roll_tiers: [0, 3], roll_tiers_exact: false, roll_value: 1.7 },
          ],
        }],
        total: 1, truncated: false,
      }),
    } as unknown as ArtifactsService);

    await page['load']();
    const sub = page['rows']()[0].substats[0];

    expect(page['rollBars'](sub)).toEqual([0, 3]);
    expect(page['barsTitle'](sub)).toBe('2 rolls, shaded by one reading of several that fit');
  });

  it('carries the roll analysis onto each substat', async () => {
    // 5-star CRIT rate of 7.4% is 3.50 + 3.89 and nothing else, so both the count and each
    // roll's tier are established and the card can colour per roll.
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [{
          ...CIRCLET,
          substats: [{ stat: 'FIGHT_PROP_CRITICAL', value: 0.074 }],
          substat_analysis: [{ rolls: 2, roll_tiers: [2, 3], roll_value: 1.9 }],
        }],
        total: 1, truncated: false,
      }),
    } as unknown as ArtifactsService);

    await page['load']();
    const sub = page['rows']()[0].substats[0];

    expect(sub.rolls).toBe(2);
    expect(sub.tiers).toEqual([2, 3]);
    expect(page['rollBars'](sub)).toEqual([2, 3]);
    expect(page['rollValuePercent'](sub)).toBe(190);
  });

  it('draws undifferentiated bars when only the count is known', async () => {
    // **`-1`, not tier 0.** "The worst roll" and "we do not know which roll" are different
    // claims, and colouring the second as the first calls a line bad on no evidence.
    //
    // **This is now a defensive path rather than a live one.** Since the backend adopted
    // Genshin Optimizer's reading, every established count carries tiers, so a null beside a
    // non-null `rolls` no longer arrives from this API. `roll_tiers` stays nullable in the
    // contract and the renderer stays honest about it; the case is pinned here so a payload
    // that does omit them degrades to grey rather than to tier 0.
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [{
          ...CIRCLET,
          substats: [{ stat: 'FIGHT_PROP_CHARGE_EFFICIENCY', value: 0.11 }],
          substat_analysis: [{ rolls: 2, roll_tiers: null, roll_value: 1.7 }],
        }],
        total: 1, truncated: false,
      }),
    } as unknown as ArtifactsService);

    await page['load']();

    expect(page['rollBars'](page['rows']()[0].substats[0])).toEqual([-1, -1]);
  });

  it('draws no bars at all when the count itself is unsettled', async () => {
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [{
          ...CIRCLET,
          substats: [{ stat: 'FIGHT_PROP_ATTACK_PERCENT', value: 0.169 }],
          substat_analysis: [{ rolls: null, roll_tiers: null, roll_value: 2.9 }],
        }],
        total: 1, truncated: false,
      }),
    } as unknown as ArtifactsService);

    await page['load']();
    const sub = page['rows']()[0].substats[0];

    expect(page['rollBars'](sub)).toEqual([]);
    // The ratio needs no decomposition, so it survives the ambiguity.
    expect(page['rollValuePercent'](sub)).toBe(290);
  });

  it('withholds the total roll value when any line is missing one', async () => {
    // A total silently short one substat reads as a worse artifact, not an incomplete sum.
    const page = healthy({
      list: vi.fn().mockResolvedValue({
        items: [{
          ...CIRCLET,
          substats: [
            { stat: 'FIGHT_PROP_CRITICAL', value: 0.074 },
            { stat: 'FIGHT_PROP_NOT_A_STAT', value: 1 },
          ],
          substat_analysis: [
            { rolls: 2, roll_tiers: [2, 3], roll_value: 1.9 },
            { rolls: null, roll_tiers: null, roll_value: null },
          ],
        }],
        total: 1, truncated: false,
      }),
    } as unknown as ArtifactsService);

    await page['load']();

    expect(page['totalRollValue'](page['rows']()[0])).toBeNull();
  });
});

// ── narrowing, ordering, and the render cap ─────────────────────────────────
//
// The cap is the fix for the audit's largest finding: the page put all 2,370 pieces in the
// DOM at once, roughly 30,000 nodes. It rendered, which is why it survived.

describe('totalRollValue', () => {
  it('adds up a fully decomposed piece', () => {
    expect(totalRollValue([{ roll_value: 1.7 }, { roll_value: 2.6 }])).toBeCloseTo(4.3);
  });

  it('is null when any substat could not be decomposed', () => {
    // **Not a partial sum.** 3.5% of the owner's real export cannot be decomposed, and adding
    // the three that could would rank a piece by less than it has — quietly, and always
    // downward.
    expect(totalRollValue([{ roll_value: 1.7 }, { roll_value: null }])).toBeNull();
    expect(totalRollValue([{ roll_value: 1.7 }, {}])).toBeNull();
  });

  it('is null for a piece with no analysis at all', () => {
    expect(totalRollValue([])).toBeNull();
    expect(totalRollValue(null)).toBeNull();
    expect(totalRollValue(undefined)).toBeNull();
  });
});

describe('comparator', () => {
  const row = (over: Partial<ArtifactRow>): ArtifactRow => ({
    id: 'x', setName: 'Set', setIcon: null, slot: 'Flower', stars: 5, level: 20,
    mainStat: 'HP', substats: [], equipped: false, setId: 's', mainStatKey: 'hp',
    slotKey: 'flower', rollValue: 1, rank: null, ...over,
  });

  /** A ranked row, with only the fields the orderings read. */
  const ranked = (over: Partial<RankingRow>): RankingRow => ({
    id: 'x', mainStatQuantity: 'flat_hp',
    current: 0, average: 0, best: 0, worst: 0, delta: 0, averageDelta: 0,
    fraction: 0, grade: 'F', refusal: null,
    caveats: { unstable: [], staleConversions: [] },
    slot: 'equip_bracer', setId: null, level: 0, rarity: 5, equipped: false,
    rollsRemaining: 5, needsSet: null, upgradeOdds: 0.5, ...over,
  });

  it('orders by roll value, best first', () => {
    const sorted = [row({ id: 'a', rollValue: 3 }), row({ id: 'b', rollValue: 9 })]
      .sort(comparator('rollValue'));

    expect(sorted.map((r) => r.id)).toEqual(['b', 'a']);
  });

  it('sinks an undecomposed piece rather than sorting it as zero', () => {
    // **The one that matters.** As zero it would sit among the worst artifacts the user owns,
    // which is a claim about it that nothing established — "unknown" is not "worst".
    const sorted = [
      row({ id: 'unknown', rollValue: null }),
      row({ id: 'poor', rollValue: 0.1 }),
      row({ id: 'good', rollValue: 8 }),
    ].sort(comparator('rollValue'));

    expect(sorted.map((r) => r.id)).toEqual(['good', 'poor', 'unknown']);
  });

  it('keeps a stable second key so equal rows do not shuffle between renders', () => {
    const sorted = [
      row({ id: 'low', rollValue: null, level: 0 }),
      row({ id: 'high', rollValue: null, level: 20 }),
    ].sort(comparator('rollValue'));

    expect(sorted.map((r) => r.id)).toEqual(['high', 'low']);
  });

  it('orders by expected upgrade value, best first', () => {
    const sorted = [
      row({ id: 'meh', rank: ranked({ averageDelta: 10 }) }),
      row({ id: 'great', rank: ranked({ averageDelta: 900 }) }),
      row({ id: 'worse', rank: ranked({ averageDelta: -50 }) }),
    ].sort(comparator('averageDelta'));

    expect(sorted.map((r) => r.id)).toEqual(['great', 'meh', 'worse']);
  });

  it('sinks an unranked piece rather than floating it above measured ones', () => {
    // **The one that matters here.** Deltas are signed, so an unranked row treated as zero
    // would sort *above* every piece that is genuinely a downgrade — presenting an unmeasured
    // artifact as better than measured ones, which is the opposite of what it knows.
    const sorted = [
      row({ id: 'unranked', rank: null }),
      row({ id: 'downgrade', rank: ranked({ averageDelta: -500 }) }),
      row({ id: 'upgrade', rank: ranked({ averageDelta: 500 }) }),
    ].sort(comparator('averageDelta'));

    expect(sorted.map((r) => r.id)).toEqual(['upgrade', 'downgrade', 'unranked']);
  });

  it('sinks a refused piece too, which carries NaN rather than a number', () => {
    const sorted = [
      row({ id: 'refused', rank: ranked({ averageDelta: Number.NaN, refusal: 'noSchedule' }) }),
      row({ id: 'scored', rank: ranked({ averageDelta: -1 }) }),
    ].sort(comparator('averageDelta'));

    expect(sorted.map((r) => r.id)).toEqual(['scored', 'refused']);
  });

  it('orders by upgrade odds, which is #291\'s own sentence', () => {
    const sorted = [
      row({ id: 'unlikely', rank: ranked({ upgradeOdds: 0.12 }) }),
      row({ id: 'likely', rank: ranked({ upgradeOdds: 0.83 }) }),
      row({ id: 'maxed', rank: ranked({ upgradeOdds: null }) }),
    ].sort(comparator('odds'));

    // A maxed piece has no odds — it sinks rather than sorting as zero, which would put it
    // among the worst pieces owned rather than outside the question.
    expect(sorted.map((r) => r.id)).toEqual(['likely', 'unlikely', 'maxed']);
  });

  it('offers today and the ceiling as their own orderings', () => {
    expect([
      row({ id: 'a', rank: ranked({ delta: 1 }) }),
      row({ id: 'b', rank: ranked({ delta: 5 }) }),
    ].sort(comparator('delta')).map((r) => r.id)).toEqual(['b', 'a']);
    expect([
      row({ id: 'a', rank: ranked({ best: 1 }) }),
      row({ id: 'b', rank: ranked({ best: 5 }) }),
    ].sort(comparator('best')).map((r) => r.id)).toEqual(['b', 'a']);
  });

  it('orders by level, rarity and set on their own keys', () => {
    expect([row({ id: 'a', level: 0 }), row({ id: 'b', level: 20 })]
      .sort(comparator('level')).map((r) => r.id)).toEqual(['b', 'a']);
    expect([row({ id: 'a', stars: 4 }), row({ id: 'b', stars: 5 })]
      .sort(comparator('stars')).map((r) => r.id)).toEqual(['b', 'a']);
    expect([row({ id: 'a', setName: 'Zed' }), row({ id: 'b', setName: 'Ace' })]
      .sort(comparator('set')).map((r) => r.id)).toEqual(['b', 'a']);
  });
});
