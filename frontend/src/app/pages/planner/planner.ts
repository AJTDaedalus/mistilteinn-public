import { Component, OnInit, computed, inject, signal } from '@angular/core';
import type { WritableSignal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CatalogueIcon } from '../../shared/icon/icon';
import { CardPicker, type CardFilter, type CardOption } from '../../shared/card-picker/card-picker';
import { characterCardFilters, characterCardOptions } from '../../shared/character-cards';
import { KQM_FILTER, listedFirst, weaponCard, weaponsById } from '../../shared/kqm/kqm';
import {
  CatalogueService,
  type CharacterSummary,
  type CharacterWeaponGuideRead,
  type WeaponSummary,
} from '../catalogue/catalogue.service';
import { allPages } from '../../api/all-pages';

import {
  PlannerService,
  type CraftingBonusRead,
  type MaterialLineRead,
  type PlanRead,
  type PlannerOptions,
  type SectionRead,
  type TalentOption,
} from './planner.service';

/** The ascension ladder, as `AvatarPromoteExcelConfigData.unlockMaxLevel` publishes it. */
const FALLBACK_CAPS: Record<number, number> = { 0: 20, 1: 40, 2: 50, 3: 60, 4: 70, 5: 80, 6: 90 };

/** Where a talent can be taken. Materials stop at 10; 11-15 come free from C3 and C5. */
const TALENT_LEVELS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

/**
 * Every level, offered whole.
 *
 * **The level picker used to be a function of the ascension picker**, listing only the levels
 * the chosen phase allows. That put the derived control in front: a user thinking "I am level
 * 62" had to work out that 62 means phase 4 before the page would offer 62 at all. Level is
 * the thing a player reads off their screen, so it leads, and the phase follows from it.
 */
const ALL_LEVELS = Array.from({ length: 90 }, (_, index) => index + 1);

/** viewBox geometry for the resin histogram. Units are arbitrary; the SVG scales to fit. */
const PLOT = { width: 360, height: 148, left: 34, right: 6, top: 10, bottom: 24 } as const;

/** Surface showing between neighbouring bars, so twelve bins read as twelve. */
const BAR_GAP = 2;

/**
 * Round numbers the probability axis is allowed to top out at.
 *
 * A scale that ends exactly at the tallest bar makes every chart look equally peaked, which is
 * the thing this histogram exists to distinguish: a narrow distribution and a broad one should
 * not draw the same picture.
 */
const NICE_CEILINGS = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1];

interface HistogramPlot {
  bars: { x: number; y: number; width: number; height: number; title: string }[];
  yTicks: { y: number; label: string }[];
  xTicks: { x: number; label: string }[];
  left: number;
  right: number;
  top: number;
  bottom: number;
  width: number;
  height: number;
}

interface TalentRow {
  talent: TalentOption;
  current: number;
  target: number;
}

/**
 * The leveling planner. `docs/DESIGN_planner.md`.
 *
 * **Level and ascension phase are separate controls on purpose.** They move independently in
 * the game — you can ascend at 80 and stay at 80 — and the owner asked for exactly that case.
 * Pairing them into one "target level" dropdown, which is what most tools do, makes the
 * ascend-and-stop plan unexpressible.
 */
@Component({
  selector: 'page-planner',
  imports: [FormsModule, CatalogueIcon, CardPicker],
  templateUrl: './planner.html',
  styleUrl: './planner.scss',
})
export class PlannerPage implements OnInit {
  private readonly planner = inject(PlannerService);
  private readonly catalogue = inject(CatalogueService);

  protected readonly characters = signal<CharacterSummary[]>([]);
  protected readonly weapons = signal<WeaponSummary[]>([]);
  protected readonly options = signal<PlannerOptions | null>(null);
  protected readonly plan = signal<PlanRead | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly characterId = signal<string | null>(null);
  protected readonly fromLevel = signal(1);
  protected readonly fromAscension = signal(0);
  protected readonly toLevel = signal(90);
  protected readonly toAscension = signal(6);

  protected readonly weaponId = signal<string | null>(null);
  protected readonly weaponFromLevel = signal(1);
  protected readonly weaponFromAscension = signal(0);
  protected readonly weaponToLevel = signal(90);
  protected readonly weaponToAscension = signal(6);

