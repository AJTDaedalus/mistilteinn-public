import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { type Slot, search } from '../../sim/search';
import { ArtifactsService } from '../artifacts/artifacts.service';
import { BuildsService } from '../builds/builds.service';
import { ExplainService } from '../explain/explain.service';
import { OptimizePage, describePieces } from './optimize';
import { OptimizeService } from './optimize.service';

const AYAKA_BUILD = {
  id: 'b1', character_id: 'c1', weapon_id: 'w1', character_level: 90,
  ascension_phase: 6, weapon_level: 90, refinement: 1, constellation_level: 0,
  talent_levels: { elemental_burst: 9 }, notes: '',
  character: { id: 'c1', name: 'Kamisato Ayaka', element: 'Cryo' },
  weapon: { id: 'w1', name: 'Mistsplitter Reforged' },
};

const HITS = [
  { talent: 'elemental_burst', label: 'Cutting DMG', index: 0, multiplier: 1.9091, hits: 1, exclusive: false },
];

const OPTIONS = {
  stats: [], rarities: [],
  slots: [
    { key: 'equip_bracer', display: 'Flower' },
    { key: 'equip_necklace', display: 'Plume' },
    { key: 'equip_shoes', display: 'Sands' },
    { key: 'equip_ring', display: 'Goblet' },
    { key: 'equip_dress', display: 'Circlet' },
  ],
};

const CONTEXT = {
  base: { base_atk: 1000, base_hp: 20000, base_def: 800, crit_rate: 0.05, crit_dmg: 0.5 },
  hit: { multiplier: 2.0, channel: 'cryo', scaling_stat: 'atk', amplifying: null },
  target: { level: 90, resistance: 0.1, def_reduction: 0, def_ignore: 0 },
  character_level: 90,
  dmg_bonus_quantity: 'cryo_dmg_bonus',
  set_bonuses: [],
};

const SLOTS = ['equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring', 'equip_dress'];

/**
 * An inventory with **one obviously best piece per slot**.
 *
 * The winner is knowable without running the kernel: every slot offers a weak piece and a
 * strong one, and more ATK is strictly better for an ATK-scaling hit with no set bonuses. A
 * fixture whose answer needed the kernel to compute it would only prove the kernel agrees
 * with itself.
 */
function inventory() {
  return SLOTS.flatMap((slot) => [
    { id: `${slot}-weak`, slot, set_id: 1, stats: { flat_atk: 10 } },
    { id: `${slot}-strong`, slot, set_id: 1, stats: { flat_atk: 100 } },
  ]);
}

function pageWith(overrides: {
  optimize?: Partial<OptimizeService>;
  builds?: Partial<BuildsService>;
  explain?: Partial<ExplainService>;
  artifacts?: Partial<ArtifactsService>;
} = {}) {
  TestBed.configureTestingModule({
    providers: [
      {
        provide: OptimizeService,
        useValue: {
          context: vi.fn().mockResolvedValue(CONTEXT),
          inventory: vi.fn().mockResolvedValue({
            version: 'v1', artifacts: inventory(), total: 10,
            truncated: false, unreadable: [],
          }),
          ...overrides.optimize,
        } as unknown as OptimizeService,
      },
      {
        provide: BuildsService,
        useValue: {
          list: vi.fn().mockResolvedValue([AYAKA_BUILD]),
          ...overrides.builds,
        } as unknown as BuildsService,
      },
      {
        provide: ExplainService,
        useValue: {
          hits: vi.fn().mockResolvedValue(HITS),
          ...overrides.explain,
        } as unknown as ExplainService,
      },
      {
        provide: ArtifactsService,
        useValue: {
          options: vi.fn().mockResolvedValue(OPTIONS),
          ...overrides.artifacts,
        } as unknown as ArtifactsService,
      },
    ],
  });
  return TestBed.runInInjectionContext(() => new OptimizePage());
}

