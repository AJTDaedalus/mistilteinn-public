import {
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';

import { Combobox, ComboboxOption } from '../../shared/combobox/combobox';
import {
  AttackRead,
  ComboRead,
  ComboStep,
  CombosService,
} from './combos.service';

type HitMode = 'atomic' | 'sequential' | 'variant';

interface Move {
  /** Composite identifier — skill_key + name (+ variant_label for variant moves). */
  key: string;
  skill_key: string;
  name: string;
  hit_count: number;
  hit_mode: HitMode;
  /** Populated only when hit_mode === 'variant'. */
  variant_label?: string;
}

/** A team member that can own combo steps. Steps are tagged with ``buildId``. */
export interface ComboMemberRef {
  buildId: string;
  agentId: string;
  agentName: string;
}

@Component({
  selector: 'combo-builder',
  imports: [Combobox],
  templateUrl: './combo-builder.html',
  styleUrl: './combo-builder.scss',
})
export class ComboBuilder {
  private svc = inject(CombosService);

  /** Team that owns these combos. Null until the team is saved. */
  teamId = input<string | null>(null);
  /** Team members in slot order. Each step is owned by one member's build;
   *  the owner picker lists them by agent name. */
  members = input<ComboMemberRef[]>([]);

  protected combos = signal<ComboRead[]>([]);
  /** Each member's attacks, keyed by build_id — populated as members change. */
  protected attacksByBuildId = signal<Map<string, AttackRead[]>>(new Map());

  protected loading = signal(false);
  protected error = signal<string | null>(null);

  // ---- draft state ----
  // ``editingId`` null + ``editing`` true ⇒ creating a new combo
  // ``editingId`` non-null            ⇒ editing the combo with that id
  // both null/false                   ⇒ list view
  protected editing = signal(false);
  protected editingId = signal<string | null>(null);
  protected draftName = signal('');
  protected draftSteps = signal<ComboStep[]>([]);

  /** Build ID of the primary (slot 1) member — the default owner for new steps. */
  protected primaryBuildId = computed(() => this.members()[0]?.buildId ?? null);

  /** Flat lookup of every member's attacks by attack id (legacy attack_id steps). */
  protected attacksById = computed(() => {
    const map = new Map<string, AttackRead>();
    for (const list of this.attacksByBuildId().values()) {
      for (const a of list) map.set(a.id, a);
    }
    return map;
  });

  constructor() {
    effect(() => {
      const tid = this.teamId();
      if (tid) void this.refresh(tid);
    });
    effect(() => {
      void this.loadMemberAttacks(this.members());
    });
  }

  // ---- list / loaders ---------------------------------------------------
  protected async refresh(teamId: string) {
    this.loading.set(true);
    this.error.set(null);
    try {
      this.combos.set(await this.svc.listForTeam(teamId));
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }

  private async loadMemberAttacks(members: ComboMemberRef[]) {
    const map = new Map<string, AttackRead[]>();
    await Promise.all(
      members.map(async (m) => {
        if (!m.agentId) return;
        try {
          map.set(m.buildId, await this.svc.getAgentAttacks(m.agentId));
        } catch (e) {
          this.error.set(e instanceof Error ? e.message : String(e));
        }
      }),
    );
    this.attacksByBuildId.set(map);
  }

  // ---- owner resolution -------------------------------------------------
  /** Agent display name for an owner build id (empty when unknown). */
  protected memberName(buildId: string | undefined): string {
    if (!buildId) return '';
    return this.members().find((m) => m.buildId === buildId)?.agentName ?? '';
  }

  /** Resolve a step's stored ``agent_id`` to a real member build id, mapping
   *  legacy role strings ('dps'/'support1'/'support2') from older saved combos.
   *  Always re-derives from the live ``members()`` input — the single
   *  resolver behind both the owner picker's displayed value and the move
   *  list, so the two can never name different members. */
  protected ownerBuildId(agentId: string | undefined): string {
    const mems = this.members();
    if (!agentId || agentId === 'dps') return mems[0]?.buildId ?? '';
    if (agentId === 'support1') return mems[1]?.buildId ?? agentId;
    if (agentId === 'support2') return mems[2]?.buildId ?? agentId;
    return agentId;
  }

  /** True when this step is owned by a build that is no longer on the team.
   *
   *  Team membership is editable while combos exist and the edit is **live** —
   *  `team-editor`'s `removeMember` writes a signal, `comboMembers` is a computed
   *  off it, and it feeds our `members()` input, so a member can vanish mid-draft
   *  with no save in between. The owning step then carries a build id matching no
   *  member (issue #80).
   *
   *  Guarded on `mems.length` so this never fires during load, when `members()`
   *  is legitimately empty and every step would otherwise look orphaned.
   */
  protected isOrphanedStep(step: ComboStep): boolean {
    if (this.isMarkerStep(step)) return false;
    const mems = this.members();
    if (mems.length === 0) return false;
    const owner = this.ownerBuildId(step.agent_id);
    return !mems.some((m) => m.buildId === owner);
  }

  /** Steps that will be dropped by the next save, in draft order. */
  protected orphanedSteps = computed(() =>
    this.draftSteps().filter((s) => this.isOrphanedStep(s)),
  );

  protected getMovesForOwner(buildId: string | undefined): Move[] {
    const attacks = this.attacksByBuildId().get(this.ownerBuildId(buildId)) ?? [];
    const seen = new Map<string, Move>();
    for (const a of attacks) {
      const hitMode = (a.hit_mode ?? 'atomic') as HitMode;
      const variantLabel = a.variant_label ?? undefined;
      const key = hitMode === 'variant'
        ? `${a.skill_key}::${a.name}::${variantLabel}`
        : `${a.skill_key}::${a.name}`;
      const existing = seen.get(key);
      if (existing) {
        existing.hit_count += 1;
      } else {
        seen.set(key, {
          key,
          skill_key: a.skill_key,
          name: a.name,
          hit_count: 1,
          hit_mode: hitMode,
          variant_label: variantLabel,
        });
      }
    }
    return Array.from(seen.values());
  }

  protected getMoveOptionsForOwner(buildId: string | undefined): ComboboxOption[] {
    return this.getMovesForOwner(buildId).map((m) => {
      const value = m.hit_mode === 'variant' ? m.key : m.name;
      const modeHint = m.hit_mode === 'sequential' ? ' (sequential)' : '';
      const label = m.variant_label
        ? `${m.name} — ${m.variant_label}${modeHint}`
        : m.name + modeHint;
      return {
        value,
        label,
        detail: m.hit_count > 1
          ? `${m.skill_key} · ${m.hit_count} hits`
          : m.skill_key,
        group: m.skill_key,
      };
    });
  }

  // ---- draft lifecycle --------------------------------------------------
  protected startNew() {
    this.editing.set(true);
    this.editingId.set(null);
    this.draftName.set('');
    this.draftSteps.set([]);
  }

  protected startEdit(c: ComboRead) {
    this.editing.set(true);
    this.editingId.set(c.id);
    this.draftName.set(c.name);
    this.draftSteps.set(
      (c.sequence ?? []).map((s) => {
        const raw = s as Record<string, unknown>;
        const isMarker = !!raw['step_type'];
        return {
          label: String(raw['label'] ?? ''),
          // Normalise legacy role strings to a real member build id so the
          // owner picker shows the right member and re-save persists the id.
          agent_id: isMarker
            ? undefined
            : this.ownerBuildId(raw['agent_id'] ? String(raw['agent_id']) : undefined),
          step_type: raw['step_type'] ? String(raw['step_type']) : undefined,
          move_name: raw['move_name'] ? String(raw['move_name']) : undefined,
          attack_id: raw['attack_id'] ? String(raw['attack_id']) : undefined,
          variant_label: raw['variant_label'] ? String(raw['variant_label']) : undefined,
          single_tap: Boolean(raw['single_tap'] ?? false),
          cycle_position: raw['cycle_position'] != null ? Number(raw['cycle_position']) : undefined,
        };
      }),
    );
  }

  protected cancelDraft() {
    this.editing.set(false);
    this.editingId.set(null);
    this.draftSteps.set([]);
  }

  // ---- step manipulation ------------------------------------------------
  protected addStep() {
    const steps = this.draftSteps();
    this.draftSteps.set([
      ...steps,
      { label: '', agent_id: this.defaultOwnerForNextStep(steps) },
    ]);
  }

  /**
   * Owner to pre-select for a newly added step: the most recent non-marker
   * step's owner (so multi-hit sequences on one agent don't need re-picking),
   * falling back to the primary member for the first step.
   */
  private defaultOwnerForNextStep(steps: ComboStep[]): string {
    for (let i = steps.length - 1; i >= 0; i--) {
      const s = steps[i];
      if (!this.isMarkerStep(s) && s.agent_id) return s.agent_id;
    }
    return this.primaryBuildId() ?? '';
  }

  protected addStunTrigger() {
    this.draftSteps.set([
      ...this.draftSteps(),
      { label: 'Stun', step_type: 'stun_trigger' },
    ]);
  }

  protected addStunEnd() {
    this.draftSteps.set([
      ...this.draftSteps(),
      { label: 'Stun End', step_type: 'stun_end' },
    ]);
  }

  protected isMarkerStep(step: ComboStep): boolean {
    return step.step_type === 'stun_trigger' || step.step_type === 'stun_end';
  }

  protected removeStep(idx: number) {
    this.draftSteps.set(this.draftSteps().filter((_, i) => i !== idx));
  }

  /**
   * Set the move on a step by its move name. The label defaults to the
   * move name when the user hasn't typed one, so step rows stay readable.
   */
  protected updateStep(idx: number, moveName: string, label?: string, ownerId?: string) {
    const next = [...this.draftSteps()];
    const cur = next[idx]?.label ?? '';
    const aid = ownerId || next[idx]?.agent_id || this.primaryBuildId() || '';
    next[idx] = {
      agent_id: aid,
      move_name: moveName || undefined,
      attack_id: undefined,
      label: (label ?? cur) || moveName,
    };
    this.draftSteps.set(next);
  }

  protected updateStepAgent(idx: number, ownerId: string) {
    const next = [...this.draftSteps()];
    const cur = next[idx];
    if (!cur) return;
    next[idx] = {
      ...cur,
      agent_id: ownerId,
      move_name: undefined,
      attack_id: undefined,
      variant_label: undefined,
      single_tap: undefined,
      cycle_position: undefined,
      label: '',
    };
    this.draftSteps.set(next);
  }

  /** Return the combobox value that identifies this step in the picker. */
  protected stepMoveValue(step: ComboStep): string {
    if (step.move_name) {
      const moves = this.getMovesForOwner(step.agent_id);
      const move = moves.find(
        (m) =>
          m.name === step.move_name &&
          (m.variant_label ?? undefined) === (step.variant_label ?? undefined),
      );
      if (move) {
        // Variant moves use composite key; atomic/sequential use just the name.
        return move.hit_mode === 'variant' ? move.key : move.name;
      }
      return step.move_name;
    }
    if (step.attack_id) {
      const a = this.attacksById().get(step.attack_id);
      return a?.name ?? '';
    }
    return '';
  }

  protected moveStep(from: number, to: number) {
    const arr = [...this.draftSteps()];
    if (from < 0 || from >= arr.length) return;
    if (to < 0 || to >= arr.length) return;
    const [item] = arr.splice(from, 1);
    arr.splice(to, 0, item);
    this.draftSteps.set(arr);
  }

  // ---- save / delete ----------------------------------------------------
  protected async saveDraft() {
    const tid = this.teamId();
    if (!tid) return;
    const name = this.draftName().trim();
    // A step whose owner has left the team is dropped, not re-pointed (issue #80).
    // Re-pointing it at the primary — which is what the old `ownerBuildId` fallback
    // and the backend resolver both effectively did — keeps a `move_name` that
    // belongs to the removed agent and may not exist on the primary's kit at all.
    // Dropping happens here, at save, rather than the moment the member is removed:
    // `removeMember` is a single click with no undo, so an immediate drop would make
    // a misclick destroy steps irrecoverably. Until then they render as departing.
    const usableSteps = this.draftSteps().filter(
      (s) => s.move_name || s.attack_id || this.isMarkerStep(s),
    );
    const rawSteps = usableSteps.filter((s) => !this.isOrphanedStep(s));
    if (!name || rawSteps.length === 0) {
      // "no steps" and "every step was dropped" are different failures, and the
      // second one happens on a screen that is visibly showing steps. Reporting
      // it as the first tells the user something they can see is false.
      this.error.set(
        name && usableSteps.length > 0
          ? 'Every step belongs to a build that has left the team. Re-add the member, '
            + 'or pick a new owner for each step, to keep them.'
          : 'Combo needs a name and at least one step.',
      );
      return;
    }
    // Steps usually already carry the owning member's build id in agent_id,
    // but one loaded via startEdit() before members() had settled may still
    // hold a raw legacy role string ('dps'/'support1'/'support2') — resolve
    // through the same live ownerBuildId() used for display so a save never
    // re-persists an unresolved literal. Markers carry no owner.
    const primary = this.primaryBuildId() ?? undefined;
    const steps = rawSteps.map((s) => ({
      ...s,
      agent_id: this.isMarkerStep(s) ? undefined : (this.ownerBuildId(s.agent_id) || primary),
    }));
    this.error.set(null);
    try {
      const editId = this.editingId();
      if (editId) {
        await this.svc.update(editId, { name, sequence: steps });
      } else {
        await this.svc.create({ name, team_id: tid, sequence: steps });
      }
      this.cancelDraft();
      await this.refresh(tid);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }

  protected async removeCombo(id: string) {
    const tid = this.teamId();
    if (!tid) return;
    try {
      await this.svc.remove(id);
      await this.refresh(tid);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }

  // ---- template helpers -------------------------------------------------

  protected onPickMove(idx: number, value: string | null) {
    const step = this.draftSteps()[idx];
    const owner = step?.agent_id || this.primaryBuildId() || '';
    if (!value) { this.updateStep(idx, '', undefined, owner); return; }
    // Variant moves use composite key; atomic/sequential use move name.
    const moves = this.getMovesForOwner(owner);
    const move = moves.find((m) => m.key === value || m.name === value);
    if (!move) { this.updateStep(idx, value, undefined, owner); return; }
    this.updateStepFromMove(idx, move, owner);
  }

  protected updateStepFromMove(idx: number, move: Move, ownerId?: string) {
    const next = [...this.draftSteps()];
    const cur = next[idx]?.label ?? '';
    const label = cur || move.name;
    const aid = ownerId || next[idx]?.agent_id || this.primaryBuildId() || '';
    next[idx] = {
      agent_id: aid,
      move_name: move.name,
      attack_id: undefined,
      label,
      variant_label: move.variant_label ?? undefined,
      single_tap: move.hit_mode === 'sequential',
    };
    this.draftSteps.set(next);
  }

  protected onLabelInput(idx: number, event: Event) {
    const v = (event.target as HTMLInputElement).value;
    const cur = this.draftSteps()[idx];
    if (!cur) return;
    const next = [...this.draftSteps()];
    next[idx] = { ...cur, label: v };
    this.draftSteps.set(next);
  }

  protected onNameInput(event: Event) {
    this.draftName.set((event.target as HTMLInputElement).value);
  }
}
