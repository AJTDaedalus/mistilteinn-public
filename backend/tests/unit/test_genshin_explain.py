"""F.1/F.2 — attribution, and the scope gate it must not be confused with.

DESIGN §1 A6 says a damage number has to be able to explain itself. These pin the mechanism
that makes that possible and, more importantly, the distinction it rests on: a tag category
is a **requirement** on the read context, so it gates; attribution has to ride alongside.
"""

from __future__ import annotations

import pytest

from app.formula.builder import read_
from app.formula.genshin import stats, tags
from app.formula.genshin.explain import ContributionLog
from app.formula.tags import Tag
from app.pando.calculator import Calculator, NodeRegistry


def _log() -> ContributionLog:
    return ContributionLog(registry=NodeRegistry())


# ---- Attribution ----------------------------------------------------------

def test_a_contribution_records_what_it_was_and_where_it_came_from():
    log = _log()

    log.add(tags.Q_ATK_PCT, 0.466, tags.SRC_ARTIFACT, "sands main stat")

    (contribution,) = log.contributions
    assert contribution.quantity == tags.Q_ATK_PCT
    assert contribution.value == pytest.approx(0.466)
    assert contribution.source == tags.SRC_ARTIFACT
    assert "sands" in contribution.note


def test_registering_and_recording_are_the_same_statement():
    """There is no way to add a stat to the graph without saying where it came from — which
    is what keeps the graph and its explanation from drifting apart."""
    log = _log()
    log.add(tags.Q_FLAT_ATK, 311.0, tags.SRC_ARTIFACT, "plume")

    assert Calculator(registry=log.registry).compute(stats.ATK_NODE) == pytest.approx(311.0)
    assert len(log.contributions) == 1


def test_an_unknown_source_is_rejected():
    """`src` labels are a closed vocabulary; a typo'd one would silently split an account."""
    with pytest.raises(ValueError, match="not a known contribution source"):
        _log().add(tags.Q_ATK_PCT, 0.1, "artefact")


def test_a_zero_contribution_is_dropped_from_both_the_graph_and_the_account():
    """Forty "+0" lines is an explanation nobody reads."""
    log = _log()
    log.add(tags.Q_CRIT_RATE, 0.0, tags.SRC_ARTIFACT, "substat that did not roll")

    assert log.contributions == []
    assert Calculator(registry=log.registry).compute(stats.CRIT_RATE_NODE) == 0


def test_explain_lists_every_contribution_and_their_sum():
    log = _log()
    log.add(tags.Q_CRIT_DMG, 0.5, tags.SRC_CHARACTER, "base")
    log.add(tags.Q_CRIT_DMG, 0.884, tags.SRC_ARTIFACT, "circlet main stat")
    log.add(tags.Q_CRIT_DMG, 0.44, tags.SRC_WEAPON, "Mistsplitter substat")

    account = log.explain(tags.Q_CRIT_DMG)

    assert "circlet main stat" in account
    assert "Mistsplitter" in account
    assert "1.824" in account


def test_explaining_an_untouched_stat_says_so_rather_than_reporting_zero():
    """"nothing registered" and "registered as zero" are different diagnoses."""
    assert "nothing registered" in _log().explain(tags.Q_ENERGY_RECHARGE)


def test_for_quantity_keeps_registration_order():
    """Order is how a reader follows a build: character, then weapon, then artifacts."""
    log = _log()
    log.add(tags.Q_ATK_PCT, 0.1, tags.SRC_CHARACTER, "ascension")
    log.add(tags.Q_ATK_PCT, 0.2, tags.SRC_WEAPON, "substat")
    log.add(tags.Q_ATK_PCT, 0.3, tags.SRC_ARTIFACT_SET, "2pc")

    assert [c.source for c in log.for_quantity(tags.Q_ATK_PCT)] == [
        tags.SRC_CHARACTER, tags.SRC_WEAPON, tags.SRC_ARTIFACT_SET,
    ]


# ---- The scope gate -------------------------------------------------------

def _dmg_bonus_under(scope: str, log: ContributionLog) -> float:
    """Read the generic DMG bonus with `scope` in context, as the damage chain will."""
    node = read_(Tag.of(**{tags.Q: tags.Q_DMG_BONUS, tags.SCOPE: scope}), "sum")
    return Calculator(registry=log.registry).compute(node)


def test_a_scope_gated_buff_applies_only_in_its_scope():
    """`+40% Charged Attack DMG` must not appear on a burst.

    This is the mechanism that lets a kit be data: the buff declares *when* it applies and
    the evaluator honours it, with no per-character branch anywhere.
    """
    log = _log()
    log.add(
        tags.Q_DMG_BONUS, 0.4, tags.SRC_CONSTELLATION, "C2: charged attacks",
        tag=tags.scoped_stat_tag(tags.Q_DMG_BONUS, "charged"),
    )

    assert _dmg_bonus_under("charged", log) == pytest.approx(0.4)
    assert _dmg_bonus_under("burst", log) == 0


def test_an_ungated_buff_applies_in_every_scope():
    log = _log()
    log.add(tags.Q_DMG_BONUS, 0.15, tags.SRC_ARTIFACT_SET, "2pc: +15% DMG")

    assert _dmg_bonus_under("charged", log) == pytest.approx(0.15)
    assert _dmg_bonus_under("burst", log) == pytest.approx(0.15)


def test_gated_and_ungated_buffs_add_inside_the_matching_scope():
    log = _log()
    log.add(tags.Q_DMG_BONUS, 0.15, tags.SRC_ARTIFACT_SET, "2pc")
    log.add(
        tags.Q_DMG_BONUS, 0.4, tags.SRC_CONSTELLATION, "C2",
        tag=tags.scoped_stat_tag(tags.Q_DMG_BONUS, "charged"),
    )

    assert _dmg_bonus_under("charged", log) == pytest.approx(0.55)
    assert _dmg_bonus_under("burst", log) == pytest.approx(0.15)


def test_a_scope_gated_contribution_is_still_attributed():
    """Gating changes what the graph sees, never what the account records."""
    log = _log()
    log.add(
        tags.Q_DMG_BONUS, 0.4, tags.SRC_CONSTELLATION, "C2",
        tag=tags.scoped_stat_tag(tags.Q_DMG_BONUS, "charged"),
    )

    (contribution,) = log.for_quantity(tags.Q_DMG_BONUS)
    assert contribution.tag.get(tags.SCOPE) == "charged"
    assert "C2" in str(contribution)
