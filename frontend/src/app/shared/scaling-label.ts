/**
 * What a hit scales off, in the game's own words, for a hit picker.
 *
 * Math-fallback P0. The hits have always been scored off ATK on these pages, whatever the
 * talent said; now that each carries its own stat, the picker says so — `Skill DMG · Max HP`
 * — so a user can see which stat the search is going to chase.
 *
 * Empty for a plain ATK hit, which is most of them and what a reader assumes: labelling every
 * normal attack `ATK` would bury the few that are not.
 */

type Stat = 'atk' | 'hp' | 'def' | 'elemental_mastery';

/** The catalogue's own spelling, from the talent rows' tails (`talent_scaling._STAT_WORDS`). */
const WORDS: Record<Stat, string> = {
  atk: 'ATK',
  hp: 'Max HP',
  def: 'DEF',
  elemental_mastery: 'Elemental Mastery',
};

export function scalingLabel(hit: {
  scaling_stat: Stat;
  extra_terms: readonly { stat: Stat }[];
}): string {
  const stats = [hit.scaling_stat, ...hit.extra_terms.map((term) => term.stat)];
  if (stats.length === 1 && stats[0] === 'atk') return '';
  return stats.map((stat) => WORDS[stat]).join(' + ');
}