describe('describePieces', () => {
  it('names pieces from the candidates the search was actually given', () => {
    // Not re-fetched: a second lookup could disagree with what was searched, and the row
    // would then describe a build the ranking did not produce.
    const named = describePieces(
      ['a', 'b'],
      [
        { id: 'a', slot: 'equip_bracer', set_id: 1, stats: {} },
        { id: 'b', slot: 'equip_dress', set_id: 1, stats: {} },
      ],
      (slot) => ({ equip_bracer: 'Flower', equip_dress: 'Circlet' })[slot] ?? slot,
    );

    expect(named).toEqual(['Flower', 'Circlet']);
  });

  it('falls back to the id for a piece it was not given', () => {
    // Better a visible id than a blank: a row silently missing a piece looks like a
    // four-piece build.
    expect(describePieces(['ghost'], [], (s) => s)).toEqual(['ghost']);
  });
});

describe('OptimizePage', () => {
  it('reports a failed load instead of rendering it as "you have no builds"', async () => {
    const page = pageWith({ builds: { list: vi.fn().mockRejectedValue(new Error('boom')) } });

    await page['load']();

    expect(page['error']()).not.toBeNull();
    expect(page['builds']()).toEqual([]);
  });

  it('runs the real kernel and picks the known winner', async () => {
    // O.3's acceptance criterion. `search()` here is the actual module four CI gates pin
    // against the Python optimizer — not a stub — so this is the first time anything but a
    // script has run it.
    const page = pageWith();
    await page['load']();

    await page['run']();

    const rows = page['rows']();
    expect(rows).not.toHaveLength(0);
    expect(rows[0].artifactIds.sort()).toEqual(
      SLOTS.map((s) => `${s}-strong`).sort(),
    );
  });

  it('names the winning pieces by slot, from the published vocabulary', async () => {
    // `ArtifactSlot.display` is the server's; writing the five names here would be a second
    // copy of it — which the first draft of this page did.
    const page = pageWith();
    await page['load']();

    await page['run']();

    expect(page['rows']()[0].pieces.sort()).toEqual(
      ['Circlet', 'Flower', 'Goblet', 'Plume', 'Sands'],
    );
  });

  it('reports how much was actually searched', async () => {
    // A search over 40 combinations and one over 4 million look identical when only the
    // winner is shown.
    const page = pageWith();
    await page['load']();

    await page['run']();

    const found = page['result']();
    expect(found?.evaluated).toBeGreaterThan(0);
    expect(typeof found?.isExact).toBe('boolean');
  });

  it('shows pieces the server could not read rather than swallowing them', async () => {
    // OQ-O2. A search over an inventory quietly missing pieces recommends the best of what
    // it was shown while looking like the best of what the user owns.
    const unreadable = [{ artifact_id: 'a9', reason: 'unknown prop FIGHT_PROP_MYSTERY' }];
    const page = pageWith({
      optimize: {
        inventory: vi.fn().mockResolvedValue({
          version: 'v1', artifacts: inventory(), total: 10,
          truncated: false, unreadable,
        }),
      } as unknown as Partial<OptimizeService>,
    });
    await page['load']();

    await page['run']();

    expect(page['unreadable']()).toEqual(unreadable);
  });

  it('surfaces a truncated inventory', async () => {
    const page = pageWith({
      optimize: {
        inventory: vi.fn().mockResolvedValue({
          version: 'v1', artifacts: inventory(), total: 10,
          truncated: true, unreadable: [],
        }),
      } as unknown as Partial<OptimizeService>,
    });
    await page['load']();

    await page['run']();

    expect(page['truncated']()).toBe(true);
  });

  it('gives a setless piece a set nothing else can match', async () => {
    // `set_id: null` must not become 0 — that is a real catalogue id, and five setless
    // starter relics would be handed a four-piece bonus they do not have.
    const page = pageWith({
      optimize: {
        inventory: vi.fn().mockResolvedValue({
          version: 'v1',
          artifacts: SLOTS.map((slot) => (
            { id: `${slot}-none`, slot, set_id: null, stats: { flat_atk: 50 } }
          )),
          total: 5, truncated: false, unreadable: [],
        }),
        context: vi.fn().mockResolvedValue({
          ...CONTEXT,
          set_bonuses: [{ set_id: 0, pieces_required: 4, stats: { atk_pct: 10 } }],
        }),
      } as unknown as Partial<OptimizeService>,
    });
    await page['load']();

    await page['run']();

    // The huge set-0 bonus must not have applied: with it, damage would be far larger.
    const withoutBonus = page['result']()?.builds[0].setCounts ?? {};
    expect(withoutBonus[0]).toBeUndefined();
  });

  it('clears a stale result when the build changes', async () => {
    // A result belongs to the build it was searched for; left up it sits under another
    // character's name.
    const page = pageWith();
    await page['load']();
    await page['run']();
    expect(page['result']()).not.toBeNull();

    await page['selectBuild']('b1');

    expect(page['result']()).toBeNull();
  });

  it('will not search a build with no talent levels set', async () => {
    const context = vi.fn();
    const page = pageWith({
      explain: { hits: vi.fn().mockResolvedValue([]) } as unknown as Partial<ExplainService>,
      optimize: { context } as unknown as Partial<OptimizeService>,
    });
    await page['load']();

    expect(page['canSearch']()).toBe(false);
    await page['run']();

    expect(context).not.toHaveBeenCalled();
  });

  it('shows the API refusal verbatim and drops the stale result', async () => {
    const detail = 'this build has no character, so there is no base to add artifacts to.';
    const page = pageWith();
    await page['load']();
    await page['run']();

    (page['optimize'] as unknown as { context: unknown }).context =
      vi.fn().mockRejectedValue({ detail });
    await page['run']();

    expect(page['actionError']()).toBe(detail);
    expect(page['result']()).toBeNull();
  });
});

