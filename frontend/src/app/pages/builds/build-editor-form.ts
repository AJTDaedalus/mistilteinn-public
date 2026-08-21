import {
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';

import { DiscSlotPicker } from './disc-slot-picker';
import { WEnginePicker } from '../../shared/wengine-picker/wengine-picker';
import { AgentPicker } from '../../shared/agent-picker/agent-picker';
import {
  AgentSummary,
  BuildRead,
  BuildsService,
  DiscRead,
  DiscSetRead,
  WEngineSummary,
} from './builds.service';
import { agentIconUrl, wEngineIconUrl } from '../../shared/icon-url';

const SKILL_LABELS = ['Basic', 'Dodge', 'Special', 'Chain', 'Core'] as const;

@Component({
  selector: 'build-editor-form',
  standalone: true,
  imports: [RouterLink, DiscSlotPicker, WEnginePicker, AgentPicker],
  templateUrl: './build-editor-form.html',
  styleUrl: './build-editor-form.scss',
})

export class BuildEditorFormComponent {
  private svc = inject(BuildsService);

  // ---- inputs --------------------------------------------------------------
  build = input<BuildRead | null>(null);
  agents = input<AgentSummary[]>([]);
  wEngines = input<WEngineSummary[]>([]);
  discSets = input<DiscSetRead[]>([]);
  discs = input<DiscRead[]>([]);
  mode = input<'create' | 'edit'>('edit');
  disabled = input(false);

  // ---- outputs -------------------------------------------------------------
  saved = output<BuildRead>();
  equipped = output<{ slot: number; discId: string | null }>();
  errored = output<string>();

  // ---- constants -----------------------------------------------------------
  protected readonly skillLabels = SKILL_LABELS;
  protected readonly coreSkillLabels: Record<number, string> = {
    0: 'A', 1: 'B', 2: 'C', 3: 'D', 4: 'E', 5: 'F', 6: 'F+',
  };
  protected readonly slotNumbers = [1, 2, 3, 4, 5, 6] as const;

  // ---- form state ----------------------------------------------------------
  protected buildId = signal<string | null>(null);
  protected agentId = signal('');
  protected wEngineId = signal<string | null>(null);
  protected mindscape = signal(0);
  protected agentLevel = signal(60);
  protected wEngineLevel = signal(60);
  protected wEngineRefinement = signal(1);
  protected coreSkillLevel = signal(5);
  // #90 Track 2: a Level I-VI picker, not the interim checkbox. The per-level value
  // ramps now exist (agents.potential_params), so every level is a distinct number
  // rather than five states that do nothing -- which is exactly the condition the
  // checkbox was holding the place for.
  //
  // 0 = not unlocked; 1..6 = Level I..VI. Level I buys the kit variant and NO value
  // bonus, which is why it is a real selectable state and not a synonym for 0.
  protected potentialRank = signal(6);
  protected readonly potentialLevels = [
    { rank: 1, roman: 'I' },
    { rank: 2, roman: 'II' },
    { rank: 3, roman: 'III' },
    { rank: 4, roman: 'IV' },
    { rank: 5, roman: 'V' },
    { rank: 6, roman: 'VI' },
  ] as const;
  protected potentialLevelLabel = computed(() => {
    const rank = this.potentialRank();
    if (rank <= 0) return 'locked';
    return this.potentialLevels.find((l) => l.rank === rank)?.roman ?? '';
  });
  protected skillLevels = signal<number[]>([12, 12, 12, 12, 12]);

  protected saving = signal(false);
  protected error = signal<string | null>(null);

  // ---- derived -------------------------------------------------------------
  protected isCreate = computed(() => this.mode() === 'create');
  protected agent = computed(() =>
    this.agents().find((a) => a.id === this.agentId()) ?? null,
  );
  protected wEngine = computed(() =>
    this.wEngines().find((w) => w.id === this.wEngineId()) ?? null,
  );

  protected agentIconUrl = agentIconUrl;
  protected wEngineIconUrl = wEngineIconUrl;


  protected matchingWEngines = computed<WEngineSummary[]>(() => {
    const a = this.agent();
    if (!a) return [];
    return this.wEngines().filter((w) => w.specialty === a.specialty);
  });

  protected otherWEngines = computed<WEngineSummary[]>(() => {
    const a = this.agent();
    if (!a) return this.wEngines();
    return this.wEngines().filter((w) => w.specialty !== a.specialty);
  });


  private discSetName = computed(() => {
    const map = new Map<string, string>();
    for (const s of this.discSets()) map.set(s.id, s.name);
    return (id: string): string => map.get(id) ?? '—';
  });

  protected discInSlot(slot: number): DiscRead | null {
    const bid = this.buildId();
    if (!bid) return null;
    return (
      this.discs().find(
        (d) => d.build_id === bid && d.build_slot === slot,
      ) ?? null
    );
  }

  constructor() {
    effect(() => {
      const b = this.build();
      if (b) this.applyBuild(b);
    });
  }

  // ---- handlers ------------------------------------------------------------
  protected onNumberInput(
    target: 'mindscape' | 'agentLevel' | 'wEngineLevel' | 'wEngineRefinement' | 'coreSkillLevel',
    event: Event,
  ) {
    const raw = (event.target as HTMLInputElement).valueAsNumber;
    if (Number.isNaN(raw)) return;
    if (target === 'mindscape') {
      this.mindscape.set(Math.max(0, Math.min(6, raw)));
    } else if (target === 'agentLevel') {
      this.agentLevel.set(Math.max(1, Math.min(60, raw)));
    } else if (target === 'wEngineLevel') {
      this.wEngineLevel.set(Math.max(1, Math.min(60, raw)));
    } else if (target === 'wEngineRefinement') {
      this.wEngineRefinement.set(Math.max(1, Math.min(5, raw)));
    } else {
      this.coreSkillLevel.set(Math.max(0, Math.min(6, raw)));
    }
  }

  protected onPotentialSelect(event: Event) {
    const raw = parseInt((event.target as HTMLSelectElement).value, 10);
    if (!Number.isNaN(raw)) this.potentialRank.set(Math.max(0, Math.min(6, raw)));
  }

  protected onSkillInput(slot: number, event: Event) {
    const raw = (event.target as HTMLInputElement).valueAsNumber;
    if (!Number.isNaN(raw)) this.setSkillLevel(slot, raw);
  }

  protected setSkillLevel(slot: number, level: number) {
    const next = [...this.skillLevels()];
    next[slot] = Math.max(1, Math.min(12, level));
    this.skillLevels.set(next);
  }

  protected onAgentPick(value: string | null) {
    this.agentId.set(value ?? '');
  }

  protected onWEnginePick(value: string | null) {
    this.wEngineId.set(value);
  }

  protected async pickDisc(slot: number, discId: string | null) {
    let bid = this.buildId();
    if (!bid) {
      if (!this.agentId()) {
        this.error.set('Select an agent before equipping discs.');
        this.errored.emit('Select an agent before equipping discs.');
        return;
      }
      await this.save();
      bid = this.buildId();
      if (!bid) return;
    }
    try {
      await this.svc.equipDisc(bid, slot, discId);
      this.equipped.emit({ slot, discId });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this.error.set(msg);
      this.errored.emit(msg);
    }
  }

  // ---- save ----------------------------------------------------------------
  protected async save() {
    if (!this.agentId()) {
      this.error.set('Pick an agent before saving.');
      return;
    }
    this.error.set(null);
    this.saving.set(true);
    try {
      const payload = {
        agent_id: this.agentId(),
        w_engine_id: this.wEngineId(),
        w_engine_level: this.wEngineLevel(),
        w_engine_refinement: this.wEngineRefinement(),
        mindscape_level: this.mindscape(),
        core_skill_level: this.coreSkillLevel(),
        potential_rank: this.potentialRank(),
        agent_level: this.agentLevel(),
        skill_levels: this.skillLevels().join(','),
      };
      const id = this.buildId();
      if (id) {
        await this.svc.update(id, payload);
        const updated = await this.svc.get(id);
        this.saved.emit(updated);
      } else {
        const created = await this.svc.create(payload);
        this.buildId.set(created.id);
        this.saved.emit(created);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this.error.set(msg);
      this.errored.emit(msg);
    } finally {
      this.saving.set(false);
    }
  }

  // ---- helpers -------------------------------------------------------------
  private applyBuild(b: BuildRead) {
    this.buildId.set(b.id);
    this.agentId.set(b.agent_id);
    this.wEngineId.set(b.w_engine_id);
    this.wEngineLevel.set(b.w_engine_level ?? 60);
    this.wEngineRefinement.set(b.w_engine_refinement ?? 1);
    this.mindscape.set(b.mindscape_level);
    this.coreSkillLevel.set(b.core_skill_level ?? 5);
    // Defaults to the server default of 6 (Level VI), which is what fairy modelled
    // unconditionally before #90.
    this.potentialRank.set(b.potential_rank ?? 6);
    this.agentLevel.set(b.agent_level);
    const parsed = b.skill_levels.split(',').map((n) => parseInt(n, 10));
    if (parsed.length === 5 && parsed.every((n) => !Number.isNaN(n))) {
      this.skillLevels.set(parsed);
    }
  }
}
