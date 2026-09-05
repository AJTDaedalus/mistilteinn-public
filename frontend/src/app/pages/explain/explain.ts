import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { apiErrorMessage } from '../../api/api-error';
import { ElementChip } from '../../shared/element/element';
import { CatalogueIcon } from '../../shared/icon/icon';
import { EntityToken } from '../../shared/token/token';
import { BuildsService, type BuildRead } from '../builds/builds.service';
import {
  ExplainService,
  type AvailableHit,
  type ExplainResponse,
} from './explain.service';

/** The seven visions plus physical — what a hit can land as. */
export const CHANNELS = [
  'physical', 'anemo', 'cryo', 'dendro', 'electro', 'geo', 'hydro', 'pyro',
] as const;

/** Which attack this is. Every stat read resolves under it, so it is not cosmetic. */
export const SCOPES = [
  'normal', 'charged', 'plunge', 'skill', 'burst', 'reaction', 'any_attack',
] as const;

/**
 * An API enum value as a label — `elemental_burst` → `Elemental burst`, `cryo` → `Cryo`.
 *
 * **The value itself is untouched**: these lists are the API's vocabulary and are posted back
 * verbatim, so only what the `<option>` prints changes. It was named `talentLabel` while doing
 * nothing talent-specific, which is why the Element and Scope selects beside the Hit picker
 * were the last controls in the app printing a raw enum on screen — "cryo", "any_attack" —
 * next to a picker that had read "Elemental burst" all along (#286).
 */
export function enumLabel(value: string): string {
  const words = value.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Why a build scores what it scores.
 *
 * **The derivation is the page, not the total.** `/builds/{id}/explain` returns every stat
 * with the parts that summed to it and where each came from, and until now nothing displayed
 * it — the damage chain has been correct and invisible since Chunk F. DESIGN §1 A6 makes a
 * number that can explain itself a product goal; this is where that becomes visible.
 *
 * **The multiplier is never typed here.** The talent is named and M.2 resolves it from the
 * build's own character at its own talent level. A number entered on this page would be a
 * second source for something the server already knows, and the one that drifted would be the
 * one on screen.
 */
@Component({
  selector: 'page-explain',
  imports: [FormsModule, RouterLink, DecimalPipe, CatalogueIcon, ElementChip, EntityToken],
  templateUrl: './explain.html',
  styleUrl: './explain.scss',
})
export class ExplainPage implements OnInit {
  protected readonly channels = CHANNELS;
  protected readonly scopes = SCOPES;
  protected readonly enumLabel = enumLabel;

  protected readonly loading = signal(true);
  /** Non-null means the page failed to load. Never rendered as "you have no builds". */
  protected readonly error = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);
  protected readonly scoring = signal(false);

  protected readonly builds = signal<BuildRead[]>([]);
  protected readonly hits = signal<AvailableHit[]>([]);
  protected readonly result = signal<ExplainResponse | null>(null);

  protected readonly buildId = signal('');
  /**
   * A **signal**, because the `hit` computed reads it.
   *
   * A plain field is invisible to a computed — Angular tracks signal reads — so changing the
   * hit left `hit()` on whatever it had cached, and the page scored the previous selection.
   */
  protected readonly hitIndex = signal(0);
  protected channel = 'physical';
  protected scope = 'normal';
  protected enemyLevel = 90;

  protected readonly build = computed(
    () => this.builds().find((b) => b.id === this.buildId()) ?? null,
  );
  protected readonly hit = computed(() => this.hits()[this.hitIndex()] ?? null);
  protected readonly canScore = computed(
    () => this.hit() !== null && !this.scoring(),
  );

  private readonly explainService = inject(ExplainService);
  private readonly buildsService = inject(BuildsService);

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const builds = await this.buildsService.list();
      this.builds.set(builds);
      if (builds.length > 0) await this.selectBuild(builds[0].id);
    } catch {
      // Surfaced, not swallowed: an empty list and a failed request look identical, and only
      // one of them means the account has no builds.
      this.error.set('Could not load your builds.');
      this.builds.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  /** Choosing a build reloads its hits — they are per character *and* per talent level. */
  protected async selectBuild(id: string): Promise<void> {
    this.buildId.set(id);
    this.hits.set([]);
    this.hitIndex.set(0);
    this.result.set(null);
    this.actionError.set(null);
    if (!id) return;
    try {
      const hits = await this.explainService.hits(id);
      this.hits.set(hits);
      // The element the character deals is the sensible default channel, and it is on the
      // row already — no second request, and no table of character-to-element here.
      const element = this.builds().find((b) => b.id === id)?.character?.element;
      if (element) {
        const guess = element.toLowerCase();
        if ((CHANNELS as readonly string[]).includes(guess)) this.channel = guess;
      }
    } catch (err) {
      this.actionError.set(apiErrorMessage(err));
    }
  }

  protected async score(): Promise<void> {
    const hit = this.hit();
    const id = this.buildId();
    if (!hit || !id) return;
    this.actionError.set(null);
    this.scoring.set(true);
    try {
      this.result.set(
        await this.explainService.explain(
          id,
          { talent: hit.talent, label: hit.label, index: hit.index },
          this.channel,
          this.scope,
          this.enemyLevel,
        ),
      );
    } catch (err) {
      // Verbatim. A build with no five pieces, an unresolvable talent — the API names which,
      // and anything this page substituted would be less useful.
      this.result.set(null);
      this.actionError.set(apiErrorMessage(err));
    } finally {
      this.scoring.set(false);
    }
  }
}
