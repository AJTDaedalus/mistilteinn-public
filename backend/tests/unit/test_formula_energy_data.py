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
    if "chance" in source:
        # A summon's hit: `if Rand < p { QueueParticle(n) }` — the expectation per hit.
        text = " ".join(_line(p, n) for p, n, _ in source["lines"])
        chance = re.search(r"Rand\.Float64\(\) < (\d*\.\d+)", text)
        assert chance, f"{name}: a chance source cites its Rand line"
        assert literal, f"{name}: a chance source cites its QueueParticle line"
        assert source["chance"] == float(chance.group(1))
        assert source["particles"] == pytest.approx(source["chance"] * float(literal.group(1)))
    elif literal and len(calls) == 1:
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


def test_a_per_second_rate_is_its_citation() -> None:
    """Furina's one per 3.25 s is KQM's measured average; Nahida's 3 per 7 s her ICD line."""
    furina = TABLE["characters"]["Furina"]["sources"][0]
    assert f"~{furina['interval']} seconds" in furina["kqm"]
    assert furina["max_seconds"] == pytest.approx(1736 / 60, abs=1e-3)
    nahida = TABLE["characters"]["Nahida"]["sources"][0]
    assert f"{nahida['interval']}*60" in _line("internal/characters/nahida/skill.go", 128)


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
    # A character carried only for a refund (Venti) has no particle sources.
    assert set(table) == {n for n, e in TABLE["characters"].items() if e["sources"]}
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


# ── Follow-ups (owner rulings 2026-11-15, DECISIONS §48) ─────────────────────────────────────

REFUNDS = [
    (name, refund)
    for group in ("characters", "constellation_refunds")
    for name, entry in TABLE[group].items()
    for refund in entry.get("refunds", ())
]


@pytest.mark.parametrize(("name", "refund"), REFUNDS, ids=[n for n, _ in REFUNDS])
def test_every_refund_cites_an_add_energy_line_that_says_what_it_claims(
    name: str, refund: dict,
) -> None:
    for path, line, needle in refund["lines"]:
        assert needle in _line(path, line), f"{name}: {path}:{line} does not contain {needle!r}"
    adds = [_line(p, n) for p, n, _ in refund["lines"] if "AddEnergy(" in _line(p, n)]
    assert adds, f"{name}: a refund with no AddEnergy line"
    text = " ".join(_line(p, n) for p, n, _ in refund["lines"])
    if "amount" in refund:
        # The amount is the literal on the cited line (Sara's `1.2 *`, Jean's 16, Venti's 15).
        assert re.search(rf"\b{refund['amount']:g}\b", text), name
    if refund["scaling"] == "per_er":
        assert "* c.NonExtraStat(attributes.ER)" in text
    if refund["scaling"] == "raiden_a4":
        assert "a4Energy(max(c.NonExtraStat(attributes.ER)-1, 0))" in text
        assert "excess := int(er * 100)" in text
    if refund["recipients"] == "team":
        # gcsim adds a team refund inside `for _, char := range c.Core.Player.Chars()`.
        assert "char.AddEnergy(" in text, name
    elif refund["recipients"] in ("others", "absorbed"):
        # The same loop, skipping the giver (`others`) or filtering by element (`absorbed`):
        # the loop line is cited too.
        assert "range c.Core.Player.Chars()" in text, name
        assert re.search(r"\b(char|x|other|this)\.AddEnergy\(", text), name
    elif refund["recipients"] == "active":
        # Whoever is on field when it lands: `active.AddEnergy` / `ActiveChar().AddEnergy`.
        assert re.search(r"(active|ActiveChar\(\))\.AddEnergy\(", text), name
    else:
        assert "c.AddEnergy(" in text, name
    assert refund["per"] in ("burst", "cast", "second")
    assert refund["count"] > 0


