import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { type Slot, search } from '../../sim/search';
import { ArtifactsService } from '../artifacts/artifacts.service';
import { RecipeOptimizeService } from './recipe-optimize.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService } from '../teams/teams.service';
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
  rotations?: Partial<RotationsService>;
  recipeOptimize?: Partial<RecipeOptimizeService>;
  teams?: Partial<TeamsService>;
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
          // `loadFilterData` calls both. Without stubs it throws, is caught, and leaves the
          // catalogue empty — which then trips the unresolved-set guard and silently stops
          // every rotation run before it calibrates anything.
          artifactSets: vi.fn().mockResolvedValue(new Map()),
          setBonuses: vi.fn().mockResolvedValue([]),
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
      ...(overrides.recipeOptimize
        ? [{
            provide: RecipeOptimizeService,
            useValue: overrides.recipeOptimize as unknown as RecipeOptimizeService,
          }]
        : []),
      {
        // Teams narrow the build grid (§6). `load()` catches a failure here rather than
        // failing the page, so an unstubbed service would leave the team picker silently
        // empty instead of erroring — which is exactly the shape of bug worth a stub.
        provide: TeamsService,
        useValue: {
          list: vi.fn().mockResolvedValue([]),
          ...overrides.teams,
        } as unknown as TeamsService,
      },
      {
        // The page loads rotations for the rotation objective (R.8). Without a stub, `load()`
        // never settles and every test here times out rather than failing on an assertion.
        provide: RotationsService,
        useValue: {
          list: vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 }),
          ...overrides.rotations,
        } as unknown as RotationsService,
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
        { id: 'a', slot: 'equip_bracer', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_HP' },
        { id: 'b', slot: 'equip_dress', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_CRITICAL' },
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
            { id: 'odd', slot: 'equip_mystery', set_id: 1, stats: { flat_atk: 9999 }, main_stat: 'FIGHT_PROP_HP' },
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


describe('OptimizePage — the rotation objective', () => {
  /** `protected` members are reachable at runtime; the cast keeps the spec honest about that. */
  const at = (page: unknown, key: string) => (page as Record<string, never>)[key];

  it('reads rotations out of the paginated envelope', async () => {
    // Treating it as an array leaves the picker empty, which looks exactly like having
    // authored no rotations — the trap W.6's compare page fell into.
    const page = pageWith({
      rotations: {
        list: vi.fn().mockResolvedValue({
          items: [{ id: 'r1', name: 'Burst' }], total: 1, offset: 0, limit: 50,
        }),
      },
    });
    await (at(page, 'load') as () => Promise<void>).call(page);

    expect((at(page, 'rotations') as () => unknown[])())
      .toEqual([{ id: 'r1', name: 'Burst' }]);
  });

  /** Pieces forming a 4-piece of each named set, four distinct slots apiece. */
  const piecesFor = (...setIds: number[]) =>
    setIds.flatMap((setId) =>
      ['equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring'].map((slot, i) => ({
        id: `${setId}-${i}`, slot, set_id: setId, stats: {},
      })),
    );

  it('starts with nothing selected, and will not search until a set is picked', () => {
    // Owner ruling 3 (docs/DECISIONS.md, 2026-08-28). It defaulted to every reachable set,
    // which cost ~3.8 min before any output — affordable only while a streaming leaderboard
    // was planned to cover it, and ruling 2 removed streaming.
    //
    // **This is the test that was missing when the default flipped**: the change passed 385
    // green tests, because nothing pinned what the default was.
    const page = pageWith();
    page['rotationId'].set('r1');

    expect((at(page, 'selectedSets') as () => ReadonlySet<number>)().size).toBe(0);
    expect((at(page, 'canSearchRotation') as () => boolean)()).toBe(false);

    (at(page, 'toggleSet') as (id: number) => void).call(page, 15003);

    expect((at(page, 'canSearchRotation') as () => boolean)()).toBe(true);
  });

  it('will not start a run whose only work is the baseline', () => {
    // Six seconds to answer a question the user did not ask.
    const page = pageWith();
    expect((at(page, 'canSearchRotation') as () => boolean)()).toBe(false);
  });

  it('costs one calibration per selected set, plus the baseline', () => {
    // The count is shown before the run because it is what the user is agreeing to.
    const page = pageWith();
    (at(page, 'candidates') as { set: (v: unknown) => void })
      .set(piecesFor(15003, 15020));

    const count = at(page, 'calibrationCount') as () => number;
    const toggle = at(page, 'toggleSet') as (id: number) => void;

    expect(count()).toBe(1);
    toggle.call(page, 15003);
    expect(count()).toBe(2);
    toggle.call(page, 15020);
    expect(count()).toBe(3);
    // Toggling off is a real toggle, not an add-only set.
    toggle.call(page, 15003);
    expect(count()).toBe(2);
  });

  it('offers every reachable set when All is pressed, and none when None is', () => {
    const page = pageWith();
    (at(page, 'candidates') as { set: (v: unknown) => void })
      .set(piecesFor(15003, 15020));

    (at(page, 'selectAllSets') as () => void).call(page);
    expect((at(page, 'selectedSets') as () => ReadonlySet<number>)().size).toBe(2);

    (at(page, 'selectNoSets') as () => void).call(page);
    expect((at(page, 'selectedSets') as () => ReadonlySet<number>)().size).toBe(0);
  });

  it('treats a pair as chosen only when both halves are set and differ', () => {
    // Two of the same set is a 4-piece, not a 2+2, and belongs to the other control.
    const page = pageWith();
    const first = at(page, 'pairFirst') as { set: (v: number | null) => void };
    const second = at(page, 'pairSecond') as { set: (v: number | null) => void };
    const chosen = at(page, 'chosenPair') as () => unknown;

    expect(chosen()).toBeNull();
    first.set(7);
    expect(chosen()).toBeNull();
    second.set(7);
    expect(chosen()).toBeNull();
    second.set(8);
    expect(chosen()).toEqual([7, 8]);
  });

  it('lets a pair alone justify a search, and costs one more calibration', () => {
    // B.5 retired `includeNoFourPiece`, so a pair is now the only way to reach a build with
    // no 4-piece — and it is a state that is actually calibrated rather than scored from
    // stat pools that nine of the sixty 2-piece bonuses have nothing to put in.
    const page = pageWith();
    page['rotationId'].set('r1');
    (at(page, 'candidates') as { set: (v: unknown) => void }).set(piecesFor(15003, 15020));

    expect((at(page, 'canSearchRotation') as () => boolean)()).toBe(false);
    expect((at(page, 'calibrationCount') as () => number)()).toBe(1);

    (at(page, 'pairFirst') as { set: (v: number) => void }).set(15003);
    (at(page, 'pairSecond') as { set: (v: number) => void }).set(15020);

    expect((at(page, 'canSearchRotation') as () => boolean)()).toBe(true);
    expect((at(page, 'calibrationCount') as () => number)()).toBe(2);
  });

  it('calibrates a pair as one state holding both sets', () => {
    const page = pageWith();
    (at(page, 'artifactSets') as { set: (m: Map<number, unknown>) => void }).set(
      new Map<number, unknown>([
        [15003, { id: 'uuid-bs', name: 'Blizzard Strayer' }],
        [15020, { id: 'uuid-wt', name: "Wanderer's Troupe" }],
      ]),
    );
    (at(page, 'pairFirst') as { set: (v: number) => void }).set(15003);
    (at(page, 'pairSecond') as { set: (v: number) => void }).set(15020);

    const targets = (at(page, 'calibrationTargets') as (c: number[]) => {
      artifactSetIds: string[]; setIds: number[]; label: string;
    }[]).call(page, []);

    expect(targets).toHaveLength(2);
    expect(targets[1].setIds).toEqual([15003, 15020]);
    expect(targets[1].artifactSetIds).toEqual(['uuid-bs', 'uuid-wt']);
    expect(targets[1].label).toContain('2+2');
  });

  it('renders no ranking while a state is still calibrating', async () => {
    // **Owner ruling 2 (docs/DECISIONS.md, 2026-08-28): only complete calculations are
    // offered.** A leaderboard that reorders while you read it is the hazard `isExact`,
    // `uncoveredSets` and `unmodelled_passives` all exist to prevent, wearing a progress bar.
    //
    // The code already satisfies this — `result` is set once, after every state finishes — so
    // this pins a property rather than building one. It is one edit from being lost in a way
    // that would look like a feature.
    const seenMidRun: unknown[] = [];

    const calibrateAll = vi.fn(async (
      _b: string, _r: string, _v: string,
      targets: { label: string }[],
      onProgress: (p: unknown) => void,
    ) => {
      for (const [i, target] of targets.entries()) {
        onProgress({ done: i, total: targets.length, current: target.label, loading: false });
        // What a user could see at this instant.
        seenMidRun.push((page as Record<string, () => unknown>)['result']());
      }
      return {
        byFourPieceSet: new Map(), noFourPiece: null,
        caveats: { unstable: [], staleConversions: [], fromCache: [] },
      };
    });

    // Declared after `calibrateAll`, which closes over it: the closure only runs once the
    // page exists, so the reference resolves.
    const page: unknown = pageWith({
      recipeOptimize: { calibrateAll } as unknown as Partial<RecipeOptimizeService>,
      optimize: {
        // Without this the run stops at the unresolved-set guard and never calibrates —
        // which is itself correct behaviour, and would have made this test vacuous.
        artifactSets: vi.fn().mockResolvedValue(
          new Map([[1, { id: 'uuid-1', name: 'Set One' }]]),
        ),
      } as unknown as Partial<OptimizeService>,
      rotations: {
        list: vi.fn().mockResolvedValue({
          items: [{ id: 'r1', name: 'Burst' }], total: 1, offset: 0, limit: 50,
        }),
      },
    });
    await (at(page, 'load') as () => Promise<void>).call(page);
    await (at(page, 'loadFilterData') as () => Promise<void>).call(page);
    (at(page, 'toggleSet') as (id: number) => void).call(page, 1);
    (at(page, 'buildId') as { set: (v: string) => void }).set(AYAKA_BUILD.id);

    await (at(page, 'runRotation') as () => Promise<void>).call(page);

    expect(calibrateAll).toHaveBeenCalled();
    expect(seenMidRun.length).toBeGreaterThan(0);
    // Not one partial ranking was visible at any point during the run.
    expect(seenMidRun.every((r) => r === null)).toBe(true);
  });

  it('starts on the single-hit objective, which stays reachable', () => {
    // OQ-W4: deleting a fast honest answer because a slow better one exists is a downgrade.
    const page = pageWith();

    expect((at(page, 'objective') as () => string)()).toBe('hit');
  });

  it('does not calibrate when no rotation is chosen', async () => {
    const page = pageWith();
    await (at(page, 'runRotation') as () => Promise<void>).call(page);

    expect((at(page, 'caveats') as () => unknown)()).toBeNull();
  });

  it('counts a four-piece set by distinct slots, not by piece count', () => {
    // Four pieces of a set sharing a slot form no combination, and calibrating for them would
    // spend ~3.2s on a state nothing can reach.
    const page = pageWith();
    const reachable = (at(page, 'reachableSets') as (p: unknown[]) => number[])
      .call(page, [
        { id: 'a', slot: 'equip_bracer', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_HP' },
        { id: 'b', slot: 'equip_bracer', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_HP' },
        { id: 'c', slot: 'equip_bracer', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_HP' },
        { id: 'd', slot: 'equip_bracer', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_HP' },
      ]);

    expect(reachable).toEqual([]);
  });

  it('orders sets by how many distinct slots the user owns', () => {
    // R.1 measured a real account at S = 35 — 36 calibrations, ~3.8 minutes. Ordering does
    // not make that shorter; it makes stopping early useful, because the sets a user has
    // farmed most come first. It also decides the order of the 4-piece filter.
    const page = pageWith();
    const reachable = (at(page, 'reachableSets') as (p: unknown[]) => number[])
      .call(page, [
        // Set 2 reaches all five slots; set 1 reaches four.
        { id: 'a', slot: 'equip_bracer', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_HP' },
        { id: 'b', slot: 'equip_necklace', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_ATTACK' },
        { id: 'c', slot: 'equip_shoes', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_ATTACK_PERCENT' },
        { id: 'd', slot: 'equip_ring', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_ATTACK_PERCENT' },
        { id: 'e', slot: 'equip_bracer', set_id: 2, stats: {}, main_stat: 'FIGHT_PROP_HP' },
        { id: 'f', slot: 'equip_necklace', set_id: 2, stats: {}, main_stat: 'FIGHT_PROP_ATTACK' },
        { id: 'g', slot: 'equip_shoes', set_id: 2, stats: {}, main_stat: 'FIGHT_PROP_ATTACK_PERCENT' },
        { id: 'h', slot: 'equip_ring', set_id: 2, stats: {}, main_stat: 'FIGHT_PROP_ATTACK_PERCENT' },
        { id: 'i', slot: 'equip_dress', set_id: 2, stats: {}, main_stat: 'FIGHT_PROP_CRITICAL' },
      ]);

    expect(reachable).toEqual([2, 1]);
  });

  it('includes a set that reaches four distinct slots', () => {
    const page = pageWith();
    const reachable = (at(page, 'reachableSets') as (p: unknown[]) => number[])
      .call(page, [
        { id: 'a', slot: 'equip_bracer', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_HP' },
        { id: 'b', slot: 'equip_necklace', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_ATTACK' },
        { id: 'c', slot: 'equip_shoes', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_ATTACK_PERCENT' },
        { id: 'd', slot: 'equip_ring', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_ATTACK_PERCENT' },
      ]);

    expect(reachable).toEqual([1]);
  });

  it('calibrates with the catalogue uuid, not the id an artifact carries', () => {
    // **The bug this pins.** An inventory snapshot's `set_id` is the nanoka id (15003);
    // `/calibrate` resolves `artifact_set_id` with `get_by_id`, which wants the catalogue
    // uuid. The page passed the nanoka id straight through, so every 4-piece calibration
    // 404'd — verified live against the real backend. Nothing caught it because no UI called
    // the endpoint until #119, and #119's tests mock `fetch`.
    const page = pageWith();
    (at(page, 'artifactSets') as { set: (m: Map<number, unknown>) => void }).set(
      new Map([[15003, { id: 'uuid-bs', name: 'Blizzard Strayer' }]]),
    );

    const targets = (at(page, 'calibrationTargets') as (c: number[]) => {
      artifactSetIds: string[];
    }[]).call(page, [15003]);

    expect(targets.map((t) => t.artifactSetIds)).toEqual([[], ['uuid-bs']]);
  });

  it('refuses to calibrate a set it cannot resolve rather than falling back to null', () => {
    // `null` is the id for "no 4-piece". Falling back to it would calibrate the baseline and
    // label it with the set's name — a recipe understating itself by the whole 4-piece bonus,
    // looking like an ordinary result.
    const page = pageWith();

    expect(() => (at(page, 'calibrationTargets') as (c: number[]) => unknown).call(page, [999]))
      .toThrow(/999/);
  });

  it('calibrates the baseline plus one recipe per selected set, named', () => {
    // `CalibrationTarget.label` has always documented itself as "for progress a user can read
    // — 'Blizzard Strayer', not a uuid", and it read `set 15003`. The filter needs the name
    // anyway, so the progress line gets it too.
    const page = pageWith();
    (at(page, 'artifactSets') as { set: (m: Map<number, unknown>) => void }).set(
      new Map<number, unknown>([
        [15003, { id: 'uuid-bs', name: 'Blizzard Strayer' }],
        [15020, { id: 'uuid-wt', name: "Wanderer's Troupe" }],
      ]),
    );

    const targets = (at(page, 'calibrationTargets') as (c: number[]) => {
      artifactSetIds: string[]; setIds: number[]; label: string;
    }[]).call(page, [15003, 15020]);

    // Uuids for `/calibrate`, catalogue ids for the search. Length is the state: 0 baseline,
    // 1 four-piece, 2 a pair.
    expect(targets.map((t) => t.artifactSetIds)).toEqual([[], ['uuid-bs'], ['uuid-wt']]);
    expect(targets.map((t) => t.setIds)).toEqual([[], [15003], [15020]]);
    expect(targets.map((t) => t.label)).toEqual([
      'no 4-piece set', 'Blizzard Strayer', "Wanderer's Troupe",
    ]);
  });
});

// ── the required main stat ──────────────────────────────────────────────────
//
// "The goblet must be Hydro DMG" is the first thing anyone decides about a Genshin build, and
// the search had no way to say it. It is also the largest single cut to a search space this
// page already fights to make finish.

describe('the main-stat constraint', () => {
  const piece = (id: string, slot: string, main: string) => ({
    id, slot, set_id: 1, stats: {}, main_stat: main,
  });

  const inventory = [
    piece('f', 'equip_bracer', 'FIGHT_PROP_HP'),
    piece('g1', 'equip_ring', 'FIGHT_PROP_FIRE_ADD_HURT'),
    piece('g2', 'equip_ring', 'FIGHT_PROP_ATTACK_PERCENT'),
    piece('c', 'equip_dress', 'FIGHT_PROP_CRITICAL'),
  ];

  /** The predicate the page applies, stated once here so the test is about the rule. */
  const keep = (wanted: Record<string, string>) =>
    inventory.filter((p) => !wanted[p.slot] || p.main_stat === wanted[p.slot]).map((p) => p.id);

  it('keeps everything when no slot is constrained', () => {
    expect(keep({})).toEqual(['f', 'g1', 'g2', 'c']);
  });

  it('narrows only the constrained slot', () => {
    // The flower and circlet survive untouched: a constraint on the goblet says nothing about
    // any other slot, and narrowing them too would silently shrink the search.
    expect(keep({ equip_ring: 'FIGHT_PROP_FIRE_ADD_HURT' })).toEqual(['f', 'g1', 'c']);
  });

  it('treats an empty string as no constraint rather than as a stat', () => {
    // The "Any" option's value. Compared as a stat it would match nothing and empty the slot.
    expect(keep({ equip_ring: '' })).toEqual(['f', 'g1', 'g2', 'c']);
  });

  it('can empty a slot, which is exactly what has to be caught before searching', () => {
    // An empty result is indistinguishable from "your artifacts are bad", and the user would
    // not know which. The page says so before the search rather than after it returns nothing.
    expect(keep({ equip_ring: 'FIGHT_PROP_ELEC_ADD_HURT' })).toEqual(['f', 'c']);
  });
});


/**
 * Starting from a team, then picking who in it.
 *
 * The owner's audit asks for this on Optimize and on Rotations. The trap it walks into is
 * narrowing the list without narrowing the *selection* — a page that keeps answering for a
 * character the user has just filtered away.
 */
describe('OptimizePage teams', () => {
  const GANYU_BUILD = {
    ...AYAKA_BUILD, id: 'b2', character_id: 'c2',
    character: { id: 'c2', name: 'Ganyu', element: 'Cryo' },
  };
  const XINGQIU_BUILD = {
    ...AYAKA_BUILD, id: 'b3', character_id: 'c3',
    character: { id: 'c3', name: 'Xingqiu', element: 'Hydro' },
  };
  const FREEZE = {
    id: 't1', name: 'Freeze',
    build1_id: 'b2', build2_id: 'b3', build3_id: null, build4_id: null,
  };

  const withTeam = () => pageWith({
    builds: {
      list: vi.fn().mockResolvedValue([AYAKA_BUILD, GANYU_BUILD, XINGQIU_BUILD]),
    } as unknown as BuildsService,
    teams: { list: vi.fn().mockResolvedValue([FREEZE]) } as unknown as TeamsService,
  });

  it('offers every build until a team is chosen', async () => {
    const page = withTeam();

    await page['load']();

    expect(page['buildOptions']().map((o) => o.label))
      .toEqual(['Kamisato Ayaka', 'Ganyu', 'Xingqiu']);
  });

  it('narrows the build grid to the team, in slot order', async () => {
    const page = withTeam();
    await page['load']();

    await page['selectTeam'](['t1']);

    expect(page['buildOptions']().map((o) => o.label)).toEqual(['Ganyu', 'Xingqiu']);
  });

  it('moves the selection off a build the team does not field', async () => {
    // The page was answering for Ayaka. Leaving her selected would put the whole result under
    // a character the user has just filtered away.
    const page = withTeam();
    await page['load']();
    expect(page['buildId']()).toBe('b1');

    await page['selectTeam'](['t1']);

    expect(page['buildId']()).toBe('b2');
  });

  it('keeps the selection when the team does field it', async () => {
    const page = withTeam();
    await page['load']();
    await page['selectBuild']('b3');

    await page['selectTeam'](['t1']);

    expect(page['buildId']()).toBe('b3');
  });

  it('widens back to every build when the team is cleared', async () => {
    const page = withTeam();
    await page['load']();
    await page['selectTeam'](['t1']);

    await page['selectTeam']([]);

    expect(page['buildOptions']().map((o) => o.label))
      .toEqual(['Kamisato Ayaka', 'Ganyu', 'Xingqiu']);
  });

  it('draws a team card with its whole party, not one character standing for it', async () => {
    const page = withTeam();

    await page['load']();

    const [card] = page['teamOptions']();
    expect(card.label).toBe('Freeze');
    expect(card.detail).toBe('Ganyu · Xingqiu');
    expect(card.icons).toHaveLength(2);
  });

  it('opens without a team picker rather than failing when teams cannot be loaded', async () => {
    // A team narrows a grid. A page that refused to open because that convenience failed
    // would be worse than one without it.
    const page = pageWith({
      teams: { list: vi.fn().mockRejectedValue(new Error('boom')) } as unknown as TeamsService,
    });

    await page['load']();

    expect(page['error']()).toBeNull();
    expect(page['teamOptions']()).toEqual([]);
    expect(page['buildId']()).toBe('b1');
  });
});


/**
 * The set filter, as two card grids (owner's audit, §6).
 *
 * Fairy's model, translated: the 4-piece selector comes first because it is far the commoner
 * build, the 2-piece one takes a *pair*, and a set cannot be in both. In ZZZ that last rule is
 * about six disc slots; here it is about five artifact slots, where a 4-piece and a 2+2 are
 * two shapes of the same five and a set can only be one of them in any build the search
 * returns.
 */
describe('OptimizePage set filter', () => {
  const CATALOGUE = new Map([
    [1, { id: 'u1', name: 'Gladiator', icon: 'set_glad', fourPieceText: '+35% Normal Attack' }],
    [2, { id: 'u2', name: 'Emblem', icon: 'set_emblem', fourPieceText: 'Bonus from ER' }],
    [3, { id: 'u3', name: 'Noblesse', icon: 'set_noblesse', fourPieceText: '+20% party ATK' }],
  ]);

  /** Three sets, each reaching all five slots, so all three are 4-piece candidates. */
  function withThreeSets() {
    const page = pageWith({
      optimize: {
        artifactSets: vi.fn().mockResolvedValue(CATALOGUE),
      } as unknown as Partial<OptimizeService>,
    }) as unknown as Record<string, never>;
    const slots = ['equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring', 'equip_dress'];
    (page['candidates'] as unknown as { set: (v: unknown) => void }).set(
      [1, 2, 3].flatMap((set_id) => slots.map((slot) => ({
        id: `${set_id}-${slot}`, slot, set_id, stats: {}, main_stat: 'FIGHT_PROP_HP',
      }))),
    );
    (page['artifactSets'] as unknown as { set: (v: unknown) => void }).set(CATALOGUE);
    return page;
  }

  const labels = (options: readonly { label: string }[]) => options.map((o) => o.label);

  it('draws a set as a card with its art and its 4-piece bonus', () => {
    const page = withThreeSets();

    const [card] = (page['fourPieceOptions'] as unknown as () => readonly {
      value: string; label: string; icon?: string | null; tooltip?: string;
    }[])();

    // Alphabetical among sets reaching the same number of slots, which is `fourPieceChoices`'
    // own tie-break — the cards keep that order rather than imposing a second one.
    expect(card.label).toBe('Emblem');
    expect(card.icon).toBe('set_emblem');
    // Too long for a card, and it is what anyone is choosing between — so, the tooltip.
    expect(card.tooltip).toBe('Bonus from ER');
  });

  it('does not offer a 4-piece set as half of a pair', () => {
    // Both are configurations of the same five slots, so a set can only be one of them in any
    // build the search returns. Offering it in both offers a choice the answer cannot honour.
    const page = withThreeSets();

    (page['setFourPiece'] as unknown as (ids: string[]) => void)(['1']);

    expect(labels((page['pairOptions'] as unknown as () => never[])()))
      .toEqual(['Emblem', 'Noblesse']);
  });

  it('does not offer a paired set as a 4-piece', () => {
    const page = withThreeSets();

    (page['setPair'] as unknown as (ids: string[]) => void)(['2', '3']);

    expect(labels((page['fourPieceOptions'] as unknown as () => never[])()))
      .toEqual(['Gladiator']);
  });

  it('keeps the last two picked rather than refusing the third', () => {
    // A capped multi-select that ignores a click looks broken; one that drops the oldest does
    // what the user plainly meant — they are swapping, not adding.
    const page = withThreeSets();

    (page['setPair'] as unknown as (ids: string[]) => void)(['1', '2', '3']);

    expect((page['pairSelected'] as unknown as () => string[])()).toEqual(['2', '3']);
  });

  it('treats one set as an unfinished pair, not as a filter', () => {
    // This search enumerates a 4-piece or a 2+2. "Two of this and three of anything" is
    // neither, so a lone 2-piece would contribute no recipe at all — said, not searched.
    const page = withThreeSets();

    (page['setPair'] as unknown as (ids: string[]) => void)(['1']);

    expect((page['chosenPair'] as unknown as () => unknown)()).toBeNull();
    expect((page['calibrationCount'] as unknown as () => number)()).toBe(1);
  });

  it('counts one calibration per 4-piece set, one for a whole pair, and one baseline', () => {
    const page = withThreeSets();

    (page['setFourPiece'] as unknown as (ids: string[]) => void)(['1']);
    (page['setPair'] as unknown as (ids: string[]) => void)(['2', '3']);

    expect((page['calibrationCount'] as unknown as () => number)()).toBe(3);
  });
});


/**
 * Equipping a result onto the build it was searched for (owner, 2026-08-29).
 *
 * The whole risk is order. Equipping into a filled slot is refused rather than swapped (A.1),
 * so pieces must come off before they go on — and a piece held by a *different* build is
 * refused too, which would land after this had already stripped the build being equipped.
 */
describe('OptimizePage equip', () => {
  const ROW = { rank: 1, damage: 100, artifactIds: ['a1', 'a2'], pieces: ['Flower', 'Plume'] };

  function pageForEquip(pieces: Record<string, string | null>, equipped: string[] = []) {
    const get = vi.fn(async (id: string) => ({
      id, build_id: pieces[id] ?? null, slot: 'equip_bracer', set_name: 'Gladiator',
    }));
    const equip = vi.fn().mockResolvedValue({});
    const list = vi.fn().mockResolvedValue({
      items: equipped.map((id) => ({ id })), total: equipped.length, offset: 0, limit: 50,
    });
    const page = pageWith({
      artifacts: {
        options: vi.fn().mockResolvedValue(OPTIONS), get, equip, list,
      } as unknown as Partial<ArtifactsService>,
    }) as unknown as Record<string, never>;
    (page['buildId'] as unknown as { set: (v: string) => void }).set('b1');
    return { page, get, equip, list };
  }

  const run = (page: Record<string, never>) =>
    (page['equipRow'] as unknown as (r: unknown) => Promise<void>).call(page, ROW);

  it('changes nothing when a piece is on another build', async () => {
    // The refusal would otherwise land *after* this build had been stripped, leaving it half
    // equipped because of something readable up front.
    const { page, equip } = pageForEquip({ a1: null, a2: 'b2' });

    await run(page);

    expect(equip).not.toHaveBeenCalled();
    expect((page['actionError'] as unknown as () => string)()).toContain('another build');
    expect((page['equipped'] as unknown as () => unknown)()).toBeNull();
  });

  it('takes the build\'s other pieces off before putting the winners on', async () => {
    // Equipping into a filled slot is refused rather than swapped (A.1), so this order is not
    // a preference — it is the only one that works.
    const { page, equip } = pageForEquip({ a1: null, a2: null }, ['old1']);

    await run(page);

    expect(equip.mock.calls).toEqual([
      ['old1', null],
      ['a1', 'b1'],
      ['a2', 'b1'],
    ]);
  });

  it('leaves a piece already on this build where it is', async () => {
    const { page, equip } = pageForEquip({ a1: 'b1', a2: null }, ['a1']);

    await run(page);

    // a1 is neither taken off nor re-equipped: it is already exactly where it belongs.
    expect(equip.mock.calls).toEqual([['a2', 'b1']]);
    expect((page['equipped'] as unknown as () => string)()).toContain('1 were already');
  });

  it('says so rather than claiming a change when the build already wears the result', async () => {
    // "Equipped 5 pieces" after a search that moved nothing reads as a change that did not
    // happen.
    const { page, equip } = pageForEquip({ a1: 'b1', a2: 'b1' }, ['a1', 'a2']);

    await run(page);

    expect(equip).not.toHaveBeenCalled();
    expect((page['equipped'] as unknown as () => string)()).toContain('Already equipped');
  });

  it('says the build was left mid-move when a failure lands after the first change', async () => {
    // Before the first PATCH, a failure means nothing happened. After it, the build is wearing
    // some of two sets — and a bare API message describes one request, not the state it left.
    const { page, equip } = pageForEquip({ a1: null, a2: null }, ['old1']);
    equip.mockRejectedValueOnce(new Error('network'));

    await run(page);

    expect((page['actionError'] as unknown as () => string)())
      .toContain('already being moved');
  });

  it('drops the equip note when a new search replaces the result it described', async () => {
    const { page } = pageForEquip({ a1: null, a2: null });
    await run(page);
    expect((page['equipped'] as unknown as () => unknown)()).not.toBeNull();

    await (page['selectBuild'] as unknown as (id: string) => Promise<void>).call(page, 'b1');

    expect((page['equipped'] as unknown as () => unknown)()).toBeNull();
  });

  it('does nothing at all without a build', async () => {
    const { page, get } = pageForEquip({ a1: null, a2: null });
    (page['buildId'] as unknown as { set: (v: string) => void }).set('');

    await run(page);

    expect(get).not.toHaveBeenCalled();
  });
});
