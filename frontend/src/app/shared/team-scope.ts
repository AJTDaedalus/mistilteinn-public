import type { CardOption } from './card-picker/card-picker';
import type { BuildRead } from '../pages/builds/builds.service';
import { TEAM_SLOTS, type TeamRead } from '../pages/teams/teams.service';

/**
 * "Start from a team, then pick who in it" — the owner's audit §6, as one implementation.
 *
 * **Extracted at the second use, not the fourth.** `shared/card-picker` exists because Fairy
 * grew three near-identical pickers and the fourth would have been subtly different; copying
 * this shape onto Optimize and Compare and then onto the rotation library would be the same
 * mistake one level up. The pieces are small — a projection and a filter — but the *decisions*
 * in them are not, and those are what would drift:
 *
 * - a team card carries **all four** characters, because electing one to stand for the team is
 *   a card that lies about what it is;
 * - the party is in **slot order**, because a team's first slot is its first slot;
 * - a slot pointing at a build that no longer exists is **skipped**, not rendered as a gap.
 *
 * `TeamRead` carries only build ids, so both functions need the build list to resolve them.
 */

/** The builds a team fields, in slot order. Empty slots and dangling ids are skipped. */
export function buildsInTeam(
  team: TeamRead | null,
  builds: readonly BuildRead[],
): BuildRead[] {
  if (!team) return [...builds];
  const byId = new Map(builds.map((b) => [b.id, b]));
  return TEAM_SLOTS
    .map((slot) => team[slot])
    .map((id) => (id ? byId.get(id) : undefined))
    .filter((b): b is BuildRead => b !== undefined);
}

/** One card per team: its name, its four faces, and its party as searchable text. */
export function teamOptions(
  teams: readonly TeamRead[],
  builds: readonly BuildRead[],
): CardOption[] {
  return teams.map((team) => {
    const party = buildsInTeam(team, builds);
    return {
      value: team.id,
      label: team.name,
      icons: party.map((b) => b.character?.icon),
      // Searched as well as shown: "which of my teams has Nahida" is how anyone looks for a
      // team they named "Bloom 2".
      detail: party.map((b) => b.character?.name).filter(Boolean).join(' · '),
    };
  });
}

/** One card per build: the character's face, and the loadout as the second line. */
export function buildOptions(builds: readonly BuildRead[]): CardOption[] {
  return builds.map((b) => ({
    value: b.id,
    label: b.character?.name || 'No character',
    icon: b.character?.icon,
    detail: `C${b.constellation_level} · ${b.weapon_display || b.weapon?.name || 'no weapon'}`,
  }));
}


/**
 * A team card from a **roster**, the shape `/rotations/options` publishes.
 *
 * The same three decisions as `teamOptions` — four faces, slot order, the party searchable —
 * against a different input. `TeamRead` carries build ids that need the build list to resolve;
 * a roster already carries its characters, and converting one into the other so a single
 * function could take both would be work in service of a signature rather than of a reader.
 *
 * What matters is that the *decisions* live here once. If a third shape appears, this is the
 * file it joins.
 */
export function rosterOptions(
  rosters: readonly { id: string; name: string; characters: readonly {
    nanoka_id: string; name: string; icon?: string | null;
  }[] }[],
): CardOption[] {
  return rosters.map((roster) => ({
    value: roster.id,
    label: roster.name,
    icons: roster.characters.map((c) => c.icon),
    detail: roster.characters.map((c) => c.name).join(' · '),
  }));
}
