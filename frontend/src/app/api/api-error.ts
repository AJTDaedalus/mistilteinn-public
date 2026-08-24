/**
 * Turn an openapi-fetch `error` body into a human-readable message.
 *
 * FastAPI sends `{ detail: "..." }` for HTTPException (401/404/429/…) and
 * `{ detail: [{ loc, msg, type }, …] }` for request-validation (422) errors.
 * Surfacing `detail` gives users a clean message (e.g. the active-job cap
 * text on a 429) instead of a raw JSON blob. Falls back to a stringified
 * body for anything unexpected.
 */
export function apiErrorMessage(error: unknown): string {
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
  return truncate(JSON.stringify(error));
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
