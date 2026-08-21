import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { describe, it, expect, beforeEach } from 'vitest';

import { OptimizerBuildDetail } from './optimizer-build-detail';
import type { OptimizerDiscBuildSchema } from './optimizer.service';

function makeBuild(overrides: Partial<OptimizerDiscBuildSchema> = {}): OptimizerDiscBuildSchema {
  const discs = Array.from({ length: 6 }, (_, i) => ({
    disc_id: `disc-${i + 1}`,
    slot: i + 1,
    set_id: 31000,
    set_name: 'Woodpecker Electro',
    main_stat_type: i < 3 ? 'hp' : 'crit_rate',
    main_stat_value: i < 3 ? 10000 : 2400,
    rarity: 'S' as const,
    substats: [
      { stat_type: 'crit_dmg', value: 960, rolls: 2 },
      { stat_type: 'atk_pct', value: 300, rolls: 1 },
    ],
    score: null,
    icon_path: '',
  }));

  return {
    total_damage: 100000,
    disc_ids: discs.map((d) => d.disc_id),
    set_counts: { 31000: 6 },
    per_combo_damage: {},
    discs,
    total_stats: {
      hp: 10000,
      atk: 2000,
      defense: 800,
      crit_rate: 5000,
      crit_dmg: 10000,
      pen_flat: 36,
      pen_ratio: 0,
      anomaly_mastery: 0,
      anomaly_proficiency: 0,
      impact: 0,
      energy_regen: 0,
      physical_dmg: 0,
      fire_dmg: 0,
      ice_dmg: 0,
      electric_dmg: 0,
      ether_dmg: 0,
    },
    ...overrides,
  };
}

@Component({
  template: `<optimizer-build-detail [build]="build" />`,
  imports: [OptimizerBuildDetail],
  standalone: true,
})
class HostComponent {
  build = makeBuild();
}

describe('OptimizerBuildDetail', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [HostComponent] });
  });

  it('renders 6 disc slots', () => {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    const cards = fixture.nativeElement.querySelectorAll('.disc-card');
    expect(cards).toHaveLength(6);
  });

  it('each card shows the correct slot number in aria-label', () => {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    const summaries = fixture.nativeElement.querySelectorAll('.disc-card__summary');
    expect(summaries[0].getAttribute('aria-label')).toContain('Slot 1');
    expect(summaries[5].getAttribute('aria-label')).toContain('Slot 6');
  });

  it('substat list count matches input substats', () => {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    // Each disc has 2 substats; detail row is inside <details> (closed by default)
    // Open the first card
    const firstCard = fixture.nativeElement.querySelector('details.disc-card') as HTMLDetailsElement;
    firstCard.open = true;
    fixture.detectChanges();
    const substats = firstCard.querySelectorAll('.disc-card__substat');
    expect(substats).toHaveLength(2);
  });

  it('shows score as "—" when disc.score is null', () => {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    const firstCard = fixture.nativeElement.querySelector('details.disc-card') as HTMLDetailsElement;
    firstCard.open = true;
    fixture.detectChanges();
    const score = firstCard.querySelector('.disc-card__score .mono')!;
    expect(score.textContent?.trim()).toBe('—');
  });

  it('renders substat rollup strip', () => {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    const rollup = fixture.nativeElement.querySelector('.build-detail__rollup');
    expect(rollup).not.toBeNull();
    const chips = rollup.querySelectorAll('.roll-chip');
    expect(chips.length).toBeGreaterThan(0);
  });
});
