"""The small calls against gcsim (DECISIONS §50, TASKS 14): two native samples at the pin.

- `venti_cons_energy_sample.json`: Venti (A4), Xiangling, Kaeya C6, Thoma C4, with the energy
  drip on — Venti's absorbed-element 15, two burst refunds, and every drip particle.
- `klee_cons_energy_sample.json`: Klee C6, Diona C1, Furina C4, Barbara C1 — a refund to every
  other member, one at a burst's end, a rate under an ICD, and one for the whole fight.

PROVENANCE.md beside them says how each was made.
"""

from __future__ import annotations

import json
from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest

from app.services import formula_energy
from scripts.gcsim.build_key_snapshot import declared_pin

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "formula" / "energy"
VENTI = json.loads((FIXTURE / "venti_cons_energy_sample.json").read_text())
KLEE = json.loads((FIXTURE / "klee_cons_energy_sample.json").read_text())
TABLE = json.loads(Path(formula_energy.TABLE).read_text())


def _cons(name: str) -> list[dict]:
    return TABLE["constellation_refunds"][name]["refunds"]


def _bursts(sample: dict, who: str) -> list[int]:
    return [c["frame"] for c in sample["casts"]
            if c["character"] == who and c["action"] == "burst"]


def _flat(sample: dict, source: str) -> list[dict]:
    return [f for f in sample["flat"] if f["source"] == source]


def test_the_samples_are_at_the_pin() -> None:
    assert VENTI["sim_version"] == declared_pin()
    assert KLEE["sim_version"] == declared_pin()


# ── Venti's absorbed element ─────────────────────────────────────────────────────────────────

def test_ventis_burst_absorbs_the_first_of_gcsims_order_the_team_applies() -> None:
    """The default the browser takes: the first of Pyro, Hydro, Electro, Cryo a teammate
    carries. This team carries Pyro (Xiangling, Thoma) and Cryo (Kaeya): gcsim picks Pyro."""
    [absorbed] = [r for r in TABLE["characters"]["Venti"]["refunds"]
                  if r["recipients"] == "absorbed"]
    carried = {e for who, e in VENTI["elements"].items() if who != "venti"}
    default = next(e for e in absorbed["absorbs"] if e in carried)
    assert default == "pyro"
    bursts = _bursts(VENTI, "venti")
    assert [a["msg"].rsplit(" ", 1)[1] for a in VENTI["absorbs"]] == [default] * len(bursts)


def test_the_absorbed_elements_members_get_15_a_venti_burst_and_no_one_else() -> None:
    bursts = len(_bursts(VENTI, "venti"))
    got = Counter(f["receiver"] for f in _flat(VENTI, "venti-a4"))
    refunds = TABLE["characters"]["Venti"]["refunds"]
    assert {r["amount"] for r in refunds} == {f["amt"] for f in _flat(VENTI, "venti-a4")} == {15}
    # Venti's own 15, and 15 to each Pyro member; nothing to Kaeya (Cryo).
    assert got == {"venti": bursts, "xiangling": bursts, "thoma": bursts}


# ── Constellation refunds ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("sample", "who", "name", "source"), [
    (VENTI, "kaeya", "Kaeya", "kaeya-c6"),
    (VENTI, "thoma", "Thoma", "thoma-c4"),
    (KLEE, "diona", "Diona", "diona-c1"),
])
def test_a_burst_refund_is_its_amount_once_a_burst_to_its_giver(
    sample: dict, who: str, name: str, source: str,
) -> None:
    [refund] = _cons(name)
    events = _flat(sample, source)
    assert {e["receiver"] for e in events} == {who}
    assert sum(e["amt"] for e in events) == pytest.approx(
        refund["amount"] * refund["count"] * len(_bursts(sample, who)))


def test_klees_c6_gives_every_other_member_3_three_times_a_burst() -> None:
    [refund] = _cons("Klee")
    events = _flat(KLEE, "klee-c6")
    bursts = len(_bursts(KLEE, "klee"))
    by = Counter(e["receiver"] for e in events)
    assert "klee" not in by
    assert set(by) == set(KLEE["elements"]) - {"klee"}
    assert set(by.values()) == {refund["count"] * bursts}
    assert {e["amt"] for e in events} == {refund["amount"]}


def test_furinas_c4_never_comes_inside_its_icd_and_the_rate_bounds_it() -> None:
    """4 a proc, at most one every 5 s (`cons.go:50`): the per-second form, an upper bound —
    gcsim's Salon lands on a grid, so its procs come a little slower (about 5.4 s here)."""
    [refund] = _cons("Furina")
    frames = [e["frame"] for e in _flat(KLEE, "furina-c4")]
    assert {e["amt"] for e in _flat(KLEE, "furina-c4")} == {refund["amount"]}
    gaps = [b - a for a, b in pairwise(frames)]
    assert min(gaps) >= refund["interval"] * 60
    span = (frames[-1] - frames[0]) / 60
    assert len(frames) - 1 <= span / refund["interval"]
    assert sum(gaps) / len(gaps) / 60 == pytest.approx(5.4, abs=0.2)


def test_barbaras_c1_is_one_every_10_s_for_the_whole_fight() -> None:
    [c1] = [r for r in _cons("Barbara") if r["requires_constellation"] == 1]
    frames = [e["frame"] for e in _flat(KLEE, "barbara-c1")]
    assert {b - a for a, b in pairwise(frames)} == {c1["interval"] * 60}
    assert {e["amt"] for e in _flat(KLEE, "barbara-c1")} == {c1["amount"]}


# ── The drip ─────────────────────────────────────────────────────────────────────────────────

def test_every_drip_particle_is_clear_and_the_active_member_catches_it_at_full_value() -> None:
    drops = [p for p in VENTI["particles"] if p["source"] == "drop"]
    assert drops
    for p in drops:
        field = 1.0 if p["is_active"] else 1.0 - 0.1 * p["party_count"]
        assert p["ele"] in ("", "none", "physical", "clear", "noelement")
        assert p["amt"] == pytest.approx(p["count"] * 2 * field * p["er"], rel=1e-12)
    # Each drop reaches every member at once; exactly one of them is on field.
    per_frame = Counter(p["frame"] for p in drops)
    assert set(per_frame.values()) == {len(VENTI["elements"])}
    for frame in per_frame:
        assert sum(p["is_active"] for p in drops if p["frame"] == frame) == 1
