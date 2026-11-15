"""The team's energy data for the formula estimate: particles per skill, burst costs, the drip.

Math-fallback P3, task 14 (`docs/DESIGN_team_math_fallback.md` §2.10). The browser's energy
model (`frontend/src/app/sim/formula-energy.ts`) does the arithmetic; this serves what it reads:

- each member's **burst energy cost** (`Character.burst_energy_cost`, game data) and **burst
  cooldown** (the burst talent's own `CD` row, game data), the second only to default the
  rotation length;
- each member's **Elemental Skill particles**, curated in `app/data/formula/energy/particles.json`
  with every count cited to the gcsim line it is read off (the game data's `energy[]` rows
  publish per-drop entries, not a count per cast: Kazuha's `per_drop` is 1 where his tap gives
  3, so they are not used as counts — DESIGN §2.10);
- the **energy drip** gcsim's waiting model already emits (`gcsim_config.ENERGY_DRIP`), as a
  mean interval: one clear particle every `start + (end - start - 1) / 2` frames, the
  expectation of `pkg/simulation/setup.go:522-531` at the pin.

A member with no curated count is `no_particle_data`, named, never zero by default without
saying so.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from app.models.enums import TalentType
from app.services import talent_scaling
from app.services.gcsim_config import ENERGY_DRIP

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.models.build import Build

TABLE = Path(__file__).resolve().parents[1] / "data" / "formula" / "energy" / "particles.json"

#: gcsim simulates at 60 frames a second (`pkg/core/player/character/energy.go` reads frames).
FRAMES_PER_SECOND = 60

_DRIP = re.compile(r"interval=(\d+),(\d+) amount=(\d+)")


class FormulaEnergyError(ValueError):
    """The particle table or a member's data cannot answer."""


@dataclass(frozen=True, slots=True)
class ParticleSource:
    """One Elemental Skill particle source, as `particles.json` curates it."""

    label: str
    #: `cast`: `particles` per cast. `second`: `particles` every `interval` seconds while it
    #: runs, at most `max_seconds` of a rotation.
    per: Literal["cast", "second"]
    particles: float
    collector: Literal["caster", "active"]
    citation: str
    interval: float | None = None
    max_seconds: float | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class MemberEnergy:
    """One member's energy data."""

    build_id: str
    name: str
    element: str | None
    burst_energy_cost: int | None
    burst_cooldown: float | None
    is_subject: bool
    status: Literal["curated", "no_particle_data"]
    sources: tuple[ParticleSource, ...] = ()


@dataclass(frozen=True, slots=True)
class Drip:
    """The enemy-particle drip, as the mean of gcsim's `energy every`."""

    particles: float
    interval_seconds: float
    config: str
    citation: str


@dataclass(frozen=True, slots=True)
class TeamEnergy:
    """Every member's energy data, the subject's flagged, and the drip."""

    members: list[MemberEnergy] = field(default_factory=list)
    drip: Drip | None = None
    gcsim_commit: str = ""


def _citation(lines: list[list[Any]], commit: str) -> str:
    by_file: dict[str, list[str]] = {}
    for path, line, _needle in lines:
        by_file.setdefault(str(path), []).append(str(line))
    cited = "; ".join(f"{path}:{','.join(ns)}" for path, ns in by_file.items())
    return f"gcsim {commit[:8]} {cited}"


@cache
def particle_table() -> dict[str, tuple[ParticleSource, ...]]:
    """`particles.json` by catalogue character name, each source with its citation."""
    data = json.loads(TABLE.read_text())
    commit = str(data["gcsim_commit"])
    out: dict[str, tuple[ParticleSource, ...]] = {}
    for name, entry in data["characters"].items():
        sources = []
        for s in entry["sources"]:
            if s["per"] not in ("cast", "second") or s["collector"] not in ("caster", "active"):
                msg = f"{name}: unknown per {s['per']!r} or collector {s['collector']!r}"
                raise FormulaEnergyError(msg)
            if s["per"] == "second" and not s.get("interval"):
                msg = f"{name}: a per-second source needs an interval"
                raise FormulaEnergyError(msg)
            citation = _citation(s["lines"], commit)
            if s.get("kqm"):
                citation += f"; KQM {s['kqm']}"
            sources.append(ParticleSource(
                label=s["label"], per=s["per"], particles=float(s["particles"]),
                collector=s["collector"], citation=citation,
                interval=s.get("interval"), max_seconds=s.get("max_seconds"),
                note=s.get("note"),
            ))
        out[name] = tuple(sources)
    return out


def table_commit() -> str:
    """The gcsim commit the particle table cites."""
    return str(json.loads(TABLE.read_text())["gcsim_commit"])


def drip() -> Drip:
    """`ENERGY_DRIP` as a mean: one clear particle per mean gap.

    `setup.go:522-531` schedules the next drop once `start` frames have passed since the last,
    `Intn(end - start)` frames later, so the gap is `start + U{0..end-start-1}`: a mean of
    `start + (end - start - 1) / 2` frames, 599.5 for `interval=480,720`.
    """
    found = _DRIP.search(ENERGY_DRIP)
    if found is None:
        msg = f"ENERGY_DRIP is not an `energy every` line: {ENERGY_DRIP!r}"
        raise FormulaEnergyError(msg)
    start, end, amount = (int(g) for g in found.groups())
    gap = start + (end - start - 1) / 2
    return Drip(
        particles=float(amount), interval_seconds=gap / FRAMES_PER_SECOND, config=ENERGY_DRIP,
        citation=f"gcsim {table_commit()[:8]} pkg/simulation/setup.go:522-531 (a clear "
                 "particle, `Intn(end - start)` frames after `start`); the line is "
                 "app/services/gcsim_config.py ENERGY_DRIP, cited to five community configs "
                 "(docs/DESIGN_waiting_for_energy.md)",
    )


def burst_cooldown(build: Build) -> float | None:
    """The burst's cooldown from its own `CD` row at its lowest published level."""
    for talent in build.character.talents:
        if talent.talent_type != TalentType.ELEMENTAL_BURST or not talent.scalings:
            continue
        row = min(talent.scalings, key=lambda s: s.level)
        return talent_scaling.cooldown(list(row.labels), list(row.params))
    return None


def team_energy(members: Sequence[Build], subject_build_id: str) -> TeamEnergy:
    """Every member's energy data. The subject must be one of the members."""
    if not any(str(b.id) == subject_build_id for b in members):
        msg = "the optimized build is not one of the members"
        raise FormulaEnergyError(msg)
    table = particle_table()
    out = []
    for build in members:
        character = build.character
        sources = table.get(character.name, ())
        out.append(MemberEnergy(
            build_id=str(build.id), name=character.name,
            element=character.element.value.lower() if character.element else None,
            burst_energy_cost=character.burst_energy_cost,
            burst_cooldown=burst_cooldown(build),
            is_subject=str(build.id) == subject_build_id,
            status="curated" if sources else "no_particle_data",
            sources=sources,
        ))
    return TeamEnergy(members=out, drip=drip(), gcsim_commit=table_commit())
