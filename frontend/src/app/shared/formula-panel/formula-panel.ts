import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';

import type { ConditionGroup } from '../../sim/formula-calibration';
import {
  defaultWhy, hitMove, reactionLabel, type ConditionValue, type FormulaCondition,
  type FormulaReaction,
} from '../../sim/formula-recipe';
import type { FormulaMove } from '../../sim/recipe';
import {
  ADDITIVE, type Additive, type Lunar, SWIRL_ELEMENTS, type Transformative,
} from '../../sim/damage';
import {
  defaultFavoniusHits,
  defaultOnField,
  energyInput,
  favoniusKey,
  favoniusProcs,
  FormulaEstimateService,
  absorbedElement,
  refundKey,
  refundOnField,
  RESONANCE_KEY,
  resonanceProcs,
  rotationSecondsOf,
  sourceKey,
  subjectHitsOf,
  subjectOnFieldOf,
  type EnergySettings,
  type ProcChoice,
  type TargetRow,
} from '../../pages/optimize/formula-estimate.service';
import {
  favoniusProcsAt,
  rawParticleEnergy,
  requiredEnergyRecharge,
  type EnergyMode,
} from '../../sim/formula-energy';
import type { AvailableHit, RefusedHit } from '../../pages/explain/explain.service';
import { RefusedHits } from '../refused-hits/refused-hits';

/** The reactions a reaction row can price (P3), in the order a player thinks of them. */
const REACTIONS: { value: Transformative | Lunar; label: string }[] = [
  { value: 'hyperbloom', label: 'Hyperbloom' },
  { value: 'bloom', label: 'Bloom' },
  { value: 'burgeon', label: 'Burgeon' },
  { value: 'burning', label: 'Burning' },
  { value: 'overloaded', label: 'Overloaded' },
  { value: 'electro_charged', label: 'Electro-Charged' },
  { value: 'superconduct', label: 'Superconduct' },
  { value: 'swirl', label: 'Swirl' },
  { value: 'shattered', label: 'Shattered' },
  { value: 'lunar_charged', label: 'Lunar-Charged' },
  { value: 'lunar_crystallize', label: 'Lunar-Crystallize' },
];

/** The energy model's modes (task 14). `wait` is the default (owner, 2026-11-15, §48). */
const ENERGY_MODES: { value: EnergyMode; label: string }[] = [
  { value: 'off', label: 'Report only' },
  { value: 'skip', label: 'Skip an unfunded burst' },
  { value: 'wait', label: 'Wait for the energy' },
];

const MOVES: { value: FormulaMove; label: string }[] = [
  { value: 'normal', label: 'Normal attack' },
  { value: 'charged', label: 'Charged / aimed' },
  { value: 'plunge', label: 'Plunge' },
  { value: 'skill', label: 'Skill' },
  { value: 'burst', label: 'Burst' },
];