describe('the two vocabularies must be the same vocabulary', () => {
  // One case per test: `TestBed` allows a single module per test, so a loop over the four
  // would configure it twice and fail for a reason unrelated to what is being checked.
  it.each(['atk', 'hp', 'def', 'elemental_mastery'])(
    'accepts %s, which the backend can send',
    async (scaling) => {
      // `as ScalingStat` asserts an agreement nothing checked. The backend's `ScalingStat`
      // is these four and the kernel's is the same four — but the first draft cast to three
      // of them, which the compiler accepted and which would have been a lie the day an
      // EM-scaling hit arrived.
      const page = pageWith({
        optimize: {
          context: vi.fn().mockResolvedValue({
            ...CONTEXT, hit: { ...CONTEXT.hit, scaling_stat: scaling },
          }),
        } as unknown as Partial<OptimizeService>,
      });
      await page['load']();

      await page['run']();

      expect(page['actionError']()).toBeNull();
      expect(page['result']()).not.toBeNull();
    },
  );

  it('passes an amplifying reaction through rather than nulling it', async () => {
    // `as null` claimed the field is always null. It is not — melt and vaporize are the
    // reason the kernel has `AMPLIFYING_MULTIPLIER` — and a search that dropped it would
    // rank every build as though the reaction did not happen.
    // Compared against the kernel called **directly** with the same inputs — a pure
    // function, so no second TestBed. If the page dropped `amplifying`, its number would
    // match the unamplified call instead of the amplified one, and both are computed here
    // rather than asserted from a constant.
    const page = pageWith({
      optimize: {
        context: vi.fn().mockResolvedValue({
          ...CONTEXT, hit: { ...CONTEXT.hit, amplifying: 'melt' },
        }),
      } as unknown as Partial<OptimizeService>,
    });
    await page['load']();

    await page['run']();

    const fromPage = page['result']()?.builds[0].damage ?? 0;
    const direct = (amplifying: 'melt' | null) =>
      search(
        inventory().map((p) => ({ id: p.id, slot: p.slot as Slot, setId: p.set_id, stats: p.stats })),
        {
          base: CONTEXT.base,
          hit: {
            multiplier: CONTEXT.hit.multiplier,
            scalingStat: 'atk',
            flatDamage: 0,
            baseDamageBonus: 0,
            amplifying,
            reactionBonus: 0,
          },
          target: { level: 90, resistance: 0.1, defReduction: 0, defIgnore: 0 },
          characterLevel: 90,
          dmgBonusQuantity: 'cryo_dmg_bonus',
          setBonuses: [],
        },
      ).builds[0].damage;

    expect(fromPage).toBeCloseTo(direct('melt'), 6);
    expect(direct('melt')).toBeGreaterThan(direct(null));
  });

  it('reports a slot the kernel does not know rather than dropping it silently', async () => {
    // The search buckets by slot, so an unknown one is never considered — the ranking would
    // be over four slots while claiming to be over five.
    const page = pageWith({
      optimize: {
        inventory: vi.fn().mockResolvedValue({
          version: 'v1',
          artifacts: [
            ...inventory(),
            { id: 'odd', slot: 'equip_mystery', set_id: 1, stats: { flat_atk: 9999 } },
          ],
          total: 11, truncated: false, unreadable: [],
        }),
      } as unknown as Partial<OptimizeService>,
    });
    await page['load']();

    await page['run']();

    expect(page['unreadable']().map((u) => u.artifact_id)).toContain('odd');
    expect(page['result']()).not.toBeNull();
  });
});

