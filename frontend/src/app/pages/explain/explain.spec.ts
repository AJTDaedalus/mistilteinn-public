import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { BuildsService } from '../builds/builds.service';
import { ExplainPage, enumLabel } from './explain';
import { ExplainService } from './explain.service';

const AYAKA_BUILD = {
  id: 'b1', character_id: 'c1', weapon_id: 'w1', character_level: 90,
  ascension_phase: 6, weapon_level: 90, refinement: 1, constellation_level: 0,
  talent_levels: { elemental_burst: 9 }, notes: '',
  character: { id: 'c1', name: 'Kamisato Ayaka', element: 'Cryo' },
  weapon: { id: 'w1', name: 'Mistsplitter Reforged' },
};

const HITS = [
  { talent: 'elemental_burst', label: 'Cutting DMG', index: 0, multiplier: 1.9091, hits: 1, exclusive: false,
    scaling_stat: 'atk', extra_terms: [] },
  { talent: 'elemental_burst', label: 'Bloom DMG', index: 0, multiplier: 2.86365, hits: 1, exclusive: false,
    scaling_stat: 'atk', extra_terms: [] },
];

const RESULT = {
  damage: 41234.5,
  stats: [{ quantity: 'atk', parts: [], sum_of_parts: 2100.4, sources: ['weapon 674', 'flower 311'] }],
  set_effects: [], simulation: null, uncited: [], differences: [],
  equipped_damage: null, unchanged: [],
};

function pageWith(explain: Partial<ExplainService>, builds: Partial<BuildsService> = {}) {
  TestBed.configureTestingModule({
    providers: [
      { provide: ExplainService, useValue: explain },
      { provide: BuildsService, useValue: builds },
    ],
  });
  return TestBed.runInInjectionContext(() => new ExplainPage());
}

function healthy(explain: Partial<ExplainService> = {}, builds: Partial<BuildsService> = {}) {
  return pageWith(
    {
      hits: vi.fn().mockResolvedValue(HITS),
      explain: vi.fn().mockResolvedValue(RESULT),
      ...explain,
    } as unknown as ExplainService,
    { list: vi.fn().mockResolvedValue([AYAKA_BUILD]), ...builds } as unknown as BuildsService,
  );
}

describe('enumLabel', () => {
  it('reads the enum value as a person would write it', () => {
    expect(enumLabel('elemental_burst')).toBe('Elemental burst');
  });

  // The Element and Scope selects print through this now, and printing the raw value is what
  // was reported (#286).
  it('capitalises a single-word channel', () => {
    expect(enumLabel('cryo')).toBe('Cryo');
  });

  it('reads a two-word scope as a sentence', () => {
    expect(enumLabel('any_attack')).toBe('Any attack');
  });
});

describe('ExplainService', () => {
  /** A stand-in for the generated client, capturing what the service actually POSTs. */
  function serviceWithCapture() {
    const calls: { body: Record<string, unknown> }[] = [];
    // Built in an injection context: `injectApi()` is a field initializer, so a bare `new`
    // throws NG0203 before the test reaches its assertion. `API_BASE_URL` has its own
    // factory, so no provider is needed — only a context to run in.
    TestBed.configureTestingModule({});
    const service = TestBed.runInInjectionContext(() => new ExplainService());
    (service as unknown as { api: unknown }).api = {
      POST: (_path: string, init: { body: Record<string, unknown> }) => {
        calls.push(init);
        return Promise.resolve({ data: RESULT, error: undefined });
      },
    };
    return { service, calls };
  }

  it('sends the talent and no multiplier at all', async () => {
    // The mutation that survived first time: the page tests assert what the *service* was
    // called with, and never see the body it builds. A `multiplier` reaching the wire would
    // be refused by `HitSpec`'s exclusivity rule — a 422 at runtime that no test noticed.
    const { service, calls } = serviceWithCapture();

    await service.explain(
      'b1', { talent: 'elemental_burst', label: 'Cutting DMG', index: 0 },
      'cryo', 'burst', 90,
    );

    const hit = (calls[0].body as { hit: Record<string, unknown> }).hit;
    expect(hit['talent']).toEqual({ talent: 'elemental_burst', label: 'Cutting DMG', index: 0 });
    expect(hit['multiplier']).toBeUndefined();
  });

  it('sends every field that carries a server default', async () => {
    // openapi-typescript marks a field with a default as required on the way in, and each
    // of these reproduces the server's own default. Asserted so a changed default on either
    // side shows up here rather than as a 422 in use.
    const { service, calls } = serviceWithCapture();

    await service.explain(
      'b1', { talent: 'elemental_burst', label: 'Cutting DMG', index: 0 },
      'cryo', 'burst', 90,
    );

    const body = calls[0].body as Record<string, Record<string, unknown>>;
    expect(body['hit']['flat_damage']).toBe(0);
    expect(body['compare_to_equipped']).toBe(false);
    expect(body['enemy']).toEqual({ level: 90, resistances: {}, default_resistance: 0.1 });
  });

  it("never states a scaling stat for a named talent — the talent's row does", async () => {
    // Math-fallback P0. This used to send `'atk'` and the server took it, so Neuvillette,
    // Furina and every other HP/DEF/EM scaler was explained off ATK. The server now refuses
    // a stat that contradicts the talent, so sending one could only be wrong or redundant.
    const { service, calls } = serviceWithCapture();

    await service.explain(
      'b1', { talent: 'elemental_skill', label: 'Skill DMG', index: 0 },
      'hydro', 'skill', 90,
    );

    const hit = (calls[0].body as { hit: Record<string, unknown> }).hit;
    expect('scaling_stat' in hit).toBe(false);
  });
});

