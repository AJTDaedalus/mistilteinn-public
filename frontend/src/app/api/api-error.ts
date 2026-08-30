/**
 * Turn anything a `catch` caught into a human-readable message.
 *
 * FastAPI sends `{ detail: "..." }` for HTTPException (401/404/429/…) and
 * `{ detail: [{ loc, msg, type }, …] }` for request-validation (422) errors.
 * Surfacing `detail` gives users a clean message — the active-job cap text on a 429 — instead
 * of a raw JSON blob.
 *
 * ## It is not only API errors, and that cost a real bug report
 *
 * **`JSON.stringify(new Error('boom'))` is `"{}"`.** An `Error`'s `message` and `name` are not
 * enumerable, so the fallback below rendered every thrown error as two braces. Callers catch
 * plenty of them: `search.ts` throws *"no candidates for Goblet; every slot needs at least
 * one"*, `gcsim-loader` throws when the wasm will not load, and the optimize page throws when
 * a set has no catalogue entry. Every one of those reached a user as `{}` — an error message
 * that is not merely unhelpful but actively looks like a different kind of failure.
 *
 * It was reported from production as *"an odd error that comes across as {}"*.
 *
 * The first fix for this was made at **one call site** in the rotation editor, which left the
 * other twenty-two. This is the one place that owes every caller an answer.
 */
export function apiErrorMessage(error: unknown): string {
  // An `Error` first: it is the commonest thing a `catch` holds and the one the fallback was
  // silently worst at.
  if (error instanceof Error) {
    return truncate(error.message || error.name || 'Error');
  }
  if (typeof error === 'string') return truncate(error);
  if (error === null || error === undefined) {
    // `JSON.stringify(undefined)` is the *value* `undefined`, so the old fallback returned
    // something that was not even a string.
    return 'Something went wrong, and nothing said what.';
  }
  if (error && typeof error === 'object' && 'detail' in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === 'string') {
      return truncate(detail);
    }
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((d) =>
          d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : null,
        )
        .filter((m): m is string => !!m);
      if (msgs.length) {
        return truncate(msgs.join('; '));
      }
    }
  }
  // A `message` on a plain object — what several browser APIs reject with, and what an
  // `Error` serialised across a worker boundary arrives as.
  if (typeof error === 'object' && 'message' in error) {
    const message = (error as { message: unknown }).message;
    if (typeof message === 'string' && message) return truncate(message);
  }
  const stringified = JSON.stringify(error);
  // `{}` is what an object with no enumerable properties gives, and it tells a user nothing.
  // Naming the shape at least says *where* to look.
  if (!stringified || stringified === '{}') {
    return 'Something went wrong, and the error carried no message.';
  }
  return truncate(stringified);
}

/** Longest message this will hand to the UI. */
const MAX_MESSAGE = 200;

/**
 * Bound what reaches a user's screen.
 *
 * The fallback above stringifies an unrecognised body, and an unrecognised body can be
 * enormous — a stack trace, a validation report over a large payload. The login page used to
 * carry this guard privately, next to a `detail` extractor that was subtly wrong; the
 * extractor is gone and the guard moved here, where every caller gets it rather than
 * whichever one happened to reimplement it.
 */
function truncate(message: string): string {
  return message.length <= MAX_MESSAGE ? message : `${message.slice(0, MAX_MESSAGE - 1)}…`;
}
