import { Component, computed, signal } from '@angular/core';

import { GCSIM_REPOSITORY, SOURCE_CODE, gcsimSourceUrl } from '../../shared/source';

/**
 * What this is, who made it, and whose work it is built on.
 *
 * **Reached from the footer, not the nav** (owner, 2026-09-22). The nav is for things you do;
 * this is read once.
 *
 * Several of the credits below are **licence obligations rather than courtesy**. The browser
 * build ships gcsim's WebAssembly under **AGPLv3** (with gcsim's MIT notice retained for the
 * code contributed before it relicensed) and Go's `wasm_exec.js` under BSD-3-Clause, and each
 * requires its notice to travel with the binary. `frontend/gcsim/*.LICENSE.txt` carries the
 * full text beside the artifacts; this page is where a reader is told they exist.
 *
 * **And it is where the source is offered** (AGPL §13), for this site and for the gcsim it
 * serves — at the exact commit of the binary served, read from `gcsim/BUILT_FROM`.
 */
@Component({
  selector: 'app-about',
  templateUrl: './about.html',
  styleUrl: './about.scss',
})
export class AboutPage {
  /** Where to talk to us. */
  protected readonly discord = 'https://discord.gg/QAgVwnQHf';

  /** This site's source and licence. The footer links the same constant. */
  protected readonly source = SOURCE_CODE;

  /** The commit the served `gcsim.wasm` was built from, once read; null until then or if absent. */
  protected readonly gcsimCommit = signal<string | null>(null);

  /** gcsim's source at that commit — or its repository, which is still an offer, if unread. */
  protected readonly gcsimSource = computed(() => gcsimSourceUrl(this.gcsimCommit()));

  constructor() {
    void this.readBuiltFrom();
  }

  /**
   * Read `gcsim/BUILT_FROM`, the provenance the build writes beside the wasm.
   *
   * **A failure leaves the link on the repository rather than hiding it.** The offer is the
   * obligation; the exact commit is the precision. An SPA catch-all answering a missing file
   * with `200 text/html` is exactly how this repo once served no art for weeks, so the body is
   * validated as a SHA rather than trusted because the status was 200.
   */
  async readBuiltFrom(fetcher: typeof fetch | undefined = globalThis.fetch): Promise<void> {
    try {
      if (!fetcher) return;
      const response = await fetcher('gcsim/BUILT_FROM');
      if (!response.ok) return;
      const text = (await response.text()).trim();
      if (/^[0-9a-f]{40}$/.test(text)) this.gcsimCommit.set(text);
    } catch {
      // Offline, or no build here: the repository link stands.
    }
  }

  /**
   * Everything this project is built on, and what each one gave it.
   *
   * `licence` is set where redistribution carries a condition — those are not optional and
   * the entry says so on the page rather than only in a text file nobody opens.
   */
  protected readonly credits = [
    {
      name: 'gcsim',
      url: GCSIM_REPOSITORY,
      // AGPLv3 since 2026-09-19, and pinned past that line since v2.50.0 (2026-11-13). The
      // MIT notice gcsim retains for earlier contributions is linked from the source section.
      licence: 'AGPL-3.0 · © 2021 The gcsim contributors',
      licenceUrl: '/gcsim/gcsim.LICENSE.txt',
      body:
        'Optimization of artifacts/weapons is built on top of GCsim’s engine. Their open ' +
        'source community is what makes optimization possible, and they are always looking ' +
        'for more hands if you want to contribute to improving simulation for Genshin Impact.',
    },
    {
      name: 'Genshin Optimizer',
      url: 'https://github.com/frzyc/genshin-optimizer',
      licence: null,
      licenceUrl: null,
      body:
        'GO was used as a baseline for what an optimizer should do, with some improvements ' +
        '(most notably the GCsim engine providing full rotation optimizations).',
    },
    {
      name: 'The Go authors',
      url: 'https://go.dev',
      licence: 'BSD-3-Clause · © 2009 The Go Authors',
      licenceUrl: '/gcsim/go.LICENSE.txt',
      body: 'Provides a WASM loader that is used to run gcsim.',
    },
    {
      name: 'nanoka',
      url: 'https://nanoka.cc',
      licence: null,
      licenceUrl: null,
      body: 'Primary source for game data and art displayed.',
    },
    {
      name: 'KeqingMains',
      url: 'https://keqingmains.com',
      licence: null,
      licenceUrl: null,
      body:
        'Source for weapon and artifact recommendations used to order build options.',
    },
    {
      name: 'Genshin Impact Wiki',
      url: 'https://genshin-impact.fandom.com',
      // Fandom is CC BY-SA **3.0**; a bare "CC BY-SA" reads as 4.0 today, which is a
      // different licence. The licence itself requires a link to its terms, so the tag
      // carries one — the other two tags point at the notices served beside the artifacts.
      licence: 'CC BY-SA 3.0',
      licenceUrl: 'https://creativecommons.org/licenses/by-sa/3.0/',
      body:
        'Source for banner information, gacha rates, and other game system specifics.',
    },
  ];
}