describe('ExplainPage', () => {
  it('reports a failed load instead of rendering it as "you have no builds"', async () => {
    const page = healthy({}, { list: vi.fn().mockRejectedValue(new Error('boom')) });

    await page['load']();

    expect(page['error']()).not.toBeNull();
    expect(page['builds']()).toEqual([]);
    expect(page['loading']()).toBe(false);
  });

  it('loads the hits the chosen build accepts', async () => {
    // From `/builds/{id}/hits`, which uses the same parse the resolver does — so a hit shown
    // here cannot be one `/explain` then refuses.
    const page = healthy();

    await page['load']();

    expect(page['hits']()).toEqual(HITS);
    expect(page['hit']()?.label).toBe('Cutting DMG');
  });

  it('names the talent rather than sending a multiplier', async () => {
    // M.2 resolves it from the character's own table at this build's talent level. A number
    // typed on this page would be a second source for something the server already knows,
    // and the one on screen would be the one that drifted.
    const explain = vi.fn().mockResolvedValue(RESULT);
    const page = healthy({ explain } as unknown as ExplainService);
    await page['load']();

    await page['score']();

    const [, hit] = explain.mock.calls[0];
    expect(hit).toEqual({ talent: 'elemental_burst', label: 'Cutting DMG', index: 0 });
    expect(hit).not.toHaveProperty('multiplier');
  });

  it('defaults the element to the character\'s own vision', async () => {
    // Read off the build row, which already carries it — no second request, and no
    // character-to-element table on this page.
    const page = healthy();

    await page['load']();

    expect(page['channel']).toBe('cryo');
  });

  it.each([
    ['no vision at all', null],
    ['a vision that is not a damage channel', 'Adaptive'],
  ])('leaves the element alone for a character with %s', async (_case, element) => {
    // Two of the 150 have no vision, and `Element` is a wider vocabulary than the eight
    // damage channels. Assigning one straight through would put a value on the request that
    // `HitSpec` refuses — a 422 caused by the page's own default.
    const page = healthy({}, {
      list: vi.fn().mockResolvedValue([
        { ...AYAKA_BUILD, character: { id: 'c1', name: 'Someone', element } },
      ]),
    } as unknown as BuildsService);

    await page['load']();

    expect(page['channel']).toBe('physical');
  });

  it('shows the derivation, not only the total', async () => {
    // The point of the page. `/explain` returns every stat with where its parts came from,
    // and nothing displayed it until now — the damage chain has been correct and invisible
    // since Chunk F.
    const page = healthy();
    await page['load']();

    await page['score']();

    const stats = page['result']()?.stats ?? [];
    expect(stats[0].sources).toEqual(['weapon 674', 'flower 311']);
  });

  it('will not score a build with no talent levels set', async () => {
    const explain = vi.fn();
    const page = healthy({ hits: vi.fn().mockResolvedValue([]), explain } as unknown as ExplainService);
    await page['load']();

    expect(page['canScore']()).toBe(false);
    await page['score']();

    expect(explain).not.toHaveBeenCalled();
  });

  it('clears a stale result when the build changes', async () => {
    // Otherwise the previous build's damage sits under the new build's name — a number that
    // looks right and refers to something else.
    const page = healthy();
    await page['load']();
    await page['score']();
    expect(page['result']()).not.toBeNull();

    await page['selectBuild']('b1');

    expect(page['result']()).toBeNull();
  });

  it('shows the API refusal verbatim and drops the stale result', async () => {
    const detail = 'this build has no character, so a talent cannot be resolved.';
    const page = healthy();
    await page['load']();
    await page['score']();

    (page['explainService'] as unknown as { explain: unknown }).explain =
      vi.fn().mockRejectedValue({ detail });
    await page['score']();

    expect(page['actionError']()).toBe(detail);
    expect(page['result']()).toBeNull();
  });

  it('surfaces a failed hit load without wiping the page', async () => {
    const page = healthy({ hits: vi.fn().mockRejectedValue(new Error('boom')) } as unknown as ExplainService);

    await page['load']();

    expect(page['actionError']()).not.toBeNull();
    expect(page['error']()).toBeNull();
    expect(page['builds']()).toHaveLength(1);
  });
});
