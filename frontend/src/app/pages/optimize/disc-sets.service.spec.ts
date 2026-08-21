import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../api/api.client';
import { DiscSetsService, type DiscSetSummary } from './disc-sets.service';

const MOCK_SETS: DiscSetSummary[] = [
  { id: 's1', hakushin_id: 100, name: 'Chaotic Metal', two_piece_text: 'ATK', four_piece_text: 'DMG', icon_path: '' },
  { id: 's2', hakushin_id: 101, name: 'Hormone Punk', two_piece_text: 'ATK', four_piece_text: 'DMG', icon_path: '' },
];

function mockFetch(body: unknown, status = 200) {
  return vi.fn<typeof globalThis.fetch>(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  );
}

function setup() {
  TestBed.configureTestingModule({
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  return TestBed.inject(DiscSetsService);
}

describe('DiscSetsService', () => {
  it('listSets() fetches /api/v1/disc-sets', async () => {
    globalThis.fetch = mockFetch({ items: MOCK_SETS, total: 2 });
    const svc = setup();
    const result = await svc.listSets();
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe('Chaotic Metal');
  });

  it('listSets() returns cached result on second call', async () => {
    const fetchSpy = mockFetch({ items: MOCK_SETS, total: 2 });
    globalThis.fetch = fetchSpy;
    const svc = setup();
    await svc.listSets();
    await svc.listSets();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
