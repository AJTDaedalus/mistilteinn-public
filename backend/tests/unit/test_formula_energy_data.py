"""The formula estimate's energy data, held to the gcsim lines it cites (TASKS 14).

`app/data/formula/energy/particles.json` cites every particle count to a gcsim line, and
`gcsim_lines.json` is a verbatim snapshot of those lines at the pin
(`scripts/gcsim/snapshot_particle_lines.py`). These tests read only committed files: no gcsim
source, no network, no database.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services import formula_energy
from app.services.talent_scaling import TalentScalingError, cooldown
from scripts.gcsim.build_key_snapshot import declared_pin

DATA = Path(formula_energy.TABLE).parent
TABLE = json.loads((DATA / "particles.json").read_text())
LINES = json.loads((DATA / "gcsim_lines.json").read_text())


def _line(path: str, line: int) -> str:
    return LINES["lines"][f"{path}:{line}"]


def test_the_table_and_its_snapshot_are_at_the_pin() -> None:
    assert TABLE["gcsim_commit"] == declared_pin()
    assert LINES["gcsim_commit"] == declared_pin()


SOURCES = [
    (name, source)
    for name, entry in TABLE["characters"].items()
    for source in entry["sources"]
]


@pytest.mark.parametrize(("name", "source"), SOURCES, ids=[n for n, _ in SOURCES])
def test_every_cited_line_says_what_the_entry_claims(name: str, source: dict) -> None:
    assert source["lines"], f"{name}: a count with no cited line"
    for path, line, needle in source["lines"]:
        assert needle in _line(path, line), f"{name}: {path}:{line} does not contain {needle!r}"


@pytest.mark.parametrize(("name", "source"), SOURCES, ids=[n for n, _ in SOURCES])
def test_a_fixed_count_is_the_number_on_its_queue_particle_line(name: str, source: dict) -> None:
    """A literal count must be the literal; a random one must be its expectation."""
    calls = [_line(p, n) for p, n, _ in source["lines"] if "QueueParticle" in _line(p, n)]
    assert calls, f"{name}: no QueueParticle line cited"
    literal = re.search(r"QueueParticle\([^,]+, (\d+(?:\.\d+)?),", calls[0])
    if literal and len(calls) == 1:
        # Guoba drops one per hit and hits four times (`hits`, from skill.go:49).
        assert source["particles"] == float(literal.group(1)) * source.get("hits", 1)
    elif name == "Jean":
        # 2, then 1 more with a 0.67 chance (two QueueParticle lines, skill.go:76,88).
        assert source["particles"] == pytest.approx(2 + 0.67)
    else:
        # `count := a; if Rand < p { count = b }`: the cited lines carry a, p and b.
        text = " ".join(_line(p, n) for p, n, _ in source["lines"])
        found = re.search(r"count := (\d+)\.0.*< ([\d.]+).*count = (\d+)", text)
        fixed = re.search(r"count := (\d+)\.0", text)
        if found:
            a, p, b = float(found.group(1)), float(found.group(2)), float(found.group(3))
            assert source["particles"] == pytest.approx(a + p * (b - a))
        elif fixed and "Rand" not in text:
            assert source["particles"] == float(fixed.group(1))
        else:
            # A count held in a named constant or a callback factory (Neuvillette, Kazuha).
            constant = re.search(r"(?:particleCount\s*=|makeParticleCB\()\s*(\d+)", text)
            assert constant, f"{name}: no count found in the cited lines"
            assert source["particles"] == float(constant.group(1))


def test_the_model_constants_are_gcsims() -> None:
    """The four rules `formula-energy.ts` applies, each on the line it cites."""
    def block(name: str) -> str:
        path, start, end = LINES["constants"][name]
        return "\n".join(_line(path, n) for n in range(start, end + 1))

    assert "r = 1.0 - 0.1*float64(partyCount)" in block("off_field")
    values = block("particle_value")
    assert "case c.Base.Element:\namt = 3" in values
    assert "case attributes.NoElement:\namt = 2" in values
    assert "default:\namt = 1" in values
    assert "amt = amt * er * p.Num" in block("er_multiplies")
    # Flat energy is added as-is, never multiplied by ER.
    assert "c.Energy += e" in block("flat_energy")
    assert "ER" not in block("flat_energy")
    assert "ReceiveParticle(p, h.active == i, len(h.chars))" in block("distribute")
    assert "max((amount-charFlatEnergy[ind])/charRawParticles[ind], 1.0)" in block("requirement")
    assert "Ele:    attributes.NoElement" in block("drip")


def test_the_drip_is_the_mean_of_gcsims_energy_every() -> None:
    drip = formula_energy.drip()
    # interval=480,720: 480 + Intn(240), whose mean is 119.5 — 599.5 frames.
    assert drip.interval_seconds == pytest.approx(599.5 / 60)
    assert drip.particles == 1
    assert "interval=480,720" in drip.config


def test_every_source_parses_with_its_citation() -> None:
    table = formula_energy.particle_table()
    assert set(table) == set(TABLE["characters"])
    for name, sources in table.items():
        for source in sources:
            assert source.citation.startswith(f"gcsim {declared_pin()[:8]} internal/characters/")
            assert source.particles > 0, name
            if source.per == "second":
                assert source.interval, name


def test_beta_characters_are_not_in_the_table() -> None:
    """The table carries released characters only; a beta name would be a leak."""
    keys = {entry["gcsim_key"] for entry in TABLE["characters"].values()}
    assert len(keys) == len(TABLE["characters"])


def test_cooldown_reads_the_first_value_of_the_cd_row() -> None:
    labels = ["Skill DMG|{param1:P}", "Duration|{param5:F1}s", "CD|{param6:F1}s", ""]
    assert cooldown(labels, [3.9, 0, 0, 0, 12.0, 15.0]) == 15.0
    bennett = ["Tap DMG|{param1:P}", "CD|{param7:F1}/{param8:F1}/{param9:F1}s"]
    assert cooldown(bennett, [2.3, 0, 0, 0, 0, 0, 5.0, 7.5, 10.0]) == 5.0
    assert cooldown(["Skill DMG|{param1:P}"], [1.0]) is None
    with pytest.raises(TalentScalingError):
        cooldown(["CD|no param"], [1.0])
