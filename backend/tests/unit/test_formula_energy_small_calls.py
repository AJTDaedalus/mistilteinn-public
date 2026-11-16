"""The owner's three small calls on the energy model (2026-11-15, DECISIONS §50, TASKS 14).

1. Electro resonance's default procs are the rate gcsim's committed samples show, not the
   cooldown ceiling.
2. The enemy-particle drip lands on whoever is active (gcsim `DistributeParticle`), so an
   on-field subject catches it on field — the browser's default; the citation is checked here.
3. Venti's A4 also gives 15 to every member of the element his burst absorbed, and
   constellation refunds gcsim implements as `AddEnergy` are served, gated by the giver's
   constellation.

Committed files only: no gcsim source, no network, no database.
"""

from __future__ import annotations

import json
import re
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import formula_energy

DATA = Path(formula_energy.TABLE).parent
TABLE = json.loads((DATA / "particles.json").read_text())
LINES = json.loads((DATA / "gcsim_lines.json").read_text())
BACKEND = Path(__file__).resolve().parents[2]


def _line(path: str, line: int) -> str:
    return LINES["lines"][f"{path}:{line}"]


# ── 1. Electro resonance: the samples' rate ──────────────────────────────────────────────────

def _bursts(sample: dict) -> list[int]:
    return [c["frame"] for c in sample["casts"]
            if c["character"] == "raidenshogun" and c["action"] == "burst"]


def _procs(sample: dict) -> list[int]:
    return sorted({e["frame"] for e in sample["particles"] if e["source"] == "electro-res"})


def test_the_default_rate_is_the_committed_samples_three_a_rotation() -> None:
    res = TABLE["resonances"]["electro"]
    samples = [json.loads((BACKEND / p).read_text()) for p in res["default_samples"]]
    assert len(samples) == 2
    for sample in samples:
        bursts = _bursts(sample)
        procs = _procs(sample)
        # Four rotations (one Raiden burst each, bursts free) and three procs each: the
        # samples' own count, which the tests beside them pin per sample.
        assert len(procs) == 3 * len(bursts) == 12
        gaps = [b - a for a, b in pairwise(bursts)]
        mean_seconds = sum(gaps) / len(gaps) / 60
        # The rate, 3 a 25 s rotation, gives the sample's own 3 a rotation to 1 %.
        assert res["default_procs_per_second"] * mean_seconds == pytest.approx(3, rel=0.01)
    assert res["default_procs_per_second"] == pytest.approx(3 / 25)
    # Under the ceiling, one every cooldown.
    assert res["default_procs_per_second"] < 1 / res["cooldown_seconds"]


def test_the_resonance_spec_serves_the_default_rate_and_its_note() -> None:
    spec = formula_energy.resonance_spec()
    assert spec.default_procs_per_second == pytest.approx(0.12)
    assert "summon_energy_sample.json" in spec.default_note
    assert "electro_res_sample.json" in spec.default_note


# ── 2. The drip lands on whoever is active ───────────────────────────────────────────────────

def test_the_drip_is_distributed_to_the_active_character_at_full_value() -> None:
    """`energy every` queues a `DistributeParticle`, which hands each member `active == i`."""
    assert "s.C.Player.DistributeParticle(character.Particle{" in _line(
        "pkg/simulation/setup.go", 527)
    assert "char.ReceiveParticle(p, h.active == i, len(h.chars))" in _line(
        "pkg/core/player/player.go", 199)
    assert "pkg/core/player/player.go:197-200" in formula_energy.drip().citation


# ── 3. Venti's absorbed element ──────────────────────────────────────────────────────────────

def _venti() -> list[dict]:
    return TABLE["characters"]["Venti"]["refunds"]


def test_ventis_a4_gives_the_absorbed_elements_members_15() -> None:
    [absorbed] = [r for r in _venti() if r["recipients"] == "absorbed"]
    asc = "internal/characters/venti/asc.go"
    burst = "internal/characters/venti/burst.go"
    assert absorbed["amount"] == 15
    assert 'char.AddEnergy("venti-a4", 15)' in _line(asc, 19)
    assert "char.Base.Element == c.qAbsorb" in _line(asc, 18)
    assert "c.qAbsorb == attributes.NoElement" in _line(asc, 14)
    assert absorbed["requires_ascension"] == 4
    assert "c.Base.Ascension >= 4" in _line(burst, 69)
    # gcsim's absorption priority, in order (burst.go:102), is what the default reads.
    order = _line(burst, 102).split("absorbCheckLocation, ")[1]
    assert absorbed["absorbs"] == [
        e.strip().removeprefix("attributes.").lower() for e in order.rstrip(")").split(",")]
    assert absorbed["absorbs"] == ["pyro", "hydro", "electro", "cryo"]


def test_ventis_self_refund_is_still_his_own() -> None:
    [own] = [r for r in _venti() if r["recipients"] == "self"]
    assert own["amount"] == 15
    assert 'c.AddEnergy("venti-a4", 15)' in _line("internal/characters/venti/asc.go", 13)


def test_the_absorbed_refund_is_served_with_its_priority() -> None:
    [spec] = [r for r in formula_energy.refund_table()["Venti"] if r.recipients == "absorbed"]
    assert spec.absorbs == ("pyro", "hydro", "electro", "cryo")
    assert spec.citation.startswith("gcsim ")


# ── 3b. Constellation refunds ────────────────────────────────────────────────────────────────

CONS = [
    (name, refund)
    for name, entry in TABLE["constellation_refunds"].items()
    for refund in entry["refunds"]
]
CITED = {
    f"{path}:{line}"
    for group in ("characters", "constellation_refunds")
    for entry in TABLE[group].values()
    for refund in entry.get("refunds", ())
    for path, line, _needle in refund["lines"]
}


