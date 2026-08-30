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

  it('passes a thrown string through without quoting it', () => {
    // It used to come back as `"nope"` — JSON-quoted, because the fallback stringified
    // everything it did not recognise. A message is not a JSON document.
    expect(apiErrorMessage('nope')).toBe('nope');
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

describe('apiErrorMessage — things that are not API errors', () => {
  it('gives an Error its message rather than two braces', () => {
    // `JSON.stringify(new Error('boom'))` is `"{}"` — `message` and `name` are not enumerable.
    // Reported from production as "an odd error that comes across as {}".
    expect(apiErrorMessage(new Error('no candidates for Goblet'))).toBe(
      'no candidates for Goblet',
    );
  });

  it('falls back to the Error name when it carries no message', () => {
    expect(apiErrorMessage(new TypeError())).toBe('TypeError');
  });

  it('passes a thrown string straight through', () => {
    expect(apiErrorMessage('gcsim rejected the config')).toBe('gcsim rejected the config');
  });

  it('says something rather than "undefined" for a thrown nothing', () => {
    // `JSON.stringify(undefined)` is the *value* `undefined`, so the old fallback returned
    // something that was not even a string.
    expect(apiErrorMessage(undefined)).toContain('nothing said what');
    expect(apiErrorMessage(null)).toContain('nothing said what');
  });

  it('reads a message off a plain object', () => {
    // What several browser APIs reject with, and what an Error serialised across a worker
    // boundary arrives as.
    expect(apiErrorMessage({ message: 'QuotaExceededError' })).toBe('QuotaExceededError');
  });

  it('names the shape rather than printing an empty object', () => {
    expect(apiErrorMessage({})).toContain('carried no message');
  });

  it('still prefers FastAPI detail over anything else', () => {
    expect(apiErrorMessage({ detail: 'that team has no builds' }))
      .toBe('that team has no builds');
  });

  it('truncates a long Error message like any other', () => {
    expect(apiErrorMessage(new Error('x'.repeat(500)))).toHaveLength(200);
  });
});
