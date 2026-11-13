import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { App } from './app';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([])],
    }).compileComponents();
  });

  it('renders the brand wordmark', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.brand__wordmark')?.textContent).toContain('mistilteinn');
  });

  /**
   * AGPL §13 — the source offer is in the shell, so it is on every page and before sign-in.
   * The test renders signed out, which is the case a page-level link would miss.
   */
  it('offers the source code in the footer, signed in or not', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const link = el.querySelector<HTMLAnchorElement>('.shell__footer a.shell__source');
    expect(link?.getAttribute('href')).toBe('https://github.com/AJTDaedalus/mistilteinn-public');
    expect(link?.textContent).toContain('Source code (AGPL-3.0)');
    expect(link?.getAttribute('rel')).toContain('noopener');
  });
});