  protected readonly talentRows = signal<TalentRow[]>([]);
  /**
   * The one character crafting each material class, keyed by class.
   *
   * **One per class, spanning both columns.** Only one character crafts a given batch, so a
   * bonus and a refund are alternatives rather than additions — `craft_multiplier` has always
   * taken the best of them and never stacked, but a grid of checkboxes said otherwise, and a
   * control that implies an interaction the game does not have is a control that misinforms.
   *
   * Keyed by *class* rather than one pick overall, because weapon materials and talent books
   * are separate batches: Albedo can craft one while Eula crafts the other.
   */
  protected readonly craftPick = signal<Record<string, string | null>>({});

  /** Mora the user says they hold. Null until they say — no scanner exports a balance. */
  protected readonly moraOwned = signal<number | null>(null);
  protected readonly talentLevels = TALENT_LEVELS;

  /** Ascension phases, with the level each unlocks — so the picker can say "5 → 80". */
  protected readonly phases = computed(() => {
    const caps = this.options()?.level_caps ?? FALLBACK_CAPS;
    return Object.entries(caps)
      .map(([phase, cap]) => ({ phase: Number(phase), cap: Number(cap) }))
      .sort((a, b) => a.phase - b.phase);
  });

  protected readonly character = computed(() =>
    this.characters().find((row) => row.id === this.characterId()) ?? null,
  );

  /** Whether the chosen character is datamined ahead of release. */
  protected readonly isBeta = computed(() => this.character()?.is_beta ?? false);

  protected readonly weapon = computed(() =>
    this.weapons().find((row) => row.id === this.weaponId()) ?? null,
  );

  /**
   * The character grid, built by the same helper the build editor and the account page use.
   *
   * **A `<select>` of 150 names was the wrong control for the one decision this page exists
   * for.** You choose who to spend a fortnight of resin on by looking at them, and the rest of
   * the app already agreed: the owner's audit asked for picture grids *"everywhere"*, and
   * `shared/character-cards` exists precisely so the third page to draw this grid does not
   * decide for itself what a character card looks like.
   */
  protected readonly characterOptions = computed(() => characterCardOptions(this.characters()));

  protected readonly characterFilters = computed(() => characterCardFilters(this.characters()));

  /**
   * What KeqingMains lists for the chosen character, or null when no guide was captured.
   *
   * **Null is not an empty list.** "Nobody has captured this character" and "KQM recommends
   * nothing for them" are different statements, and a card marked *not recommended* on the
   * strength of the first would be a claim about KQM that nobody made.
   */
  protected readonly weaponGuide = signal<CharacterWeaponGuideRead | null>(null);

  private readonly recommendedWeapons = computed(() => weaponsById(this.weaponGuide()));

  /**
   * The weapon grid, ranked by the same guide the build editor and the optimizer rank by.
   *
   * Ranking matters more here than anywhere else in the app: this page prices a weapon at
   * roughly 900 resin of ascension materials, so "which weapon" is the expensive half of the
   * question and picking it off an alphabetical list of 260 names is the worst way to answer.
   */
  protected readonly weaponOptions = computed<CardOption[]>(() => {
    const listed = this.recommendedWeapons();
    const cards = this.weapons().map((row) => weaponCard(row, listed.get(row.id)));
    return listedFirst(cards, (card) => listed.get(card.value)?.position);
  });

  protected readonly weaponFilters = computed<CardFilter[]>(() => {
    const filters: CardFilter[] = [];
    // Offered only when there is a guide — a filter whose only outcome is an empty grid is not
    // a filter. Same rule as the build editor's.
    if (this.recommendedWeapons().size > 0) filters.push(KQM_FILTER);
    const stars = [...new Set(this.weapons().map((row) => row.stars))]
      .sort((a, b) => b - a)
      .map((value) => ({ value: String(value), label: `${value}\u2605` }));
    if (stars.length > 1) filters.push({ group: 'stars', label: 'Rarity', options: stars });
    return filters;
  });