def test_raidens_refund_is_five_a_burst_once_a_second() -> None:
    raiden = TABLE["characters"]["Raiden Shogun"]["refunds"][0]
    assert raiden["count"] == 5
    assert "c.restoreCount < 5" in _line("internal/characters/raiden/burst.go", 96)
    assert raiden["amount_row"]["label"] == "Musou Isshin Energy Restoration"


def test_the_favonius_proc_is_gcsims() -> None:
    fav = TABLE["weapons"]["favonius"]
    for path, line, needle in fav["lines"]:
        assert needle in _line(path, line)
    assert fav["particles"] == 3
    assert "3, attributes.NoElement" in _line("internal/weapons/common/favonius.go", 56)
    # Only while the wielder is the active character: who catches the particles follows.
    assert "c.Player.Active() != char.Index()" in _line("internal/weapons/common/favonius.go", 44)


#: Every Favonius weapon's refinement `param_list` in the seeded catalogue (nanoka 7.2.51),
#: verbatim: all five weapons carry the same five rows.
FAVONIUS_ROWS = {
    1: [0.6, 12, 0, 0, 0, 0, 0, 0], 2: [0.7, 10.5, 0, 0, 0, 0, 0, 0],
    3: [0.8, 9, 0, 0, 0, 0, 0, 0], 4: [0.9, 7.5, 0, 0, 0, 0, 0, 0], 5: [1, 6, 0, 0, 0, 0, 0, 0],
}


@pytest.mark.parametrize("refine", [1, 2, 3, 4, 5])
def test_favonius_chance_and_cooldown_by_refinement_match_gcsims_formula(refine: int) -> None:
    """Our catalogue's row, read the way the endpoint reads it, is gcsim's formula."""
    chance, cooldown_s = formula_energy.favonius_proc(FAVONIUS_ROWS[refine])
    assert chance == pytest.approx(0.50 + refine * 0.1)
    assert cooldown_s == pytest.approx((810 - refine * 90) / 60)


def test_summon_cadences_are_their_citations() -> None:
    chars = TABLE["characters"]
    oz = chars["Fischl"]["sources"][0]
    assert "dur := 600" in _line("internal/characters/fischl/skill.go", 128)
    assert oz["max_seconds"] == 600 / 60
    assert chars["Fischl"]["sources"][1]["on"] == "burst"
    ring = chars["Kuki Shinobu"]["sources"][0]
    assert ring["interval"] == 90 / 60
    assert ring["max_seconds"] == 720 / 60
    ticks = chars["Sangonomiya Kokomi"]["sources"][1]
    assert ticks["interval"] == 120 / 60
    stele = chars["Zhongli"]["sources"][1]
    assert stele["interval"] == 120 / 60
    eye = chars["Raiden Shogun"]["sources"][0]
    assert eye["max_seconds"] == 1500 / 60
    # KQM's realistic rate: one strike a second, half of them a particle — 30 a minute.
    assert 60 / eye["interval"] * eye["particles"] == 30
    assert "30P/M when triggered once per second" in eye["kqm"]


# ── Refinements (owner rulings 2026-11-15, DECISIONS §49) ────────────────────────────────────


