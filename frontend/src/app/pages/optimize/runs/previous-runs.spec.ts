import { ComponentFixture, TestBed } from '@angular/core/testing';

import type { OptimizationRunSummary } from './optimization-runs.service';
import { OptimizationRunsService } from './optimization-runs.service';
import { PreviousRuns } from './previous-runs';

const row = (over: Partial<OptimizationRunSummary> = {}): OptimizationRunSummary => ({
  id: 'r1', name: 'Skirk melt', visibility: 'private', share_key: null,
  score: 1_376_712.1, margin: 0.031, iterations: 100,
  character_id: 'c1', rotation_id: null, created_at: '2026-09-03T00:00:00Z',
  summary: { energy_model: 'waiting' },
  ...over,
} as OptimizationRunSummary);

describe('PreviousRuns', () => {
  let fixture: ComponentFixture<PreviousRuns>;
  let mine: ReturnType<typeof vi.fn>;
  let published: ReturnType<typeof vi.fn>;

  async function build(characterId: string | null = null): Promise<void> {
    fixture = TestBed.createComponent(PreviousRuns);
    fixture.componentRef.setInput('characterId', characterId);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  beforeEach(async () => {
    mine = vi.fn().mockResolvedValue([row()]);
    published = vi.fn().mockResolvedValue([]);
    await TestBed.configureTestingModule({
      imports: [PreviousRuns],
      providers: [{ provide: OptimizationRunsService, useValue: { mine, published } }],
    }).compileComponents();
  });

  it('lists saved runs on arrival, before anything is started', async () => {
    // The owner's stated first impression of the page.
    await build();

    expect(mine).toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('Skirk melt');
  });

  it('formats a score for reading rather than comparing', async () => {
    await build();

    expect(fixture.nativeElement.textContent).toContain('1,376,712');
  });

  it('shows how far ahead of the runner-up it was', async () => {
    // "It won by 0.3%" and "by 12%" are different claims, and a reader deciding whether to
    // refarm needs the second one.
    await build();

    expect(fixture.nativeElement.textContent).toContain('+3.1%');
  });

  it('shows no margin when there was no runner-up to be ahead of', async () => {
    mine.mockResolvedValue([row({ margin: null })]);
    await build();

    expect(fixture.nativeElement.textContent).not.toContain('+');
  });

  it('says which energy model the run used', async () => {
    await build();

    expect(fixture.nativeElement.textContent).toContain('waiting');
  });

  it('switches to shared runs', async () => {
    await build();
    fixture.nativeElement.querySelectorAll('.runs__tab')[1].click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(published).toHaveBeenCalled();
  });

  it('opens a run when its row is clicked', async () => {
    await build();
    const opened: string[] = [];
    fixture.componentInstance.opened.subscribe((id) => opened.push(id));

    fixture.nativeElement.querySelector('.runs__open').click();

    expect(opened).toEqual(['r1']);
  });

  it('offers a per-character filter only when the page knows the character', async () => {
    await build(null);
    expect(fixture.nativeElement.querySelector('.runs__filter')).toBeFalsy();

    await build('c1');
    expect(fixture.nativeElement.querySelector('.runs__filter')).toBeTruthy();
  });

  it('narrows to one character when asked', async () => {
    await build('c1');
    fixture.nativeElement.querySelector('.runs__filter input').click();
    await fixture.whenStable();

    expect(mine).toHaveBeenLastCalledWith({ character_id: 'c1' });
  });

  it('says so when there is nothing saved yet', async () => {
    mine.mockResolvedValue([]);
    await build();

    expect(fixture.nativeElement.textContent).toContain('No saved runs yet');
  });

  it('a failed list does not stop a new search', async () => {
    // This panel sits above the optimizer. A dead list that blocked the page would turn a
    // convenience into an outage.
    mine.mockRejectedValue(new Error('nope'));
    await build();

    expect(fixture.nativeElement.textContent).toContain('still start a new search');
  });
});