describe('explaining the winner', () => {
  /** What the server would return for a build whose search damage is `damage`. */
  function explanation(damage: number) {
    return {
      damage,
      stats: [{ quantity: 'atk', parts: [], sum_of_parts: 1500, sources: ['flower 100'] }],
      set_effects: [], simulation: null, uncited: [], differences: [],
      equipped_damage: null, unchanged: [],
    };
  }

  it('hands the winning five back to the server', async () => {
    // `/explain` takes `artifact_ids`, so the same combination the kernel scored is what the
    // server accounts for. Anything else would explain a different build.
    const explain = vi.fn().mockResolvedValue(explanation(1));
    const page = pageWith({ explain: { explain } as unknown as Partial<ExplainService> });
    await page['load']();
    await page['run']();
    const winner = page['rows']()[0];

    await page['explainRow'](winner);

    const [buildId, hit, , , , artifactIds] = explain.mock.calls[0];
    expect(buildId).toBe('b1');
    expect(hit).toEqual({ talent: 'elemental_burst', label: 'Cutting DMG', index: 0 });
    expect([...artifactIds].sort()).toEqual([...winner.artifactIds].sort());
  });

  it('reports how far the two implementations diverge', async () => {
    // The point of the pairing. The browser's f32 kernel and the server's f64 chain compute
    // the same build, and C.2 measured their divergence at up to 3.4e-07 — so a difference
    // of that order is the tolerance working, and a larger one is a real disagreement.
    const page = pageWith({
      explain: {
        explain: vi.fn(async () => explanation(0)),
      } as unknown as Partial<ExplainService>,
    });
    await page['load']();
    await page['run']();
    const winner = page['rows']()[0];

    // The server "agrees" exactly: divergence is zero.
    (page['explain'] as unknown as { explain: unknown }).explain =
      vi.fn().mockResolvedValue(explanation(winner.damage));
    await page['explainRow'](winner);
    expect(page['divergence']()).toBeCloseTo(0, 12);

    // And a 1% disagreement is reported as 1%, not smoothed away.
    (page['explain'] as unknown as { explain: unknown }).explain =
      vi.fn().mockResolvedValue(explanation(winner.damage * 1.01));
    await page['explainRow'](winner);
    expect(page['divergence']()).toBeCloseTo(0.01, 6);
  });

  it('shows the derivation, not just the total', async () => {
    const page = pageWith({
      explain: {
        explain: vi.fn().mockResolvedValue(explanation(1234)),
      } as unknown as Partial<ExplainService>,
    });
    await page['load']();
    await page['run']();

    await page['explainRow'](page['rows']()[0]);

    expect(page['explained']()?.result.stats[0].sources).toEqual(['flower 100']);
  });

  it('drops a stale explanation when a new search runs', async () => {
    // An explanation belongs to the ranking it came from. Left up, it sits under a new
    // winner and describes a build no longer on screen.
    const page = pageWith({
      explain: {
        explain: vi.fn().mockResolvedValue(explanation(1)),
      } as unknown as Partial<ExplainService>,
    });
    await page['load']();
    await page['run']();
    await page['explainRow'](page['rows']()[0]);
    expect(page['explained']()).not.toBeNull();

    await page['run']();

    expect(page['explained']()).toBeNull();
  });

  it('shows the API refusal verbatim and drops the stale explanation', async () => {
    const detail = 'the pieces to explain must be five pieces, one per slot.';
    const page = pageWith({
      explain: {
        explain: vi.fn().mockResolvedValue(explanation(1)),
      } as unknown as Partial<ExplainService>,
    });
    await page['load']();
    await page['run']();
    await page['explainRow'](page['rows']()[0]);

    (page['explain'] as unknown as { explain: unknown }).explain =
      vi.fn().mockRejectedValue({ detail });
    await page['explainRow'](page['rows']()[0]);

    expect(page['actionError']()).toBe(detail);
    expect(page['explained']()).toBeNull();
  });

  it('has no divergence to report before anything is explained', async () => {
    const page = pageWith();
    await page['load']();
    await page['run']();

    expect(page['divergence']()).toBeNull();
  });
});