  /**
   * The full splash for the selected character.
   *
   * `UI_AvatarIcon_Ayaka` → `UI_Gacha_AvatarImg_Ayaka`, the substitution
   * `scripts/download_icons.py` vendors under. Falls back to the avatar icon, which is what
   * the Travelers need: they have an icon upstream and no splash.
   */
  protected readonly splash = computed(() => {
    const icon = this.character()?.icon;
    if (!icon) return null;
    return icon.startsWith('UI_AvatarIcon_')
      ? icon.replace('UI_AvatarIcon_', 'UI_Gacha_AvatarImg_')
      : icon;
  });

  protected readonly levels = ALL_LEVELS;

  /**
   * The ascension phases a level can legally be in — one, or exactly two.
   *
   * **Two only at a cap.** Phase 5 tops out at 80 and phase 6 begins there, so a character at
   * 80 is either ascended or not and both are real states the game distinguishes. Every other
   * level sits inside exactly one phase and there is nothing to ask.
   *
   * That is why the phase control is not a seven-item list any more. Offering all seven made
   * every combination look available while five of them were states the game cannot produce,
   * and the backend rejected them after the fact — *"level 50 is outside 1-20, which is what
   * ascension phase 0 unlocks"*. A control that can express an impossible thing and relies on
   * the server to say no is a control that should not have offered it.
   */
  protected ascensionsAt(level: number): { phase: number; cap: number }[] {
    const caps = this.options()?.level_caps ?? FALLBACK_CAPS;
    return this.phases().filter(({ phase, cap }) => {
      const floor = phase === 0 ? 1 : (caps[phase - 1] ?? 1);
      return level >= floor && level <= cap;
    });
  }

  /** Whether this level is one the user has to answer a question about. */
  protected ascensionAmbiguous(level: number): boolean {
    return this.ascensionsAt(level).length > 1;
  }

  /**
   * A phase written the way the game writes it: `A6 80/90`.
   *
   * The number alone does not answer the question being asked — at level 80, "5" and "6" are
   * *before* and *after* the same ascension — and the cap is what separates them: `A5 80/80`
   * is capped where it stands, `A6 80/90` has ninety levels of headroom.
   *
   * **The game's own `current/max` shorthand**, which is what the character screen shows, so
   * the answer is read rather than translated. The long form this replaced spelled it out in
   * words (*"A6 — ascended, can reach 90"*) and said less: it named the ceiling without
   * showing the gap to it.
   */
  protected ascensionLabel(phase: number, level: number): string {
    const caps = this.options()?.level_caps ?? FALLBACK_CAPS;
    return `A${phase} ${level}/${caps[phase] ?? 90}`;
  }

  /**
   * Set a level and keep its phase legal.
   *
   * **The paired control must move with it.** Setting "from ascension" to 6 while the level
   * signal still held 1 rendered an empty `<select>` — no option matched — while `run()`
   * happily posted `level: 1`. The user saw a blank box and got a bill for levelling 1→90
   * instead of 80→90, and nothing rejected it because 1/6 is a legal state.
   *
   * Now that level leads, the same hazard runs the other way and is closed here: a phase left
   * over from the previous level is silently replaced rather than posted.
   */
  protected setLevel(
    level: number,
    levelSignal: WritableSignal<number>,
    ascension: WritableSignal<number>,
  ): void {
    levelSignal.set(level);
    const allowed = this.ascensionsAt(level).map((entry) => entry.phase);
    // **The lower phase when the old one no longer fits**, because "I am level 62" means not
    // yet ascended past what 62 needs. The user can say otherwise wherever there is a choice.
    if (!allowed.includes(ascension())) ascension.set(allowed[0] ?? 0);
  }

