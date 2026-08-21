"""Jane's Assault CRIT reaches the anomaly calc (#162, B1b).

The kit's own escalation (a) proposed exactly this shape — "a generic
anomaly_crit_rate/anomaly_crit_dmg stat pair feeding a CritArea-equivalent into
the anomaly damage formula, plus an enemy_gnawed Condition" — and then declined
to author it because neither existed. Both now do.

Pins the values against the DB text rather than the guide, and pins the two
scoping properties that decide whether this is a fix or an over-credit: it is
Physical-only, and it is Gnawed-gated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.buff_resolver import resolve_modifiers
from app.services.modifier_loader import load_agent_modifiers
from app.services.modifiers import ActiveConditions, Condition, ModifierTarget

_JANE = Path(__file__).resolve().parents[2] / "app" / "data" / "modifiers" / "agents" / "jane.json"


def _rows():
    d = json.loads(_JANE.read_text())
    return [m for m in d["modifiers"] if m["stat"].startswith("anomaly_crit")]


_SOURCE_ID = json.loads(_JANE.read_text())["source_id"]


class TestAuthoredValues:
    """DB core-passive text, level 7: base CRIT Rate 40%, +0.16%/AP, CRIT DMG 50%."""

    def test_base_crit_rate_is_forty_percent(self) -> None:
        rate = [r for r in _rows() if r["stat"] == "anomaly_crit_rate" and "scaling_stat" not in r]
        assert len(rate) == 1
        assert rate[0]["value"] == 4000

    def test_the_ap_rider_is_sixteen_bp_per_point(self) -> None:
        rider = [r for r in _rows() if r.get("scaling_stat") == "anomaly_proficiency_excess"]
        assert len(rider) == 1
        assert rider[0]["scaling_ratio"] == 16
        assert rider[0]["excess_threshold"] == 0, "every point counts; no AP floor in the DB text"
        # `value` is the CAP for this baker. 4000 base + 6000 = the 10000 clamp in
        # `crit_multiplier`, so a larger cap would be authored-but-unreachable.
        assert rider[0]["value"] == 6000

    def test_crit_dmg_is_fifty_plus_fifty_at_m2(self) -> None:
        dmg = [r for r in _rows() if r["stat"] == "anomaly_crit_dmg"]
        assert len(dmg) == 2
        assert all(r["value"] == 5000 for r in dmg)
        assert {r.get("min_mindscape", 0) for r in dmg} == {0, 2}


class TestScoping:
    """The two properties that separate a fix from an over-credit."""

    @pytest.mark.parametrize("row", _rows(), ids=lambda r: r["source_label"])
    def test_every_row_is_physical_scoped(self, row: dict) -> None:
        """Assault is the Physical anomaly. Unscoped, this would crit every element."""
        assert row.get("element_scope") == ["physical"]

    @pytest.mark.parametrize("row", _rows(), ids=lambda r: r["source_label"])
    def test_every_row_is_gnawed_gated(self, row: dict) -> None:
        """`always` would over-credit whenever Gnawed is down — past D-KV17's ceiling."""
        assert row["conditions"] == [Condition.ENEMY_GNAWED.value]

    @pytest.mark.parametrize("row", _rows(), ids=lambda r: r["source_label"])
    def test_every_row_is_a_team_buff(self, row: dict) -> None:
        """DB: 'if ANY squad member triggers Assault…'. ZO registers teamBuff."""
        assert row["target"] == "team"


class TestTheRowsActuallyResolve:
    """Guards the "authored but never reaches the calc" failure mode.

    A kit row that resolves into no bucket contributes zero silently — the
    `anomaly_mastery_excess` trap. Value assertions on the JSON alone cannot see
    that.
    """

    @staticmethod
    def _resolved(conditions: set, element: str):
        mods = load_agent_modifiers(_SOURCE_ID)
        return resolve_modifiers(
            [m for m in mods if m.stat.startswith("anomaly_crit")],
            ActiveConditions(active=conditions),
            target_filter=ModifierTarget.TEAM,
            damage_element=element,
        )

    def test_gnawed_physical_resolves_both_buckets(self) -> None:
        buffs = self._resolved({Condition.ENEMY_GNAWED}, "physical")
        assert buffs.anomaly_crit_rate == 4000, "base CRIT Rate did not reach the bucket"
        assert buffs.anomaly_crit_dmg == 10000, "core 50% + M2 50% did not sum"

    def test_without_gnawed_nothing_resolves(self) -> None:
        buffs = self._resolved(set(), "physical")
        assert buffs.anomaly_crit_rate == 0
        assert buffs.anomaly_crit_dmg == 0

    def test_a_non_physical_anomaly_gets_nothing(self) -> None:
        """The #164 dependency, from the consuming end."""
        buffs = self._resolved({Condition.ENEMY_GNAWED}, "fire")
        assert buffs.anomaly_crit_rate == 0, (
            "Jane's Physical Assault CRIT reached a Fire anomaly — element_scope "
            "is not being honoured (#164)"
        )
        assert buffs.anomaly_crit_dmg == 0
