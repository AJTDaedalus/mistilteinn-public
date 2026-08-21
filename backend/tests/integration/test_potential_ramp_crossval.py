"""Stored Potential ramps vs ZO's `potentialParams`, against a real seeded DB (#90 Track 2).

`docs/RESEARCH_potential_ramps.md` established that deriving the ramps from nanoka
reproduces ZO for **27 of 28** params across the 10 agents that have them, the 28th being
ZO's own defect (Jane's `25` where `0.25` belongs). This test keeps that true.

It is a *cross-reference*, not an oracle. nanoka is the source of truth (`CLAUDE.md`); ZO
is a second derivation of the same prose and is known to be wrong once. So a disagreement
here does not mean fairy is wrong — it means the two disagree, and the failure message says
which side to examine. The one known disagreement is asserted explicitly, so a future ZO
sync that *fixes* Jane will also fail this and prompt a deliberate update rather than
silently changing what "agreement" means.

Set `POTENTIAL_REQUIRE_DB=1` to turn "seeded DB required" skips into failures, the same
contract as `CROSSVAL_REQUIRE_DB`. A skip here is *cannot check*, never *clean*: the ramps
are importer-assigned, so a migrated-but-not-re-seeded DB has them NULL everywhere.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.database import async_session_factory
from app.models.agent import Agent

# The ZO checkout location this repo standardises on (CLAUDE.md, "Reference Documents").
# Read-only, and the test skips when it is absent, so S108's tempfile concern does not
# apply — this is a fixed path to a developer-provisioned clone, not a temp file we write.
_ZO_STATS = Path("/tmp/genshin-optimizer/libs/zzz/stats/src/allStat_gen.json")  # noqa: S108
_REQUIRE_DB = bool(os.environ.get("POTENTIAL_REQUIRE_DB"))

# fairy agent name -> ZO sheet key. Koleda is absent deliberately: she has no ZO sheet
# entry for Potential at all, because her Potential is unreleased.
_ZO_KEYS = {
    "Nekomata": "Nekomata",
    "Soldier 11": "Soldier11",
    "Lycaon": "Lycaon",
    "Burnice": "Burnice",
    "Grace": "Grace",
    "Ellen": "Ellen",
    "Harumasa": "Harumasa",
    "Rina": "Rina",
    "Jane": "Jane",
    "Soldier 0 - Anby": "Soldier0Anby",
}

# The single known disagreement, asserted rather than tolerated. ZO's Jane param 0 index 4
# is 25; the correct value is 0.25 (see the module docstring).
_KNOWN_ZO_DEFECTS = {("Jane", 0, 4): (25.0, 0.25)}


def _skip_or_fail(reason: str) -> None:
    if _REQUIRE_DB:
        pytest.fail(f"POTENTIAL_REQUIRE_DB is set but the data is missing: {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="module")
def zo_potential_params() -> dict[str, list[list[float]]]:
    if not _ZO_STATS.is_file():
        pytest.skip(f"ZO checkout not present at {_ZO_STATS}")
    chars = json.loads(_ZO_STATS.read_text())["char"]
    return {
        name: chars[key]["potentialParams"]
        for name, key in _ZO_KEYS.items()
        if chars.get(key, {}).get("potentialParams")
    }


@pytest.fixture
async def seeded_ramps() -> dict[str, list[list[float]]]:
    """{agent name: ramps} for every agent carrying them, or {} if unusable."""
    try:
        async with async_session_factory() as session:
            agents = (
                await session.execute(select(func.count()).select_from(Agent))
            ).scalar_one()
            if not agents:
                return {}
            rows = (
                await session.execute(
                    select(Agent.name, Agent.potential_params).where(
                        Agent.potential_params.is_not(None)
                    )
                )
            ).all()
    except Exception:
        return {}
    return dict(rows)


class TestStoredRampsMatchZo:
    async def test_every_param_agrees_except_the_known_defect(
        self, seeded_ramps: dict, zo_potential_params: dict
    ) -> None:
        if not seeded_ramps:
            _skip_or_fail("app DB unreachable, unseeded, or seeded before #90 Track 2")

        mismatches: list[str] = []
        compared = 0
        for agent_name, zo_params in zo_potential_params.items():
            ours = seeded_ramps.get(agent_name)
            assert ours is not None, f"{agent_name}: ZO has ramps but the DB has none"
            assert len(ours) == len(zo_params), (
                f"{agent_name}: {len(ours)} params stored, ZO has {len(zo_params)} — "
                f"a param-count change re-binds every later index, so this is never a "
                f"cosmetic difference"
            )
            for param_index, (mine, theirs) in enumerate(zip(ours, zo_params, strict=True)):
                for level, (a, b) in enumerate(zip(mine, theirs, strict=True)):
                    compared += 1
                    if round(float(a), 6) == round(float(b), 6):
                        continue
                    known = _KNOWN_ZO_DEFECTS.get((agent_name, param_index, level))
                    if known and round(float(b), 6) == known[0] and round(float(a), 6) == known[1]:
                        continue
                    mismatches.append(
                        f"{agent_name} param[{param_index}][{level}]: fairy={a} ZO={b}"
                    )

        # Not merely "something was compared": name the coverage, so a fixture
        # regeneration that silently drops agents fails instead of passing quieter.
        # Only 7 of the 10 appear at the PINNED ZO commit — Nekomata, Rina and Jane's
        # Potential shipped in 3.1, after the pin. That is also why the Jane-defect test
        # below skips here. Their ramps are still imported and still asserted for shape;
        # what is absent is ZO's second opinion on them, which no public source offers
        # either (docs/evidence/potential_public_sources.md, D6).
        assert compared >= 120, (
            f"only {compared} values compared against ZO — expected at least 120 "
            f"(7 agents x 20 params x 6 levels at the pinned commit). A shrinking "
            f"comparison passes for the wrong reason."
        )
        assert not mismatches, (
            "fairy and ZO disagree on a Potential ramp. nanoka is the source of truth and "
            "ZO is a regex scrape of the same prose, so check ZO first — but confirm "
            "against the nanoka text before changing anything:\n  "
            + "\n  ".join(mismatches)
        )

    async def test_the_known_zo_defect_is_still_present_on_their_side(
        self, zo_potential_params: dict
    ) -> None:
        """If ZO fixes Jane, this fails — deliberately.

        The waiver above would then be silently tolerating an agreement rather than a
        disagreement, which quietly weakens the check. Better to be told.
        """
        jane = zo_potential_params.get("Jane")
        if jane is None:
            pytest.skip("ZO has no Jane potentialParams")
        assert float(jane[0][4]) == 25.0, (
            "ZO appears to have fixed Jane's 100x error (param[0][4] is no longer 25). "
            "Remove the entry from _KNOWN_ZO_DEFECTS — the two sources now agree."
        )


class TestStoredRampShape:
    async def test_every_ramp_is_six_long_and_starts_at_zero(
        self, seeded_ramps: dict
    ) -> None:
        """Six game levels, index 0 = Level I (kit variant, no value bonus)."""
        if not seeded_ramps:
            _skip_or_fail("app DB unreachable, unseeded, or seeded before #90 Track 2")

        for agent_name, ramps in seeded_ramps.items():
            for param_index, ramp in enumerate(ramps):
                assert len(ramp) == 6, f"{agent_name} param[{param_index}]: {len(ramp)} entries"
                assert ramp[0] == 0, (
                    f"{agent_name} param[{param_index}]: Level I must be 0 — it buys the "
                    f"kit variant and no value bonus"
                )

    async def test_only_agents_with_potential_carry_ramps(self, seeded_ramps: dict) -> None:
        """Also catches JSONB `'null'` masquerading as a value.

        `Agent.potential_params` is `JSONB(none_as_null=True)` so "no ramps" is SQL NULL.
        Without that flag SQLAlchemy stores Python None as the JSON scalar `'null'`,
        which `IS NOT NULL` happily matches — and it only bites rows INSERTED with None,
        so it stayed invisible locally and appeared on prod the moment a re-seed inserted
        two new agents. The `!= 'null'` arm is what makes this test able to see it.
        """
        if not seeded_ramps:
            _skip_or_fail("app DB unreachable, unseeded, or seeded before #90 Track 2")

        async with async_session_factory() as session:
            without = (
                await session.execute(
                    select(Agent.name).where(
                        Agent.has_potential.is_(False), Agent.potential_params.is_not(None)
                    )
                )
            ).scalars().all()
            json_nulls = (
                await session.execute(
                    select(Agent.name).where(
                        text("agents.potential_params = 'null'::jsonb")
                    )
                )
            ).scalars().all()
        assert not without, f"agents without a Potential tree carry ramps: {sorted(without)}"
        assert not json_nulls, (
            f"agents store JSONB 'null' instead of SQL NULL: {sorted(json_nulls)} — the "
            f"column needs none_as_null=True and these rows need normalising"
        )

    async def test_koleda_is_present_but_uncorroborated(self, seeded_ramps: dict) -> None:
        """Koleda parses like any other agent even though her Potential is unreleased.

        Asserted so the state is deliberate rather than incidental: the importer reads
        nanoka's `latest` by policy, so her ramps ARE imported — as pre-release values,
        with no ZO sheet and no public source to check them against. See her
        `known_issues.json` blocker.
        """
        if not seeded_ramps:
            _skip_or_fail("app DB unreachable, unseeded, or seeded before #90 Track 2")
        assert "Koleda" in seeded_ramps
        assert "Koleda" not in _ZO_KEYS


class TestRampBindingEndToEnd:
    """Ellen's bound rows resolve to the right number at every Potential level (#90).

    This is the whole of Track 2 in one assertion: the ramp is imported from nanoka, the
    modifier binds an index, and the build's rank picks the entry. The three layers are
    tested separately elsewhere; this is the one that would catch them disagreeing.

    Expected, from the node text "CRIT DMG increases by N% per stack. At 10 stacks, the
    attack ignores M% of the target's Ice RES", in basis points:

        rank 0  not unlocked   rows absent (they are `potential: "unlocked"`)
        rank 1  Level I        0 / 0        (buys the kit variant, no value bonus)
        rank 2  Level II       160 / 330
        rank 6  Level VI       480 / 1000
    """

    async def test_each_level_resolves_to_its_own_value(self, seeded_ramps: dict) -> None:
        if not seeded_ramps:
            _skip_or_fail("app DB unreachable, unseeded, or seeded before #90 Track 2")

        from app.services.modifier_loader import load_agent_modifiers
        from app.services.modifiers import bind_potential_param, potential_allows

        ramps = seeded_ramps["Ellen"]
        bound = {
            mod.stat: mod
            for mod in load_agent_modifiers("1191")
            if mod.potential_param is not None
        }
        assert set(bound) == {"crit_dmg", "res_ignore"}, sorted(bound)

        expected = {
            1: {"crit_dmg": 0, "res_ignore": 0},
            2: {"crit_dmg": 160, "res_ignore": 330},
            3: {"crit_dmg": 240, "res_ignore": 500},
            4: {"crit_dmg": 320, "res_ignore": 670},
            5: {"crit_dmg": 400, "res_ignore": 830},
            6: {"crit_dmg": 480, "res_ignore": 1000},
        }
        for rank, wanted in expected.items():
            for stat, value in wanted.items():
                mod = bound[stat]
                assert potential_allows(mod, rank), f"{stat} should be live at rank {rank}"
                assert bind_potential_param(mod, rank, ramps).value == value, (
                    f"{stat} at rank {rank}"
                )

    async def test_a_locked_build_never_sees_them(self, seeded_ramps: dict) -> None:
        """They are Potential-only mechanics, so rank 0 must not merely zero them — the
        rows must not be live at all."""
        if not seeded_ramps:
            _skip_or_fail("app DB unreachable, unseeded, or seeded before #90 Track 2")

        from app.services.modifier_loader import load_agent_modifiers
        from app.services.modifiers import potential_allows

        bound = [m for m in load_agent_modifiers("1191") if m.potential_param is not None]
        assert bound
        assert not [m for m in bound if potential_allows(m, 0)]

    async def test_level_one_is_live_but_worth_nothing(self, seeded_ramps: dict) -> None:
        """The distinction rank 0 and Level I collapse into under a boolean toggle: the
        mechanic EXISTS at Level I (the kit variant is bought) but scales to nothing."""
        if not seeded_ramps:
            _skip_or_fail("app DB unreachable, unseeded, or seeded before #90 Track 2")

        from app.services.modifier_loader import load_agent_modifiers
        from app.services.modifiers import bind_potential_param, potential_allows

        ramps = seeded_ramps["Ellen"]
        for mod in load_agent_modifiers("1191"):
            if mod.potential_param is None:
                continue
            assert potential_allows(mod, 1), "Level I is unlocked — the row is live"
            assert bind_potential_param(mod, 1, ramps).value == 0
