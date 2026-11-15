"""Summons, a Favonius proc and a flat refund, against gcsim's own energy events (TASKS 14).

The follow-ups to #392 (owner rulings 2026-11-15, DECISIONS §48). Two committed gcsim outputs
at the pin (PROVENANCE.md beside them):

- `summon_energy_sample.json`: one sample of `summon_energy.txt` — Raiden (a Favonius Lance R3,
  on field), Fischl, Kokomi and Zhongli, bursts free so the rotation repeats. Every particle
  event, every flat-energy event, the summons' hits and the Favonius procs.
- `summon_rates.json`: 3000 iterations each of `summon_rates_1.txt` (Oz from skill and burst,
  Kuki's ring, Zhongli's stele) and `summon_rates_2.txt` (Kokomi's jellyfish, Sara's Ambush and
  A4), each read by a fourth member who never takes the field, so every particle reaches them at
  the off-field 0.6 and the mean energy per source divides back into a particle count.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

import pytest

from app.services import formula_energy
from scripts.gcsim.build_key_snapshot import declared_pin

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "formula" / "energy"
SAMPLE = json.loads((FIXTURE / "summon_energy_sample.json").read_text())
RATES = json.loads((FIXTURE / "summon_rates.json").read_text())
TABLE = {name: {s.label: s for s in sources}
         for name, sources in formula_energy.particle_table().items()}
REFUNDS = formula_energy.refund_table()

#: gcsim `energy.go:61-71`.
VALUE = {"same": 3.0, "clear": 2.0, "different": 1.0}
#: Raiden's burst restoration at burst level 9 in our catalogue ("Musou Isshin Energy
#: Restoration", param 17 of the seeded row) — gcsim's `burstRestore[8]` is the same 2.4.
RAIDEN_RESTORE_LV9 = 2.4


def _value(receiver: str, ele: str, elements: dict[str, str]) -> float:
    if ele in ("", "none", "physical"):
        return VALUE["clear"]
    return VALUE["same"] if elements[receiver] == ele else VALUE["different"]


def test_both_outputs_are_at_the_pin() -> None:
    assert SAMPLE["sim_version"] == declared_pin()
    assert RATES["sim_version"] == declared_pin()


@pytest.mark.parametrize(
    "event", SAMPLE["particles"], ids=lambda e: f"{e['frame']}-{e['receiver']}-{e['source']}",
)
def test_every_particle_is_count_times_value_times_field_times_er(event: dict) -> None:
    field = 1.0 if event["is_active"] else 1.0 - 0.1 * event["party_count"]
    value = _value(event["receiver"], event["ele"], SAMPLE["elements"])
    assert event["amt"] == pytest.approx(event["count"] * value * field * event["er"], rel=1e-12)


#: gcsim's default particle delay (`pkg/core/player/character/character.go:144`).
PARTICLE_DELAY = 100


def test_a_favonius_proc_is_three_clear_particles_caught_by_whoever_is_active_on_landing() -> None:
    """gcsim `favonius.go:44`: a proc needs the wielder active, and its 3 clear particles land
    100 frames later. So the wielder catches them on field **unless someone else took the
    field in those 100 frames** — which is what the panel's 100 % for the optimized wielder,
    0 % for a teammate's proc, assume, and why both are editable."""
    fav = [e for e in SAMPLE["particles"] if e["source"] == "favonius-raidenshogun"]
    assert {e["count"] for e in fav} == {3}
    assert {e["ele"] for e in fav} == {"none"}
    landed = sorted({e["frame"] for e in fav})
    assert landed == [f + PARTICLE_DELAY for f in SAMPLE["favonius_procs"]]
    for frame in landed:
        on_field = [e["receiver"] for e in fav if e["frame"] == frame and e["is_active"]]
        assert len(on_field) == 1
        swapped_in = [c["character"] for c in SAMPLE["casts"]
                      if frame - PARTICLE_DELAY < c["frame"] <= frame
                      and c["character"] != "raidenshogun"]
        assert on_field == (swapped_in[:1] if swapped_in else ["raidenshogun"])
    # In this rotation five of the six land on the wielder; one lands on Zhongli, who took the
    # field to start the next loop inside the delay.
    caught = Counter(e["receiver"] for e in fav if e["is_active"])
    assert caught == Counter({"raidenshogun": 5, "zhongli": 1})


def test_favonius_procs_respect_the_cooldown_our_catalogue_states() -> None:
    """R3: `[0.8, 9, …]` in the catalogue; gcsim's `810 - 90 R` frames is the same 9 s."""
    _, cooldown_s = formula_energy.favonius_proc([0.8, 9, 0, 0, 0, 0, 0, 0])
    procs = SAMPLE["favonius_procs"]
    assert len(procs) >= 2
    assert min(b - a for a, b in pairwise(procs)) >= cooldown_s * 60


