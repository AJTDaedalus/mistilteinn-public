import type { components } from '../../api/api.types';
import type { CardOption } from '../card-picker/card-picker';

export type WeaponGuide = components['schemas']['CharacterWeaponGuideRead'];
export type WeaponRecommendation = components['schemas']['WeaponRecommendationRead'];
export type SetRecommendation = components['schemas']['SetRecommendationRead'];

/**
 * Turning a KeqingMains guide into picker decorations, in one place.
 *
 * **Two pages already did this for weapons and neither did it for sets.** `builds` and
 * `optimize` each carried a near-identical `recommended` map and `weaponOptions` computed;
 * adding the set half to both would have made four copies of a rule about somebody else's
 * words, which is the shape `shared/{icon,token,element,combobox}` exists to stop.
 *
 * Everything here is presentation. The judgements are KQM's, published verbatim by the
 * backend, and nothing in this file summarises, ranks or derives — see
 * `app/services/kqm_weapons.py` for why that line is drawn where it is.
 */

/** `weapon row id -> what KQM said`, for the pickers that work in row ids. */
export function weaponsById(guide: WeaponGuide | null): Map<string, WeaponRecommendation> {
  // **Annotated, because the inference is wrong here and only Angular's compiler says so.**
  // `new Map(list.map((w) => [w.weapon_id, w]))` gives TypeScript a `(string | Rec)[]` rather
  // than a tuple, so the value type collapses to `{}` and `.position` does not exist on it.
  // `npx tsc` passes; the container build fails.
  const listed = new Map<string, WeaponRecommendation>();
  for (const weapon of guide?.weapons ?? []) {
    // **Null when this pin has no such weapon** — the row keeps its citation and loses only
    // its link, so there is nothing to key it by and nothing to mark.
    if (weapon.weapon_id) listed.set(weapon.weapon_id, weapon);
  }
  return listed;
}

/**
 * `set nanoka id -> what KQM said`, keeping the **best** position where a guide lists a set
 * under several playstyles.
 *
 * Zhongli's guide carries 32 set rows across five playstyles, so a set can appear four times
 * with four positions. The card can show one, and KQM's order is the recommendation, so the
 * earliest wins — the same rule the capture already applies to a weapon listed twice.
 */
export function setsByNanokaId(guide: WeaponGuide | null): Map<number, SetRecommendation> {
  const listed = new Map<number, SetRecommendation>();
  for (const entry of guide?.sets ?? []) {
    if (entry.kind !== 'set' || entry.set_nanoka_id == null) continue;
    const held = listed.get(entry.set_nanoka_id);
    if (!held || entry.position < held.position) listed.set(entry.set_nanoka_id, entry);
  }
  return listed;
}

/**
 * The rows KQM described by a *stat* rather than by a set — `2pc HP% / ER / Hydro%`.
 *
 * **Kept as sentences and never resolved to cards.** Such a row names every set whose
 * two-piece grants that stat; turning it into one set would be inventing a name KQM did not
 * write, which is the failure mode this repo's data rules exist to prevent.
 */
export function statAdvice(guide: WeaponGuide | null): SetRecommendation[] {
  return (guide?.sets ?? []).filter((entry) => entry.kind !== 'set');
}

/**
 * One card, marked with what KQM said about it.
 *
 * `#3` is a **position, not a rank** — their table carries an order and no rank numbers, and
 * calling it a rank would put a word in the source's mouth. `relative_dps` is their published
 * comparison where a full guide states one; a quick guide states an order and no number, and
 * deriving one would be a figure this app invented under someone else's name.
 *
 * The note is KQM's own sentence, verbatim, on hover.
 */
export function marked(
  card: CardOption,
  listed: WeaponRecommendation | SetRecommendation | undefined,
): CardOption {
  if (!listed) {
    // **False, not absent.** A card is drawn as recommended only when a cited source lists it,
    // and a card with no `recommended` key at all is a third state nothing downstream
    // distinguishes. The card's own tooltip is left alone — a set's 4-piece bonus is not
    // KQM's to remove.
    return { ...card, recommended: false, tags: { ...card.tags, kqm: '' } };
  }
  return {
    ...card,
    detail: [`KQM #${listed.position}`, listed.relative_dps, listed.playstyle, card.detail]
      .filter(Boolean).join(' · '),
    // KQM's sentence first, then whatever the card already explained — a set card carries its
    // 4-piece bonus here, and dropping it to make room for the citation would trade one true
    // thing for another. Verbatim in both halves; summarising KQM would be this app asserting
    // a judgement it did not make, under someone else's name.
    tooltip: [listed.note, card.tooltip].filter(Boolean).join('\n\n'),
    recommended: true,
    tags: { ...card.tags, kqm: 'listed' },
  };
}

/**
 * One weapon's card, for either picker.
 *
 * **A listed weapon shows KQM's comparison where its substat would go, and that is a choice
 * both pages had already made separately.** A card's second line holds about four segments
 * before it wraps, and `KQM #1 · 114.2% · Burst Support · 5★ · CRIT DMG` is five. The substat
 * is on the weapon's own page; KQM's position and their percentage are the reason this card is
 * at the top of the list, so they win the space.
 */
export function weaponCard(
  weapon: { id: string; name: string; icon?: string | null; stars: number;
            sub_stat_display?: string | null },
  listed: WeaponRecommendation | undefined,
): CardOption {
  return marked({
    value: weapon.id,
    label: weapon.name,
    icon: weapon.icon,
    detail: listed
      ? `${weapon.stars}★`
      : `${weapon.stars}★ · ${weapon.sub_stat_display || 'no substat'}`,
    tags: { stars: String(weapon.stars) },
  }, listed);
}

/** KQM's order first; everything else keeps the order it arrived in. */
export function listedFirst<T>(
  cards: readonly T[], position: (card: T) => number | undefined,
): T[] {
  return [...cards].sort(
    (a, b) => (position(a) ?? Number.MAX_SAFE_INTEGER) - (position(b) ?? Number.MAX_SAFE_INTEGER),
  );
}

/** The chip offered only when there is a guide — a filter whose only outcome is empty is not one. */
export const KQM_FILTER = {
  group: 'kqm',
  label: 'KeqingMains',
  options: [{ value: 'listed', label: 'KQM lists it' }],
};
