import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { type Slot, search } from '../../sim/search';
import { ArtifactsService } from '../artifacts/artifacts.service';
import {
  RecipeOptimizeService,
  type CalibrationCaveats,
  type CalibrationResult,
} from './recipe-optimize.service';
import { RotationsService } from '../rotations/rotations.service';
import { TeamsService } from '../teams/teams.service';
import { BuildsService } from '../builds/builds.service';
import { ExplainService } from '../explain/explain.service';
import { OptimizePage, SLOT_ORDER, describePieces, marginalPerRoll } from './optimize';
import type { Recipe } from '../../sim/recipe';
import type { KernelCandidate } from './optimize.service';
import { OptimizeService } from './optimize.service';

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
  hit: { multiplier: 2.0, channel: 'cryo', scaling_stat: 'atk', amplifying: null, extra_terms: [] },
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

/**
 * A returning user's remembered selections.
 *
 * §15 stopped the page selecting `builds[0]`, so `load()` no longer chooses anything on its
 * own — which is the point, and which would otherwise leave every test below operating on a
 * page with no build selected. Seeding the memory models the ordinary case (someone who has
 * used the page before) rather than reinstating the default through the harness; the
 * fresh-user case, where nothing is remembered and so nothing is selected, is pinned
 * explicitly in `OptimizePage defaults`.
 */
function rememberSelections(): void {
  localStorage.setItem('mistilteinn:optimize:buildId', 'b1');
  localStorage.setItem('mistilteinn:optimize:rotationId', 'r1');
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
  rememberSelections();
  return TestBed.runInInjectionContext(() => new OptimizePage());
}

