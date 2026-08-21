/**
 * Canonical "how many rolls does this substat represent" helper.
 *
 * Convention (issue #65 / DECISIONS.md "OQ1 resolved"): displayed roll
 * counts are TOTAL rolls, initial substat included — matching ZO and
 * community shorthand ("a 3-roll crit disc"). Before this, `disc-card`
 * and `disc-rollup` both excluded the initial roll while `rank-table`
 * showed the total, so the same disc reported different numbers on
 * different pages.
 */
export function totalRolls(rolls: number | undefined): number {
  return rolls ?? 1;
}