  /**
   * Crafting help as two tables of two columns: what each material class can gain.
   *
   * **The flat checkbox list read as one undifferentiated pile of twelve.** A passive is
   * really two facts — *which materials* it touches and *what it does to them* — and the list
   * encoded both in a sentence, so telling apart "Albedo doubles weapon ascension materials"
   * from "Xingqiu refunds some talent materials" meant reading every row.
   *
   * A character appears in both tables when their passive names both classes: Sucrose doubles
   * either and Dori refunds either. That is duplication on screen and it is **correct** — the
   * question each table answers is "what can help *this* class", and the honest answer names
   * them twice.
   */
  protected readonly craftGroups = computed(() => {
    const all = this.options()?.bonuses ?? [];
    const of = (materialClass: string, effects: readonly string[]) =>
      all
        .filter((bonus) => bonus.classes.includes(materialClass)
          && effects.includes(bonus.effect))
        // **Checkable first.** Talent crafting's bonus column listed Prune and Yae Miko —
        // neither of which can be applied — above Eula, Layla and Sucrose, which can. A
        // column whose actionable rows are buried under its unactionable ones is read as
        // decoration.
        .sort((a, b) => Number(b.applicable) - Number(a.applicable));
    // **The game's own three recipe categories**, named as the game names them. They were
    // two, and "Weapon crafting" / "Talent crafting" were this app's own words for them —
    // which hid that a third exists and that Sucrose and Dori belong to it rather than to
    // both of the others. `services/planner/crafting.py`.
    return [
      { key: 'talent', label: 'Character talent materials' },
      { key: 'weapon_ascension', label: 'Weapon ascension materials' },
      { key: 'enhancement', label: 'Character and weapon enhancement materials' },
    ].map((group) => ({
      ...group,
      // Only `double`. A bonus *regional* material would need the regional family modelled,
      // which the owner ruled out, so the backend no longer classifies those passives at all
      // — they are not planner-relevant, the way a cooking passive is not.
      bonus: of(group.key, ['double']),
      refund: of(group.key, ['refund']),
    })).filter((group) => group.bonus.length > 0 || group.refund.length > 0);
  });

  /**
   * One sentence for a column's greyed rows, or null when it has none.
   *
   * **Null rather than an empty string**, so a column whose every row is checkable renders no
   * footnote at all rather than a stray "Greyed:" with nothing after it.
   *
   * The two reasons are different facts and are not collapsed: a refund's *size* is
   * unpublished, and a bonus regional material needs a family this app has not modelled. A
   * column holding both says both.
   */
  protected unappliedNote(bonuses: readonly CraftingBonusRead[]): string | null {
    const reasons = new Set(
      bonuses.filter((bonus) => !bonus.applicable).map((bonus) => (
        bonus.effect === 'refund'
          ? 'the chance is published, the size of the refund is not'
          : 'needs the regional material family modelled'
      )),
    );
    return reasons.size ? [...reasons].join('; ') : null;
  }

  async ngOnInit(): Promise<void> {
    // **Weapons are no longer loaded here.** They are loaded per character, filtered to the
    // class that character can hold — a bow on a sword user is not a plan anyone can act on,
    // and it was 260 rows in a `<select>` offering mostly that.
    const [characters, options] = await Promise.all([
      // **The one caller that opts in.** Beta characters are seeded and marked, and hidden
      // from every list that does not ask — so the build editor never offers one, no build can
      // hold one, and the optimizer cannot reach one. Pricing an upcoming character is the
      // whole reason the owner reopened the beta ruling.
      allPages((offset, limit) =>
        this.catalogue.listCharacters({ include_beta: true, offset, limit }),
      ),
      this.planner.options(),
    ]);
    this.characters.set(characters.items);
    this.options.set(options);
  }

  protected pickCharacter(ids: readonly string[]): void {
    void this.selectCharacter(ids[0] ?? null);
  }

  protected pickWeapon(ids: readonly string[]): void {
    this.weaponId.set(ids[0] ?? null);
  }

  /** Load the talents, the weapons of this character's class, and KQM's guide. */
  protected async selectCharacter(id: string | null): Promise<void> {
    this.characterId.set(id);
    this.plan.set(null);
    this.weaponId.set(null);
    this.weapons.set([]);
    this.weaponGuide.set(null);
    if (!id) return;
    const options = await this.planner.options(id);
    this.options.set(options);
    this.talentRows.set(
      (options.talents ?? []).map((talent) => ({ talent, current: 1, target: 10 })),
    );
    const chosen = this.characters().find((row) => row.id === id);
    if (!chosen) return;
    try {
      const page = await allPages((offset, limit) =>
        this.catalogue.listWeapons({
          weapon_type: chosen.weapon_type, include_beta: true, offset, limit,
        }),
      );
      this.weapons.set(page.items as WeaponSummary[]);
      // Never fatal. The picker works without a guide, and a page that refused to open
      // because a recommendation could not be fetched would be worse than one that marks
      // nothing.
      this.weaponGuide.set(await this.catalogue.weaponGuide(chosen.nanoka_id));
    } catch {
      this.error.set('Could not load weapons for that character.');
    }
  }

