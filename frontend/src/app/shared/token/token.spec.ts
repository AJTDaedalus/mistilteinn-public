import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { EntityToken } from './token';

function render(icon: string | null, name: string, meta?: string | null) {
  TestBed.configureTestingModule({ imports: [EntityToken] });
  const fixture = TestBed.createComponent(EntityToken);
  fixture.componentRef.setInput('icon', icon);
  fixture.componentRef.setInput('name', name);
  if (meta !== undefined) fixture.componentRef.setInput('meta', meta);
  fixture.detectChanges();
  return fixture.nativeElement as HTMLElement;
}

describe('EntityToken', () => {
  it('shows the art beside the name', () => {
    const el = render('UI_AvatarIcon_Ayaka', 'Kamisato Ayaka');

    expect(el.querySelector('img')?.getAttribute('src')).toBe(
      '/icons/UI_AvatarIcon_Ayaka.webp',
    );
    expect(el.querySelector('.name')?.textContent?.trim()).toBe('Kamisato Ayaka');
  });

  it('degrades to the name alone when there is no art', () => {
    // Art is decoration; the name is the row. A build whose character has no icon must not
    // render as an empty slot.
    const el = render(null, 'Kamisato Ayaka');

    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('.name')?.textContent?.trim()).toBe('Kamisato Ayaka');
  });

  it('omits the meta line entirely when there is none', () => {
    // Rendering an empty `.meta` gives every token without one a phantom second row, so a
    // list mixing the two no longer aligns.
    expect(render(null, 'Ayaka', null).querySelector('.meta')).toBeNull();
  });

  it('renders the meta line when given one', () => {
    expect(render(null, 'Ayaka', 'C0 · Mistsplitter').querySelector('.meta')?.textContent)
      .toContain('Mistsplitter');
  });

  it('leaves the image alt empty, because the name is already text beside it', () => {
    // A screen reader reading "Kamisato Ayaka, Kamisato Ayaka" is worse than one reading it
    // once. The art is decorative here in the precise sense the spec means.
    expect(render('UI_AvatarIcon_Ayaka', 'Kamisato Ayaka').querySelector('img')
      ?.getAttribute('alt')).toBe('');
  });
});
