import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GcsimBadge, type GcsimStatus } from './gcsim-badge';

const PIN = 'b107b5dc5cb88977bed5270e5d83e64934730d4d';

describe('GcsimBadge', () => {
  let fixture: ComponentFixture<GcsimBadge>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [GcsimBadge] }).compileComponents();
    fixture = TestBed.createComponent(GcsimBadge);
  });

  function render(gcsim: GcsimStatus | null) {
    fixture.componentRef.setInput('gcsim', gcsim);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('draws nothing for a character gcsim simulates fully', () => {
    const el = render({ status: 'full', key: 'nahida', pin: PIN, missing_actions: [], reason: null });
    expect(el.querySelector('.badge')).toBeNull();
  });

  it('draws nothing when no block was sent', () => {
    expect(render(null).querySelector('.badge')).toBeNull();
  });

  it('says No gcsim in words and carries gcsim\'s own refusal', () => {
    const reason = "gcsim has no character key for 'Kachina' (normalised 'kachina') at pin b107b5dc5cb8.";
    const el = render({ status: 'none', key: null, pin: PIN, missing_actions: [], reason });
    const badge = el.querySelector('.badge')!;

    expect(badge.textContent?.trim()).toBe('No gcsim');
    expect(badge.getAttribute('title')).toBe(reason);
    expect(badge.classList).toContain('badge--none');
    expect(badge.getAttribute('aria-label')).toContain(reason);
  });

  it('names the moves a partial character lacks, readably', () => {
    const el = render({
      status: 'partial', key: 'diluc', pin: PIN,
      missing_actions: ['charge', 'high_plunge', 'low_plunge'], reason: null,
    });
    const badge = el.querySelector('.badge')!;

    expect(badge.textContent?.trim()).toBe('Partial gcsim');
    expect(badge.getAttribute('title'))
      .toBe('gcsim does not implement: charge, high plunge, low plunge.');
    expect(badge.classList).not.toContain('badge--none');
  });

  it('marks a full character missing only plunges quietly, with the plunges in the tooltip', () => {
    // Owner, 2026-11-13: plunges do not make a character partial, but they are still listed.
    const el = render({
      status: 'full', key: 'jean', pin: PIN,
      missing_actions: ['high_plunge', 'low_plunge'], reason: null,
    });
    const badge = el.querySelector('.badge')!;

    expect(badge.textContent?.trim()).toBe('No plunge');
    expect(badge.classList).toContain('badge--quiet');
    expect(badge.getAttribute('title')).toContain('high plunge, low plunge');
    expect(badge.getAttribute('title')).toContain('Not partial');
  });
});
