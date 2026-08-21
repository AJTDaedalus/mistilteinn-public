"""End-to-end anchors for the #101 divisor work — real seeded DB, real loaders.

`tests/unit/test_buildup_divisors.py` asserts what the *spec files* say. This module
asserts the things that only a real DB can show, and that a JSON-only test would report as
green while production was wrong:

1. **an `atomic` re-classification actually reached the DB.** DESIGN §5.2's trap:
   `apply_skill_overrides` has no path that resets a row to `atomic`, so deleting a move
   entry changes nothing until a full `python -m scripts.seed_db` re-imports the agent. A
   deploy that runs migrations and the override seeder alone silently keeps the old,
   wrong classification.
2. **every authored `buildup` still relates to its DB rows the way its receipt claims** —
   either equal to the row sum, or deliberately different *and* carrying a
   `DOCUMENTED_DEVIATIONS` entry that says why.
The third anchor — that L5 still runs when the whole harness runs — lives in
`test_validate_kits_l5_after_l4.py`, which cannot carry this module's asyncio mark.

Skips cleanly without a seeded DB, like the other integration tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.data.loaders.moves import load_agent_moves
from app.data.loaders.skill_overrides import load_skill_overrides
from app.database import async_session_factory
from app.models.agent import Agent, Attack
from app.models.enums import PotentialVariant
from app.repositories.attack import visible_to
from scripts.audit_agent_data_binding import DOCUMENTED_DEVIATIONS

pytestmark = pytest.mark.asyncio


async def _rows_by_move() -> dict[tuple[str, str], list[Attack]]:
    """Rows as an UNLOCKED build sees them (#90).

    Since #90 `attacks` stores both Potential states, so an unfiltered select sums the
    base row *and* its Potential replacement for the moves where the two differ --
    Jane's Salchow Jump would read 78572 against an authored 51232, which is the
    authored value plus the superseded base row's 27340. Every `buildup` in this corpus
    was authored against the Potential-unlocked kit (the only kit fairy stored between
    #85 and #90), so UNLOCKED is the variant these authored values must be compared to.
    """
    async with async_session_factory() as session:
        agents = (await session.execute(select(Agent))).scalars().all()
        attacks = (
            await session.execute(
                select(Attack).where(visible_to(PotentialVariant.UNLOCKED))
            )
        ).scalars().all()
    if not agents:
        pytest.skip("App DB not seeded — seeded DB required")
    id_to_name = {a.id: a.name for a in agents}
    out: dict[tuple[str, str], list[Attack]] = {}
    for at in attacks:
        out.setdefault((id_to_name.get(at.agent_id, at.agent_id), at.name), []).append(at)
    return out


# Moves this branch re-classified to `atomic` by deleting their override entry.
#
# `Basic Attack: Silenced Shot` was here with 3 rows until 2026-08-20, when Task 19c made it a
# `per_tick` channel (D-CH1a) and split its `Counter` row into a move of its own (D-CH6). It is
# now neither atomic nor 3 rows, so it moves to the channel pin below rather than being deleted
# — a re-classification that leaves no assertion behind is how a move quietly stops being
# checked.
ATOMIC_RECLASSIFIED = [
    ("Seth", "Basic Attack: Lightning Strike - Electrified", 2),
    ("Trigger", "Basic Attack: Harmonizing Shot - Tartarus", 2),
    # The split half: its own move now, and atomic, because a Perfect-Dodge counter has no
    # channel semantics of its own.
    ("Trigger", "Basic Attack: Silenced Shot - Counter", 1),
]

# Moves re-classified to `channel`, with the row count the seeder must leave behind.
CHANNEL_RECLASSIFIED = [
    ("Burnice", "EX Special Attack: Intense Heat Stirring Method", 2),
    ("Burnice", "EX Special Attack: Intense Heat Stirring Method - Double Shot", 2),
    ("Yixuan", "EX Special Attack: Cloud-Shaper", 1),
    ("Norma", "EX Special Attack: En-Nah Barrage", 6),
    # 2, not 3: `Counter` left for a move of its own (D-CH6).
    ("Trigger", "Basic Attack: Silenced Shot", 2),
]

# Moves re-classified to `variant`, with the labels the seeder must have written.
VARIANT_RECLASSIFIED = [
    ("Alice", "Basic Attack: Starshine Waltz", {"One-Staged", "Two-Staged", "Three-Staged"}),
    (
        "Yidhari",
        "Basic Attack: Frostbite Embrace",
        {"Level-1 Charge", "Level-2 Charge", "Level-3 Charge (Spin + Smash)"},
    ),
    (
        "Yuzuha",
        "Basic Attack: Tanuki Helper",
        {"Coordinated Attack (during Tanuki Cloak)", "Auto-Attack (Yuzuha off-field)"},
    ),
]


class TestReclassificationReachedTheDatabase:
    """DESIGN §5.2 — the trap, as a test rather than a paragraph."""

    @pytest.mark.parametrize(("agent", "move", "n_rows"), ATOMIC_RECLASSIFIED)
    async def test_atomic_moves_are_atomic_in_the_db(
        self, agent: str, move: str, n_rows: int
    ) -> None:
        rows = (await _rows_by_move()).get((agent, move))
        assert rows, f"no DB rows for {agent} / {move}"
        assert len(rows) == n_rows
        modes = {getattr(r.hit_mode, "value", r.hit_mode) for r in rows}
        assert modes == {"atomic"}, (
            f"{agent} / {move} is {modes} in the DB, not atomic. The override entry was "
            "deleted, but only a FULL `python -m scripts.seed_db` resets a row to atomic — "
            "`seed_skill_overrides` alone cannot, and never will."
        )

    @pytest.mark.parametrize(("agent", "move", "n_rows"), CHANNEL_RECLASSIFIED)
    async def test_channel_moves_are_channel_in_the_db(
        self, agent: str, move: str, n_rows: int
    ) -> None:
        """Same trap as the atomic pin, one mode along.

        A move file authoring a `channel` block while the DB still says `atomic` is silent:
        the engine runs the old instantaneous path and returns a plausible number. LCH catches
        it at build time (`channel_move_no_db_rows`); this catches it against real data, and
        also pins the ROW COUNT, which is what a `split_moves` regression would move.
        """
        rows = (await _rows_by_move()).get((agent, move))
        assert rows, f"no DB rows for {agent} / {move}"
        assert len(rows) == n_rows
        modes = {getattr(r.hit_mode, "value", r.hit_mode) for r in rows}
        assert modes == {"channel"}, (
            f"{agent} / {move} is {modes} in the DB, not channel — re-run "
            "`python -m scripts.seed_db`. Until then the engine serves pre-channel numbers "
            "for this move."
        )

    @pytest.mark.parametrize(("agent", "move", "labels"), VARIANT_RECLASSIFIED)
    async def test_variant_moves_carry_their_labels(
        self, agent: str, move: str, labels: set[str]
    ) -> None:
        rows = (await _rows_by_move()).get((agent, move))
        assert rows, f"no DB rows for {agent} / {move}"
        modes = {getattr(r.hit_mode, "value", r.hit_mode) for r in rows}
        assert modes == {"variant"}
        assert {r.variant_label for r in rows} == labels

    async def test_no_move_declares_atomic_in_an_override_file(self) -> None:
        """`atomic` is the default, so it is expressed by deleting the entry.

        An entry that spells out `"hit_mode": "atomic"` would be a no-op the seeder cannot
        act on — the reader would think the move had been re-classified when it had not.
        """
        offenders = [
            f"{stem}/{name}"
            for stem, agent in load_skill_overrides().items()
            for name, entry in agent.moves.items()
            if getattr(entry.hit_mode, "value", entry.hit_mode) == "atomic"
        ]
        assert offenders == []


class TestAuthoredBuildupAgainstDatabaseRows:
    async def test_every_authored_buildup_is_the_row_sum_or_documented(self) -> None:
        """The whole of #101 in one assertion, against live data.

        A curated total may legitimately differ from its move's DB row sum — that is what
        a corrected press count *means* when the excluded row carries gauge. What it may
        not do is differ silently.
        """
        by_move = await _rows_by_move()
        undocumented: list[str] = []
        for stem, spec in load_agent_moves().items():
            for name, move in spec.moves.items():
                if move.buildup is None:
                    continue
                rows = by_move.get((spec.agent_name or stem, name))
                if not rows:
                    continue
                db_sum = sum(r.anomaly_buildup for r in rows)
                if move.buildup == db_sum:
                    continue
                if (spec.agent_name, name) in DOCUMENTED_DEVIATIONS:
                    continue
                undocumented.append(
                    f"{spec.agent_name} / {name}: authored {move.buildup} vs DB sum {db_sum}"
                )
        assert undocumented == []

    @pytest.mark.parametrize(
        ("agent", "move", "expected_cycle"),
        [
            # Corrected on this branch; the arithmetic each receipt claims, re-checked
            # against the rows the DB actually holds.
            ("Alice", "Basic Attack: Celestial Overture", 30135),
            ("Caesar", "Basic Attack: Rampaging Slash", 63870),
            ("Hugo", "Basic Attack: Dark Abyss Quartet", 13198),
            ("Lucy", "Basic Attack: Lady's Bat", 32026),
            ("Promeia", "Basic Attack: Sweeping Edge", 62215),
        ],
    )
    async def test_authored_cycle_total_is_reachable_from_the_rows(
        self, agent: str, move: str, expected_cycle: int
    ) -> None:
        """The authored total must be a sum of *some* subset of the move's rows.

        A number that is not reachable from any subset is a placeholder, which is the
        class of defect issue #82 closed and #101 re-opened for the divisor.
        """
        rows = (await _rows_by_move()).get((agent, move))
        assert rows, f"no DB rows for {agent} / {move}"
        gauges = [r.anomaly_buildup for r in rows]
        reachable = {0}
        for g in gauges:
            reachable |= {r + g for r in reachable}
        assert expected_cycle in reachable, (
            f"{agent} / {move}: {expected_cycle} is not the sum of any subset of {gauges}"
        )
        spec = load_agent_moves()[agent.lower().replace(" - ", "_").replace(" ", "_")]
        assert spec.moves[move].buildup == expected_cycle

    async def test_seths_atomic_activation_still_totals_the_row_sum(self) -> None:
        """The smallest re-classified move, end to end through the loader.

        Seth's Electrified authors no `buildup` after Task 6, so the simulator falls back
        to `sum(anomaly_buildup)` over the step's rows. Under `atomic` the step holds every
        row, so one activation applies the full 29388 — byte-identical to the value the
        spec used to hard-code, but now re-derived from the DB on every run.
        """
        rows = (await _rows_by_move())[("Seth", "Basic Attack: Lightning Strike - Electrified")]
        spec = load_agent_moves()["seth"].moves["Basic Attack: Lightning Strike - Electrified"]
        assert spec.buildup is None, "must stay on the DB-row fallback"
        assert spec.hits == 1, "documented press count; inert under atomic but not deleted"
        assert sum(r.anomaly_buildup for r in rows) == 29388
