import type { RotationStep } from './rotations.service';

/**
 * Repair any group a reorder split apart.
 *
 * A group is a **contiguous chunk** — the API refuses one that appears in more than one place,
 * because gathering scattered members would reorder the user's rotation and repeating them
 * where they stand would put the chunk somewhere nobody wrote it.
 *
 * Dragging a grouped tile out of its group, or an ungrouped one through the middle of it,
 * produces exactly that shape. Nothing in the editor prevented it: the timeline drew two runs
 * each badged `×2`, the preview compiled the group twice, and the save failed with a 422 the
 * user could not trace back to the drag.
 *
 * **The repair keeps the first run and releases the rest**, rather than gathering them. The
 * user moved a step deliberately, and moving it back for them would be undoing the edit they
 * just made; releasing it leaves the rotation exactly as they arranged it, minus a claim about
 * repetition that the arrangement no longer supports.
 */
export function regroup(steps: RotationStep[]): RotationStep[] {
  const seen = new Set<string>();
  let previous = '';
  return steps.map((step) => {
    if (!step.group) {
      previous = '';
      return step;
    }
    const broken = step.group !== previous && seen.has(step.group);
    seen.add(step.group);
    previous = step.group;
    return broken ? { ...step, group: '', group_repeat: 1 } : step;
  });
}
