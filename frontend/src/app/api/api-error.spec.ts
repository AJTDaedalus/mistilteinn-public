import { describe, expect, it } from 'vitest';

import { apiErrorMessage } from './api-error';

describe('apiErrorMessage', () => {
  it('returns the string detail for HTTPException bodies (e.g. 429)', () => {
    const err = { detail: 'You already have 3 active jobs (max 3).' };
    expect(apiErrorMessage(err)).toBe('You already have 3 active jobs (max 3).');
  });

  it('joins msg fields from 422 validation detail arrays', () => {
    const err = {
      detail: [
        { loc: ['body', 'top_n'], msg: 'must be >= 1', type: 'value_error' },
        { loc: ['body', 'combo_id'], msg: 'field required', type: 'missing' },
      ],
    };
    expect(apiErrorMessage(err)).toBe('must be >= 1; field required');
  });

  it('falls back to a stringified body when there is no detail', () => {
    const err = { error: 'boom' };
    expect(apiErrorMessage(err)).toBe(JSON.stringify(err));
  });

  it('stringifies non-object errors', () => {
    expect(apiErrorMessage('nope')).toBe('"nope"');
  });

  it('bounds what reaches the screen', () => {
    // The fallback stringifies an unrecognised body, and those can be enormous. This guard
    // used to live privately on the login page, beside a `detail` extractor that was wrong;
    // it moved here so every caller gets it rather than whichever one reimplemented it.
    const huge = { detail: 'x'.repeat(500) };
    const message = apiErrorMessage(huge);

    expect(message.length).toBeLessThanOrEqual(200);
    expect(message.endsWith('…')).toBe(true);
  });

  it('leaves a short message exactly as sent', () => {
    expect(apiErrorMessage({ detail: 'Too many requests.' })).toBe('Too many requests.');
  });
});
