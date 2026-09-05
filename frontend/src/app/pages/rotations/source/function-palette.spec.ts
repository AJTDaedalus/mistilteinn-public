import { ComponentFixture, TestBed } from '@angular/core/testing';

import { FunctionPalette } from './function-palette';

describe('FunctionPalette', () => {
  let fixture: ComponentFixture<FunctionPalette>;

  function build(functions: { name: string; parameters: string[] }[]): void {
    fixture = TestBed.createComponent(FunctionPalette);
    fixture.componentRef.setInput('functions', functions);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [FunctionPalette] }).compileComponents();
  });

  it('shows nothing at all when the rotation declares no functions', () => {
    // Most rotations declare none, and a permanently empty panel is furniture.
    build([]);

    expect(fixture.nativeElement.querySelector('.palette')).toBeFalsy();
  });

  it('offers each declared function as a button', () => {
    build([{ name: 'opener', parameters: [] }, { name: 'combo', parameters: ['n'] }]);

    const labels = Array.from(
      fixture.nativeElement.querySelectorAll('.palette__call'),
    ).map((b) => (b as HTMLElement).textContent?.trim());
    expect(labels).toEqual(['opener()', 'combo(n)']);
  });

  it('uses the parameter name as the placeholder, not a number', () => {
    // A `0` would look like an answer. The name says what the call still needs, and a call
    // with the wrong arity is refused by the validator with the arity named.
    build([{ name: 'cancel', parameters: ['travel_frames'] }]);

    expect(fixture.nativeElement.textContent).toContain('cancel(travel_frames)');
  });

  it('emits a complete statement, so what is drawn is what gcsim reads', () => {
    build([{ name: 'opener', parameters: [] }]);
    const drawn: string[] = [];
    fixture.componentInstance.called.subscribe((call) => drawn.push(call));

    fixture.nativeElement.querySelector('.palette__call').click();

    expect(drawn).toEqual(['opener();']);
  });
});
