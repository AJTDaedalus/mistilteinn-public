import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { Emblem } from './emblem';

/**
 * The emblem is the brand mark, so what is tested is the properties that make it *usable as
 * one* — it scales, it names itself, and it takes its colour from tokens rather than baking
 * the palette in. Its exact geometry is a design choice and not a claim about the world.
 */
describe('Emblem', () => {
  function render(inputs: Partial<{ size: number; label: string }> = {}) {
    const fixture = TestBed.createComponent(Emblem);
    if (inputs.size !== undefined) fixture.componentRef.setInput('size', inputs.size);
    if (inputs.label !== undefined) fixture.componentRef.setInput('label', inputs.label);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('scales without redrawing — one viewBox, any size', () => {
    // A raster or a traced path would need a second asset for the favicon. Three ellipses
    // do not, which is half the reason the mark is geometry.
    const small = render({ size: 16 }).querySelector('svg');
    expect(small?.getAttribute('width')).toBe('16');
    expect(small?.getAttribute('viewBox')).toBe('0 0 64 64');

    const large = render({ size: 128 }).querySelector('svg');
    expect(large?.getAttribute('viewBox')).toBe('0 0 64 64');
  });

  it('announces itself to a screen reader by default', () => {
    const svg = render().querySelector('svg');
    expect(svg?.getAttribute('role')).toBe('img');
    expect(svg?.getAttribute('aria-label')).toBe('Mistilteinn');
  });

  it('can be silenced where a wordmark already says the name', () => {
    // In the shell the emblem sits next to the word "mistilteinn". Announcing it twice is
    // worse than not announcing it.
    const svg = render({ label: '' }).querySelector('svg');
    expect(svg?.getAttribute('aria-label')).toBe('');
  });

  it('takes every colour from a token, so the palette has one definition', () => {
    const html = render().innerHTML;
    expect(html).toContain('var(--brass)');
    // No literal colours: a hex here would be a second palette, drifting from _tokens.scss
    // the moment either changed — the same drift the note-format finding made concrete.
    expect(html).not.toMatch(/#[0-9a-fA-F]{3,6}\b/);
  });

  it('puts every node on an orbit tip rather than near one', () => {
    // The first draft eyeballed them and the mark read as beads scattered around an atom.
    // The six tips are the ellipses' major-axis endpoints at radius 25 from (32, 32), so
    // this checks the nodes against the geometry they are supposed to derive from.
    const svg = render().querySelector('svg')!;
    const tips = [0, 60, 120, 180, 240, 300].map((deg) => {
      const r = (deg * Math.PI) / 180;
      return [32 + 25 * Math.cos(r), 32 + 25 * Math.sin(r)];
    });

    const nodes = [...svg.querySelectorAll('.emblem__bead, .emblem__gem')].map((n) => [
      Number(n.getAttribute('cx')),
      Number(n.getAttribute('cy')),
    ]);

    expect(nodes).toHaveLength(6);
    for (const [cx, cy] of nodes) {
      const onATip = tips.some(([tx, ty]) => Math.hypot(tx - cx, ty - cy) < 0.2);
      expect(onATip, `node (${cx}, ${cy}) is not on an orbit tip`).toBe(true);
    }
  });

  it('draws the three orbits the reference has', () => {
    // Not a pixel assertion — a count. The mark *is* three crossing ellipses; a version with
    // two or four would be a different mark, and that should not happen by accident.
    expect(render().querySelectorAll('ellipse')).toHaveLength(3);
  });
});
