/**
 * What the user picked last, so the page can open where they left it.
 *
 * The rule this implements (owner, `BACKLOG_optimize.md` §15): *"Providing defaults is almost
 * never going to be useful. If anything remember what the user did last and keep it there,
 * but filling something ourselves is useless."*
 *
 * The page used to select the first build and the first rotation in the list — which is how
 * it opened on Aino, who is simply first alphabetically. A populated field reads as a choice
 * somebody made, so inventing one states something false about the user. Recalling their last
 * selection states something true; recalling nothing leaves the field empty, which is also
 * true.
 *
 * **A recalled id is a suggestion, never a fact.** It can name a build that has since been
 * deleted, or one belonging to a different account on a shared browser, so every caller
 * checks it against the list it actually loaded — see `recallAmong`.
 */

import { browserStore, type WebStorage } from '../../shared/browser-store';

const PREFIX = 'mistilteinn:optimize:';

/** The selections worth remembering. Data the user chose — never which tool is in front. */
export type Remembered = 'buildId' | 'teamId' | 'rotationId';

/**
 * The search settings worth restoring, as one blob.
 *
 * Owner: *"it would be nice if the optimize tab remembered the last selected options, both for
 * a user — 'what did I have open last time I did an optimization' — and for a character —
 * 'when I last optimized this character, what did I have selected?'"*
 *
 * Both, because they answer different questions. Reopening the page should look like you left
 * it; picking a character you tuned last week should bring back what you chose *for them*, not
 * what you happened to be doing five minutes ago on someone else.
 */
export interface Selections {
  /** `hit` or `rotation`. */
  objective: string;
  /** Catalogue ids of the 4-piece sets to search. */
  sets: number[];
  /** The 2+2 pair, or null. */
  pair: [number, number] | null;
  /** `{slot: [main stat keys]}` — the main-stat filter. */
  mainStats: Record<string, string[]>;
}

/** Where a character's own settings live. `null` for the page-wide "last time" blob. */
export type Scope = string | null;

function slot(scope: Scope): string {
  return scope === null ? 'selections' : `selections:${scope}`;
}

/**
 * Store this character's settings **and** the page-wide ones, in that order.
 *
 * Written together on purpose: they always agree at the moment of writing, and two call sites
 * that could drift apart is how "the page remembered something the character did not" happens.
 */
export function rememberSelections(
  store: WebStorage | null, character: Scope, selections: Selections,
): void {
  if (store === null) return;
  const payload = JSON.stringify(selections);
  for (const key of [slot(null), ...(character === null ? [] : [slot(character)])]) {
    try {
      store.setItem(PREFIX + key, payload);
    } catch {
      // A full or blocked store means the page opens with defaults next time, which is the
      // same outcome as never having remembered.
    }
  }
}

/**
 * This character's settings, falling back to the page-wide ones, then to null.
 *
 * **The character's own come first.** Reopening on Skirk should restore what was chosen for
 * Skirk rather than the last thing done to anybody, which is the distinction the owner drew.
 */
export function recallSelections(store: WebStorage | null, character: Scope): Selections | null {
  if (store === null) return null;
  for (const key of [...(character === null ? [] : [slot(character)]), slot(null)]) {
    try {
      const raw = store.getItem(PREFIX + key);
      if (raw === null) continue;
      const found = JSON.parse(raw) as Selections;
      // A blob written by an older version can be missing fields a caller will index into.
      // Missed rather than repaired, for the reason `readRecipe` gives: a half-restored
      // selection is a claim about what the user chose.
      if (
        typeof found?.objective === 'string'
        && Array.isArray(found?.sets)
        && typeof found?.mainStats === 'object' && found.mainStats !== null
      ) {
        return found;
      }
    } catch {
      // Unparseable is a miss, never a throw.
    }
  }
  return null;
}

/** Store `value` under `field`, or forget it when empty. Never throws. */
export function remember(
  store: WebStorage | null, field: Remembered, value: string,
): void {
  if (store === null) return;
  try {
    if (value) store.setItem(PREFIX + field, value);
    else store.removeItem(PREFIX + field);
  } catch {
    // A full or blocked store means the page opens empty next time, which is the same
    // outcome as never having remembered. It is not worth failing a page load over.
  }
}

/** What was stored under `field`, or `''`. Never throws. */
export function recall(store: WebStorage | null, field: Remembered): string {
  if (store === null) return '';
  try {
    return store.getItem(PREFIX + field) ?? '';
  } catch {
    return '';
  }
}

/**
 * The remembered `field` **if it is still one of `available`**, otherwise `''`.
 *
 * The empty string is the honest answer here and the whole point of §15: falling back to
 * `available[0]` would reintroduce the invented default by the back door, one layer further
 * from where anyone would look for it.
 */
export function recallAmong(
  store: WebStorage | null, field: Remembered, available: readonly { id: string }[],
): string {
  const id = recall(store, field);
  return available.some((item) => item.id === id) ? id : '';
}

export { browserStore };