def test_raidens_refund_is_flat_five_a_burst_to_every_member() -> None:
    """Each restoration is the row × (1 + 0.006 × whole percent of her ER above 100 %), the
    same to every member on field or off, and never multiplied by the receiver's ER."""
    refunds = [e for e in SAMPLE["flat"] if e["source"] == "raiden-burst"]
    raiden_er = {e["er"] for e in SAMPLE["particles"] if e["receiver"] == "raidenshogun"}
    assert len(raiden_er) == 1
    er = raiden_er.pop()
    expected = RAIDEN_RESTORE_LV9 * (1 + 0.006 * math.floor((er - 1) * 100))
    assert refunds
    for e in refunds:
        assert e["amt"] == pytest.approx(expected, rel=1e-12)
    bursts = [c for c in SAMPLE["casts"] if c["character"] == "raidenshogun"
              and c["action"] == "burst"]
    by_receiver = Counter(e["receiver"] for e in refunds)
    assert set(by_receiver.values()) == {5 * len(bursts)}
    assert len(by_receiver) == 4
    spec = REFUNDS["Raiden Shogun"][0]
    assert (spec.count, spec.recipients, spec.scaling) == (5, "team", "raiden_a4")


def test_summon_hits_per_cast_are_the_tables_cadence() -> None:
    hits = SAMPLE["hits"]
    casts = Counter(c["character"] for c in SAMPLE["casts"] if c["action"] == "skill")
    oz = TABLE["Fischl"]["Oz (from Nightrider)"]
    assert len(hits["Oz (Skill)"]) == casts["fischl"] * oz.max_seconds / oz.interval
    first = TABLE["Sangonomiya Kokomi"]["Bake-Kurage (first tick)"]
    ticks = TABLE["Sangonomiya Kokomi"]["Bake-Kurage (ticks)"]
    assert first.per == "cast"
    assert len(hits["Bake-Kurage"]) == casts["sangonomiyakokomi"] * (
        1 + ticks.max_seconds / ticks.interval)
    stele = TABLE["Zhongli"]["Stone Stele (resonance)"]
    # Between recasts the stele resonates every 120 frames (a recast restarts the clock).
    gaps = Counter(b - a for a, b in pairwise(hits["Stone Stele (Tick)"]))
    assert gaps.most_common(1)[0][0] == stele.interval * 60
    assert gaps[stele.interval * 60] >= len(hits["Stone Stele (Tick)"]) - 2 * casts["zhongli"]


def _particles_per_iteration(run: dict, source: str) -> tuple[float, float]:
    """A source's mean particles per iteration and its standard error, from the receiver's
    mean energy: every particle reaches them off field at 0.6, valued 1 (another element)."""
    stat = run["sources"][source]
    per = 0.6 * run["receiver_er"] * 1.0
    return stat["mean"] / per, stat["sd"] / per / math.sqrt(run["iterations"])


RATE_CASES = [
    # (run, gcsim source, table entry, hits abilities)
    (0, "fischl", ("Fischl", "Oz (from Nightrider)"), ("Oz (Skill)", "Oz (Burst)")),
    (0, "kukishinobu", ("Kuki Shinobu", "Grass Ring of Sanctification"),
     ("Grass Ring of Sanctification",)),
    (1, "sangonomiyakokomi", ("Sangonomiya Kokomi", "Bake-Kurage (ticks)"), ("Bake-Kurage",)),
]


@pytest.mark.parametrize(("run", "source", "entry", "abilities"), RATE_CASES,
                         ids=[c[1] for c in RATE_CASES])
def test_a_summons_chance_per_hit_is_gcsims_over_three_thousand_runs(
    run: int, source: str, entry: tuple[str, str], abilities: tuple[str, ...],
) -> None:
    data = RATES["runs"][run]
    assert data["always_off_field"]
    hits = sum(data["hits"][a] for a in abilities)
    mean, err = _particles_per_iteration(data, source)
    chance = TABLE[entry[0]][entry[1]].chance
    assert chance is not None
    assert mean == pytest.approx(hits * chance, abs=4 * err)


def test_a_steles_particle_icd_eats_a_recast_initial_hit() -> None:
    """Zhongli's 1.5 s ICD: a recast landing within 1.5 s of the old stele's last tick drops
    nothing, so gcsim's count sits a little under hits × 0.5 — the table's note says so."""
    data = RATES["runs"][0]
    hits = data["hits"]["Stone Stele (Tick)"] + data["hits"]["Stone Stele (Initial)"]
    mean, err = _particles_per_iteration(data, "zhongli")
    assert mean < hits * 0.5 - 4 * err
    assert mean > (hits - data["hits"]["Stone Stele (Initial)"]) * 0.5 - 4 * err
    assert "1.5 s" in TABLE["Zhongli"]["Stone Stele (on cast)"].note


def test_saras_ambush_and_a4_are_the_tables() -> None:
    data = RATES["runs"][1]
    ambushes = data["hits"]["Tengu Juurai: Ambush"]
    mean, err = _particles_per_iteration(data, "kujousara")
    assert err == 0  # 3 a hit, no chance
    assert mean == pytest.approx(ambushes * TABLE["Kujou Sara"][
        "Tengu Stormcall (its aimed shot's Ambush)"].particles)
    # A4: 1.2 × her ER (1 + 0.3 substat + 0.2 Emblem = 1.5) to every member, flat.
    spec = REFUNDS["Kujou Sara"][0]
    assert spec.scaling == "per_er"
    assert spec.amount == 1.2
    assert data["sources"]["sara-a4"]["mean"] == pytest.approx(ambushes * 1.2 * 1.5)


def test_flat_energy_events_are_never_scaled_by_the_receivers_er() -> None:
    by_frame: dict[int, set[float]] = defaultdict(set)
    for e in SAMPLE["flat"]:
        by_frame[e["frame"]].add(e["amt"])
    assert all(len(v) == 1 for v in by_frame.values())
