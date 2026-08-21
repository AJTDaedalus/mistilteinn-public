import { Component, computed, inject, signal } from '@angular/core';

import { BuffContextStore, type CustomBuff } from '../buff-context.store';
import { BuffPresetsService, type BuffPresetRead } from '../buff-presets.service';
import { customBuffId, isUnaddressableLabel, slugify } from '../custom-buff-id';
import { formatStatValue, statMeta } from '../stat-meta';

/** One row of the editor: the buff plus everything the template needs pre-computed. */
interface BuffRow {
  index: number;
  buff: CustomBuff;
  /** `custom:<slug>` — how `disabled_buffs` addresses this buff. */
  id: string;
  /** In-game stat name ("Fire DMG %", "CRIT Rate"), never the field key. */
  statLabel: string;
  /** Percent for bp stats, raw units otherwise — what the number input shows. */
  inputValue: number;
  /** Whether the input is a percentage ("%" suffix) or a flat quantity. */
  isPercent: boolean;
  /** "+25.00%" / "+500" — the contribution as the calc will resolve it. */
  contribution: string;
  /** The single condition the editor exposes; `always` when the buff carries none. */
  condition: string;
  enabled: boolean;
  /** Non-null when this row cannot be sent as-is; the server would 422 on it. */
  problem: string | null;
}

interface StatOption {
  stat: string;
  label: string;
}

/**
 * Conditions a *stage* buff can sensibly carry.
 *
 * Deliberately not the engine's whole `Condition` vocabulary: nearly all of it describes
 * agent-kit states ("after using EX Special", "equipper is Attack"), which a Deadly
 * Assault or Shiyu stage effect is not. Offering those would invite a user to author a
 * buff gated on a state no stage grants, and it would never fire — the silent-no-op
 * failure this whole feature is built to avoid. The two here are encounter-level, which
 * is what a stage buff is.
 */
const CONDITION_OPTIONS: readonly { value: string; label: string }[] = [
  { value: 'always', label: 'Always' },
  { value: 'enemy_stunned', label: 'While the enemy is stunned' },
];

const DEFAULT_STAT = 'dmg_bonus';

/**
 * A new row is born with a usable name, not an empty one.
 *
 * The label is the buff's id, and the server rejects a label that slugifies to nothing —
 * so an empty new row would make *every* calculation 422 until the user got around to
 * naming it. Clicking "add" must never break the run in progress; the placeholder is
 * addressable from the first render and the user renames it whenever they like.
 */
function nextPlaceholderLabel(existing: readonly CustomBuff[]): string {
  // Compared by SLUG, not by label: the server rejects duplicates by slug, so a buff the
  // user renamed to "stage buff 2" already owns the id "Stage buff 2" would take. Exact-
  // label matching would hand out a name that 422s the very next calculation — the
  // failure this function exists to prevent, one case over.
  const taken = new Set(existing.map((b) => slugify(b.label)));
  for (let n = existing.length + 1; ; n++) {
    const candidate = `Stage buff ${n}`;
    if (!taken.has(slugify(candidate))) return candidate;
  }
}

/**
 * `target` reads as "who does this buff apply to", and the two options are labelled for
 * what the engine actually does with them (#64):
 *
 * - `"team"` — "Whole squad". Synthesized as a TEAM-target modifier held by one member;
 *   the simulator's merge hands it to whoever is acting, exactly once each.
 * - `"self"` — "DPS only", not "active agent only". It is held by the calculation's
 *   subject (the `"dps"` key / the build being optimized or ranked) and is not
 *   distributed, so it applies to that agent whether or not it happens to be on field.
 */
function blankBuff(stat: string, label: string): CustomBuff {
  return {
    label,
    stat,
    value: 0,
    target: 'team',
    conditions: ['always'],
    scopes: ['all'],
    max_stacks: 1,
  };
}

/**
 * Stage-buff editor + preset controls (#64, Tasks B8/B9).
 *
 * Deadly Assault and Shiyu stages grant squad-wide buffs that rotate with the patch
 * cycle. They belong to the *encounter*, not to a build, so they live on the
 * request-scoped `BuffContext` (DESIGN_buff_context.md §2.3) and this panel edits that
 * store directly — every calc surface reading the store picks the edit up with no
 * further wiring.
 *
 * Two properties the UI has to carry, because getting either wrong is invisible:
 *
 * - The stat picker is **served** (`/damage/custom-buff-stats`), not hardcoded, so it
 *   can only offer stats the buff resolver actually reads (Task B2).
 * - Applying a preset **copies** its buffs into this run (DESIGN §2.4). It is not a live
 *   reference, so editing the preset afterwards changes nothing already computed. The
 *   template says so where the button is, not in a tooltip.
 */
@Component({
  selector: 'app-stage-buffs-panel',
  standalone: true,
  templateUrl: './stage-buffs-panel.html',
  styleUrl: './stage-buffs-panel.scss',
})
export class StageBuffsPanelComponent {
  private readonly store = inject(BuffContextStore);
  private readonly presets = inject(BuffPresetsService);

  protected readonly CONDITION_OPTIONS = CONDITION_OPTIONS;

  protected readonly statOptions = signal<StatOption[]>([]);
  protected readonly presetList = signal<BuffPresetRead[]>([]);
  protected readonly selectedPresetId = signal<string>('');
  protected readonly newPresetName = signal<string>('');
  protected readonly error = signal<string | null>(null);
  protected readonly notice = signal<string | null>(null);
  protected readonly busy = signal(false);

