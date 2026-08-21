"""Task 22 (C4) — `impact_pct` resolver semantics.

Shockstar Disco's 2pc grants **Impact +6%**. The kit authored it as `stat: "impact_pct"`,
which resolved in no `buff_resolver` bucket, so the buff was loaded, rendered as a chip,
and then silently discarded — the 2pc did nothing. L0 caught it as `unresolvable_stat`.

The fix is not a rename. The codebase's `impact` key is a **flat** stat; the 2pc is a
**percentage**, and there was nothing for it to be a percentage *of*: `agent.base_impact`
(83–120 across the 58 seeded agents) was never read into the snapshot at all, so fairy's
Impact was disc Impact alone.

Representation, mirroring the `am_pct` precedent already in `compute_total_stats`:

    impact = floor(base_impact * (10000 + impact_pct) / 10000) + flat_impact

Sources (read this session):
  * ZO `data/util/listing.ts:50-58` — `impact` is in `flatAndPercentStats`, alongside
    atk/def/hp/anomProf/anomMas/enerRegen. `data/common/index.ts:40-56` then applies the
    percent to the **base**: `initial x = base x * (1 + initial x%)`. Same bracket as ATK.
  * `references/ZZZ Stats and Damage Calculation.html` — "While Impact has no innate
    effect on the damage an Agent deals, it will increase the amount of Daze they are
    able to inflict"; Daze Buildup = Daze MV x Impact x (Daze RES / taken mods).

That second citation is why this task moves no damage number, and why TASKS' acceptance
("shows increased Impact — and therefore daze/stun") overstates it: Impact drives Daze
**buildup**, and fairy models stun through the per-enemy `stun_dmg_taken_ratio`, not
through a buildup gauge. Nothing in `app/` reads `TotalStats.impact` today. This makes
the stat correct and the 2pc real; a Daze-buildup model would be a separate feature.
"""

from __future__ import annotations

from app.services.stat_calculator import StatInputs, compute_total_stats
from scripts.validate_kits import RESOLVABLE_STATS


def _impact(base: int = 100, pct: int = 0, flat: int = 0) -> int:
    return compute_total_stats(
        StatInputs(agent_base_impact=base, impact_pct=pct, impact=flat)
    ).impact


class TestImpactPctResolves:
    def test_impact_pct_is_a_resolvable_stat(self) -> None:
        """The whole defect: it was in no bucket, so the calc never saw it."""
        assert "impact_pct" in RESOLVABLE_STATS

    def test_flat_impact_still_resolves(self) -> None:
        assert "impact" in RESOLVABLE_STATS


class TestImpactBracket:
    def test_base_impact_reaches_the_calc(self) -> None:
        """It did not before: Impact was disc Impact alone, missing the agent's 83-120."""
        assert _impact(base=100) == 100

    def test_pct_applies_to_base(self) -> None:
        # Shockstar Disco 2pc on a 100-base-Impact agent: 100 * 1.06 = 106.
        assert _impact(base=100, pct=600) == 106

    def test_flat_is_added_after_the_pct(self) -> None:
        # floor(100 * 1.06) + 40 = 106 + 40 = 146, not floor(140 * 1.06) = 148.
        assert _impact(base=100, pct=600, flat=40) == 146

    def test_pct_does_not_multiply_disc_impact(self) -> None:
        """The percent is a percent of the *base* stat — ZO's initial bracket."""
        assert _impact(base=0, pct=600, flat=50) == 50

    def test_floor_not_round(self) -> None:
        # floor(95 * 1.06) = floor(100.7) = 100
        assert _impact(base=95, pct=600) == 100
