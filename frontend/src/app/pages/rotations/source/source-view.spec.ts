import { ComponentFixture, TestBed } from '@angular/core/testing';

import type { RotationSourceRead } from '../rotations.service';
import { RotationsService } from '../rotations.service';
import { SourceView } from './source-view';

function read(over: Partial<RotationSourceRead> = {}): RotationSourceRead {
  return {
    tree: { nodes: [] },
    diagnostics: [],
    source: '',
    editable_in_builder: true,
    ...over,
  } as RotationSourceRead;
}

describe('SourceView', () => {
  let fixture: ComponentFixture<SourceView>;
  let validate: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    validate = vi.fn().mockResolvedValue(read());
    await TestBed.configureTestingModule({
      imports: [SourceView],
      providers: [{ provide: RotationsService, useValue: { validateSource: validate } }],
    }).compileComponents();
    fixture = TestBed.createComponent(SourceView);
    fixture.componentRef.setInput('teamId', 'team-1');
    fixture.componentRef.setInput('source', 'noelle skill;');
    fixture.detectChanges();
  });

  /**
   * Let the debounce fire and the request settle.
   *
   * **Real timers, not `fakeAsync`.** This app is zoneless, so `zone-testing` is absent and
   * `fakeAsync` throws; and the component awaits a promise inside its timeout, which fake
   * timers alone would not flush.
   */
  async function settle(ms = 350): Promise<void> {
    await new Promise((r) => setTimeout(r, ms));
    await Promise.resolve();
    fixture.detectChanges();
  }

  function type(value: string): void {
    const area: HTMLTextAreaElement =
      fixture.nativeElement.querySelector('.source__editor');
    area.value = value;
    area.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  it('shows the source it was given', () => {
    const area: HTMLTextAreaElement =
      fixture.nativeElement.querySelector('.source__editor');

    expect(area.value).toContain('noelle skill;');
  });

  it('does not send a request per keystroke', async () => {
    // The parser is Python, so a keystroke costs a round trip. Debounced deliberately.
    type('n');
    type('no');
    type('noe');
    await settle();

    expect(validate).toHaveBeenCalledTimes(1);
  });

  it('emits a tree once the source parses', async () => {
    const trees: unknown[] = [];
    fixture.componentInstance.parsed.subscribe((t) => trees.push(t));
    validate.mockResolvedValue(read({ tree: { nodes: [{ kind: 'action' }] } } as never));

    type('noelle burst;');
    await settle();

    expect(trees.length).toBe(1);
  });

  it('holds unparseable text as a draft and emits nothing', async () => {
    // **The failure this must not have.** Losing a rotation because the user was mid-word.
    const trees: unknown[] = [];
    fixture.componentInstance.parsed.subscribe((t) => trees.push(t));
    validate.mockResolvedValue(read({
      diagnostics: [{ severity: 'error', message: 'nope', line: 1, column: 1, length: 1, path: [] }],
    } as never));

    type('if .x.burst.rea');
    await settle();
    fixture.detectChanges();

    expect(trees.length).toBe(0);
    expect(fixture.nativeElement.textContent).toContain('draft');
  });

  it('shows an error with its position', async () => {
    validate.mockResolvedValue(read({
      diagnostics: [
        { severity: 'error', message: 'nothing defines `f`', line: 4, column: 2, length: 1, path: [] },
      ],
    } as never));

    type('f();');
    await settle();
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent;
    expect(text).toContain('nothing defines');
    expect(text).toContain('4:2');
  });

  it('separates a warning from an error', async () => {
    validate.mockResolvedValue(read({
      diagnostics: [
        { severity: 'warning', message: 'carried as written', line: 2, column: 1, length: 1, path: [] },
      ],
    } as never));

    type('999;');
    await settle();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.source__item--warning')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('.source__item--error')).toBeFalsy();
  });

  it('ignores an answer that arrived after the text moved on', async () => {
    // Applying a stale response would show diagnostics for text the user has already
    // changed, which reads as the editor being wrong rather than late.
    const resolvers: ((value: RotationSourceRead) => void)[] = [];
    validate.mockImplementation(
      () => new Promise<RotationSourceRead>((r) => { resolvers.push(r); }),
    );

    type('first');
    await settle();
    type('second');
    await settle();

    // The first request answers last, and it is about text that is no longer on screen.
    resolvers[0](read({
      diagnostics: [
        { severity: 'error', message: 'stale', line: 1, column: 1, length: 1, path: [] },
      ],
    } as never));
    await settle(10);

    expect(fixture.nativeElement.textContent).not.toContain('stale');
  });

  it('offers a declared function as a button and draws a call', async () => {
    // Owner's split: authoring an `fn` stays text, calling one is a click.
    validate.mockResolvedValue(read({
      functions: [{ name: 'opener', parameters: [] }],
    } as never));

    type('fn opener() {\n  a skill;\n}');
    await settle();

    const button: HTMLElement = fixture.nativeElement.querySelector('.palette__call');
    expect(button).toBeTruthy();
    button.click();
    fixture.detectChanges();

    const area: HTMLTextAreaElement =
      fixture.nativeElement.querySelector('.source__editor');
    expect(area.value).toContain('opener();');
  });

  it('says why the source view is the only way in, when it is', () => {
    fixture.componentRef.setInput('required', true);
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('user-defined function');
  });
});
