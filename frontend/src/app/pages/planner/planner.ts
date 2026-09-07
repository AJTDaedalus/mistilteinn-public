import { Component, OnInit, computed, inject, signal } from '@angular/core';
import type { WritableSignal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CatalogueIcon } from '../../shared/icon/icon';
import { CatalogueService, type CharacterSummary, type WeaponSummary } from '../catalogue/catalogue.service';
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
  imports: [FormsModule, CatalogueIcon],
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
  protected readonly selectedBonuses = signal<Set<string>>(new Set());
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

  protected readonly weapon = computed(() =>
    this.weapons().find((row) => row.id === this.weaponId()) ?? null,
  );

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

  /**
   * Clamp a level into the range its ascension phase allows.
   *
   * **The paired control must move with it.** Setting "from ascension" to 6 while the level
   * signal still held 1 rendered an empty `<select>` — no option matched — while `run()`
   * happily posted `level: 1`. The user saw a blank box and got a bill for levelling 1→90
   * instead of 80→90, and nothing rejected it because 1/6 is a legal state.
   */
  protected setAscension(
    phase: number,
    ascension: WritableSignal<number>,
    level: WritableSignal<number>,
  ): void {
    ascension.set(phase);
    const allowed = this.levelsFor(phase);
    const current = level();
    if (!allowed.includes(current)) {
      level.set(current < allowed[0] ? allowed[0] : allowed[allowed.length - 1]);
    }
  }

  /** Levels a character may legally reach, given the ascension phase asked for. */
  protected levelsFor(phase: number): number[] {
    const cap = (this.options()?.level_caps ?? FALLBACK_CAPS)[phase] ?? 90;
    const floor = phase === 0 ? 1 : ((this.options()?.level_caps ?? FALLBACK_CAPS)[phase - 1] ?? 1);
    const out: number[] = [];
    for (let level = floor; level <= cap; level += 1) out.push(level);
    return out;
  }

  protected readonly bonusesApplicable = computed(
    () => (this.options()?.bonuses ?? []).filter((bonus) => bonus.applicable),
  );

  protected readonly bonusesReported = computed(
    () => (this.options()?.bonuses ?? []).filter((bonus) => !bonus.applicable),
  );

  async ngOnInit(): Promise<void> {
    const [characters, weapons, options] = await Promise.all([
      allPages((offset, limit) => this.catalogue.listCharacters({ offset, limit })),
      allPages((offset, limit) => this.catalogue.listWeapons({ offset, limit })),
      this.planner.options(),
    ]);
    this.characters.set(characters.items);
    this.weapons.set(weapons.items);
    this.options.set(options);
  }

  /** Load the talents (and any builds) for a newly picked character. */
  protected async pickCharacter(id: string): Promise<void> {
    this.characterId.set(id);
    this.plan.set(null);
    const options = await this.planner.options(id);
    this.options.set(options);
    this.talentRows.set(
      (options.talents ?? []).map((talent) => ({ talent, current: 1, target: 10 })),
    );
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
    this.fromLevel.set(build.character_level);
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
        this.setAscension(
          build.weapon_ascension, this.weaponFromAscension, this.weaponFromLevel,
        );
      }
    }
  }

  protected toggleBonus(characterId: string): void {
    this.selectedBonuses.update((current) => {
      const next = new Set(current);
      if (next.has(characterId)) next.delete(characterId);
      else next.add(characterId);
      return next;
    });
  }

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
          bonus_character_ids: [...this.selectedBonuses()],
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

  /** Bar height as a percentage of the tallest bin, so a flat histogram still reads. */
  protected barHeight(section: SectionRead, probability: number): number {
    const peak = Math.max(...section.resin.histogram.map((bin) => bin.probability), 0.0001);
    return Math.max(2, (probability / peak) * 100);
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

  protected bonusLabel(bonus: CraftingBonusRead): string {
    const what = bonus.classes.map((name) => name.replace('_', ' ')).join(' and ');
    return `${bonus.character_name} — ${Math.round(bonus.chance * 100)}% on ${what}`;
  }
}
