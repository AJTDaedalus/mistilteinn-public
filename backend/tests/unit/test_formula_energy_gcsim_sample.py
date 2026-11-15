"""gcsim's own particle events, against the energy model's rules and the particle table.

`tests/fixtures/formula/energy/national_energy_sample.json` is every particle event and burst
drain of one native gcsim sample at the pin (PROVENANCE.md beside it): the owner's National
team, bursts free (`ignore_burst_energy`) so the rotation repeats identically, no drip. Each
event must be exactly `count × value(element) × field × ER`; each skill's particles per cast
must be the table's; and the energy Xiangling banks over a steady rotation must be what the
closed form gives. `npm run formula:verify` holds the browser's `formula-energy.ts` to the same
drain.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.services import formula_energy
from scripts.gcsim.build_key_snapshot import declared_pin

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "formula" / "energy"
SAMPLE = json.loads((FIXTURE / "national_energy_sample.json").read_text())

#: gcsim `energy.go:61-71` (KQM's Energy library page states the same 3 / 2 / 1).
VALUE = {"same": 3.0, "clear": 2.0, "different": 1.0}


def _value(receiver: str, ele: str) -> float:
    if ele in ("", "none", "physical"):
        return VALUE["clear"]
    return VALUE["same"] if SAMPLE["elements"][receiver] == ele else VALUE["different"]


def test_the_sample_is_at_the_pin() -> None:
    assert SAMPLE["sim_version"] == declared_pin()
    assert len(SAMPLE["particles"]) > 100


@pytest.mark.parametrize("event", SAMPLE["particles"], ids=lambda e: f"{e['frame']}-{e['receiver']}")
def test_every_particle_is_count_times_value_times_field_times_er(event: dict) -> None:
    field = 1.0 if event["is_active"] else 1.0 - 0.1 * event["party_count"]
    expected = event["count"] * _value(event["receiver"], event["ele"]) * field * event["er"]
    assert event["amt"] == pytest.approx(expected, rel=1e-12)


def test_off_field_is_sixty_percent_in_a_party_of_four() -> None:
    """KQM: "In a party of 4, a unit off-field gains 60% of the Energy"."""
    off = [e for e in SAMPLE["particles"] if not e["is_active"]]
    assert off
    for e in off:
        assert e["party_count"] == 4
        assert e["amt"] / (e["count"] * _value(e["receiver"], e["ele"]) * e["er"]) == (
            pytest.approx(0.6))


def _drops(source: str) -> list[float]:
    """The counts one source dropped, once per drop (each drop reaches every member)."""
    seen: dict[int, float] = {}
    for e in SAMPLE["particles"]:
        if e["source"] == source:
            seen[e["frame"]] = e["count"]
    return [seen[f] for f in sorted(seen)]


def test_particles_per_cast_are_the_tables() -> None:
    table = {name: sources[0].particles for name, sources in formula_energy.particle_table().items()}
    # Four rotations; the first Guoba's last particle lands after the run ends nowhere — count
    # the per-drop numbers instead.
    assert set(_drops("xingqiu")) == {5}
    assert len(_drops("xingqiu")) == 4
    assert table["Xingqiu"] == 5
    assert set(_drops("yelan")) == {4}
    assert table["Yelan"] == 4
    # Guoba: one particle per hit, four hits a cast.
    assert set(_drops("xiangling")) == {1}
    assert len(_drops("xiangling")) == 4 * 4
    assert table["Xiangling"] == 4
    # The config holds Bennett's skill at level 1: 3 every time (skill.go:242), not the tap's
    # 2.25 the table defaults to — the panel's per-cast field is where a hold is entered.
    assert set(_drops("bennett")) == {3}


def test_a_steady_rotation_banks_what_the_closed_form_gives() -> None:
    """Xiangling's fourth drain: ER × Σ count × value × field over the rotation before it."""
    drains = [d for d in SAMPLE["drains"] if d["character"] == "xiangling"]
    assert len(drains) == 4
    start, end = drains[2]["frame"], drains[3]["frame"]
    window = [e for e in SAMPLE["particles"]
              if e["receiver"] == "xiangling" and start < e["frame"] <= end]
    er = window[0]["er"]
    # The rotation as the model takes it: Bennett 3 off field, Guoba 4 (two caught on field,
    # two off), Xingqiu 5 off, Yelan 4 off — same element 3, different 1, off field 0.6.
    caught = Counter((e["source"], e["is_active"]) for e in window)
    assert caught == Counter({("xiangling", True): 2, ("xiangling", False): 2,
                              ("bennett", False): 1, ("xingqiu", False): 1, ("yelan", False): 1})
    closed_form = er * (3 * 3 * 0.6 + (2 * 3 * 1.0 + 2 * 3 * 0.6) + 5 * 1 * 0.6 + 4 * 1 * 0.6)
    assert drains[3]["pre_drain"] == pytest.approx(closed_form, rel=1e-12)
    assert closed_form == pytest.approx(39.97176, abs=1e-9)
    # gcsim's own requirement for that rotation (energy_stats.go:85): cost over raw energy.
    assert drains[3]["max_energy"] / (closed_form / er) == pytest.approx(80 / 20.4)
