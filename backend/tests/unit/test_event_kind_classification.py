"""Every event kind the simulator emits must be explicitly classified (C1, #163).

The event→step mapper is a long `if/elif` chain whose tail logs a warning and
scores zero. That tail only fires for kinds carrying `damage > 0`, so a
damage-carrying kind nobody wired is a **silent understatement** discovered, if
ever, by someone reading server logs.

Two real defects this test would have caught at commit time:

* `phase_flow_unlock_assist` — Remielle's auto-triggered Assist on gaining 3
  Voidflares — carried real ASSIST_FOLLOWUP damage, was in no branch and no
  unscored set, and was scored as zero.
* `_DELIBERATELY_UNSCORED_EVENT_KINDS` listed `"energy"`. No such kind exists;
  the simulator emits `energy_spend`. The entry matched nothing, so the real kind
  was unclassified — a stale waiver in all but name, and exactly what
  `known_issues.json`'s stale-waiver rule exists to prevent one level up.

The classification is deliberately a partition: a kind is scored as standard
damage, scored some other way, or explicitly not scored. "Not in any of them" is
the bug.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.optimizer_pipeline import (
    _DELIBERATELY_UNSCORED_EVENT_KINDS,
    _OWNERLESS_EVENT_KINDS,
    _STANDARD_DAMAGE_EVENT_KINDS,
)

_SIMULATOR = Path(__file__).resolve().parents[2] / "app" / "services" / "anomaly_simulator.py"

# Kinds handled by a dedicated branch in the mapper rather than by membership in
# one of the frozensets. Each needs its own damage shape.
_SPECIALLY_MAPPED = frozenset(
    {
        "anomaly_tick",  # -> AnomalyStep, with buildup share + RefringeArea folded in
        "disorder",  # -> AnomalyStep at disorder_mv_bp proc-equivalents
        "vortex",  # -> AnomalyStep at vortex_mv_bp proc-equivalents
        "luminize",  # -> LuminizeStep, three ownership shapes (E-8 / P-F2)
        "phase_flow_tick",  # -> ComboStep when she is the DPS; unscored as a support
        "stun_trigger",  # -> StunTriggerStep marker
        "stun_end",  # -> StunEndStep marker
    }
)

# Known-unhandled, tracked, and deliberately still noisy. Anomaly-derived: it
# scales off the original anomaly's per-proc damage and AP with its own optional
# crit path, so it needs a step type rather than a ComboStep. Listing it as
# "deliberately unscored" would silence the warning while the damage stayed lost.
_KNOWN_UNHANDLED = frozenset({"abloom"})


def _emitted_event_kinds() -> set[str]:
    """Kinds passed to a `TimelineEvent(...)` constructor in the simulator.

    Matches `kind="..."` but requires a word boundary before `kind`, so
    `cyclone_kind="sweeping"` — a local variable, not an event kind — is not
    mistaken for one. That false positive is why this helper exists rather than a
    bare grep.
    """
    source = _SIMULATOR.read_text()
    return set(re.findall(r'(?<![a-z_])kind="([a-z_]+)"', source))


class TestTheHelperItself:
    def test_finds_the_obvious_kinds(self) -> None:
        kinds = _emitted_event_kinds()
        assert {"hit", "anomaly_tick", "luminize"} <= kinds

    def test_does_not_mistake_cyclone_kind_for_an_event_kind(self) -> None:
        """`_cyclone_kind = "sweeping"` is a Velina Windbite local, not a kind."""
        assert "sweeping" not in _emitted_event_kinds()


class TestClassification:
    def test_every_emitted_kind_is_accounted_for(self) -> None:
        classified = (
            _STANDARD_DAMAGE_EVENT_KINDS
            | _DELIBERATELY_UNSCORED_EVENT_KINDS
            | _OWNERLESS_EVENT_KINDS
            | _SPECIALLY_MAPPED
            | _KNOWN_UNHANDLED
        )
        unclassified = sorted(_emitted_event_kinds() - classified)
        assert not unclassified, (
            f"Event kinds emitted by the simulator but classified nowhere: {unclassified}. "
            "A damage-carrying kind that reaches the mapper's tail is scored as ZERO "
            "behind a once-per-process log line. Add a branch, add it to "
            "_STANDARD_DAMAGE_EVENT_KINDS, or list it in "
            "_DELIBERATELY_UNSCORED_EVENT_KINDS with a reason."
        )

    def test_no_classification_names_a_kind_that_is_not_emitted(self) -> None:
        """The stale-waiver rule, applied to event kinds.

        `_DELIBERATELY_UNSCORED_EVENT_KINDS` carried `"energy"` for exactly this
        reason — a plausible-looking entry that matched nothing, leaving the real
        `energy_spend` unclassified while looking handled.
        """
        emitted = _emitted_event_kinds()
        stale = sorted(
            (_STANDARD_DAMAGE_EVENT_KINDS | _DELIBERATELY_UNSCORED_EVENT_KINDS) - emitted
        )
        assert not stale, (
            f"Classified event kinds that the simulator never emits: {stale}. "
            "Either the kind was renamed and the entry rotted, or it was a guess."
        )

    @pytest.mark.parametrize("kind", sorted(_KNOWN_UNHANDLED))
    def test_known_unhandled_kinds_stay_noisy(self, kind: str) -> None:
        """Tracked-but-unfixed must not be quietly reclassified as intentional."""
        assert kind not in _DELIBERATELY_UNSCORED_EVENT_KINDS
        assert kind not in _STANDARD_DAMAGE_EVENT_KINDS


class TestCritEligibility:
    """Anomaly damage does not crit; the standard set is the crit-bearing set."""

    @pytest.mark.parametrize("kind", ["anomaly_tick", "disorder", "vortex", "luminize", "abloom"])
    def test_no_anomaly_family_kind_is_routed_as_standard_damage(self, kind: str) -> None:
        """A mis-route here inflates rather than under-counts.

        `_STANDARD_DAMAGE_EVENT_KINDS` maps onto `ComboStep`, which goes through
        `calculate_build_damage` and therefore has a CritArea. Routing an anomaly
        kind through it would silently give anomaly damage crit.
        """
        assert kind not in _STANDARD_DAMAGE_EVENT_KINDS

    def test_the_sets_are_disjoint(self) -> None:
        """A kind that is both scored and deliberately unscored is a contradiction."""
        assert not (_STANDARD_DAMAGE_EVENT_KINDS & _DELIBERATELY_UNSCORED_EVENT_KINDS)