describe('pairing an explanation with its row', () => {
  it('pairs by rank rather than by position', async () => {
    // `rows()[rank - 1]` is right as rows are built and is an assumption the template should
    // not carry: a filtered or reordered list would silently pair an explanation with a
    // *different* build — the "number that refers to something else" this page rules out.
    // The default inventory yields **one** row: its weak pieces are strictly dominated, so
    // the Pareto prefilter removes them and one combination survives. Two rows need two
    // options that trade off — flat ATK against crit rate, neither dominating the other.
    const page = pageWith({
      optimize: {
        inventory: vi.fn().mockResolvedValue({
          version: 'v1',
          artifacts: [
            ...SLOTS.slice(1).map((slot) => (
              { id: `${slot}-only`, slot, set_id: 1, stats: { flat_atk: 100 } }
            )),
            { id: 'atk', slot: SLOTS[0], set_id: 1, stats: { flat_atk: 200 } },
            { id: 'crit', slot: SLOTS[0], set_id: 1, stats: { crit_rate: 0.4 } },
          ],
          total: 6, truncated: false, unreadable: [],
        }),
      } as unknown as Partial<OptimizeService>,
      explain: {
        explain: vi.fn().mockResolvedValue({
          damage: 99, stats: [], set_effects: [], simulation: null, uncited: [],
          differences: [], equipped_damage: null, unchanged: [],
        }),
      } as unknown as Partial<ExplainService>,
    });
    await page['load']();
    await page['run']();
    expect(page['rows']().length).toBeGreaterThan(1);
    const second = page['rows']()[1];

    await page['explainRow'](second);

    const paired = page['pairing']();
    expect(paired?.shown.rank).toBe(second.rank);
    expect(paired?.row.artifactIds).toEqual(second.artifactIds);
  });

  it('pairs with nothing when the ranking no longer holds that rank', async () => {
    // The state a crash would come from: an explanation outliving the row it describes.
    const page = pageWith({
      explain: {
        explain: vi.fn().mockResolvedValue({
          damage: 1, stats: [], set_effects: [], simulation: null, uncited: [],
          differences: [], equipped_damage: null, unchanged: [],
        }),
      } as unknown as Partial<ExplainService>,
    });
    await page['load']();
    await page['run']();
    await page['explainRow'](page['rows']()[0]);

    page['explained'].set({ ...page['explained']()!, rank: 999 });

    expect(page['pairing']()).toBeNull();
    expect(page['divergence']()).toBeNull();
  });
});
