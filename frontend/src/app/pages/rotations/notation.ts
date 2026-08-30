import type { ActionOffer } from './rotations.service';

/**
 * How a move is written down: the community's letter, then the character's own name for it.
 *
 * `Q - Illusory Heart`, not `Illusory Heart` and not `burst`. A player reading a guide meets
 * **E** and **Q** long before they meet "All Schemes to Know", and gcsim's `skill`/`burst` are
 * neither. The letter is the fast channel and the name is the one that says *whose* burst.
 *
 * ## Four letters, and no invented fifth
 *
 * `N`, `C`, `E`, `Q` are what KQM's guides actually write — normal attack, charged attack,
 * elemental skill, elemental burst — and they are the four a rotation is usually made of.
 *
 * **The other six get no letter**, because there is no community notation to borrow. A plunge
 * is written out; a dash is written out; `P` would collide between the high and low plunges,
 * and `J`/`W` for jump and walk would be this repo inventing shorthand and then teaching it to
 * people. That is the same call `weapon_symbols.py` makes about the crossbow and `gcsim_keys`
 * makes about naming a charged attack after the normal-attack talent: **absent beats
 * plausible.**
 */
const LETTERS: Readonly<Record<string, string>> = {
  attack: 'N',
  charge: 'C',
  skill: 'E',
  burst: 'Q',
};

/** The letter a rotation is written with, or `null` where the community writes none. */
export function actionLetter(base: string): string | null {
  return LETTERS[base] ?? null;
}

/**
 * An action key as a word: `high_plunge` → `High plunge`.
 *
 * Only the six actions that are not talents reach this — the other four carry the character's
 * own name for the move. It is **formatting, not renaming**: the key still governs everything,
 * and calling a charged attack "Akara" would be a wrong name rather than an unpolished one
 * (`gcsim_keys._ACTION_TALENTS`).
 */
export function humanise(key: string): string {
  const words = key.replaceAll('_', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * One move, as every surface writes it: `Q - Illusory Heart`, `E - All Schemes to Know (hold)`.
 *
 * Shared by the palette, the step list, the detail pane and the timeline's labels, because a
 * move that reads four different ways across one screen is four things to learn instead of one.
 */
export function moveLabel(offer: ActionOffer): string {
  const letter = actionLetter(offer.base);
  // `name` is the character's own when the action is a talent, and the action key otherwise —
  // which is where the underscores live.
  const name = offer.name === offer.action || offer.name === offer.base
    ? humanise(offer.name)
    : offer.name;
  const variant = offer.variant ? ` (${humanise(offer.variant).toLowerCase()})` : '';
  return letter ? `${letter} - ${name}${variant}` : `${name}${variant}`;
}


/**
 * Mark a drag as started, and give it something to carry.
 *
 * **Firefox cancels a `dragstart` that calls no `setData`.** Not a warning, not a degraded
 * drag — no drag at all. Chrome does not care, which is why three drag sources shipped without
 * it and a browser check in Chrome could not see it.
 *
 * The payload is a label rather than an index: nothing reads it back (the drag's meaning lives
 * in the component's own signals), so what goes in it is what another application would receive
 * if the user dropped there.
 */
export function beginDrag(event: DragEvent, label: string): void {
  event.dataTransfer?.setData('text/plain', label);
}