  /**
   * Read a starting state off one of the user's builds.
   *
   * **A build may be hypothetical** — this app lets you gear a character you do not own — so
   * the page fills the controls and leaves them editable rather than locking to the build.
   */
  protected applyBuild(buildId: string): void {
    const build = (this.options()?.builds ?? []).find((row) => row.build_id === buildId);
    if (!build) return;
    this.setLevel(build.character_level, this.fromLevel, this.fromAscension);
    this.fromAscension.set(build.ascension_phase);
    this.talentRows.update((rows) =>
      rows.map((row) => ({
        ...row,
        current: build.talent_levels[row.talent.talent_type] ?? row.current,
      })),
    );
    if (build.weapon_id) {
      this.weaponId.set(build.weapon_id);
      this.weaponFromLevel.set(build.weapon_level);
      // **Null when this account holds no physical copy**, and then it is left alone rather
      // than filled from the character's phase — which is what the API used to send, so a
      // level-20 weapon on a 90/6 character prefilled "20/6" and every weapon ascension bill
      // silently vanished from the plan.
      if (build.weapon_ascension !== null && build.weapon_ascension !== undefined) {
        this.setLevel(build.weapon_level, this.weaponFromLevel, this.weaponFromAscension);
        // The build's own phase wins over the one `setLevel` inferred, which is the whole
        // point of reading it: at a cap level both are legal and only the build knows which.
        this.weaponFromAscension.set(build.weapon_ascension);
      }
    }
  }

  protected pickCraft(materialClass: string, characterId: string | null): void {
    this.craftPick.update((current) => ({ ...current, [materialClass]: characterId }));
  }

  protected crafterFor(materialClass: string): string | null {
    return this.craftPick()[materialClass] ?? null;
  }

  /**
   * The ids to send: one per class, de-duplicated.
   *
   * A character named by both classes — Sucrose doubles either, Dori refunds either — is one
   * id, not two. The backend filters each bonus by class anyway, so sending it once applies
   * it to both.
   */
  private readonly selectedBonusIds = computed(() => [
    ...new Set(Object.values(this.craftPick()).filter((id): id is string => Boolean(id))),
  ]);

  protected setTalent(index: number, field: 'current' | 'target', value: number): void {
    this.talentRows.update((rows) =>
      rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    );
  }