/** `normal_attack` → `Normal attack`. */
function talentName(raw: string): string {
  const spaced = raw.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * The formula target and the assumptions it rests on — one panel, shared by Optimize, Rank and
 * Upgrade (math-fallback P1, task 8; `DESIGN_team_math_fallback.md` §2.5).
 *
 * **The target** is one or more abilities, each with a count (GO's multi-target: Σ count × hit)
 * and the move it is, which decides which move-scoped bonuses reach it. Refused rows are shown
 * disabled in each picker and named with their reason below it, never dropped (owner,
 * 2026-11-13).
 *
 * **The assumptions** are every conditional from the team's resonance, the sets in scope and
 * each member's kit sheet (P2: a kit says whether it is verified against GO, and a member with
 * no sheet is named as contributing no kit buffs),
 * each a visible control showing its default and why — self-triggered on (at max), situational
 * off (owner, 2026-11-13) — and the source it is cited to; then, after a run, every assumption
 * the recipe itself listed. A number that cannot say what it assumed is the thing this repo
 * refuses.
 */
@Component({
  selector: 'formula-panel',
  imports: [RefusedHits],
  templateUrl: './formula-panel.html',
  styleUrl: './formula-panel.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FormulaPanel {
  private readonly service = inject(FormulaEstimateService);

  readonly hits = input<readonly AvailableHit[]>([]);
  readonly refusedHits = input<readonly RefusedHit[]>([]);
  /** The conditions the team and sets in scope expose. */
  readonly groups = input<readonly ConditionGroup[]>([]);
  /** The last estimate's own assumptions; empty before a run. */
  readonly assumptions = input<readonly string[]>([]);
  /** Sets whose 4-piece the estimate could not score, already named. */
  readonly withheld = input<readonly string[]>([]);
  /**
   * The optimized character's element, lower case (P3): it decides which additive reaction an
   * ability can trigger and a new swirl row's element. Empty offers both and leaves the recipe
   * to refuse a mismatch by name.
   */
  readonly element = input<string>('');
  /**
   * Weapon procs a row can count (owner approval 2026-11-14, `DECISIONS.md` §45): the equipped
   * weapon's and any weapon picked for comparison. Empty hides *Add weapon proc*.
   */
  readonly procs = input<readonly ProcChoice[]>([]);

  protected readonly moves = MOVES;
  protected readonly energyModes = ENERGY_MODES;
  protected readonly energySettings = this.service.energy;

  /**
   * The energy section (task 14): every member's skill particles with their casts, the share
   * the optimized character catches on field, the drip and flat energy — each editable, each
   * with its default and citation — and the ER the burst needs, from the same closed form the
   * estimate scores with. `null` before the team's data has arrived.
   */
  protected readonly energyView = computed(() => {
    const data = this.service.teamEnergy();
    if (!data) return null;
    const settings = this.service.energy();
    const subject = data.members.find((m) => m.is_subject) ?? null;
    const subjectHits = subjectHitsOf(this.service.rows());
    const rowsOnField = subjectOnFieldOf(this.service.rows());
    const onField = settings.subjectOnField ?? rowsOnField;
    const input = energyInput(data, settings, subjectHits, rowsOnField);
    const model = input ? { ...input, baseEnergyRecharge: 0 } : null;
    const seconds = rotationSecondsOf(data, settings);
    const resonance = data.resonance ?? null;
    return {
      subject,
      rotationSeconds: rotationSecondsOf(data, settings),
      rotationIsDefault: settings.rotationSeconds === null,
      drip: data.drip,
      // The drip lands on whoever is active (gcsim `DistributeParticle`): an on-field
      // subject catches it on field by default (owner ruling 2026-11-15, DECISIONS §50).
      dripOnField: settings.onField['drip'] ?? (onField ? 1 : 0),
      dripOnFieldIsDefault: settings.onField['drip'] === undefined,
      requirement: model ? requiredEnergyRecharge(model) : null,
      raw: model ? rawParticleEnergy(model) : 0,
      onField,
      onFieldIsDefault: settings.subjectOnField === null,
      rowsOnField,
      resonance: resonance ? {
        res: resonance,
        procs: resonanceProcs(resonance, settings, seconds),
        ceiling: seconds / resonance.cooldown_seconds,
        procsIsDefault: settings.resonanceProcs === null,
        onField: settings.onField[RESONANCE_KEY] ?? (onField ? 1 : 0),
        key: RESONANCE_KEY,
      } : null,
      members: data.members.map((member) => ({
        member,
        casts: settings.casts[member.build_id] ?? 1,
        bursts: settings.bursts[member.build_id] ?? 1,
        countsBursts: member.sources.some((s) => s.on === 'burst')
          || (member.refunds ?? []).some((r) => r.per === 'burst'),
        manual: settings.manual[member.build_id] ?? 0,
        refunds: (member.refunds ?? []).map((refund, i) => {
          const key = refundKey(member.build_id, i);
          // Venti's absorbed element (DECISIONS §50): the user's, else the first of gcsim's
          // order a teammate carries.
          const absorbed = refund.recipients === 'absorbed'
            ? absorbedElement(member, refund, settings, data.members, i) : null;
          const reaches = refund.recipients === 'team'
            || refund.recipients === 'active'
            || (refund.recipients === 'self' && member.is_subject)
            || (refund.recipients === 'others' && !member.is_subject)
            || (refund.recipients === 'absorbed' && absorbed !== null
              && absorbed === subject?.element);
          return {
            key, refund,
            count: settings.refundCounts[key] ?? refund.count,
            reaches,
            basis: refund.basis ?? 'kit',
            toggled: settings.refundToggles[key] ?? false,
            absorbed,
            absorbedIsDefault: settings.absorbed[key] === undefined,
            onField: refund.recipients === 'active'
              ? refundOnField(member, i, settings, onField) : null,
          };
        }),
        favonius: member.favonius ? (() => {
          const key = favoniusKey(member.build_id);
          const hits = settings.favoniusHits[member.build_id]
            ?? defaultFavoniusHits(member, settings, subjectHits);
          return {
            fav: member.favonius,
            hits,
            hitsIsDefault: settings.favoniusHits[member.build_id] === undefined,
            critRate: member.crit_rate ?? 0,
            // The optimized holder's procs move with each candidate's crit (§49); shown here
            // at the build's.
            procs: member.is_subject && input?.subjectFavonius
              ? favoniusProcsAt(input.subjectFavonius, seconds, member.crit_rate ?? 0)
              : favoniusProcs(member, hits, seconds),
            perCandidate: member.is_subject,
            onField: settings.onField[key] ?? (member.is_subject ? 1 : 0),
            key,
          };
        })() : null,
        sources: member.sources.map((source, i) => {
          const key = sourceKey(member.build_id, i);
          return {
            key, source,
            particles: settings.particles[key] ?? source.particles,
            onField: settings.onField[key] ?? defaultOnField(member, source, onField),
          };
        }),
      })),
    };
  });
  protected readonly reactions = REACTIONS;
  protected readonly swirlElements = SWIRL_ELEMENTS;

  /** The additive reactions this character's abilities can trigger. */
  protected readonly additives = computed(() => (Object.keys(ADDITIVE) as Additive[])
    .filter((a) => !this.element() || ADDITIVE[a].element === this.element()));
  protected readonly rows = this.service.rows;
  protected readonly teamState = this.service.conditionals;

  protected readonly hitGroups = computed(() => {
    const groups: { talent: string; items: AvailableHit[]; refused: RefusedHit[] }[] = [];
    const groupFor = (raw: string) => {
      const talent = talentName(raw);
      let group = groups.find((g) => g.talent === talent);
      if (!group) groups.push((group = { talent, items: [], refused: [] }));
      return group;
    };
    for (const hit of this.hits()) groupFor(hit.talent).items.push(hit);
    for (const row of this.refusedHits()) groupFor(row.talent).refused.push(row);
    return groups;
  });

  /** Whether the groups say anything about kits (P2): then they, not a blanket line, do. */
  protected readonly hasKits = computed(() => this.groups().some((g) => g.kind !== undefined));
  /** A weapon passive or a weapon without one is listed (task 12). */
  protected readonly hasWeapons = computed(
    () => this.groups().some((g) => g.kind === 'weapon' || g.kind === 'no-weapon'),
  );

  /**
   * Groups that carry a control, for the per-row overrides. A candidate weapon's are not: they
   * are that candidate's own setting, one per candidate run (§46), not a row's.
   */
  protected readonly conditional = computed(
    () => this.groups().filter((g) => g.conditions.length > 0 && !g.candidate),
  );
  /** Anything to put back to its default, the equipped run's or a candidate's. */
  protected readonly resettable = computed(
    () => this.groups().some((g) => g.conditions.length > 0),
  );
  /** A candidate group heads the candidates' part of the list (they come last). */
  protected startsCandidates(index: number): boolean {
    const groups = this.groups();
    return !!groups[index]?.candidate && (index === 0 || !groups[index - 1].candidate);
  }
  protected readonly candidateState = this.service.candidateConditionals;

  /**
   * A hit's identity in the picker. **All three parts**: `index` is the part within one
   * labelled row (`2-Hit DMG` has parts 0 and 1), so `talent#index` collided across every row
   * of a talent and the closed select showed whichever colliding option came last — found
   * driving Kachina, whose target read "Low/High Plunge DMG" over a 1-Hit row.
   */
  protected hitKey(hit: { talent: string; label: string; index: number }): string {
    return `${hit.talent}#${hit.label}#${hit.index}`;
  }

  protected pickHit(row: TargetRow, key: string): void {
    const hit = this.hits().find((h) => this.hitKey(h) === key);
    if (!hit) return;
    const fresh = { talent: hit.talent, label: hit.label, index: hit.index };
    // **The move belongs to the hit it was set for.** Kept across a change of ability, a row
    // first made for a 1-Hit DMG and switched to a burst's slash stayed a normal attack, so a
    // burst-scoped kit buff (Skirk's Serpent's Subtlety) silently missed it — found driving it.
    this.service.updateRow(row.id, {
      hit: fresh, label: hit.label, move: hitMove(hit),
    });
  }

  protected pickMove(row: TargetRow, value: string): void {
    this.service.updateRow(row.id, {
      move: MOVES.some((m) => m.value === value) ? value as FormulaMove : null,
    });
  }

  /**
   * On `change`, and an emptied or non-positive box keeps the last value: `Number('')` is 0,
   * and a count of 0 is refused by the recipe rather than read as "this row does nothing".
   */
  protected setCount(row: TargetRow, box: HTMLInputElement): void {
    const value = Number(box.value);
    if (box.value.trim() !== '' && Number.isFinite(value) && value > 0) {
      this.service.updateRow(row.id, { count: value });
    } else {
      box.value = String(row.count);
    }
  }

  protected add(): void {
    const first = this.hits()[0];
    if (first) this.service.addRow(first);
  }

  // ── Reactions (math-fallback P3) ────────────────────────────────────────────────────────

  /** A new reaction row: a swirl for an Anemo character, else the first reaction. */
  protected addReaction(): void {
    const first = this.hits()[0];
    if (!first) return;
    const anemo = this.element() === 'anemo';
    this.service.addReactionRow(first, anemo
      ? { reaction: 'swirl', swirled: 'pyro' }
      : { reaction: 'hyperbloom' });
  }

  protected pickReaction(row: TargetRow, value: string): void {
    const choice = REACTIONS.find((r) => r.value === value);
    if (!choice) return;
    const reaction: FormulaReaction = choice.value === 'swirl'
      ? { reaction: 'swirl', swirled: row.reaction?.swirled ?? 'pyro' }
      : { reaction: choice.value };
    this.service.updateRow(row.id, { reaction, label: reactionLabel(reaction) });
  }

  protected pickSwirled(row: TargetRow, value: string): void {
    if (!row.reaction || !(SWIRL_ELEMENTS as readonly string[]).includes(value)) return;
    const reaction: FormulaReaction = { ...row.reaction, swirled: value };
    this.service.updateRow(row.id, { reaction, label: reactionLabel(reaction) });
  }

  protected pickAdditive(row: TargetRow, value: string): void {
    this.service.updateRow(row.id, {
      additive: value in ADDITIVE ? value as Additive : null,
    });
  }

  // ── Weapon procs (owner approval 2026-11-14, §45) ────────────────────────────────────────

  protected procKey(proc: { source: string; key: string }): string {
    return `${proc.source}#${proc.key}`;
  }

  /** The panel's name for a proc: the weapon and the proc, so two weapons' procs differ. */
  protected procLabel(proc: ProcChoice): string {
    return proc.weapon ? `${proc.weapon}: ${proc.label}` : proc.label;
  }

  protected addProc(): void {
    const first = this.hits()[0];
    const proc = this.procs()[0];
    if (first && proc) this.service.addProcRow(first, proc);
  }

  protected pickProc(row: TargetRow, key: string): void {
    const proc = this.procs().find((p) => this.procKey(p) === key);
    if (!proc) return;
    this.service.updateRow(row.id, { proc: { source: proc.source, key: proc.key },
      label: proc.label });
  }

  protected remove(row: TargetRow): void {
    this.service.removeRow(row.id);
  }

  protected key(group: ConditionGroup, condition: FormulaCondition): string {
    return `${group.sourceId}/${condition.key}`;
  }

  protected valueOf(group: ConditionGroup, condition: FormulaCondition): ConditionValue {
    if (group.candidate) {
      return this.candidateState()[group.candidate.weaponId]?.[condition.key] ?? condition.default;
    }
    return this.teamState()[this.key(group, condition)] ?? condition.default;
  }

  /** Write one condition: the team's state, or a candidate weapon's own (§46). */
  private write(group: ConditionGroup, condition: FormulaCondition, value: ConditionValue): void {
    if (group.candidate) {
      this.service.setCandidateCondition(group.candidate.weaponId, condition.key, value);
    } else {
      this.service.setCondition(this.key(group, condition), value);
    }
  }

  protected isDefault(group: ConditionGroup, condition: FormulaCondition): boolean {
    return this.valueOf(group, condition) === condition.default;
  }

  protected defaultText(condition: FormulaCondition, group?: ConditionGroup): string {
    const shown = condition.kind === 'toggle'
      ? (condition.default ? 'on' : 'off')
      : condition.default === '' ? 'none' : String(condition.default);
    // A kit's own condition is triggered by the character, not by whoever wears a set.
    const who = group?.kind === 'kit' ? 'the character triggers it'
      : group?.kind === 'weapon' ? 'the wielder triggers it' : 'the wearer triggers it';
    return `Default ${shown} — ${defaultWhy(condition, who)}`;
  }

  protected stackChoices(condition: FormulaCondition): number[] {
    const max = condition.max ?? 0;
    return Array.from({ length: Math.max(max, 0) + 1 }, (_, i) => i);
  }

  protected setToggle(group: ConditionGroup, condition: FormulaCondition, on: boolean): void {
    this.write(group, condition, on ? 1 : 0);
  }

  protected setChoice(group: ConditionGroup, condition: FormulaCondition, raw: string): void {
    const value = condition.kind === 'choice' ? raw : Number(raw);
    this.write(group, condition, value);
  }

  protected setNumber(group: ConditionGroup, condition: FormulaCondition, box: HTMLInputElement): void {
    const value = Number(box.value);
    const max = condition.max ?? Infinity;
    if (box.value.trim() !== '' && Number.isFinite(value) && value >= 0 && value <= max) {
      this.write(group, condition, value);
    } else {
      box.value = String(this.valueOf(group, condition));
    }
  }

  protected reset(): void {
    this.service.resetConditions();
  }

  /** A row's override as the select reads it: `''` for "team setting". */
  protected overrideOf(row: TargetRow, group: ConditionGroup, condition: FormulaCondition): string {
    const value = row.overrides[this.key(group, condition)];
    return value === undefined ? '' : `v:${value}`;
  }

  /** The values one override select offers, as `[value, label]`. */
  protected overrideChoices(condition: FormulaCondition): [string, string][] {
    switch (condition.kind) {
      case 'toggle':
        return [['v:1', 'On'], ['v:0', 'Off']];
      case 'choice':
        return [['v:', 'None'], ...(condition.options ?? []).map(
          (o): [string, string] => [`v:${o}`, o],
        )];
      default:
        return this.stackChoices(condition).map((n): [string, string] => [`v:${n}`, String(n)]);
    }
  }

  protected setOverride(
    row: TargetRow, group: ConditionGroup, condition: FormulaCondition, raw: string,
  ): void {
    if (raw === '') {
      this.service.overrideRow(row.id, this.key(group, condition), undefined);
      return;
    }
    const text = raw.slice(2);
    const value = condition.kind === 'choice' ? text : Number(text);
    this.service.overrideRow(row.id, this.key(group, condition), value);
  }

  // ── Energy (math-fallback P3, task 14) ─────────────────────────────────────────────────

  protected setEnergyMode(value: string): void {
    if (ENERGY_MODES.some((m) => m.value === value)) {
      this.service.setEnergy({ mode: value as EnergyMode });
    }
  }

  /** A non-negative number from a box on `change`, or the box restored and `null`. */
  private numberFrom(box: HTMLInputElement, shown: number, positive = false): number | null {
    const value = Number(box.value);
    if (box.value.trim() !== '' && Number.isFinite(value) && (positive ? value > 0 : value >= 0)) {
      return value;
    }
    box.value = String(shown);
    return null;
  }

  protected setRotation(box: HTMLInputElement, shown: number): void {
    const value = this.numberFrom(box, shown, true);
    if (value !== null) this.service.setEnergy({ rotationSeconds: value });
  }

  protected resetRotation(): void {
    this.service.setEnergy({ rotationSeconds: null });
  }

  private patchMap(
    field: 'casts' | 'particles' | 'onField' | 'manual' | 'bursts' | 'favoniusHits'
      | 'refundCounts',
    key: string, value: number,
  ): void {
    const current: EnergySettings = this.service.energy();
    this.service.setEnergy({ [field]: { ...current[field], [key]: value } });
  }

  protected setCasts(buildId: string, box: HTMLInputElement, shown: number): void {
    const value = this.numberFrom(box, shown);
    if (value !== null) this.patchMap('casts', buildId, value);
  }

  protected setParticles(key: string, box: HTMLInputElement, shown: number): void {
    const value = this.numberFrom(box, shown);
    if (value !== null) this.patchMap('particles', key, value);
  }

  /** The on-field share is entered as a percent and kept as a fraction. */
  protected setOnField(key: string, box: HTMLInputElement, shown: number): void {
    const value = this.numberFrom(box, Math.round(shown * 100));
    if (value === null) return;
    if (value > 100) {
      box.value = String(Math.round(shown * 100));
      return;
    }
    this.patchMap('onField', key, value / 100);
  }

  protected setBursts(buildId: string, box: HTMLInputElement, shown: number): void {
    const value = this.numberFrom(box, shown);
    if (value !== null) this.patchMap('bursts', buildId, value);
  }

  protected setFavoniusHits(buildId: string, box: HTMLInputElement, shown: number): void {
    const value = this.numberFrom(box, shown);
    if (value !== null) this.patchMap('favoniusHits', buildId, value);
  }

  protected setRefundCount(key: string, box: HTMLInputElement, shown: number): void {
    const value = this.numberFrom(box, shown);
    if (value !== null) this.patchMap('refundCounts', key, value);
  }

  /** An `assumption` refund: counted only when the user accepts its stated assumption. */
  protected setRefundToggle(key: string, on: boolean): void {
    const current = this.service.energy();
    this.service.setEnergy({ refundToggles: { ...current.refundToggles, [key]: on } });
  }

  /** The element Venti's burst absorbed: an element, `none`, or `default` (gcsim's order). */
  protected setAbsorbed(key: string, value: string): void {
    const { [key]: _dropped, ...rest } = this.service.energy().absorbed;
    this.service.setEnergy({ absorbed: value === 'default' ? rest : { ...rest, [key]: value } });
  }

  protected setManual(buildId: string, box: HTMLInputElement, shown: number): void {
    const value = this.numberFrom(box, shown);
    if (value !== null) this.patchMap('manual', buildId, value);
  }

  /** `on`/`off` states it; `default` hands it back to the rows. */
  protected setSubjectOnField(value: string): void {
    this.service.setEnergy({ subjectOnField: value === 'default' ? null : value === 'on' });
  }

  protected setResonanceProcs(box: HTMLInputElement, shown: number): void {
    const value = this.numberFrom(box, shown);
    if (value !== null) this.service.setEnergy({ resonanceProcs: value });
  }

  protected resetResonanceProcs(): void {
    this.service.setEnergy({ resonanceProcs: null });
  }

  protected setFlatEnergy(box: HTMLInputElement, shown: number): void {
    const value = this.numberFrom(box, shown);
    if (value !== null) this.service.setEnergy({ flatEnergy: value });
  }

  /** Off, the waiting model has nothing to wait on, so it steps back to skip and says so. */
  protected setDrip(on: boolean): void {
    const mode = this.service.energy().mode;
    this.service.setEnergy({ drip: on, ...(on || mode !== 'wait' ? {} : { mode: 'skip' }) });
  }

  protected percent(value: number): string {
    return `${(value * 100).toFixed(1)}%`;
  }
}
