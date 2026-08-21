/**
 * The id a stage buff is known by — `custom:<slug of its label>` (#64, DESIGN §2.3).
 *
 * This is a deliberate second implementation of `backend/app/services/modifiers.py`'s
 * `slugify` / `custom_buff_label`, and the duplication is load-bearing rather than
 * accidental: `disabled_buffs` entries are composed **client-side** (the toggle lives in
 * the stage-buff editor), so the client has to be able to name a buff without a round
 * trip. The two copies are pinned to the same cases by `custom-buff-id.spec.ts` here and
 * `test_custom_buff_synthesis.py` on the backend — if this drifts, switching a stage
 * buff off silently stops working, which is the one thing a toggle may not do.
 *
 * `\p{L}\p{N}` is the JS spelling of Python's `str.isalnum()` for this purpose: both are
 * Unicode-aware, so "Étage 3" and "3" slug the same way in both languages.
 */
const ALPHANUMERIC = /[\p{L}\p{N}]/u;

export const CUSTOM_BUFF_PREFIX = 'custom:';

/** Lowercase, non-alphanumeric → underscore, collapsed and trimmed. */
export function slugify(label: string): string {
  const out: string[] = [];
  let lastUnderscore = true;
  for (const ch of label.toLowerCase()) {
    if (ALPHANUMERIC.test(ch)) {
      out.push(ch);
      lastUnderscore = false;
    } else if (!lastUnderscore) {
      out.push('_');
      lastUnderscore = true;
    }
  }
  return out.join('').replace(/^_+|_+$/g, '');
}

/** The `disabled_buffs` id for a stage buff with this label. */
export function customBuffId(label: string): string {
  return `${CUSTOM_BUFF_PREFIX}${slugify(label)}`;
}

/**
 * True when `label` has nothing to build a slug from, so its id would be the bare
 * prefix — the server rejects it with a 422, and the editor should say so first.
 */
export function isUnaddressableLabel(label: string): boolean {
  return slugify(label) === '';
}