  protected readonly rows = computed<BuffRow[]>(() => {
    const disabled = new Set(this.store.disabledBuffs());
    const seen = new Map<string, string>();
    return this.store.customBuffs().map((buff, index) => {
      const { unit } = statMeta(buff.stat);
      const isPercent = unit === 'bp';
      const id = customBuffId(buff.label);
      let problem: string | null = null;
      if (buff.label.trim() === '' || isUnaddressableLabel(buff.label)) {
        problem = 'Needs a name containing at least one letter or digit.';
      } else if (seen.has(id)) {
        problem = `Same id as "${seen.get(id)}" — give them distinguishable names.`;
      } else {
        seen.set(id, buff.label);
      }
      return {
        index,
        buff,
        id,
        statLabel: statMeta(buff.stat).label,
        inputValue: isPercent ? buff.value / 100 : buff.value,
        isPercent,
        contribution: formatStatValue(buff.stat, buff.value),
        condition: buff.conditions?.[0] ?? 'always',
        enabled: !disabled.has(id),
        problem,
      };
    });
  });

  protected readonly hasProblems = computed(() => this.rows().some((r) => r.problem !== null));

  /** Summary for a collapsed header: "3 stage buffs" / "No stage buffs". */
  protected readonly summary = computed(() => {
    const n = this.rows().length;
    if (n === 0) return 'No stage buffs';
    const active = this.rows().filter((r) => r.enabled).length;
    return active === n ? `${n} stage buff${n === 1 ? '' : 's'}` : `${active} of ${n} active`;
  });

  constructor() {
    void this.loadStatOptions();
    void this.loadPresets();
  }

  private async loadStatOptions(): Promise<void> {
    try {
      const stats = await this.presets.statOptions();
      this.statOptions.set(
        stats
          .map((stat) => ({ stat, label: statMeta(stat).label }))
          .sort((a, b) => a.label.localeCompare(b.label) || a.stat.localeCompare(b.stat)),
      );
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }

  private async loadPresets(): Promise<void> {
    try {
      this.presetList.set(await this.presets.list());
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }

  // ── editing ───────────────────────────────────────────────────────────────

  protected addBuff(): void {
    const first = this.statOptions()[0]?.stat ?? DEFAULT_STAT;
    this.store.addCustomBuff(blankBuff(first, nextPlaceholderLabel(this.store.customBuffs())));
  }

  protected removeBuff(index: number): void {
    this.store.removeCustomBuff(index);
  }

  protected setLabel(row: BuffRow, label: string): void {
    // Re-key `disabled_buffs` with the label: the id is derived from it, so a rename
    // would otherwise leave a switched-off buff switched on under its new name.
    const wasDisabled = !row.enabled;
    this.store.updateCustomBuff(row.index, { ...row.buff, label });
    if (wasDisabled) {
      this.store.toggleBuff(row.id, true);
      this.store.toggleBuff(customBuffId(label), false);
    }
  }

  protected setStat(row: BuffRow, stat: string): void {
    this.store.updateCustomBuff(row.index, { ...row.buff, stat });
  }

  /** `value` arrives in display units — percent for bp stats — and is stored as bp. */
  protected setValue(row: BuffRow, value: number): void {
    const bp = row.isPercent ? Math.round(value * 100) : Math.round(value);
    this.store.updateCustomBuff(row.index, { ...row.buff, value: bp });
  }

  protected setTarget(row: BuffRow, target: string): void {
    const next: CustomBuff['target'] = target === 'self' ? 'self' : 'team';
    this.store.updateCustomBuff(row.index, { ...row.buff, target: next });
  }

  protected setCondition(row: BuffRow, condition: string): void {
    this.store.updateCustomBuff(row.index, { ...row.buff, conditions: [condition] });
  }

  protected toggleEnabled(row: BuffRow, enabled: boolean): void {
    this.store.toggleBuff(row.id, enabled);
  }

  protected clearAll(): void {
    this.store.setCustomBuffs([]);
  }

  // ── presets ───────────────────────────────────────────────────────────────

  protected async applyPreset(): Promise<void> {
    const preset = this.presetList().find((p) => p.id === this.selectedPresetId());
    if (!preset) return;
    // Copy, not reference (DESIGN §2.4) — the run owns these buffs from here on.
    this.store.setCustomBuffs(preset.buffs);
    this.notice.set(`Copied ${preset.buffs.length} buff(s) from "${preset.name}" into this run.`);
  }

  protected async saveAsPreset(): Promise<void> {
    const name = this.newPresetName().trim();
    if (name === '') {
      this.error.set('Give the preset a name first.');
      return;
    }
    await this.run(async () => {
      const created = await this.presets.create(name, this.store.customBuffs());
      this.presetList.set([...this.presetList(), created].sort((a, b) => a.name.localeCompare(b.name)));
      this.selectedPresetId.set(created.id);
      this.newPresetName.set('');
      this.notice.set(`Saved "${created.name}".`);
    });
  }

  protected async updateSelectedPreset(): Promise<void> {
    const id = this.selectedPresetId();
    if (!id) return;
    await this.run(async () => {
      const updated = await this.presets.update(id, { buffs: this.store.customBuffs() });
      this.presetList.set(this.presetList().map((p) => (p.id === id ? updated : p)));
      this.notice.set(
        `Overwrote "${updated.name}" with this run's buffs. Results already calculated are unchanged.`,
      );
    });
  }

  protected async deleteSelectedPreset(): Promise<void> {
    const id = this.selectedPresetId();
    if (!id) return;
    await this.run(async () => {
      await this.presets.remove(id);
      this.presetList.set(this.presetList().filter((p) => p.id !== id));
      this.selectedPresetId.set('');
      this.notice.set('Preset deleted. The buffs stay in this run until you clear them.');
    });
  }

  /** Shared busy/error handling for the preset calls. */
  private async run(fn: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    this.notice.set(null);
    try {
      await fn();
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.busy.set(false);
    }
  }
}