def test_every_add_energy_call_at_the_pin_is_curated_or_says_why_not() -> None:
    """The sweep is complete: each `AddEnergy(` in gcsim's character packages at the pin is
    cited by a refund or listed with a reason it is not curated, so the next re-pin's new call
    arrives as a red test rather than a refund nobody counted."""
    inventory = set(LINES["add_energy"])
    assert len(inventory) == 93
    uncurated = TABLE["uncurated_add_energy"]
    assert all(reason.strip() for reason in uncurated.values())
    assert not set(uncurated) & CITED, "a call both curated and listed as not"
    assert inventory <= CITED | set(uncurated), sorted(inventory - CITED - set(uncurated))
    # Every Traveler's is listed: the catalogue names every Traveler "Traveler".
    assert all(k in uncurated for k in inventory if "/traveler/" in k)


@pytest.mark.parametrize(("name", "refund"), CONS, ids=[n for n, _ in CONS])
def test_a_constellation_refund_cites_its_constellation_gate(name: str, refund: dict) -> None:
    n = refund["requires_constellation"]
    assert 1 <= n <= 6, name
    text = " ".join(_line(p, ln) for p, ln, _ in refund["lines"])
    gate = rf"Cons\s*(?:(?:>=|<|==)\s*{n}|>\s*{n - 1})\b"  # Lisa's is `Cons > 0`
    assert re.search(gate, text), f"{name}: no C{n} gate cited"
    assert refund["label"].startswith(f"C{n}:"), name
    basis = refund["basis"]
    if basis in ("kit", "assumption"):
        assert isinstance(refund["amount"], (int, float)), name
        assert refund["count"] > 0, name
    if basis != "kit":
        assert refund["condition"].strip(), f"{name}: a {basis} refund says why"
    if refund["per"] == "second":
        assert refund["interval"] > 0, name
        assert refund["on"] in ("skill", "burst", "rotation"), name


def test_the_counted_constellation_refunds_are_the_reviewed_nine() -> None:
    """Counted by default: a fixed number a burst or a cast, the kit's alone. A change to this
    list is a deliberate decision, not a side effect."""
    counted = [(name, r["label"]) for name, r in CONS if r["basis"] == "kit"]
    assert {name for name, _ in counted} == {
        "Kaeya", "Thoma", "Klee", "Furina", "Shikanoin Heizou", "Diona", "Aino", "Barbara",
        "Ororon",
    }
    assert len(counted) == 9


def test_klees_c6_is_three_ticks_of_3_to_every_other_member() -> None:
    [klee] = TABLE["constellation_refunds"]["Klee"]["refunds"]
    burst = "internal/characters/klee/burst.go"
    loop = re.search(r"i := burstStart \+ (\d+); i < burstStart\+(\d+); i \+= (\d+)",
                     _line(burst, 81))
    assert loop
    first, end, step = (int(g) for g in loop.groups())
    assert klee["count"] == len(range(first, end, step)) == 3
    assert klee["amount"] == 3
    assert klee["recipients"] == "others"
    assert "if i == c.Index() {" in _line(burst, 89)


def test_kaeya_thoma_diona_ororon_heizou_and_aino_are_once_a_trigger() -> None:
    by_name = {name: r for name, r in CONS if r["basis"] == "kit"}
    expected = {"Kaeya": (15, "burst"), "Thoma": (15, "burst"), "Diona": (15, "burst"),
                "Ororon": (8, "burst"), "Shikanoin Heizou": (9.0, "burst"),
                "Aino": (10, "cast")}
    for name, (amount, per) in expected.items():
        r = by_name[name]
        assert (r["amount"], r["per"], r["count"], r["recipients"]) == (amount, per, 1, "self")


def test_furina_and_barbara_are_rates() -> None:
    by_name = {name: r for name, r in CONS if r["basis"] == "kit"}
    furina, barbara = by_name["Furina"], by_name["Barbara"]
    assert "c.AddStatus(c4IcdKey, 5*60, true)" in _line("internal/characters/furina/cons.go", 50)
    assert (furina["interval"], furina["on"]) == (5, "skill")
    # skillMaxDuration 1736 frames: the Salon's whole life.
    assert furina["max_seconds"] == pytest.approx(1736 / 60, abs=0.01)
    assert "delay+10*60" in _line("internal/characters/barbara/cons.go", 15)
    assert (barbara["interval"], barbara["on"]) == (10, "rotation")
    assert "max_seconds" not in barbara


def _build(name: str, cons: int, ascension: int = 6) -> SimpleNamespace:
    return SimpleNamespace(
        character=SimpleNamespace(name=name, talents=[]), constellation_level=cons,
        ascension_phase=ascension, talent_levels={},
    )


def _refunds(name: str, cons: int) -> tuple[formula_energy.Refund, ...]:
    return formula_energy._refunds(_build(name, cons))  # type: ignore[arg-type]


def test_a_build_below_the_constellation_is_not_served_the_refund() -> None:
    assert _refunds("Kaeya", 5) == ()
    [c6] = _refunds("Kaeya", 6)
    assert (c6.amount, c6.basis, c6.requires_constellation) == (15.0, "kit", 6)
    assert [r.requires_constellation for r in _refunds("Barbara", 1)] == [1]
    assert sorted(r.requires_constellation or 0 for r in _refunds("Barbara", 6)) == [1, 4]


def test_a_fight_refund_is_served_with_its_reason_and_an_assumption_with_its_condition() -> None:
    [tartaglia] = _refunds("Tartaglia", 6)
    assert tartaglia.basis == "fight"
    assert "OnTargetDied" in (tartaglia.condition or "")
    [navia] = _refunds("Navia", 1)
    assert navia.basis == "assumption"
    assert "shrapnel" in (navia.condition or "")
