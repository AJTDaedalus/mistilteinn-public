"""Unit tests for build_step_attribution — specifically the ATK/ATK% split."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.attribution import build_step_attribution
from app.services.buff_resolver import Contribution, ResolvedBuffs


def _make_build(
    agent_base_atk: int = 800,
    wengine_base_atk: int = 700,
    agent_crit_rate: int = 500,
    agent_crit_dmg: int = 5000,
    agent_element: str = "physical",
    agent_pen_ratio: int = 0,
    agent_pen_flat: int = 0,
    agent_name: str = "Ellen Joe",
) -> MagicMock:
    snap = MagicMock()
    snap.agent_base_atk = agent_base_atk
    snap.wengine_base_atk = wengine_base_atk
    snap.agent_crit_rate = agent_crit_rate
    snap.agent_crit_dmg = agent_crit_dmg
    snap.agent_element = agent_element
    snap.agent_pen_ratio = agent_pen_ratio
    snap.agent_pen_flat = agent_pen_flat
    snap.agent_name = agent_name
    return snap


def _make_disc(
    flat_atk: int = 0,
    atk_pct: int = 0,
    crit_rate: int = 0,
    crit_dmg: int = 0,
    pen_ratio: int = 0,
    pen_flat: int = 0,
) -> MagicMock:
    disc = MagicMock()
    disc.flat_atk = flat_atk
    disc.atk_pct = atk_pct
    disc.crit_rate = crit_rate
    disc.crit_dmg = crit_dmg
    disc.pen_ratio = pen_ratio
    disc.pen_flat = pen_flat
    disc.physical_dmg = 0
    return disc


def _make_buffs(
    atk_pct: list[Contribution] | None = None,
    flat_atk: list[Contribution] | None = None,
    final_atk_pct: list[Contribution] | None = None,
    final_flat_atk: list[Contribution] | None = None,
) -> ResolvedBuffs:
    buffs = MagicMock(spec=ResolvedBuffs)
    buffs.stat_attributions = {
        "atk_pct": atk_pct or [],
        "flat_atk": flat_atk or [],
        "final_atk_pct": final_atk_pct or [],
        "final_flat_atk": final_flat_atk or [],
        "crit_rate": [],
        "crit_dmg": [],
    }
    buffs.dmg_bonus_attributions = []
    buffs.combat_attributions = {}
    return buffs


class TestAtkAttributionSplit:
    def test_disc_atk_pct_not_in_flat_zone(self):
        build = _make_build()
        disc = _make_disc(flat_atk=300, atk_pct=9600)
        buffs = _make_buffs()
        attr = build_step_attribution(build, MagicMock(), disc, buffs)

        flat_sources = [c.source for c in attr.atk_components.contributions]
        assert "Discs (ATK%)" not in flat_sources

    def test_disc_atk_pct_in_pct_zone(self):
        build = _make_build()
        disc = _make_disc(flat_atk=300, atk_pct=9600)
        buffs = _make_buffs()
        attr = build_step_attribution(build, MagicMock(), disc, buffs)

        pct_sources = [c.source for c in attr.atk_pct_components.contributions]
        assert "Discs (ATK%)" in pct_sources

    def test_disc_flat_atk_in_flat_zone(self):
        build = _make_build()
        disc = _make_disc(flat_atk=354)
        buffs = _make_buffs()
        attr = build_step_attribution(build, MagicMock(), disc, buffs)

        flat_sources = [c.source for c in attr.atk_components.contributions]
        assert "Discs (flat ATK)" in flat_sources

    def test_buff_atk_pct_in_pct_zone(self):
        build = _make_build()
        disc = _make_disc()
        buffs = _make_buffs(atk_pct=[Contribution(source="W-Engine ATK%", value=1000)])
        attr = build_step_attribution(build, MagicMock(), disc, buffs)

        pct_sources = [c.source for c in attr.atk_pct_components.contributions]
        assert "W-Engine ATK%" in pct_sources

    def test_buff_atk_pct_not_in_flat_zone(self):
        build = _make_build()
        disc = _make_disc()
        buffs = _make_buffs(atk_pct=[Contribution(source="W-Engine ATK%", value=1000)])
        attr = build_step_attribution(build, MagicMock(), disc, buffs)

        flat_sources = [c.source for c in attr.atk_components.contributions]
        assert "W-Engine ATK%" not in flat_sources

    def test_agent_base_atk_in_flat_zone(self):
        build = _make_build(agent_base_atk=863)
        disc = _make_disc()
        buffs = _make_buffs()
        attr = build_step_attribution(build, MagicMock(), disc, buffs)

        flat_sources = [c.source for c in attr.atk_components.contributions]
        assert "Agent base ATK" in flat_sources
        agent_contrib = next(
            c for c in attr.atk_components.contributions if c.source == "Agent base ATK"
        )
        assert agent_contrib.value == 863

    def test_disc_atk_pct_value_preserved(self):
        build = _make_build()
        disc = _make_disc(atk_pct=9600)
        buffs = _make_buffs()
        attr = build_step_attribution(build, MagicMock(), disc, buffs)

        disc_pct = next(
            c for c in attr.atk_pct_components.contributions if c.source == "Discs (ATK%)"
        )
        assert disc_pct.value == 9600


class TestAttributionEnrichment:
    """Task 2.1 acceptance: every contribution from build_step_attribution
    carries source_category."""

    def test_no_contribution_has_none_source_category(self):
        build = _make_build(agent_name="Ellen Joe")
        disc = _make_disc(flat_atk=100, atk_pct=600, crit_rate=480, pen_flat=9)
        buffs = _make_buffs()
        stats = MagicMock()
        attr = build_step_attribution(build, stats, disc, buffs)

        all_contribs = [
            c
            for zone in [
                attr.atk_components,
                attr.atk_pct_components,
                attr.crit_rate,
                attr.crit_dmg,
                attr.boost_bonuses,
                attr.pen_ratio,
                attr.pen_flat,
            ]
            for c in zone.contributions
        ]
        assert all_contribs, "Expected at least some contributions"
        for c in all_contribs:
            assert c.source_category is not None, (
                f"Contribution '{c.source}' missing source_category"
            )

    def test_agent_base_atk_tagged_as_base(self):
        build = _make_build(agent_base_atk=1000, wengine_base_atk=0, agent_name="Ellen Joe")
        disc = _make_disc()
        buffs = _make_buffs()
        attr = build_step_attribution(build, MagicMock(), disc, buffs)

        base_contribs = [c for c in attr.atk_components.contributions if "Agent base" in c.source]
        assert base_contribs
        assert base_contribs[0].source_category == "base"
        assert base_contribs[0].owner_agent_name == "Ellen Joe"

    def test_disc_flat_atk_tagged_as_discs(self):
        build = _make_build(agent_name="Ellen Joe")
        disc = _make_disc(flat_atk=500)
        buffs = _make_buffs()
        attr = build_step_attribution(build, MagicMock(), disc, buffs)

        disc_contribs = [c for c in attr.atk_components.contributions if "Discs" in c.source]
        assert disc_contribs
        assert disc_contribs[0].source_category == "discs"
