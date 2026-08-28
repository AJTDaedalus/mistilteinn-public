import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { CatalogueIcon } from './icon';

function render(icon: string | null) {
  TestBed.configureTestingModule({ imports: [CatalogueIcon] });
  const fixture = TestBed.createComponent(CatalogueIcon);
  fixture.componentRef.setInput('icon', icon);
  fixture.componentRef.setInput('alt', 'Kamisato Ayaka');
  fixture.detectChanges();
  return fixture;
}

describe('CatalogueIcon', () => {
  it('renders the vendored path for a basename', () => {
    // `characters.icon` is `UI_AvatarIcon_Ayaka`; `download_icons.py` writes
    // `public/icons/UI_AvatarIcon_Ayaka.webp`. The two must agree, and this is where.
    const img = render('UI_AvatarIcon_Ayaka').nativeElement.querySelector('img');

    expect(img.getAttribute('src')).toBe('/icons/UI_AvatarIcon_Ayaka.webp');
    expect(img.getAttribute('alt')).toBe('Kamisato Ayaka');
  });

  it('renders nothing at all for a row with no icon name', () => {
    // A null `icon` column is a seeding gap. Rendering a broken `<img>` for it would put a
    // browser's own error glyph in the row and look like a fetch that failed.
    expect(render(null).nativeElement.querySelector('img')).toBeNull();
  });

  it('hides itself when the image fails to load', () => {
    // Three of the 475 are genuinely not published upstream, and a fresh clone that has not
    // run the script has none of them. **Art is decoration; a name and a stat are the row.**
    const fixture = render('UI_RelicIcon_15012_3');
    const img = fixture.nativeElement.querySelector('img');

    img.dispatchEvent(new Event('error'));
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('img')).toBeNull();
  });

  it('tries again when the basename changes', () => {
    // `failed` used to latch for the component's lifetime. That was invisible while every
    // instance sat in a `@for` keyed to a fixed row, and became a real bug once long-lived
    // instances arrived whose `[icon]` changes — rotations' step art follows a `<select>`.
    // One step set to a character with no published art poisoned every character after it.
    const fixture = render('UI_RelicIcon_15012_3');
    fixture.nativeElement.querySelector('img').dispatchEvent(new Event('error'));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('img')).toBeNull();

    fixture.componentRef.setInput('icon', 'UI_AvatarIcon_Ayaka');
    fixture.detectChanges();

    const img = fixture.nativeElement.querySelector('img');
    expect(img).not.toBeNull();
    expect(img.getAttribute('src')).toBe('/icons/UI_AvatarIcon_Ayaka.webp');
  });

  it('stays hidden while the same failed basename is re-set', () => {
    // The reset keys on the value, not on every write: re-rendering with the same missing
    // icon must not re-request it on each change detection pass.
    const fixture = render('UI_RelicIcon_15012_3');
    fixture.nativeElement.querySelector('img').dispatchEvent(new Event('error'));
    fixture.detectChanges();

    fixture.componentRef.setInput('icon', 'UI_RelicIcon_15012_3');
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('img')).toBeNull();
  });

  it('is lazy, so a page of hundreds does not fetch hundreds at once', () => {
    const img = render('UI_AvatarIcon_Ayaka').nativeElement.querySelector('img');

    expect(img.getAttribute('loading')).toBe('lazy');
  });

  it('reserves its box, so a late image does not shift the row', () => {
    // Width and height on the element rather than in CSS alone: without them the row
    // reflows when each icon lands, and a list of 260 weapons jumps under the reader.
    const img = render('UI_AvatarIcon_Ayaka').nativeElement.querySelector('img');

    expect(img.getAttribute('width')).toBe('40');
    expect(img.getAttribute('height')).toBe('40');
  });
});
