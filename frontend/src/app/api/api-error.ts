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
      return detail;
    }
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((d) =>
          d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : null,
        )
        .filter((m): m is string => !!m);
      if (msgs.length) {
        return msgs.join('; ');
      }
    }
  }
  return JSON.stringify(error);
}
