import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { AboutPage } from './about';
import { SOURCE_CODE } from '../../shared/source';

function open(): any {
  TestBed.configureTestingModule({});
  return TestBed.runInInjectionContext(() => new AboutPage()) as any;
}

describe('AboutPage', () => {
  /**
   * **Shape, not the constant.** Asserting the literal restated line 21 of `about.ts` back at
   * itself: the only edit it could fail on was the deliberate one. It was also blind to the
   * failure that will actually happen — a Discord invite expiring — which no test can catch
   * offline, and which is why the link is a permanent invite rather than a temporary one.
   */
  it('points at a Discord invite', () => {
    expect(open().discord).toMatch(/^https:\/\/discord\.gg\/[A-Za-z0-9-]+$/);
  });

  describe('credits', () => {
    /**
     * gcsim ships in the browser build as WebAssembly under **AGPLv3** (pinned past its
     * relicence at v2.50.0, owner 2026-11-13) and Go's `wasm_exec.js` loads it under
     * BSD-3-Clause. Both licences require their notice to travel with the binary, so these two
     * are **obligations, not thanks** — and this page is where a reader is told the full text
     * exists beside the artifacts.
     */
    it('carries the licences the build is obliged to name', () => {
      const credits = open().credits as { name: string; licence: string | null }[];
      const find = (name: string) => credits.find((c) => c.name === name)!;
      expect(find('gcsim').licence).toContain('AGPL-3.0');
      expect(find('The Go authors').licence).toContain('BSD-3-Clause');
    });

    it('links every credit somewhere a reader can check', () => {
      for (const credit of open().credits) {
        expect(credit.url).toMatch(/^https:\/\//);
        expect(credit.body.length).toBeGreaterThan(20);
      }
    });

    /**
     * The licence tag is the compliance-bearing text on this page, so naming a licence
     * without a way to read it is the entry that undercuts the rest. gcsim's and Go's point
     * at the notices served beside the artifacts; the wiki's points at the CC deed, which
     * CC BY-SA itself requires.
     */
    it('makes every named licence reachable', () => {
      const credits = open().credits as { licence: string | null; licenceUrl: string | null }[];
      for (const credit of credits.filter((c) => c.licence)) {
        expect(credit.licenceUrl).toBeTruthy();
      }
    });

    it('names a licence version where the licence has them', () => {
      const credits = open().credits as { name: string; licence: string | null }[];
      // A bare "CC BY-SA" reads as 4.0 today; Fandom is 3.0, a different licence.
      const wiki = credits.find((c) => c.name === 'Genshin Impact Wiki')!;
      expect(wiki.licence).toBe('CC BY-SA 3.0');
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

  /**
   * AGPL §13: a network service offers its users the source. The page states both offers —
   * this site's and the gcsim it serves — and the gcsim one names the commit of the binary
   * actually served, read from the build's own provenance rather than restated.
   */
  describe('the source offer', () => {
    const SHA = 'b'.repeat(40);
    const respond = (body: string, ok = true) =>
      (async () => ({ ok, text: async () => body })) as unknown as typeof fetch;

    it('offers this site’s source, from the one constant the footer also uses', () => {
      expect(open().source).toBe(SOURCE_CODE);
      expect(SOURCE_CODE.url).toBe('https://github.com/AJTDaedalus/mistilteinn-public');
    });

    it('links gcsim at the exact commit the served wasm was built from', async () => {
      const page = open();
      await page.readBuiltFrom(respond(`${SHA}\n`));
      expect(page.gcsimCommit()).toBe(SHA);
      expect(page.gcsimSource()).toBe(`https://github.com/genshinsim/gcsim/tree/${SHA}`);
    });

    it('keeps offering the repository when the commit cannot be read', async () => {
      // The SPA catch-all answers a missing file with 200 and the index page. Trusting the
      // status would put HTML into a URL; the body is checked as a SHA instead.
      open(); // configures TestBed once; each page below is a fresh instance in it
      for (const fetcher of [respond('<!doctype html>'), respond(SHA, false), undefined]) {
        const page = TestBed.runInInjectionContext(() => new AboutPage()) as any;
        await page.readBuiltFrom(fetcher);
        expect(page.gcsimCommit()).toBeNull();
        expect(page.gcsimSource()).toBe('https://github.com/genshinsim/gcsim');
      }
    });

    it('survives a fetch that throws', async () => {
      const page = open();
      await page.readBuiltFrom((async () => { throw new Error('offline'); }) as unknown as typeof fetch);
      expect(page.gcsimSource()).toBe('https://github.com/genshinsim/gcsim');
    });
  });
});
