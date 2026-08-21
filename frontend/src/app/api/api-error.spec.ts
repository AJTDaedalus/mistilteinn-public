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
});
