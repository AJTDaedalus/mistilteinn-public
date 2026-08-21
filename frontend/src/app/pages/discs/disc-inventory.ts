import { Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { BuildsService, DiscRead, DiscSetRead } from '../builds/builds.service';
import { DiscList } from '../../shared/disc-list/disc-list';
import { DiscFilterState, defaultFilters } from '../../shared/disc-list/disc-filters';

@Component({
  selector: 'page-disc-inventory',
  standalone: true,
  imports: [DiscList],
  templateUrl: './disc-inventory.html',
  styleUrl: './disc-inventory.scss',
})
export class DiscInventoryPage implements OnInit {
  private svc = inject(BuildsService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  protected discs = signal<DiscRead[]>([]);
  protected discSets = signal<DiscSetRead[]>([]);
  protected loading = signal(true);
  protected error = signal<string | null>(null);

  protected filters = signal<DiscFilterState>(defaultFilters());

  async ngOnInit() {
    this.restoreFiltersFromUrl();
    try {
      const [discs, discSets] = await Promise.all([
        this.svc.listDiscs(),
        this.svc.listDiscSets(),
      ]);
      this.discs.set(discs);
      this.discSets.set(discSets);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }

  protected onFiltersChange(f: DiscFilterState): void {
    this.filters.set(f);
    this.pushFiltersToUrl(f);
  }

  private pushFiltersToUrl(f: DiscFilterState): void {
    const queryParams: Record<string, string | number | null> = {};
    if (f.slot) queryParams['slot'] = f.slot;
    if (f.mainStats.length) queryParams['main'] = f.mainStats.join(',');
    if (f.substats.length) queryParams['sub'] = f.substats.join(',');
    if (f.sets.length) queryParams['set'] = f.sets.join(',');
    // Always serialize rarity and minLevel so the empty/zero states are
    // distinguishable from "not set" and can be round-tripped through the URL.
    queryParams['rarity'] = f.rarities.length ? f.rarities.join(',') : '';
    queryParams['lvMin'] = f.minLevel;
    if (f.equipped !== 'all') queryParams['eq'] = f.equipped;
    if (f.sort !== 'level') queryParams['sort'] = f.sort;
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams,
      queryParamsHandling: 'replace',
      replaceUrl: true,
    });
  }

  private restoreFiltersFromUrl(): void {
    const p = this.route.snapshot.queryParamMap;
    const f: DiscFilterState = defaultFilters();
    if (p.has('slot')) f.slot = Number(p.get('slot')) || 0;
    if (p.has('main')) f.mainStats = (p.get('main') ?? '').split(',').filter(Boolean);
    if (p.has('sub')) f.substats = (p.get('sub') ?? '').split(',').filter(Boolean);
    if (p.has('set')) f.sets = (p.get('set') ?? '').split(',').filter(Boolean);
    if (p.has('rarity')) f.rarities = (p.get('rarity') ?? '').split(',').filter(Boolean);
    if (p.has('lvMin')) f.minLevel = Number(p.get('lvMin')) || 0;
    if (p.has('eq')) f.equipped = (p.get('eq') ?? 'all') as DiscFilterState['equipped'];
    if (p.has('sort')) f.sort = (p.get('sort') ?? 'level') as DiscFilterState['sort'];
    this.filters.set(f);
  }
}