def test_yae_is_gcsims_rate_one_a_strike_under_a_shared_icd() -> None:
    """Ruling 4: gcsim's rate, with KQM's disagreement recorded beside it."""
    [totems] = TABLE["characters"]["Yae Miko"]["sources"]
    assert "Yae Miko" not in TABLE["not_curated"]
    # One particle a strike (the literal), behind an ICD the character holds — shared by
    # every totem — of 2.5 s, shorter than a totem's own 176-frame cadence.
    skill = "internal/characters/yaemiko/skill.go"
    assert "QueueParticle(c.Base.Key.String(), 1," in _line(skill, 47)
    assert "c.StatusIsActive(particleICDKey)" in _line("internal/characters/yaemiko/skill.go", 43)
    icd = float(re.search(r"particleICDKey, ([\d.]+)\*60", _line(
        "internal/characters/yaemiko/skill.go", 46)).group(1))
    cadence = int(re.search(r"kitsuneTick\(totem\), (\d+)\)", _line(
        "internal/characters/yaemiko/kitsune.go", 166)).group(1))
    assert icd < cadence / 60
    assert totems["interval"] == pytest.approx(cadence / 60, abs=1e-6)
    assert totems["particles"] == 1
    assert totems["shared_icd"] is True
    # 15 s, and Edict of Cleansing's 10 s more, on by default (`revelation = 1`).
    base = int(re.search(r"kitsuneDur = (\d+)", _line(
        "internal/characters/yaemiko/kitsune.go", 13)).group(1))
    bonus = int(re.search(r"return (\d+) \* 60", _line(
        "internal/characters/yaemiko/stellar.go", 51)).group(1)) * 60
    assert "revelation = 1" in _line("internal/characters/yaemiko/yaemiko.go", 39)
    assert totems["max_seconds"] == (base + bonus) / 60
    # The cadence's second citation, and the disagreement, both in the entry.
    assert "Every following hit takes 3s" in totems["kqm"]
    assert "only the first one generates Particles" in totems["kqm"]
    assert "KQM's library disagrees" in totems["note"]
    [source] = formula_energy.particle_table()["Yae Miko"]
    assert source.shared_icd is True


def test_nothing_is_left_to_the_user_now() -> None:
    assert TABLE["not_curated"] == {}
    assert formula_energy.not_curated() == {}


def test_electro_resonance_is_gcsims_high_voltage() -> None:
    """Ruling 1: one Electro particle on an Electro reaction, 5 s cooldown, four members."""
    res = TABLE["resonances"]["electro"]
    for path, line, needle in res["lines"]:
        assert needle in _line(path, line), f"{path}:{line} does not contain {needle!r}"
    setup = "pkg/simulation/setup.go"
    assert "len(chars) < 4" in _line(setup, 108)
    assert "v < 2" in _line(setup, 118)
    frames = int(re.search(r"s\.F-last < (\d+)", _line(setup, 185)).group(1))
    assert res["cooldown_seconds"] == frames / 60
    assert res["particles"] == int(re.search(r"Num:\s+(\d+)", _line(setup, 190)).group(1))
    assert "attributes.Electro" in _line(setup, 191)
    # The reactions it listens to, and the partner element each needs.
    events = {_line(setup, n).split("event.")[1].split(",")[0] for n in range(200, 208)}
    assert events == {"OnOverload", "OnSuperconduct", "OnStellarConduct", "OnElectroCharged",
                      "OnLunarCharged", "OnQuicken", "OnAggravate", "OnHyperbloom"}
    assert set(res["trigger_elements"]) == {"pyro", "cryo", "hydro", "dendro"}
    assert "(CD: 5s)" in res["kqm"]
    spec = formula_energy.resonance_spec()
    assert (spec.element, spec.particles, spec.cooldown_seconds) == ("electro", 1.0, 5.0)
    assert spec.citation.startswith(f"gcsim {declared_pin()[:8]} pkg/simulation/setup.go:")
    assert "KQM library.keqingmains.com" in spec.citation


@pytest.mark.parametrize(("elements", "has", "triggers"), [
    (["electro", "electro", "hydro", "geo"], True, True),
    (["electro", "electro", "anemo", "geo"], True, False),
    (["electro", "electro", "electro", "dendro"], True, True),
    (["electro", "hydro", "geo", "pyro"], False, True),
    (["electro", "electro", "hydro"], False, True),  # three members: no resonance at all
])
def test_the_team_has_high_voltage_by_the_resonance_tally(
    elements: list[str], has: bool, triggers: bool,
) -> None:
    found = formula_energy.team_resonance(elements)
    assert (found is not None) == has
    if found is not None:
        assert found.team_can_trigger == triggers
