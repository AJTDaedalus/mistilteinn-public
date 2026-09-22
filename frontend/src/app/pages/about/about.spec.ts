import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { AboutPage } from './about';

function open(): any {
  TestBed.configureTestingModule({});
  return TestBed.runInInjectionContext(() => new AboutPage()) as any;
}

describe('AboutPage', () => {
  it('points at the project Discord', () => {
    expect(open().discord).toBe('https://discord.gg/QAgVwnQHf');
  });

  describe('credits', () => {
    /**
     * gcsim ships in the browser build as WebAssembly under MIT and Go's `wasm_exec.js`
     * loads it under BSD-3-Clause. Both licences require their notice to travel with the
     * binary, so these two are **obligations, not thanks** — and this page is where a reader
     * is told the full text exists beside the artifacts.
     */
    it('carries the licences the build is obliged to name', () => {
      const credits = open().credits as { name: string; licence: string | null }[];
      const find = (name: string) => credits.find((c) => c.name === name)!;
      expect(find('gcsim').licence).toContain('MIT');
      expect(find('The Go authors').licence).toContain('BSD-3-Clause');
    });

    it('links every credit somewhere a reader can check', () => {
      for (const credit of open().credits) {
        expect(credit.url).toMatch(/^https:\/\//);
        expect(credit.body.length).toBeGreaterThan(40);
      }
    });

    it('names the two the owner called out first', () => {
      const names = open().credits.map((c: any) => c.name);
      expect(names[0]).toBe('gcsim');
      expect(names[1]).toBe('Genshin Optimizer');
    });

    it('credits every source the app actually ships data from', () => {
      const names = open().credits.map((c: any) => c.name);
      // Each of these is redistributed here, not merely consulted: catalogue rows and art,
      // cited recommendations, and the banner and income snapshots.
      for (const required of ['nanoka', 'KeqingMains', 'Genshin Impact Wiki']) {
        expect(names).toContain(required);
      }
    });

    /**
     * Owner, 2026-09-22: exclude YuanShen unless licensing requires it, and drop the two that
     * are observations rather than borrowed material. YuanShenResources declares **no
     * licence** — GitLab reports none, there is no LICENSE file, and its README carries a
     * disclaimer with no attribution condition — so nothing compels the credit. Pinned here
     * so a future edit re-adds it on purpose rather than by habit.
     */
    it('omits the ones the owner ruled out', () => {
      const names = open().credits.map((c: any) => c.name);
      for (const excluded of [
        'YuanShenResources', 'Fribbels Star Rail Optimizer', 'Community wish-rate research',
        'Genshin income bookkeeping',
      ]) {
        expect(names).not.toContain(excluded);
      }
    });

    it('has no duplicate entries', () => {
      const names = open().credits.map((c: any) => c.name);
      expect(new Set(names).size).toBe(names.length);
    });
  });
});