describe('describePieces', () => {
  it('names pieces from the candidates the search was actually given', () => {
    // Not re-fetched: a second lookup could disagree with what was searched, and the row
    // would then describe a build the ranking did not produce.
    const named = describePieces(
      ['a', 'b'],
      [
        {
          id: 'a', slot: 'equip_bracer', set_id: 1, stats: {},
          main_stat: 'FIGHT_PROP_HP', rarity: 5, level: 20,
        },
        {
          id: 'b', slot: 'equip_dress', set_id: 1, stats: {},
          main_stat: 'FIGHT_PROP_CRITICAL', rarity: 5, level: 20,
        },
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

  it("passes a mixed-stat hit's further terms through rather than scoring the first alone", async () => {
    // Math-fallback P0. `{a} ATK+{b} Max HP` is one hit worth both terms; a page that dropped
    // `extra_terms` would score it on ATK alone. Compared against the kernel called directly,
    // as above.
    const extra = [{ stat: 'hp' as const, multiplier: 0.05 }];
    const page = pageWith({
      optimize: {
        context: vi.fn().mockResolvedValue({
          ...CONTEXT, hit: { ...CONTEXT.hit, extra_terms: extra },
        }),
      } as unknown as Partial<OptimizeService>,
    });
    await page['load']();

    await page['run']();

    const fromPage = page['result']()?.builds[0].damage ?? 0;
    const direct = (extraTerms: { stat: 'hp'; multiplier: number }[]) =>
      search(
        inventory().map((p) => ({ id: p.id, slot: p.slot as Slot, setId: p.set_id, stats: p.stats })),
        {
          base: CONTEXT.base,
          hit: {
            multiplier: CONTEXT.hit.multiplier,
            scalingStat: 'atk',
            flatDamage: 0,
            baseDamageBonus: 0,
            amplifying: null,
            reactionBonus: 0,
            extraTerms,
          },
          target: { level: 90, resistance: 0.1, defReduction: 0, defIgnore: 0 },
          characterLevel: 90,
          dmgBonusQuantity: 'cryo_dmg_bonus',
          setBonuses: [],
        },
      ).builds[0].damage;

    expect(fromPage).toBeCloseTo(direct(extra), 6);
    expect(direct(extra)).toBeGreaterThan(direct([]));
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
    // Details toggles, so the open pane has to be closed before this row can be re-explained.
    await page['explainRow'](winner);
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

  it('closes the details pane when its own row is pressed again', async () => {
    // Owner, 2026-08-31: *"clicking 'details' again should compress the row on optimize."*
    const explain = vi.fn().mockResolvedValue(explanation(1));
    const page = pageWith({ explain: { explain } as unknown as Partial<ExplainService> });
    await page['load']();
    await page['run']();

    await page['explainRow'](page['rows']()[0]);
    expect(page['explained']()?.rank).toBe(page['rows']()[0].rank);

    await page['explainRow'](page['rows']()[0]);
    expect(page['explained']()).toBeNull();
    // Closing asks the server nothing — it is a disclosure, not a second query.
    expect(explain).toHaveBeenCalledTimes(1);
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
    // Close the pane the first call opened, then ask again — the refusal is on the re-open.
    await page['explainRow'](page['rows']()[0]);
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


describe('marginalPerRoll', () => {
  /** §13 — moved under details, so it must answer about the row it is shown beside. */
  const hit = (over: Record<string, unknown> = {}) => ({
    // `mine` — the hit belongs to the character being optimized. Without it `evaluateHit`
    // freezes the hit at its calibrated damage, so nothing responds to a stat bump and this
    // whole table reads empty. Which is the new behaviour working, not a broken fixture.
    mine: true,
    abil: 'x', attackTag: 1, element: 'cryo', talent: 2, scaling: 'atk', flatDamage: 0,
    calibratedScaling: 1000, bonusDmg: 0, critRate: 0.5, critDmg: 1, conversions: {},
    calibratedBase: { atk: 1000, hp: 10000, def: 800 },
    calibratedPercent: { atk: 0, hp: 0, def: 0 },
    calibratedFlat: { atk: 0, hp: 0, def: 0 },
    defMultiplier: 0.5, resMultiplier: 0.9, ampMultiplier: 1, gcsimAverageDamage: 900, ...over,
  });
  const withHit = () => ({
    hits: [hit()], seed: '1',
    meta: {
      seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [],
      minimumEnergyRecharge: null,
    },
  }) as unknown as Recipe;

  it('ranks the stats this build actually responds to, best first', () => {
    const found = marginalPerRoll(withHit(), [{}, {}, {}, {}, {}]);

    expect(found.length).toBeGreaterThan(0);
    for (let i = 1; i < found.length; i += 1) {
      expect(found[i - 1].delta).toBeGreaterThanOrEqual(found[i].delta);
    }
  });

  it('answers for a stat the build holds none of', () => {
    // A build with no CRIT DMG must still be able to ask what CRIT DMG would be worth — the
    // bump is applied to the resolved stats, not to a pool that may not contain the key.
    const found = marginalPerRoll(withHit(), [{}, {}, {}, {}, {}]);

    expect(found.some((row) => row.delta > 0)).toBe(true);
  });

  it('omits quantities the recipe cannot respond to rather than showing them as zero', () => {
    // A calibration freezes what it does not read, so a bump in one of those evaluates to
    // exactly 0. Printing that beside real numbers claims the stat is worthless, which is a
    // different statement from "this recipe cannot see it".
    const found = marginalPerRoll(withHit(), [{}, {}, {}, {}, {}]);

    // `every` on an empty array is true, so the guard is the assertion here, not decoration.
    expect(found.length).toBeGreaterThan(0);
    expect(found.every((row) => row.delta !== 0)).toBe(true);
  });
});

describe('OptimizePage rotation scope', () => {
  const rotations = [
    { id: 'r-a', name: 'Freeze', team_id: 't-1' },
    { id: 'r-b', name: 'Overload', team_id: 't-2' },
  ];

  it('offers only the rotations the chosen team has', () => {
    // **An unscoped list offers a guaranteed failure.** A rotation belongs to a team, and
    // `/calibrate` refuses one whose team does not include the build — *"rotation X is for a
    // team that does not include Furina, so it never acts on this build"*. Offering it anyway
    // means the only feedback is a 422 after the click, naming a mismatch the page knew.
    const page = pageWith();
    page['rotations'].set(rotations);

    page['teamId'].set('t-1');
    expect(page['rotationOptions']().map((r) => r.value)).toEqual(['r-a']);

    page['teamId'].set('t-2');
    expect(page['rotationOptions']().map((r) => r.value)).toEqual(['r-b']);
  });

  it('shows every rotation when no team narrows the page', () => {
    // "Any team" means any, and an empty list here would read as having authored none.
    const page = pageWith();
    page['rotations'].set(rotations);
    page['teamId'].set('');

    expect(page['rotationOptions']().map((r) => r.value)).toEqual(['r-a', 'r-b']);
  });

  it('drops a chosen rotation the new team does not have', async () => {
    // It goes with the team for the same reason the build does: leaving it selected holds the
    // page's answer under a rotation the user just filtered away.
    const page = pageWith();
    page['rotations'].set(rotations);
    page['teamId'].set('t-1');
    page['rotationId'].set('r-a');

    await page['selectTeam'](['t-2']);

    expect(page['rotationId']()).toBe('');
  });
});

describe('OptimizePage marginalForExpanded', () => {
  it('is empty while no row is expanded', () => {
    // It is a `computed` rather than a `marginalFor(row)` call in the template because the
    // page runs on default change detection: as a method it rebuilt two Maps over the whole
    // candidate list and evaluated the recipe nine times on every tick, for as long as a
    // details pane stayed open.
    const page = pageWith();

    expect(page['marginalForExpanded']()).toEqual([]);
  });

  it('stays empty when the expanded row names pieces the page does not hold', () => {
    const page = pageWith();
    page['explained'].set({ rank: 1 } as never);

    expect(page['marginalForExpanded']()).toEqual([]);
  });
});

describe('OptimizePage barWidth', () => {
  /** §14 — the bar is a table cell with a width, so a bad width is a broken style attribute. */
  it('scales against the best line in the same table', () => {
    const page = pageWith();

    expect(page['barWidth'](50, 100)).toBe(50);
    expect(page['barWidth'](100, 100)).toBe(100);
  });

  it('returns zero rather than Infinity when nothing scored', () => {
    // Angular writes the result straight into `style.width.%`. `Infinity` and `NaN` are not
    // widths, and a table where every quantity evaluated to nothing is reachable.
    const page = pageWith();

    expect(page['barWidth'](0, 0)).toBe(0);
    expect(page['barWidth'](5, -1)).toBe(0);
  });

  it('clamps rather than overflowing its cell', () => {
    const page = pageWith();

    expect(page['barWidth'](150, 100)).toBe(100);
    expect(page['barWidth'](-5, 100)).toBe(0);
  });
});

describe('OptimizePage energy shortfall', () => {
  /**
   * §9 — the number the instability warning could not give. `recipe-energy.ts` had no input
   * and no consumer; both ends are wired now.
   */
  const withMinimum = (minimum: number | null) => ({
    hits: [], seed: '1',
    meta: {
      seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [],
      minimumEnergyRecharge: minimum,
    },
  }) as unknown as Recipe;

  it('names what the build has, what the rotation needs, and the gap', () => {
    const page = pageWith();
    page['scoredRecipe'].set(withMinimum(0.3));
    page['winningPools'].set([{ energy_recharge: 0.12 }, {}, {}, {}, {}]);

    expect(page['energyGap']()).toEqual({ has: 0.12, needs: 0.3, shortfall: 0.3 - 0.12 });
  });

  it('says nothing when the build clears the threshold', () => {
    const page = pageWith();
    page['scoredRecipe'].set(withMinimum(0.3));
    page['winningPools'].set([{ energy_recharge: 0.35 }, {}, {}, {}, {}]);

    expect(page['energyGap']()).toBeNull();
  });

  it('says nothing when no threshold was measured', () => {
    // **An unmeasured threshold is not a passed one**, and the sweep only runs for an unstable
    // rotation whose burst is what varied — so most searches have no minimum. Warning on every
    // one of them would be the cry-wolf shape `recipeIsShaky` was already thresholded to avoid.
    const page = pageWith();
    page['scoredRecipe'].set(withMinimum(null));
    page['winningPools'].set([{ energy_recharge: 0.0 }, {}, {}, {}, {}]);

    expect(page['energyGap']()).toBeNull();
  });

  it('sums the Energy Recharge across all five slots', () => {
    // ER is an artifact stat spread over the build, not one piece's main stat. Reading one
    // pool would understate it and warn a build that clears the threshold.
    const page = pageWith();
    page['scoredRecipe'].set(withMinimum(0.5));
    page['winningPools'].set([
      { energy_recharge: 0.1 }, { energy_recharge: 0.1 }, { energy_recharge: 0.1 },
      { energy_recharge: 0.1 }, { energy_recharge: 0.05 },
    ]);

    expect(page['energyGap']()?.has).toBeCloseTo(0.45, 9);
  });
});

describe('OptimizePage per-row bursts', () => {
  /**
   * §22, owner: *"when ER requirements aren't met, it'd be nice to show on each set the
   * individual failure of ER, since the global 'Energy insufficient' details are for the
   * baseline."*
   *
   * The global line is measured once, on the baseline, so it reads identically under every
   * row. This says what **this** row's five pieces fund.
   */
  const sweep = [
    { energyRecharge: 0.2, burstInstances: 2, dps: 100 },
    { energyRecharge: 0.6, burstInstances: 3, dps: 120 },
  ] as unknown as CalibrationCaveats['energySweep'];

  const withSweep = (page: OptimizePage) => {
    page['caveats'].set({
      unstable: [], staleConversions: [], fromCache: [], unscoredLabels: [],
      energyCost: null, energySweep: sweep,
    } as unknown as CalibrationCaveats);
  };

  it('reports a row short of the best the ladder saw', () => {
    const page = pageWith();
    withSweep(page);
    expect(page['burstsFor'](0.2)).toEqual({ funded: 2, most: 3, short: true });
  });

  it('rounds the count, because a burst count is a mean and reads like one', () => {
    // The owner saw `3.166666666666666/3.2833333333333337 bursts`. Rounded in the component
    // rather than the template so the badge and its tooltip cannot disagree.
    const page = pageWith();
    page['caveats'].set({
      unstable: [], staleConversions: [], fromCache: [], unscoredLabels: [],
      energyCost: null,
      energySweep: [
        { energyRecharge: 0.2, burstInstances: 3.166666666666666, dps: 100 },
        { energyRecharge: 0.6, burstInstances: 3.2833333333333337, dps: 120 },
      ],
    } as unknown as CalibrationCaveats);

    expect(page['burstsFor'](0.2)).toEqual({ funded: 3.2, most: 3.3, short: false });
  });

  it('stays quiet when the gap is smaller than half a burst', () => {
    // 3.17 against 3.28 is 0.117 of a burst — the ladder's own variance, not something a
    // player lost. A badge that fires on a tenth of a burst is one every row carries.
    const page = pageWith();
    page['caveats'].set({
      unstable: [], staleConversions: [], fromCache: [], unscoredLabels: [],
      energyCost: null,
      energySweep: [
        { energyRecharge: 0.2, burstInstances: 3.17, dps: 100 },
        { energyRecharge: 0.6, burstInstances: 3.28, dps: 120 },
      ],
    } as unknown as CalibrationCaveats);

    expect(page['burstsFor'](0.2)?.short).toBe(false);
    expect(page['burstsFor'](0.9)?.short).toBe(false);
  });

  it('does not flag a row that funds everything the ladder could buy', () => {
    // "3 of 3" under every line is noise. A row only reports when it is behind.
    const page = pageWith();
    withSweep(page);
    expect(page['burstsFor'](0.9)).toEqual({ funded: 3, most: 3, short: false });
  });

  it('says nothing when the run measured no ladder', () => {
    // **Null is not zero.** "This build funds no bursts" and "we did not measure" are
    // different sentences, and rendering the first for the second would be a lie about gear.
    const page = pageWith();
    expect(page['burstsFor'](0.2)).toBeNull();
  });

  it('says nothing when the row carries no Energy Recharge of its own', () => {
    // The kernel search scores a damage number without ever resolving a stat block, so its
    // builds leave `energyRecharge` undefined rather than reporting a 0 they did not measure.
    const page = pageWith();
    withSweep(page);
    expect(page['burstsFor'](undefined)).toBeNull();
  });
});

describe('OptimizePage caveat attribution', () => {
  /**
   * Owner ruling, 2026-08-31: the baseline keeps being calibrated — the upgrade list needs it
   * to price a swap that breaks the winner's set — but it must stop judging the ranking.
   * `searchRecipe` picks its states from `fourPieceSets`, which never contains `null`, so no
   * result row was ever scored with the baseline.
   */
  const caveats = (over: Record<string, unknown> = {}) => ({
    unstable: [], staleConversions: [], characters: [], fromCache: [], unscoredLabels: [], ...over,
  }) as unknown as CalibrationCaveats;

  it('does not call the scoring unreliable because the baseline is unstable', () => {
    const page = pageWith();
    page['caveats'].set(caveats({
      unstable: [{ label: 'the baseline (no 4-piece bonus)', abilities: ['Skirk: burst'] }],
      unscoredLabels: ['the baseline (no 4-piece bonus)'],
    }));

    expect(page['recipeIsShaky']()).toBe(false);
    expect(page['splitCaveats'](true).unstable.map((e) => e.label))
      .toEqual(['the baseline (no 4-piece bonus)']);
    expect(page['rankingCaveats']().unstable).toEqual([]);
  });

  it('still calls it unreliable when a set that scored the ranking is unstable', () => {
    // The half that must not be lost: Finale *is* searched, so its instability is a verdict
    // on the order and has to reach the reader.
    const page = pageWith();
    page['caveats'].set(caveats({
      unstable: [
        { label: 'Finale of the Deep Galleries', abilities: ['Skirk: burst'] },
        { label: 'the baseline (no 4-piece bonus)', abilities: ['Skirk: burst'] },
      ],
      unscoredLabels: ['the baseline (no 4-piece bonus)'],
    }));

    expect(page['recipeIsShaky']()).toBe(true);
    expect(page['rankingCaveats']().unstable.map((e) => e.label))
      .toEqual(['Finale of the Deep Galleries']);
    // The names are what makes the warning actionable — an ability that varies is the thing
    // the reader can do something about.
    expect(page['rankingCaveats']().unstable[0].abilities).toEqual(['Skirk: burst']);
  });

  it('ignores a frozen conversion on a recipe that scored nothing', () => {
    const page = pageWith();
    page['caveats'].set(caveats({
      staleConversions: [
        { label: 'the baseline (no 4-piece bonus)', term: 'flatDamage', damageShare: 0.903 },
      ],
      unscoredLabels: ['the baseline (no 4-piece bonus)'],
    }));

    expect(page['recipeIsShaky']()).toBe(false);
    expect(page['splitCaveats'](true).staleConversions).toHaveLength(1);
  });

  it('keeps a frozen conversion on a recipe that did score', () => {
    const page = pageWith();
    page['caveats'].set(caveats({
      staleConversions: [
        { label: 'Finale of the Deep Galleries', term: 'flatDamage', damageShare: 0.886 },
      ],
    }));

    expect(page['recipeIsShaky']()).toBe(true);
  });
});

describe('OptimizePage comparator', () => {
  /**
   * §11 — every row is a percentage of the character's current build, not of the
   * calibration's no-four-piece recipe. The owner: *"the 'no 4p' baseline doesn't make any
   * sense. The baseline should be the current build of the character."*
   */
  const recipe = () => ({
    hits: [], seed: '1',
    meta: {
      seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [],
      minimumEnergyRecharge: null,
    },
  }) as unknown as Recipe;

  /** A recipe that actually produces damage, so an assertion about it can fail. */
  const scoring = () => ({
    hits: [{
      abil: 'x', attackTag: 1, element: 'cryo', talent: 2, scaling: 'atk', flatDamage: 0,
      calibratedScaling: 1000, bonusDmg: 0, critRate: 0, critDmg: 0, conversions: {},
      calibratedBase: { atk: 1000, hp: 10000, def: 800 },
      calibratedPercent: { atk: 0, hp: 0, def: 0 },
      calibratedFlat: { atk: 0, hp: 0, def: 0 },
      defMultiplier: 0.5, resMultiplier: 0.9, ampMultiplier: 1, gcsimAverageDamage: 900,
    }],
    seed: '1',
    meta: {
      seed: '1', staleConversions: [], characters: [], unstable: [], calibratedSetIds: [],
      minimumEnergyRecharge: null,
    },
  }) as unknown as Recipe;

  const calibration = (over: Record<string, unknown> = {}) => ({
    byFourPieceSet: new Map<number, Recipe>(),
    byPair: new Map<string, Recipe>(),
    noFourPiece: recipe(),
    caveats: {},
    ...over,
  } as unknown as CalibrationResult);

  it('refuses a build that is not wearing five pieces', () => {
    const page = pageWith();
    page['equippedIds'].set(['a', 'b']);

    expect(page['comparatorFrom']([], calibration())).toBeNull();
  });

  it('refuses when a worn piece was not among the searched candidates', () => {
    // A main-stat filter can remove a piece the build is wearing. Its stats are then not to
    // hand, and inventing them would put every percentage on the page slightly wrong.
    const page = pageWith();
    page['equippedIds'].set(['a', 'b', 'c', 'd', 'e']);

    expect(page['comparatorFrom']([], calibration())).toBeNull();
  });

  it('refuses a build wearing a 4-piece nobody calibrated', () => {
    // Scoring it on another set's recipe would credit a bonus it does not have — and unlike
    // the same mistake in `upgrades`, this number is what every row is a percentage *of*.
    const page = pageWith();
    const worn = ['a', 'b', 'c', 'd', 'e'].map((id, i) => ({
      id, slot: SLOT_ORDER[i], set_id: 99, stats: {}, main_stat: 'x',
    })) as unknown as KernelCandidate[];
    page['equippedIds'].set(['a', 'b', 'c', 'd', 'e']);

    expect(page['comparatorFrom'](worn, calibration())).toBeNull();
  });

  it('scores a build with no 4-piece on the no-four-piece recipe', () => {
    const page = pageWith();
    const worn = ['a', 'b', 'c', 'd', 'e'].map((id, i) => ({
      id, slot: SLOT_ORDER[i], set_id: i, stats: {}, main_stat: 'x',
    })) as unknown as KernelCandidate[];
    page['equippedIds'].set(['a', 'b', 'c', 'd', 'e']);

    const found = page['comparatorFrom'](worn, calibration());

    expect(found).not.toBeNull();
    expect(found?.label).toBe('your current build');
  });

  it('scores the build it is given, on the matching four-piece recipe', () => {
    // A recipe with a real hit, so the number is not zero. The first version of this test used
    // an empty `hits` array and asserted `0 === 0` — it would have passed against any
    // implementation, including one that returned a constant.
    const page = pageWith();
    const worn = SLOT_ORDER.map((slot, i) => ({
      id: `p${i}`, slot, set_id: 7, stats: { atk_pct: 0.1 }, main_stat: 'x',
    })) as unknown as KernelCandidate[];
    page['equippedIds'].set(worn.map((p) => (p as unknown as { id: string }).id));

    const found = page['comparatorFrom'](
      worn, calibration({ byFourPieceSet: new Map([[7, scoring()]]) }),
    );

    expect(found?.damage).toBeGreaterThan(0);
  });

  it('does not depend on the order the pieces come in', () => {
    // A property, not a guarded trap: `candidateStatsFrom` sums the pools, so order cannot
    // matter. Recorded because the code orders them anyway — to match `winningPools` — and a
    // reader is owed the reason that ordering is cosmetic rather than load-bearing.
    const page = pageWith();
    const worn = SLOT_ORDER.map((slot, i) => ({
      id: `p${i}`, slot, set_id: 7, stats: { atk_pct: i / 10 }, main_stat: 'x',
    })) as unknown as KernelCandidate[];
    page['equippedIds'].set(worn.map((p) => (p as unknown as { id: string }).id));

    const inOrder = page['comparatorFrom'](
      worn, calibration({ byFourPieceSet: new Map([[7, scoring()]]) }),
    );
    const reversed = page['comparatorFrom'](
      [...worn].reverse(), calibration({ byFourPieceSet: new Map([[7, scoring()]]) }),
    );

    expect(inOrder?.damage).toBeGreaterThan(0);
    expect(reversed?.damage).toBe(inOrder?.damage);
  });

  it('falls back to the top result when no comparator can be established', async () => {
    const page = pageWith();
    await page['load']();
    await page['run']();

    // Rank 1 against itself is level, so it reads 0% and the rest are negative — the owner's
    // stated fallback for a character with no build.
    expect(page['comparator']()).toBeNull();
    expect(page['rows']()[0].percent).toBe(0);
    for (const row of page['rows']().slice(1)) {
      expect(row.percent!).toBeLessThanOrEqual(0);
    }
  });
});

describe('OptimizePage artifact cards', () => {
  /** §16 — the pieces a row won with, fetched by id after the search. */
  it('never asks for an empty set of ids', async () => {
    // **The trap this guards.** `?ids=` with an empty array is dropped from the query string
    // by the HTTP client, so the server sees no filter and answers with the *entire*
    // inventory — the caller asking for nothing getting everything. With no results there is
    // nothing to fetch, so the call must not be made at all.
    const list = vi.fn().mockResolvedValue({ items: [], total: 0 });
    const page = pageWith({ artifacts: { list } as unknown as Partial<ArtifactsService> });

    await page['load']();
    await page['loadCards']([]);

    // Not `not.toHaveBeenCalled()`: §11 made `selectBuild` fetch the build's own pieces
    // through the same method, so the broad assertion would fail for an unrelated reason and
    // say nothing about the case this test is named for.
    expect(list.mock.calls.filter(([filters]) => 'ids' in (filters ?? {}))).toEqual([]);
    expect(page['cards']().size).toBe(0);
  });

  it('leaves the cards off rather than failing the results when the fetch dies', async () => {
    // A ranking is complete without cards — rank, damage and five slot names. Replacing a
    // good answer with an error because an enrichment failed is the wrong trade.
    const page = pageWith({
      artifacts: {
        list: vi.fn().mockRejectedValue(new Error('boom')),
      } as unknown as Partial<ArtifactsService>,
    });
    await page['load']();

    await page['loadCards']([
      { rank: 1, damage: 1, artifactIds: ['a'], pieces: ['Flower'] },
    ]);

    expect(page['cards']().size).toBe(0);
  });

  it('discards a reply that arrives after the results it was fetched for', async () => {
    // The single-hit search is fast and the rotation search is minutes, so both can be in
    // flight. A slow reply landing under a newer ranking would show the previous search's
    // pieces beside the current search's numbers.
    const page = pageWith({
      artifacts: {
        list: vi.fn().mockResolvedValue({
          items: [{
            id: 'stale', slot: 'equip_bracer', rarity: 'five_star', level: 20,
            main_stat_type: 'FIGHT_PROP_HP', main_stat_value: 4780, substats: [],
            substat_analysis: [], artifact_set_id: null, set_name: null,
          }],
          total: 1,
        }),
        options: vi.fn().mockResolvedValue({ stats: [], slots: [], rarities: [] }),
      } as unknown as Partial<ArtifactsService>,
    });
    await page['load']();

    // `rows()` is empty here, so the ids this call was made for match nothing on screen.
    await page['loadCards']([
      { rank: 1, damage: 1, artifactIds: ['stale'], pieces: ['Flower'] },
    ]);

    expect(page['cards']().size).toBe(0);
  });

  it('returns a row\'s cards in the order the row names its pieces', () => {
    const page = pageWith();
    const card = (id: string) => ({
      id, icon: null, setName: 'S', slot: 'Flower', level: 20, mainStat: 'HP 4,780',
      substats: [],
    });
    page['cards'].set(new Map([['b', card('b')], ['a', card('a')]]));

    const got = page['cardsFor'](
      { rank: 1, damage: 1, artifactIds: ['a', 'b'], pieces: [] },
    );

    expect(got.map((c) => c.id)).toEqual(['a', 'b']);
  });

  it('skips a piece it has no card for rather than leaving a hole', () => {
    const page = pageWith();
    page['cards'].set(new Map([['a', {
      id: 'a', icon: null, setName: 'S', slot: 'Flower', level: 20, mainStat: 'HP 4,780',
      substats: [],
    }]]));

    const got = page['cardsFor'](
      { rank: 1, damage: 1, artifactIds: ['a', 'missing'], pieces: [] },
    );

    expect(got.map((c) => c.id)).toEqual(['a']);
  });
});

describe('OptimizePage defaults', () => {
  /**
   * §15 — the page must not state a choice the user did not make.
   *
   * These construct the page *without* `rememberSelections()`, which is the one place in this
   * file that matters: the harness seeds a returning user, so a fresh one is only visible if
   * a test clears the memory itself.
   */
  it('selects no build when nothing is remembered', async () => {
    localStorage.clear();
    const page = pageWith();
    localStorage.clear();

    await page['load']();

    // It opened on Aino before this, because she sorts first — which reads as a
    // recommendation rather than as the arbitrary pick it was.
    expect(page['buildId']()).toBe('');
    expect(page['builds']().length).toBeGreaterThan(0);
  });

  it('selects no rotation when nothing is remembered', async () => {
    localStorage.clear();
    const page = pageWith({
      rotations: {
        list: vi.fn().mockResolvedValue({
          items: [{ id: 'r1', name: 'Burst' }], total: 1, offset: 0, limit: 50,
        }),
      } as unknown as Partial<RotationsService>,
    });
    localStorage.clear();

    await page['load']();

    expect(page['rotations']()).toHaveLength(1);
    expect(page['rotationId']()).toBe('');
  });

  it('restores a remembered build', async () => {
    const page = pageWith();
    localStorage.setItem('mistilteinn:optimize:buildId', 'b1');

    await page['load']();

    expect(page['buildId']()).toBe('b1');
  });

  it('forgets a remembered build that has since been deleted', async () => {
    // One `pageWith` per test: TestBed refuses a second configure once instantiated.
    const page = pageWith();
    localStorage.setItem('mistilteinn:optimize:buildId', 'deleted-since');

    await page['load']();

    // Not `builds[0]`: a stale id falls back to nothing, or §15 would be undone one layer
    // down from where anyone would look for it.
    expect(page['buildId']()).toBe('');
  });

  it('remembers a build the user picks', async () => {
    const page = pageWith();
    await page['load']();

    await page['selectBuild']('b1');

    expect(localStorage.getItem('mistilteinn:optimize:buildId')).toBe('b1');
  });

  it('sets Element from the build before it waits on any request', async () => {
    // It used to be the *last* thing in `selectBuild`'s `try`, after the hit list and after
    // the whole equipped inventory — so on a real account the field visibly caught up a beat
    // later, reported as "the element field seems to update itself late" (#287). Nothing has
    // to be fetched to know it: the build is already in hand and carries its character.
    //
    // The stub never resolves, so this asserts the value is there while both requests are
    // still outstanding. That is the state the report was about.
    // `load()` selects the remembered build through this same method, so the stub has to
    // answer once before it is made to hang — otherwise the page never finishes loading and
    // the test times out rather than failing on the assertion.
    const hits = vi.fn().mockResolvedValue(HITS);
    const page = pageWith({ explain: { hits } as unknown as ExplainService });
    await page['load']();
    page['channel'] = 'physical';
    hits.mockReturnValue(new Promise<never>(() => undefined));

    void page['selectBuild']('b1');

    expect(page['channel']).toBe('cryo');
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
        [15003, { id: 'uuid-bs', name: 'Blizzard Strayer', simulable: true }],
        [15020, { id: 'uuid-wt', name: "Wanderer's Troupe", simulable: true }],
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
        caveats: { unstable: [], staleConversions: [], characters: [], fromCache: [] },
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
          new Map([[1, { id: 'uuid-1', name: 'Set One', simulable: true }]]),
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

  it('starts on the rotation objective, with single-hit still reachable', () => {
    // §15, and the reverse of what this test used to pin. OQ-W4's point stands — deleting a
    // fast honest answer because a slow better one exists is a downgrade — but *which of two
    // kept tools is in front* is a different question, and the owner's answer is the rotation
    // one: "it's the primary upgrade we provide so keep it at the forefront."
    //
    // Choosing the tool is not the same as inventing the user's data, which is why this
    // starts populated while `buildId` and `rotationId` start empty.
    const page = pageWith();

    expect((at(page, 'objective') as () => string)()).toBe('rotation');
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
      new Map([[15003, { id: 'uuid-bs', name: 'Blizzard Strayer', simulable: true }]]),
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
        [15003, { id: 'uuid-bs', name: 'Blizzard Strayer', simulable: true }],
        [15020, { id: 'uuid-wt', name: "Wanderer's Troupe", simulable: true }],
      ]),
    );

    const targets = (at(page, 'calibrationTargets') as (c: number[]) => {
      artifactSetIds: string[]; setIds: number[]; label: string;
    }[]).call(page, [15003, 15020]);

    // Uuids for `/calibrate`, catalogue ids for the search. Length is the state: 0 baseline,
    // 1 four-piece, 2 a pair.
    expect(targets.map((t) => t.artifactSetIds)).toEqual([[], ['uuid-bs'], ['uuid-wt']]);
    expect(targets.map((t) => t.setIds)).toEqual([[], [15003], [15020]]);
    // The baseline says it is the baseline. It read "no 4-piece set", and the progress line
    // "Calibrating no 4-piece set" then looked like a set the user had picked — reported from
    // production as "it's weird 'no 4p' was an option".
    expect(targets.map((t) => t.label)).toEqual([
      'the baseline (no 4-piece bonus)', 'Blizzard Strayer', "Wanderer's Troupe",
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
    piece('g3', 'equip_ring', 'FIGHT_PROP_ELEMENT_MASTERY'),
    piece('c', 'equip_dress', 'FIGHT_PROP_CRITICAL'),
  ];

  /**
   * The page's own `constrained`, not a restatement of it.
   *
   * **The previous version of this block declared its own `keep` predicate inline** and
   * asserted against that — so it was a test about a rule rather than about the code, and it
   * stayed green through a change from one main stat per slot to several. A test that cannot
   * fail when the thing it names changes is not holding it.
   */
  function keep(wanted: Record<string, readonly string[]>) {
    const page = pageWith();
    page['mainStatBySlot'].set(wanted);
    return page['constrained'](inventory as never).map((p) => p.id);
  }

  it('keeps everything when no slot is constrained', () => {
    expect(keep({})).toEqual(['f', 'g1', 'g2', 'g3', 'c']);
  });

  it('narrows only the constrained slot', () => {
    // The flower and circlet survive untouched: a constraint on the goblet says nothing about
    // any other slot, and narrowing them too would silently shrink the search.
    expect(keep({ equip_ring: ['FIGHT_PROP_FIRE_ADD_HURT'] })).toEqual(['f', 'g1', 'c']);
  });

  it('keeps a piece matching any of several wanted stats', () => {
    // Owner, 2026-08-30. Somebody who will take ATK% *or* EM on the sands had to run the
    // search twice and compare two rankings by eye — which is the search doing less than it
    // could, since both are one walk over a slightly larger bucket.
    expect(keep({
      equip_ring: ['FIGHT_PROP_ATTACK_PERCENT', 'FIGHT_PROP_ELEMENT_MASTERY'],
    })).toEqual(['f', 'g2', 'g3', 'c']);
  });

  it('treats an empty list as no constraint rather than as a stat nothing has', () => {
    // What "Any" leaves behind. Compared as a value it would match nothing and empty the slot.
    expect(keep({ equip_ring: [] })).toEqual(['f', 'g1', 'g2', 'g3', 'c']);
  });

  it('can empty a slot, which is exactly what has to be caught before searching', () => {
    // An empty result is indistinguishable from "your artifacts are bad", and the user would
    // not know which. The page says so before the search rather than after it returns nothing.
    expect(keep({ equip_ring: ['FIGHT_PROP_ELEC_ADD_HURT'] })).toEqual(['f', 'c']);
  });
});

describe('choosing main stats', () => {
  it('adds and removes one at a time, leaving the others alone', () => {
    const page = pageWith();

    page['toggleMainStat']('equip_ring', 'FIGHT_PROP_ATTACK_PERCENT');
    page['toggleMainStat']('equip_ring', 'FIGHT_PROP_ELEMENT_MASTERY');

    expect(page['mainStatBySlot']()['equip_ring'])
      .toEqual(['FIGHT_PROP_ATTACK_PERCENT', 'FIGHT_PROP_ELEMENT_MASTERY']);

    page['toggleMainStat']('equip_ring', 'FIGHT_PROP_ATTACK_PERCENT');

    expect(page['mainStatBySlot']()['equip_ring']).toEqual(['FIGHT_PROP_ELEMENT_MASTERY']);
  });

  it('is "any" again once the last one is removed', () => {
    // Rather than a constraint nothing satisfies, which would empty the slot and stop the
    // search returning anything at all.
    const page = pageWith();
    page['toggleMainStat']('equip_ring', 'FIGHT_PROP_ATTACK_PERCENT');

    page['toggleMainStat']('equip_ring', 'FIGHT_PROP_ATTACK_PERCENT');

    expect(page['anyMainStat']('equip_ring')).toBe(true);
  });

  it('clears a slot back to any in one move', () => {
    const page = pageWith();
    page['toggleMainStat']('equip_ring', 'FIGHT_PROP_ATTACK_PERCENT');
    page['toggleMainStat']('equip_ring', 'FIGHT_PROP_ELEMENT_MASTERY');

    page['clearMainStat']('equip_ring');

    expect(page['anyMainStat']('equip_ring')).toBe(true);
  });
});

describe('one Optimize button', () => {
  it('runs the single-hit search when that is the mode', async () => {
    // The page used to render `Search` in the top row unconditionally *and* `Search rotation`
    // beside the mode control. Choosing "with rotation" and pressing the top one ran the
    // single-hit search and ignored the whole block below it — including the set filter, which
    // is how a 4-piece choice looked like it did nothing.
    const page = pageWith();
    // Spied rather than run: `optimizeNow` is a router, and what it routes to is the claim.
    const single = vi.fn().mockResolvedValue(undefined);
    const rotation = vi.fn().mockResolvedValue(undefined);
    (page as unknown as Record<string, unknown>)['run'] = single;
    (page as unknown as Record<string, unknown>)['runRotation'] = rotation;
    page['objective'].set('hit');

    await page['optimizeNow']();

    expect(single).toHaveBeenCalled();
    expect(rotation).not.toHaveBeenCalled();
  });

  it('runs the rotation search when that is the mode', async () => {
    const page = pageWith();
    // Spied rather than run: `optimizeNow` is a router, and what it routes to is the claim.
    const single = vi.fn().mockResolvedValue(undefined);
    const rotation = vi.fn().mockResolvedValue(undefined);
    (page as unknown as Record<string, unknown>)['run'] = single;
    (page as unknown as Record<string, unknown>)['runRotation'] = rotation;
    page['objective'].set('rotation');

    await page['optimizeNow']();

    expect(rotation).toHaveBeenCalled();
    expect(single).not.toHaveBeenCalled();
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
    [1, { id: 'u1', name: 'Gladiator', icon: 'set_glad', fourPieceText: '+35% Normal Attack', simulable: true }],
    [2, { id: 'u2', name: 'Emblem', icon: 'set_emblem', fourPieceText: 'Bonus from ER', simulable: true }],
    [3, { id: 'u3', name: 'Noblesse', icon: 'set_noblesse', fourPieceText: '+20% party ATK', simulable: true }],
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

  it('marks the sets KeqingMains lists and shows them first', () => {
    // **The set half of the guide had no caller at all until 2026-09-04.** 346 rows captured,
    // cited and served, read by nothing — the same shape as `/compare-weapons` and
    // `createGpuKernel` before it. `docs/RESEARCH_kqm_not_reaching_the_ui.md`.
    const page = withThreeSets();
    (page['weaponGuide'] as unknown as { set: (v: unknown) => void }).set({
      character: 'Hu Tao', url: 'https://keqingmains.com/hutao/', retrieved_at: '2026-09-02',
      weapons: [],
      sets: [{
        position: 1, kind: 'set', as_written: '4pc Noblesse Oblige (4NO)', note: '101%',
        set_id: 'u3', set_nanoka_id: 3, set_name: 'Noblesse', pieces: '4pc',
        playstyle: '', relative_dps: '',
      }],
    });

    const options = (page['fourPieceOptions'] as unknown as () => readonly {
      label: string; detail?: string; tooltip?: string; recommended?: boolean;
    }[])();

    // Listed first, ahead of the alphabetical tie-break the rest keep.
    expect(options[0].label).toBe('Noblesse');
    expect(options[0].recommended).toBe(true);
    expect(options[0].detail).toContain('KQM #1');
    // KQM's sentence and the set's own bonus, both kept.
    expect(options[0].tooltip).toBe('101%\n\n+20% party ATK');
    // And nothing is claimed about the two they did not list.
    expect(options[1].recommended).toBe(false);
  });

  it('shows a stat-described two-piece as KQM sentence, never as a card', () => {
    // `2pc HP% / ER` names every set whose two-piece grants HP%, not a set. Turning it into a
    // card would invent a name KQM never wrote.
    const page = withThreeSets();
    (page['weaponGuide'] as unknown as { set: (v: unknown) => void }).set({
      character: 'Hu Tao', url: 'https://keqingmains.com/hutao/', retrieved_at: '2026-09-02',
      weapons: [],
      sets: [{
        position: 1, kind: 'stat', as_written: '2pc HP% / ER', note: 'Flexible.',
        set_id: null, set_nanoka_id: null, set_name: null, pieces: '2pc',
        playstyle: '', relative_dps: '',
      }],
    });

    const advice = (page['setAdvice'] as unknown as () => readonly { as_written: string }[])();
    const options = (page['fourPieceOptions'] as unknown as () => readonly {
      recommended?: boolean;
    }[])();

    expect(advice.map((row) => row.as_written)).toEqual(['2pc HP% / ER']);
    expect(options.every((card) => card.recommended === false)).toBe(true);
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

describe('switching mode does not leave the other mode findings up', () => {
  it('drops the rotation findings when Optimize runs', async () => {
    // `run()` replaced `result` and left `scoredRecipe`, `winningPools`, `caveats` and
    // `recipeNotes` standing — so switching to single hit and pressing Optimize left "Pieces
    // that would beat the winner" on screen, computed from the previous rotation's recipe,
    // under a heading naming a winner that is now a different build. The mode select is the
    // natural way to compare the two now that there is one button, so this is the sequence the
    // change invites.
    const page = pageWith();
    (page as unknown as Record<string, unknown>)['run'] = vi.fn().mockResolvedValue(undefined);
    page['objective'].set('hit');
    page['scoredRecipe'].set({ terms: [] } as never);
    page['winningPools'].set([{}] as never);
    page['caveats'].set({ unstable: ['x'], staleConversions: [], characters: [] } as never);

    await page['optimizeNow']();

    expect(page['scoredRecipe']()).toBeNull();
    expect(page['winningPools']()).toBeNull();
    expect(page['caveats']()).toBeNull();
  });

  it('drops them when a different build is chosen', async () => {
    // Same hole, same reason: a finding about one character's winner has no meaning under
    // another character's name.
    const page = pageWith();
    page['scoredRecipe'].set({ terms: [] } as never);
    page['winningPools'].set([{}] as never);

    await page['selectBuild']('');

    expect(page['scoredRecipe']()).toBeNull();
    expect(page['winningPools']()).toBeNull();
  });
});

describe('Optimize refuses a search the page has already predicted is empty', () => {
  it('is disabled when a slot constraint no piece satisfies is set', () => {
    // The page says "No artifact you own matches the main stats chosen for …" directly above
    // the button. Letting it be pressed anyway spends a six-second gcsim calibration in
    // rotation mode to return the empty list it had just predicted.
    const page = pageWith();
    page['candidates'].set([
      { id: 'g', slot: 'equip_ring', set_id: 1, stats: {}, main_stat: 'FIGHT_PROP_HP' },
    ] as never);
    page['mainStatBySlot'].set({ equip_ring: ['FIGHT_PROP_ELEC_ADD_HURT'] });

    expect(page['impossibleSlots']().length).toBeGreaterThan(0);
    expect(page['canOptimize']()).toBe(false);
  });
});

describe('sets gcsim cannot simulate', () => {
  /** Four slots of one set — enough for `fourPieceChoices` to reach it. */
  const pieces = (...setIds: number[]) =>
    setIds.flatMap((setId) =>
      ['equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring'].map((slot, i) => ({
        id: `${setId}-${i}`, slot, set_id: setId, stats: {},
      })),
    );

  const withCatalogue = (entries: [number, unknown][]) => {
    const page = pageWith();
    page['artifactSets'].set(new Map<number, never>(entries as never));
    page['candidates'].set(pieces(15003, 15020) as never);
    return page;
  };

  it('is not offered as a 4-piece', () => {
    // Reproduced from production: "All 4-piece" selected every set the inventory could field
    // four of, one of them was Scarlet Proof, and the whole calibration failed with a 422
    // naming it — so a run over a mixed selection returned nothing rather than the sets it
    // could have done.
    const page = withCatalogue([
      [15003, { id: 'a', name: 'Blizzard Strayer', simulable: true }],
      [15020, { id: 'b', name: 'Scarlet Proof', simulable: false }],
    ]);

    expect(page['fourPieceChoices']().map((c) => c.setId)).toEqual([15003]);
  });

  it('is named rather than silently dropped', () => {
    // A set vanishing from the picker looks exactly like not owning enough of it, and the
    // reason is worth saying: usually a set released after the pinned gcsim build.
    const page = withCatalogue([
      [15003, { id: 'a', name: 'Blizzard Strayer', simulable: true }],
      [15020, { id: 'b', name: 'Scarlet Proof', simulable: false }],
    ]);

    expect(page['unsimulableSets']()).toEqual(['Scarlet Proof']);
  });

  it('is not offered as a 4-piece at all', () => {
    // Was "is not selected by All 4-piece" until that button was removed (owner: selecting
    // every reachable set is ~28 calibrations at six seconds each, which nobody waits for).
    // The invariant it was really protecting outlives the button: a set gcsim cannot simulate
    // must never reach the picker, because choosing it fails the whole calibration with a 422.
    const page = withCatalogue([
      [15003, { id: 'a', name: 'Blizzard Strayer', simulable: true }],
      [15020, { id: 'b', name: 'Scarlet Proof', simulable: false }],
    ]);

    expect(page['fourPieceChoices']().map((c) => c.setId)).toEqual([15003]);
  });

  it('treats a set the catalogue does not mention as unknown, not as unusable', () => {
    // `loadFilterData` swallows its own failure by design. Treating an empty catalogue as
    // "nothing is simulable" would turn that into a silently disabled feature — a gate with
    // nothing able to satisfy it, which is a shape this page has already been bitten by.
    const page = withCatalogue([]);

    expect(page['fourPieceChoices']()).toHaveLength(2);
    expect(page['unsimulableSets']()).toEqual([]);
  });
});

describe('an unknown simulable flag does not disable the feature', () => {
  const pieces = (...setIds: number[]) =>
    setIds.flatMap((setId) =>
      ['equip_bracer', 'equip_necklace', 'equip_shoes', 'equip_ring'].map((slot, i) => ({
        id: `${setId}-${i}`, slot, set_id: setId, stats: {},
      })),
    );

  it('still offers a set whose catalogue entry omits the flag', () => {
    // An older backend, or a cached response predating the field. Defaulting absent to `false`
    // in the service defeated the `!== false` guard before it ever ran: every set became
    // unsimulable, the picker emptied, and the page said the inventory could field no 4-piece.
    const page = pageWith();
    page['artifactSets'].set(
      new Map<number, never>([[15003, { id: 'a', name: 'Blizzard Strayer' }]] as never),
    );
    page['candidates'].set(pieces(15003) as never);

    expect(page['fourPieceChoices']()).toHaveLength(1);
    expect(page['unsimulableSets']()).toEqual([]);
  });

  it('keeps an unsimulable set out of the list the request is built from', () => {
    // `fourPieceChoices` is the picker; `reachableSets` is what becomes the calibration
    // request. The guard belongs in both — nothing prunes a selection when the catalogue
    // changes under it, and it is the request that provokes the 422.
    const page = pageWith();
    page['artifactSets'].set(new Map<number, never>([
      [15003, { id: 'a', name: 'Blizzard Strayer', simulable: true }],
      [15020, { id: 'b', name: 'Scarlet Proof', simulable: false }],
    ] as never));

    expect(page['reachableSets'](pieces(15003, 15020) as never)).toEqual([15003]);
  });
});

describe('exhaustive and trustworthy are different claims', () => {
  it('is not shaky when nothing was caveated', () => {
    const page = pageWith();
    page['caveats'].set({ unstable: [], staleConversions: [], characters: [], fromCache: [] } as never);

    expect(page['recipeIsShaky']()).toBe(false);
  });

  it('is shaky when the rotation did not run the same way twice', () => {
    // `calibrate.ts`: "Stability is reported, not enforced… It is the caller's job not to rank
    // on it." The caller does rank on it, so at minimum the word "Exact" must not imply the
    // ranking is sound.
    const page = pageWith();
    page['caveats'].set({
      unstable: ['the baseline (no 4-piece bonus)'], staleConversions: [], characters: [], fromCache: [],
    } as never);

    expect(page['recipeIsShaky']()).toBe(true);
  });

  it('is shaky when conversions no probe could resolve cover the damage', () => {
    // Measured in production: four terms at ~90% damage share each, printed under "Exact —
    // the best five over this inventory". An exhaustive walk over a scorer that could not see
    // most of what it was ranking.
    const page = pageWith();
    page['caveats'].set({
      unstable: [],
      staleConversions: [{ label: 'x', term: 'flatDamage', damageShare: 0.903 }],
      fromCache: [],
    } as never);

    expect(page['recipeIsShaky']()).toBe(true);
  });

  it('says nothing when there was no rotation search at all', () => {
    // The single-hit search has no recipe, so it has no caveats and no claim to qualify.
    const page = pageWith();

    expect(page['recipeIsShaky']()).toBe(false);
  });
});

describe('the scoring warning does not cry wolf', () => {
  it('stays quiet for a frozen term covering almost none of the damage', () => {
    // `staleConversionsIn`: "83 hits carrying 2% of the damage is a footnote, and 5 hits
    // carrying 40% is not." Firing on any entry gave a 0.3% term the same red sentence as the
    // 90.3% case this was written for.
    const page = pageWith();
    page['caveats'].set({
      unstable: [],
      staleConversions: [{ label: 'x', term: 'flatDamage', damageShare: 0.003 }],
      fromCache: [],
    } as never);

    expect(page['recipeIsShaky']()).toBe(false);
  });

  it('speaks for a frozen term covering a real share', () => {
    const page = pageWith();
    page['caveats'].set({
      unstable: [],
      staleConversions: [{ label: 'x', term: 'flatDamage', damageShare: 0.06 }],
      fromCache: [],
    } as never);

    expect(page['recipeIsShaky']()).toBe(true);
  });

  it('speaks for an unstable rotation whatever its conversions did', () => {
    // Instability is not a matter of degree: the rotation did not run the same way twice.
    const page = pageWith();
    page['caveats'].set({ unstable: ['x'], staleConversions: [], characters: [], fromCache: [] } as never);

    expect(page['recipeIsShaky']()).toBe(true);
  });
});


/**
 * The build ranking decides who keeps a piece — `BACKLOG_frontend.md` §3.
 *
 * Before this, a piece held by another build was refused outright: *"take them off that build
 * first"*. That refusal is the friction the ranking exists to remove, and removing it wrongly
 * is how someone loses a goblet off a character they were not looking at.
 */
describe('OptimizePage equip, with a ranking', () => {
  const ROW = { rank: 1, damage: 100, artifactIds: ['a1', 'a2'], pieces: ['Flower', 'Plume'] };

  function pageRanked(mineRank: number | null, holderRank: number | null) {
    const get = vi.fn(async (id: string) => ({
      id, build_id: id === 'a2' ? 'b2' : null, slot: 'equip_bracer', set_name: 'Gladiator',
    }));
    const equip = vi.fn().mockResolvedValue({});
    const list = vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
    const page = pageWith({
      artifacts: {
        options: vi.fn().mockResolvedValue(OPTIONS), get, equip, list,
      } as unknown as Partial<ArtifactsService>,
    }) as unknown as Record<string, never>;
    (page['buildId'] as unknown as { set: (v: string) => void }).set('b1');
    (page['builds'] as unknown as { set: (v: unknown[]) => void }).set([
      { id: 'b1', optimizer_priority: mineRank, character: { name: 'Skirk' } },
      { id: 'b2', optimizer_priority: holderRank, character: { name: 'Ayaka' } },
    ]);
    return { page, equip };
  }

  const run = (page: Record<string, never>) =>
    (page['equipRow'] as unknown as (r: unknown) => Promise<void>).call(page, ROW);

  it('takes the piece when this build ranks higher, and says whose it was', async () => {
    const { page, equip } = pageRanked(0, 3);

    await run(page);

    expect(equip).toHaveBeenCalledWith('a2', null);
    // Named, not silent: a piece vanishing off a character nobody was looking at is the
    // failure mode this message exists to prevent.
    expect((page['equipped'] as unknown as () => string)()).toContain('Ayaka');
    expect((page['actionError'] as unknown as () => unknown)()).toBeNull();
  });

  it('refuses when the holder ranks higher, and names them', async () => {
    const { page, equip } = pageRanked(3, 0);

    await run(page);

    expect(equip).not.toHaveBeenCalled();
    expect((page['actionError'] as unknown as () => string)()).toContain('Ayaka');
  });

  it('an unranked build takes from nobody', async () => {
    // Without a rank there is no claim to make, and silently preferring the build you happen
    // to be looking at is exactly the surprise the ranking is meant to remove.
    const { page, equip } = pageRanked(null, 5);

    await run(page);

    expect(equip).not.toHaveBeenCalled();
    expect((page['actionError'] as unknown as () => string)()).toContain('no priority');
  });

  it('outranks an unranked holder', async () => {
    const { page, equip } = pageRanked(2, null);

    await run(page);

    expect(equip).toHaveBeenCalledWith('a2', null);
  });
});
