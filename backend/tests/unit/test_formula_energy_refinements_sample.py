"""Electro resonance, Yae's totems and the on-field subject, against gcsim (TASKS 14).

The owner's four refinements of 2026-11-15 (DECISIONS §49, DESIGN §2.11 "Refinements"). Three
committed gcsim samples at the pin (PROVENANCE.md beside them):

- `summon_energy_sample.json` (#393's): Raiden on field with Fischl, Kokomi and Zhongli — an
  Electro resonance team, whose `electro-res` particles gave Raiden 72.6 energy;
- `electro_res_sample.json`: Raiden, Fischl, Xingqiu and Bennett, a second resonance team;
- `yae_energy_sample.json`: Yae Miko casting one totem, then three, each left to expire.
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
SUMMON = json.loads((FIXTURE / "summon_energy_sample.json").read_text())
RES = json.loads((FIXTURE / "electro_res_sample.json").read_text())
YAE = json.loads((FIXTURE / "yae_energy_sample.json").read_text())
VALUE = {"same": 3.0, "clear": 2.0, "different": 1.0}
#: The summon config's rotation: each loop's bursts land 1500 frames apart (its casts).
ROTATION_FRAMES = 1500


def _value(receiver: str, ele: str, elements: dict[str, str]) -> float:
    if ele in ("", "none", "physical"):
        return VALUE["clear"]
    return VALUE["same"] if elements[receiver] == ele else VALUE["different"]


def _field(event: dict) -> float:
    return 1.0 if event["is_active"] else 1.0 - 0.1 * event["party_count"]


def test_the_new_samples_are_at_the_pin() -> None:
    assert RES["sim_version"] == declared_pin()
    assert YAE["sim_version"] == declared_pin()


# ── 1. Electro resonance ─────────────────────────────────────────────────────────────────────

def _resonance(sample: dict) -> list[dict]:
    return [e for e in sample["particles"] if e["source"] == "electro-res"]


@pytest.mark.parametrize("sample", [SUMMON, RES], ids=["summon", "electro_res"])
def test_every_resonance_particle_is_one_electro_particle_valued_like_any_other(
    sample: dict,
) -> None:
    events = _resonance(sample)
    assert events
    spec = formula_energy.resonance_spec()
    for e in events:
        assert e["count"] == spec.particles
        assert e["ele"] == spec.element
        value = _value(e["receiver"], e["ele"], sample["elements"])
        assert e["amt"] == pytest.approx(e["count"] * value * _field(e) * e["er"], rel=1e-12)


@pytest.mark.parametrize("sample", [SUMMON, RES], ids=["summon", "electro_res"])
def test_resonance_procs_never_come_closer_than_the_cooldown(sample: dict) -> None:
    """The bound the panel's proc count is held under: one per 5 s, so `rotation / 5`."""
    frames = sorted({e["frame"] for e in _resonance(sample)})
    cooldown = formula_energy.resonance_spec().cooldown_seconds * 60
    assert min(b - a for a, b in pairwise(frames)) >= cooldown
    # Every member receives each proc at once — distributed, with no landing delay.
    per_frame = Counter(e["frame"] for e in _resonance(sample))
    assert set(per_frame.values()) == {len(sample["elements"])}
    # Three a 25 s rotation in both teams, under the five the cooldown allows.
    rotations = 4
    assert len(frames) == 3 * rotations
    assert len(frames) / rotations <= ROTATION_FRAMES / cooldown


def test_raidens_resonance_energy_is_the_closed_form_at_three_procs_a_rotation() -> None:
    """#393's 72.6: 3 procs × 4 rotations × 3 (her element) × field × her ER, the field being
    her share caught on field (8 of 12 here) — what the panel computes with procs = 3 and that
    share entered."""
    raiden = [e for e in _resonance(SUMMON) if e["receiver"] == "raidenshogun"]
    total = sum(e["amt"] for e in raiden)
    assert total == pytest.approx(72.5795677776, rel=1e-12)
    on = sum(1 for e in raiden if e["is_active"]) / len(raiden)
    assert on == pytest.approx(8 / 12)
    er = raiden[0]["er"]
    field = on + (1 - on) * 0.6
    assert total == pytest.approx(3 * 4 * 1 * 3 * field * er, rel=1e-12)


# ── 2. The on-field subject's summons ────────────────────────────────────────────────────────

def test_an_on_field_subject_catches_the_summons_on_field() -> None:
    """The evidence for ruling 2: Raiden, on field, caught all 24 Oz drops and 28 of her own 36
    Eye drops on field. A summon's particle lands on whoever is active when it lands."""
    raiden = [e for e in SUMMON["particles"] if e["receiver"] == "raidenshogun"]
    oz = [e for e in raiden if e["source"] == "fischl"]
    eye = [e for e in raiden if e["source"] == "raidenshogun"]
    assert (sum(e["is_active"] for e in oz), len(oz)) == (24, 24)
    assert (sum(e["is_active"] for e in eye), len(eye)) == (28, 36)


# ── 4. Yae Miko: gcsim's rate ────────────────────────────────────────────────────────────────

def _yae_particles() -> list[int]:
    return [e["frame"] for e in YAE["particles"] if e["receiver"] == "yaemiko"]


def test_yaes_particles_are_one_per_strike_on_a_single_totem_and_on_three() -> None:
    [totems] = formula_energy.particle_table()["Yae Miko"]
    cadence = round(totems.interval * 60)
    frames = _yae_particles()
    casts = [c["frame"] for c in YAE["casts"] if c["character"] == "yaemiko"]
    assert len(casts) == 4  # one cast, then three
    single = [f for f in frames if f < casts[1]]
    triple = [f for f in frames if f > casts[1]]
    # Every gap is the totem's own cadence, with one totem and with three: the shared ICD
    # turns three totems' strikes into one totem's particles.
    assert {b - a for a, b in pairwise(single)} == {cadence}
    assert {b - a for a, b in pairwise(triple)} == {cadence}
    # Eight for a totem set at full length, alone or three together.
    assert len(single) == 8
    assert len(triple) == 8
    # Three totems strike three times as often; the particles do not follow.
    hits = YAE["totem_hits"]
    assert len([h for h in hits if h > casts[1]]) == 3 * len([h for h in hits if h < casts[1]])


def test_yaes_particles_are_count_times_value_times_field_times_er() -> None:
    for e in YAE["particles"]:
        value = _value(e["receiver"], e["ele"], YAE["elements"])
        assert e["amt"] == pytest.approx(e["count"] * value * _field(e) * e["er"], rel=1e-12)


def test_the_per_second_form_is_within_one_particle_of_gcsims_count() -> None:
    """`max_seconds / interval` = 25 / 2.933 = 8.52 a totem set, against gcsim's 8 whole
    strikes (the first lands 2 s after the cast): the continuous form's rounding, stated."""
    [totems] = formula_energy.particle_table()["Yae Miko"]
    continuous = totems.max_seconds / totems.interval
    assert continuous == pytest.approx(8.52, abs=0.01)
    assert abs(continuous - 8) < 1
