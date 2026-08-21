import {
  Component,
  computed,
  input,
  output,
  signal,
  viewChild,
  ElementRef,
} from '@angular/core';

import type { components } from '../../api/api.types';
import { wEngineIconUrl, specialtyIconUrl } from '../icon-url';

const SIGNATURE_MAP: Record<string, string> = {
  // S-Rank (Playable & Core Cast)
  alice: 'Practiced Perfection',
  caesar: 'Tusks of Fury',
  burnice: 'Flamemaker Shaker',
  ellen: 'Deep Sea Visitor',
  'zhu yuan': 'Riot Suppressor Mark VI',
  jane: 'Sharpened Stinger',
  miyabi: 'Hailstorm Shrine',
  grace: 'Fusion Compiler',
  rina: 'Weeping Cradle',
  lycaon: 'The Restrained',
  koleda: 'Hellfire Gears',
  nekomata: 'Steel Cushion',
  'soldier 11': 'The Brimstone',
  qingyi: 'Ice-Jade Teapot',
  lighter: 'Blazing Laurel',
  yanagi: 'Timeweaver',
  
  // S-Rank (Expanded, Custom & Faction Agents)
  aria: 'Angel in the Shell',
  'orphie & magus': 'Bellicose Blaze',
  'ye shunguang': 'Cloudcleave Radiance',
  seed: 'Cordis Germina',
  lucia: 'Dreamlit Hearth',
  vivian: 'Flight of Fancy',
  'astra yao': 'Elegant Vanity',
  yuzuha: 'Metanukimorphosis',
  zhao: 'Half-Sugar Bunny',
  evelyn: 'Heartstring Nocturne',
  hugo: 'Myriad Eclipse',
  'ju fufu': 'Roaring Fur-nace',
  trigger: 'Spectral Gaze',
  'soldier 0 - anby': 'Severed Innocence',
  pyrois: 'Sol Exuvia',
  dialyn: 'Yesterday Calls',
  promeia: 'Frostfall Sickle',
  'nangong yu': 'Neon Fantasies',
  banyue: 'Wrathful Vajra',

  // A-Rank (Playable & Core Cast)
  anby: 'Demara Battery Mark II',
  anton: 'Drill Rig - Red Axis',
  ben: 'Big Cylinder',
  billy: 'Starlight Engine Replica',
  corin: 'Housekeeper',
  lucy: 'Kaboom the Cannon',
  nicole: 'The Vault',
  piper: 'Roaring Ride',
  seth: 'Peacekeeper - Specialized',
  soukaku: 'Bashful Demon',
  sokyaku: 'Bashful Demon',
  
  // A-Rank (Expanded & Custom Agents)
  manato: "Grill O'Wisp",
  pulchra: 'Box Cutter',
  'pan yinhu': 'Tremor Trigram Vessel',
};

export type WEngineSummary = components['schemas']['WEngineSummary'];

@Component({
  selector: 'wengine-picker',
  standalone: true,
  imports: [],
  templateUrl: './wengine-picker.html',
  styleUrl: './wengine-picker.scss',
})
export class WEnginePicker {
  allWEngines = input<WEngineSummary[]>([]);
  selectedId = input<string | null>(null);
  agentName = input<string | null>(null);
  agentSpecialty = input<string | null>(null);
  disabled = input<boolean>(false);
  placeholder = input<string>('Select W-Engine…');

  selectedChange = output<string | null>();

  protected dialogRef = viewChild<ElementRef<HTMLDialogElement>>('pickerDialog');
  protected search = signal('');
  protected selectedSpecialty = signal<string | null>(null);
  protected activeRarities = signal<string[]>([]);

  protected readonly wEngineIcon = wEngineIconUrl;
  protected readonly specialtyIcon = specialtyIconUrl;

  protected selectedWEngine = computed(() => {
    return this.allWEngines().find((w) => w.id === this.selectedId()) ?? null;
  });

  protected specialties = ['attack', 'stun', 'anomaly', 'support', 'defense', 'rupture'] as const;
  protected rarities = ['S', 'A', 'B'] as const;

