import { describe, expect, it } from 'vitest';

import { recall, recallAmong, remember } from './remembered';
import type { WebStorage } from '../../shared/browser-store';

/**
 * §15 — the page must not invent the user's data, and must not launder an invented default
 * through the memory either.
 */

function memory(over: Partial<WebStorage> = {}): WebStorage {
  const map = new Map<string, string>();
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
    get length() { return map.size; },
    key: (i) => [...map.keys()][i] ?? null,
    ...over,
  };
}

const BUILDS = [{ id: 'b1' }, { id: 'b2' }];

describe('remember / recall', () => {
  it('round-trips a selection', () => {
    const store = memory();
    remember(store, 'buildId', 'b2');

    expect(recall(store, 'buildId')).toBe('b2');
  });

  it('keeps the three fields apart', () => {
    const store = memory();
    remember(store, 'buildId', 'b1');
    remember(store, 'rotationId', 'r9');

    expect(recall(store, 'buildId')).toBe('b1');
    expect(recall(store, 'rotationId')).toBe('r9');
  });

  it('forgets rather than storing an empty selection', () => {
    const store = memory();
    remember(store, 'buildId', 'b1');
    remember(store, 'buildId', '');

    expect(recall(store, 'buildId')).toBe('');
  });

  it('is namespaced, so it cannot collide with the recipe cache', () => {
    const store = memory();
    remember(store, 'buildId', 'b1');

    expect(store.key(0)).toBe('mistilteinn:optimize:buildId');
  });

  it('survives a store that throws on write and on read', () => {
    // Blocked site data throws rather than returning null. A page that cannot remember is
    // not a page that should fail to open.
    const write = memory({ setItem: () => { throw new Error('QuotaExceeded'); } });
    const read = memory({ getItem: () => { throw new Error('SecurityError'); } });

    expect(() => remember(write, 'buildId', 'b1')).not.toThrow();
    expect(recall(read, 'buildId')).toBe('');
  });

  it('reads and writes nothing when there is no store', () => {
    expect(recall(null, 'buildId')).toBe('');
    expect(() => remember(null, 'buildId', 'b1')).not.toThrow();
  });
});

describe('recallAmong', () => {
  it('returns the remembered id when it is still there', () => {
    const store = memory();
    remember(store, 'buildId', 'b2');

    expect(recallAmong(store, 'buildId', BUILDS)).toBe('b2');
  });

  it('returns nothing for a build that has since been deleted', () => {
    // **Not `available[0]`.** Falling back to the first entry is exactly the invented default
    // §15 removes, and putting it here would hide it one layer from where anyone would look.
    const store = memory();
    remember(store, 'buildId', 'gone');

    expect(recallAmong(store, 'buildId', BUILDS)).toBe('');
  });

  it('returns nothing when nothing was ever remembered', () => {
    expect(recallAmong(memory(), 'buildId', BUILDS)).toBe('');
  });

  it('returns nothing when the list itself is empty', () => {
    const store = memory();
    remember(store, 'buildId', 'b1');

    expect(recallAmong(store, 'buildId', [])).toBe('');
  });
});
