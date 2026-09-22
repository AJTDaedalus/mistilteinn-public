import { Component } from '@angular/core';

/**
 * What this is, who made it, and whose work it is built on.
 *
 * **Reached from the footer, not the nav** (owner, 2026-09-22). The nav is for things you do;
 * this is read once.
 *
 * Several of the credits below are **licence obligations rather than courtesy**. The browser
 * build ships gcsim's WebAssembly under MIT and Go's `wasm_exec.js` under BSD-3-Clause, and
 * both require their notice to travel with the binary. `frontend/gcsim/*.LICENSE.txt` carries
 * the full text beside the artifacts; this page is where a reader is told they exist.
 */
@Component({
  selector: 'app-about',
  templateUrl: './about.html',
  styleUrl: './about.scss',
})
export class AboutPage {
  /** Where to talk to us. */
  protected readonly discord = 'https://discord.gg/QAgVwnQHf';

  /**
   * Everything this project is built on, and what each one gave it.
   *
   * `licence` is set where redistribution carries a condition — those are not optional and
   * the entry says so on the page rather than only in a text file nobody opens.
   */
  protected readonly credits = [
    {
      name: 'gcsim',
      url: 'https://github.com/genshinsim/gcsim',
      licence: 'MIT · © 2021 genshinsim',
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
