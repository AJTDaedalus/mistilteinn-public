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
      body:
        'Optimization of artifacts/weapons is built on top of GCsim’s engine. Their open ' +
        'source community is what makes optimization possible, and they are always looking ' +
        'for more hands if you want to contribute to improving simulation for Genshin Impact.',
    },
    {
      name: 'Genshin Optimizer',
      url: 'https://github.com/frzyc/genshin-optimizer',
      licence: null,
      body:
        'GO was used as a baseline for what an optimizer should do, with some improvements ' +
        '(most notably the GCsim engine providing full rotation optimizations).',
    },
    {
      name: 'The Go authors',
      url: 'https://go.dev',
      licence: 'BSD-3-Clause · © 2009 The Go Authors',
      body:
        'gcsim runs in your browser as WebAssembly, and the loader that starts it, ' +
        'wasm_exec.js, comes from the Go project.',
    },
    {
      name: 'nanoka',
      url: 'https://nanoka.cc',
      licence: null,
      body:
        'Every character, weapon, artifact set and enemy in the catalogue is imported from ' +
        'nanoka’s data, and the artwork on those pages is served from their assets.',
    },
    {
      name: 'YuanShenResources',
      url: 'https://gitlab.com/Dimbreath/AnimeGameData',
      licence: null,
      body:
        'The game’s own tables, pinned to a commit and committed here as a snapshot: level ' +
        'growth curves, artifact main-stat pools and the substat value tables the optimizer ' +
        'depends on.',
    },
    {
      name: 'KeqingMains',
      url: 'https://keqingmains.com',
      licence: null,
      body:
        'Weapon and artifact-set recommendations for 102 characters, cited row by row, which ' +
        'is what lets a build page suggest anything at all.',
    },
    {
      name: 'Genshin Impact Wiki',
      url: 'https://genshin-impact.fandom.com',
      licence: 'CC BY-SA',
      body:
        'The wish planner’s banner history — 291 runs and what each featured — plus the ' +
        'starglitter quantities and the 4★ rates the refund is computed from.',
    },
    {
      name: 'Community wish-rate research',
      url: 'https://www.bilibili.com/video/BV19Y411W7W5',
      licence: null,
      body:
        'HoYoverse publishes the base and “including pity” rates but never the shape of the ' +
        'soft-pity ramp. The curves this planner uses are the community’s estimate over 9.45 ' +
        'million wishes, fitted to reproduce the published figures.',
    },
    {
      name: 'Genshin income bookkeeping',
      url: 'https://docs.google.com/spreadsheets/d/1l9HPu2cAzTckdXtr7u-7D8NSKzZNUqOuvbmxERFZ_6w',
      licence: null,
      body:
        'Primogem income per patch, maintained by sectoidfodder and contributors. It is where ' +
        'the planner’s F2P, Welkin and Battle Pass figures come from.',
    },
    {
      name: 'Fribbels Star Rail Optimizer',
      url: 'https://github.com/fribbels/hsr-optimizer',
      licence: null,
      body:
        'The wish planner is laid out after their Warp Planner, deliberately, so that anyone ' +
        'who has used that one already knows this one.',
    },
  ];
}