  protected async run(): Promise<void> {
    const characterId = this.characterId();
    if (!characterId) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      this.plan.set(
        await this.planner.plan({
          character_id: characterId,
          character_from: { level: this.fromLevel(), ascension: this.fromAscension() },
          character_to: { level: this.toLevel(), ascension: this.toAscension() },
          talents: this.talentRows().map((row) => ({
            talent_id: row.talent.talent_id,
            current: row.current,
            target: row.target,
          })),
          weapon_id: this.weaponId(),
          weapon_from: this.weaponId()
            ? { level: this.weaponFromLevel(), ascension: this.weaponFromAscension() }
            : null,
          weapon_to: this.weaponId()
            ? { level: this.weaponToLevel(), ascension: this.weaponToAscension() }
            : null,
          bonus_character_ids: this.selectedBonusIds(),
          mora_owned: this.moraOwned(),
        }),
      );
    } catch (cause: unknown) {
      // The backend rejects a state the game cannot produce with a sentence saying which —
      // "level 50 is outside 1-20, which is what ascension phase 0 unlocks". Show it.
      const detail = (cause as { detail?: unknown } | null)?.detail;
      this.error.set(typeof detail === 'string' ? detail : 'The planner could not price that.');
      this.plan.set(null);
    } finally {
      this.busy.set(false);
    }
  }

  // -- rendering helpers ----------------------------------------------------------------

  protected number(value: number | null | undefined): string {
    return value === null || value === undefined ? '—' : value.toLocaleString();
  }

  protected round(value: number): string {
    return Math.round(value).toLocaleString();
  }

  /**
   * A section's resin, or `null` when **nothing in it could be priced**.
   *
   * Driving the page found this: a section whose whole cost is unpriced showed "Resin ~ 0"
   * with the explanation underneath, and the number is what a reader takes away. Zero is an
   * answer; this is the absence of one.
   */
  protected sectionResin(section: SectionRead): string {
    const nothingPriced =
      section.resin.expected === 0
      && (section.resin.unpriced.length > 0 || section.resin.unpriced_sources.length > 0);
    return nothingPriced ? '—' : `\u2248 ${this.round(section.resin.expected)}`;
  }

  /**
   * The resin histogram as SVG geometry: bars, and both axes' ticks.
   *
   * **Computed here rather than in the template.** The old chart was a flex row of `<div>`s
   * with a percentage height, which can draw bars and cannot draw an axis: there is nowhere to
   * hang a tick, and the bar heights were relative to the tallest bar rather than to a scale,
   * so two sections' charts looked alike while meaning different things.
   *
   * One series, so no legend — the caption names it. Sizes are viewBox units; the SVG scales
   * to its column.
   */
  protected plot(section: SectionRead): HistogramPlot {
    const bins = section.resin.histogram;
    const peak = Math.max(...bins.map((bin) => bin.probability), 0.0001);
    const yMax = NICE_CEILINGS.find((step) => step >= peak) ?? 1;

    const left = PLOT.left;
    const right = PLOT.width - PLOT.right;
    const top = PLOT.top;
    const bottom = PLOT.height - PLOT.bottom;
    const span = right - left;
    const slot = span / bins.length;

    const bars = bins.map((bin, index) => {
      const height = ((bin.probability / yMax) * (bottom - top)) || 0;
      return {
        // **A 2px gap between neighbours**, not a bar per slot: contiguous fills read as one
        // block and the eye cannot count them.
        x: left + index * slot + BAR_GAP / 2,
        width: Math.max(1, slot - BAR_GAP),
        y: bottom - height,
        height,
        title: `${this.round(bin.low)}–${this.round(bin.high)} resin: `
          + `${(bin.probability * 100).toFixed(1)}%`,
      };
    });

    // Three is enough to read a scale off and few enough not to crowd a chart this size.
    const yTicks = [0, 0.5, 1].map((fraction) => ({
      y: bottom - fraction * (bottom - top),
      label: `${Math.round(yMax * fraction * 100)}%`,
    }));

    // Ticks on bin *edges*, so a label names a real boundary rather than a bar's middle. The
    // last one is the final bin's `high`, which is the only edge no bin starts at.
    const edges = [0, Math.floor(bins.length / 2), bins.length];
    const xTicks = [...new Set(edges)].map((index) => ({
      x: left + index * slot,
      label: this.round(
        index === bins.length ? bins[bins.length - 1].high : bins[index].low,
      ),
    }));

    // **Not `...PLOT`.** `PLOT.right` is the right *padding* (6) and `right` is the computed
    // right *edge* (354); spreading it last silently replaced one with the other, which the
    // typecheck caught and a chart would have shown as every bar crushed against the y axis.
    return {
      bars, yTicks, xTicks, left, right, top, bottom,
      width: PLOT.width, height: PLOT.height,
    };
  }

  protected rowsToShow(section: SectionRead): MaterialLineRead[] {
    return section.materials.filter((line) => line.required > 0);
  }

  /** Everything a section could not price, as one sentence — or null when it priced it all. */
  protected gaps(section: SectionRead): string | null {
    const parts: string[] = [];
    if (section.resin.unpriced.length) {
      parts.push(`${section.resin.unpriced.length} material(s) at an unpublished drop rate`);
    }
    parts.push(...section.resin.unpriced_sources);
    return parts.length ? `Resin unknown for ${parts.join(', ')}.` : null;
  }

  /**
   * "Mon/Thu/Sun" for a domain material, "" for anything else.
   *
   * Derived, not curated: `DailyDungeonConfigData` names which dungeons run on which day and
   * each dungeon publishes what it drops.
   */
  protected days(line: MaterialLineRead): string {
    return line.domain_days
      .map((day) => day.slice(0, 1).toUpperCase() + day.slice(1, 3))
      .join('/');
  }
}
