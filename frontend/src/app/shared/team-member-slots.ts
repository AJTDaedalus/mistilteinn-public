/** A selectable team member slot, labelled by agent name. */
export interface TeamMemberSlot {
  index: number;
  label: string;
}

export interface TeamSlots {
  build1_id?: string | null;
  build2_id?: string | null;
  build3_id?: string | null;
}

/**
 * The team's build rows with the member at `activeIndex` first, then the rest
 * in slot order — the ordering {@link buffContextForBuilds} expects, since it
 * reads `active_conditions`/`stack_counts` off the head and unions
 * `disabled_buffs` across the whole list.
 *
 * Returns `[]` when the target slot is empty or its row isn't in `builds` yet
 * (builds still loading), so callers can treat "nothing to seed from" as one
 * case. Members whose rows are missing are skipped rather than faked.
 */
export function teamBuildsTargetFirst<T extends { id: string }>(
  team: TeamSlots,
  activeIndex: number,
  builds: readonly T[],
): T[] {
  const ids = [team.build1_id ?? null, team.build2_id ?? null, team.build3_id ?? null];
  const byId = new Map(builds.map((b) => [b.id, b]));
  const targetId = ids[activeIndex] ?? null;
  const target = targetId ? byId.get(targetId) : undefined;
  if (!target) return [];
  const others = ids
    .filter((id): id is string => !!id && id !== target.id)
    .map((id) => byId.get(id))
    .filter((b): b is T => !!b);
  return [target, ...others];
}

/**
 * Builds the slot list for a team's members, labelled by agent name. Only
 * filled slots appear — including slot 0, which a `build_mode=clean` import can
 * leave empty when it re-points team slots and no build matched. Each slot
 * keeps its original index, so callers can select by slot rather than by
 * position. Falls back to "Member N" when the agent can't be resolved yet
 * (e.g. builds/agents still loading).
 */
export function teamMemberSlots(
  team: TeamSlots,
  nameForBuild: (buildId: string) => string | null,
): TeamMemberSlot[] {
  const ids = [
    team.build1_id ?? null,
    team.build2_id ?? null,
    team.build3_id ?? null,
  ];
  const slots: TeamMemberSlot[] = [];
  ids.forEach((id, index) => {
    if (!id) return;
    const name = nameForBuild(id);
    slots.push({ index, label: name || `Member ${index + 1}` });
  });
  return slots;
}