  protected filteredWEngines = computed(() => {
    const q = this.search().toLowerCase().trim();
    const spec = this.selectedSpecialty();
    const rars = this.activeRarities();

    let list = this.allWEngines();

    // 1. Text filter
    if (q) {
      list = list.filter((w) => w.name.toLowerCase().includes(q));
    }

    // 2. Specialty filter
    if (spec) {
      list = list.filter((w) => w.specialty.toLowerCase() === spec.toLowerCase());
    }

    // 3. Rarity filter
    if (rars.length > 0) {
      list = list.filter((w) => rars.includes(w.rarity));
    }

    // Sort: selected W-Engine first, then agent's signature W-Engine first, then matching specialty first, then rarity S -> A -> B, then alphabetical name
    const currentId = this.selectedId();
    const agentSpec = this.agentSpecialty()?.toLowerCase();
    const agentName = this.agentName();

    return [...list].sort((a, b) => {
      // Selected first
      if (a.id === currentId && b.id !== currentId) return -1;
      if (b.id === currentId && a.id !== currentId) return 1;

      // Signature first
      if (agentName) {
        const signatureName = SIGNATURE_MAP[agentName.toLowerCase().trim()];
        if (signatureName) {
          const aIsSig = a.name.toLowerCase() === signatureName.toLowerCase();
          const bIsSig = b.name.toLowerCase() === signatureName.toLowerCase();
          if (aIsSig && !bIsSig) return -1;
          if (bIsSig && !aIsSig) return 1;
        }
      }

      // Matching specialty first
      if (agentSpec) {
        const aMatches = a.specialty.toLowerCase() === agentSpec;
        const bMatches = b.specialty.toLowerCase() === agentSpec;
        if (aMatches && !bMatches) return -1;
        if (bMatches && !aMatches) return 1;
      }

      // Rarity sort (S -> A -> B)
      const rarityRank: Record<string, number> = { S: 3, A: 2, B: 1 };
      const aRank = rarityRank[a.rarity] ?? 0;
      const bRank = rarityRank[b.rarity] ?? 0;
      if (aRank !== bRank) return bRank - aRank;

      // Base ATK sort (descending)
      if (a.base_atk !== b.base_atk) return b.base_atk - a.base_atk;

      // Alphabetical name
      return a.name.localeCompare(b.name);
    });
  });

  protected isSignature(name: string): boolean {
    const agent = this.agentName();
    if (!agent) return false;
    const sig = SIGNATURE_MAP[agent.toLowerCase().trim()];
    return !!sig && name.toLowerCase() === sig.toLowerCase();
  }

  protected openDialog(): void {
    if (this.disabled()) return;

    // Set default specialty/class filter to the agent's specialty
    const spec = this.agentSpecialty();
    this.selectedSpecialty.set(spec ? spec.toLowerCase() : null);

    // Reset search and rarity filters
    this.search.set('');
    this.activeRarities.set([]);

    this.dialogRef()?.nativeElement.showModal();
  }

  protected closeDialog(): void {
    this.dialogRef()?.nativeElement.close();
  }

  protected selectWEngine(id: string | null): void {
    this.selectedChange.emit(id);
    this.closeDialog();
  }

  protected toggleSpecialty(spec: string): void {
    const current = this.selectedSpecialty();
    if (current === spec) {
      this.selectedSpecialty.set(null); // click again to clear
    } else {
      this.selectedSpecialty.set(spec);
    }
  }

  protected toggleRarity(rarity: string): void {
    const cur = this.activeRarities();
    const next = cur.includes(rarity) ? cur.filter((r) => r !== rarity) : [...cur, rarity];
    this.activeRarities.set(next);
  }

  protected isRaritySelected(rarity: string): boolean {
    return this.activeRarities().includes(rarity);
  }

  protected formatStatType(type: string | null | undefined): string {
    if (!type) return '';
    const map: Record<string, string> = {
      hp: 'HP',
      hp_pct: 'HP%',
      atk: 'ATK',
      atk_pct: 'ATK%',
      def: 'DEF',
      def_pct: 'DEF%',
      crit_rate: 'Crit Rate',
      crit_dmg: 'Crit DMG',
      pen_flat: 'PEN',
      pen_ratio: 'PEN Ratio',
      anomaly_mastery: 'Anomaly Mastery',
      anomaly_proficiency: 'Anomaly Proficiency',
      impact: 'Impact',
      energy_regen: 'Energy Regen',
    };
    return map[type.toLowerCase()] ?? type;
  }

  protected formatStatValue(type: string | null | undefined, val: number | null | undefined): string {
    if (!type || val === null || val === undefined) return '';
    const t = type.toLowerCase();
    if (t === 'anomaly_proficiency') {
      return String(val); // anomaly proficiency is flat
    }
    const isPct = t.endsWith('_pct') || t.includes('rate') || t.includes('dmg') || t.includes('ratio') || t.includes('regen') || t.includes('mastery') || t.includes('impact');
    if (isPct) {
      return `${val / 100}%`;
    }
    return String(val);
  }
}
