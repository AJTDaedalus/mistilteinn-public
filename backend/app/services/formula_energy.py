"""The team's energy data for the formula estimate: particles per skill, burst costs, the drip.

Math-fallback P3, task 14 (`docs/DESIGN_team_math_fallback.md` §2.11). The browser's energy
model (`frontend/src/app/sim/formula-energy.ts`) does the arithmetic; this serves what it reads:

- each member's **burst energy cost** (`Character.burst_energy_cost`, game data) and **burst
  cooldown** (the burst talent's own `CD` row, game data), the second only to default the
  rotation length;
- each member's **Elemental Skill particles**, curated in `app/data/formula/energy/particles.json`
  with every count cited to the gcsim line it is read off (the game data's `energy[]` rows
  publish per-drop entries, not a count per cast: Kazuha's `per_drop` is 1 where his tap gives
  3, so they are not used as counts — DESIGN §2.11);
- the **energy drip** gcsim's waiting model already emits (`gcsim_config.ENERGY_DRIP`), as a
  mean interval: one clear particle every `start + (end - start - 1) / 2` frames, the
  expectation of `pkg/simulation/setup.go:522-531` at the pin.

A member with no curated count is `no_particle_data`, named, never zero by default without
saying so.

**Follow-ups (owner rulings 2026-11-15, DESIGN §2.11, DECISIONS §48).** Summons whose particles
come with a chance per hit carry that chance and a cited hit cadence; a kit's **flat refunds**
(gcsim `AddEnergy`: Raiden's burst, Sara's and Jean's and Venti's A4) are served per member with
their amount, recipients and how they scale; and a member holding a **Favonius** weapon is
served with the proc's chance and cooldown from our catalogue's refinement row, and the
member's own crit rate and ER (pass 1, `kit_buffs.pass_one`) that the proc count and the
ER-scaled refunds read.

**Refinements (owner rulings 2026-11-15, DESIGN §2.11, DECISIONS §49).** A team with **Electro
resonance** (four members, two Electro: the tally `resonance.py` applies) is served the
resonance's particle — one Electro particle a qualifying reaction, a 5 s cooldown, cited to
gcsim's `SetupResonance` and KQM's resonance table — and whether any member can react with
Electro at all. **Yae Miko** is curated at gcsim's rate: one particle a totem strike, a 2.5 s
ICD shared by her totems (`shared_icd`, so skill casts do not multiply it), at a totem's
176-frame cadence for the totems' 25 s. The browser decides the proc count, the on-field
shares and the per-candidate Favonius crit rate.

**Small calls (owner rulings 2026-11-15, DESIGN §2.11, DECISIONS §50).** The resonance carries
its default proc rate, 0.12 a second (3 a 25 s rotation), read off the two committed gcsim
samples it names; the drip's citation names who catches it (whoever is active,
`player.go:197-200`). Venti's A4 also gives 15 to every member of the element his burst
absorbed (`recipients: absorbed`, with gcsim's absorption order). **Constellation refunds**:
every constellation `AddEnergy` in gcsim's character packages at the pin is curated
(`constellation_refunds`), each served only to a build with that constellation and with its
`basis` — `kit` (counted), `assumption` (a toggle the browser leaves off, its `condition`
stated) or `fight` (never counted, `condition` saying why) — and every other `AddEnergy` call is
listed with why it is not curated (`uncurated_add_energy`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from app.formula.genshin import resonance, sheets, tags
from app.models.enums import TalentType
from app.pando.calculator import Calculator
from app.services import kit_buffs, talent_scaling
from app.services.build_assembler import BuildAssemblyError
from app.services.gcsim_config import ENERGY_DRIP
from app.services.stat_calculator import StatInputError
from app.services.talent_boosts import TalentBoostError, effective_talent_levels

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
    #: `skill`: counted per skill cast. `burst`: per burst (Oz from Fischl's burst).
    on: Literal["skill", "burst"] = "skill"
    #: A summon hit's chance of a particle, the literal on its `Rand` line; `particles` is it
    #: times the particles a hit drops.
    chance: float | None = None
    #: The particle ICD is the character's, shared by every summon of the source (Yae's
    #: totems, `yaemiko/skill.go:43`): more casts standing together add no particles, so skill
    #: casts do not multiply it.
    shared_icd: bool = False


@dataclass(frozen=True, slots=True)
class ResonanceSpec:
    """Electro resonance's particle (High Voltage), as `particles.json` curates it."""

    name: str
    element: str
    particles: float
    cooldown_seconds: float
    #: Team elements whose reaction with Electro triggers it (gcsim `setup.go:200-207`).
    trigger_elements: tuple[str, ...]
    note: str
    citation: str
    #: The default procs a second of rotation: the rate gcsim's committed samples show (owner
    #: ruling 2026-11-15, DECISIONS §50), still capped by the cooldown in the browser.
    default_procs_per_second: float = 0.0
    default_note: str = ""


@dataclass(frozen=True, slots=True)
class TeamResonance:
    """A team's High Voltage: the spec, and whether a member can react with Electro at all."""

    spec: ResonanceSpec
    #: A member of a trigger element is on the team, so a qualifying reaction is possible.
    team_can_trigger: bool


#: When a refund triggers: per `burst`, per skill `cast`, or every `interval` seconds while it
#: runs (`second`, at most `max_seconds` a trigger, the trigger being a burst or a cast: `on`).
RefundPer = Literal["burst", "cast", "second"]
#: Who receives it: every member (`team`), the giver (`self`), every member but the giver
#: (`others`), whoever is on field when it lands (`active`), or every member of the element
#: Venti's burst absorbed (`absorbed`, DECISIONS §50).
Recipients = Literal["team", "self", "others", "active", "absorbed"]
#: Whether it is counted: `kit` — a fixed number a trigger, counted; `assumption` — it depends
#: on the fight, but a stated, cited assumption makes it countable: a toggle, off by default;
#: `fight` — it depends on the fight and no assumption answers it: listed, never counted.
Basis = Literal["kit", "assumption", "fight"]

_PERS = ("burst", "cast", "second")
_RECIPIENTS = ("team", "self", "others", "active", "absorbed")
_BASES = ("kit", "assumption", "fight")


@dataclass(frozen=True, slots=True)
class RefundSpec:
    """One flat-energy refund as `particles.json` curates it, before a build resolves it."""

    label: str
    per: RefundPer
    count: float
    recipients: Recipients
    scaling: Literal["none", "per_er", "raiden_a4"]
    citation: str
    amount: float | None = None
    #: `(talent type, label)`: the amount is that talent row's value at the build's level.
    amount_row: tuple[str, str] | None = None
    requires_ascension: int | None = None
    note: str | None = None
    #: The giver's constellation it needs; a build below it is not served the refund at all.
    requires_constellation: int | None = None
    basis: Basis = "kit"
    #: The assumption a toggle states, or why a `fight` refund is not counted.
    condition: str | None = None
    #: Venti's absorption priority (gcsim `venti/burst.go:102`), for `absorbed` recipients.
    absorbs: tuple[str, ...] | None = None
    interval: float | None = None
    max_seconds: float | None = None
    #: What starts a per-second refund: a skill cast, a burst, or nothing (`rotation`: it runs
    #: the whole fight, Barbara's C1).
    on: Literal["skill", "burst", "rotation"] = "burst"


@dataclass(frozen=True, slots=True)
class Refund:
    """A refund resolved for one build: energy per trigger before scaling, or why not."""

    label: str
    per: RefundPer
    count: float
    recipients: Recipients
    scaling: Literal["none", "per_er", "raiden_a4"]
    amount: float | None
    citation: str
    note: str | None = None
    #: Why the refund cannot be counted for this build (an ascension it lacks, a missing row).
    unavailable: str | None = None
    requires_constellation: int | None = None
    basis: Basis = "kit"
    condition: str | None = None
    absorbs: tuple[str, ...] | None = None
    interval: float | None = None
    max_seconds: float | None = None
    on: Literal["skill", "burst", "rotation"] = "burst"


@dataclass(frozen=True, slots=True)
class FavoniusProc:
    """A member's Favonius weapon: the proc's chance and cooldown at their refinement."""

    weapon: str
    refinement: int
    chance: float
    cooldown_seconds: float
    particles: float
    citation: str


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
    refunds: tuple[Refund, ...] = ()
    favonius: FavoniusProc | None = None
    #: The build's own totals (pass 1), as fractions: what the proc count and an ER-scaled
    #: refund read for a teammate. `None` when the build's stats cannot be assembled.
    energy_recharge: float | None = None
    crit_rate: float | None = None
    #: Why a member is left to the user (`not_curated`), when the table says.
    note: str | None = None


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
    #: Electro resonance's particles, when the team has the resonance (refinements, §49).
    resonance: TeamResonance | None = None


def _citation(lines: list[list[Any]], commit: str) -> str:
    by_file: dict[str, list[str]] = {}
    for path, line, _needle in lines:
        by_file.setdefault(str(path), []).append(str(line))
    cited = "; ".join(f"{path}:{','.join(ns)}" for path, ns in by_file.items())
    return f"gcsim {commit[:8]} {cited}"


def _load() -> dict[str, Any]:
    return json.loads(TABLE.read_text())


def _cited(entry: dict[str, Any], commit: str) -> str:
    citation = _citation(entry["lines"], commit)
    if entry.get("kqm"):
        citation += f"; KQM {entry['kqm']}"
    return citation


@cache
def particle_table() -> dict[str, tuple[ParticleSource, ...]]:
    """`particles.json` by catalogue character name, each source with its citation.

    A character carried only for a refund (Venti) has no sources and is not in this map.
    """
    data = _load()
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
            if s.get("on", "skill") not in ("skill", "burst"):
                msg = f"{name}: unknown on {s['on']!r}"
                raise FormulaEnergyError(msg)
            sources.append(ParticleSource(
                label=s["label"], per=s["per"], particles=float(s["particles"]),
                collector=s["collector"], citation=_cited(s, commit),
                interval=s.get("interval"), max_seconds=s.get("max_seconds"),
                note=s.get("note"), on=s.get("on", "skill"), chance=s.get("chance"),
                shared_icd=bool(s.get("shared_icd", False)),
            ))
        if sources:
            out[name] = tuple(sources)
    return out


@cache
def refund_table() -> dict[str, tuple[RefundSpec, ...]]:
    """Each character's flat-energy refunds, cited to the `AddEnergy` line they are read off.

    The kits' own (`characters`) and the constellation refunds (`constellation_refunds`, owner
    ruling 2026-11-15, DECISIONS §50), in that order.
    """
    data = _load()
    commit = str(data["gcsim_commit"])
    out: dict[str, tuple[RefundSpec, ...]] = {}
    groups = [*data["characters"].items(), *data.get("constellation_refunds", {}).items()]
    for name, entry in groups:
        specs = list(out.get(name, ()))
        for r in entry.get("refunds", ()):
            if (r["per"] not in _PERS or r["recipients"] not in _RECIPIENTS
                    or r["scaling"] not in ("none", "per_er", "raiden_a4")
                    or r.get("basis", "kit") not in _BASES
                    or r.get("on", "burst") not in ("skill", "burst", "rotation")):
                msg = f"{name}: a refund with an unknown per, recipients, scaling or basis: {r}"
                raise FormulaEnergyError(msg)
            named = ("amount" in r) + ("amount_row" in r)
            if named > 1 or (named == 0 and r.get("basis", "kit") != "fight"):
                # A `fight` refund is never counted, so one whose amount is not a literal
                # (Sethos's C6 returns what his A1 drained) may leave it out.
                msg = f"{name}: a refund names an amount or a talent row, exactly one"
                raise FormulaEnergyError(msg)
            if r["per"] == "second" and not r.get("interval"):
                msg = f"{name}: a per-second refund needs an interval"
                raise FormulaEnergyError(msg)
            if r["per"] == "second" and r.get("on") != "rotation" and not r.get("max_seconds"):
                msg = f"{name}: a per-second refund on a cast or burst needs a duration"
                raise FormulaEnergyError(msg)
            if r.get("basis", "kit") != "kit" and not r.get("condition"):
                msg = f"{name}: a refund that is not the kit's alone says why (condition)"
                raise FormulaEnergyError(msg)
            if (r["recipients"] == "absorbed") != bool(r.get("absorbs")):
                msg = f"{name}: an absorbed-element refund names the absorption order"
                raise FormulaEnergyError(msg)
            row = r.get("amount_row")
            specs.append(RefundSpec(
                label=r["label"], per=r["per"], count=float(r["count"]),
                recipients=r["recipients"], scaling=r["scaling"], citation=_cited(r, commit),
                amount=float(r["amount"]) if "amount" in r else None,
                amount_row=(row["talent"], row["label"]) if row else None,
                requires_ascension=r.get("requires_ascension"), note=r.get("note"),
                requires_constellation=r.get("requires_constellation"),
                basis=r.get("basis", "kit"), condition=r.get("condition"),
                absorbs=tuple(r["absorbs"]) if r.get("absorbs") else None,
                interval=r.get("interval"), max_seconds=r.get("max_seconds"),
                on=r.get("on", "burst"),
            ))
        if specs:
            out[name] = tuple(specs)
    return out


@cache
def favonius_spec() -> tuple[frozenset[str], float, str]:
    """The Favonius weapons by catalogue name, the particles a proc drops, its citation."""
    data = _load()
    fav = data["weapons"]["favonius"]
    return frozenset(fav["names"]), float(fav["particles"]), _cited(fav, data["gcsim_commit"])


@cache
def resonance_spec() -> ResonanceSpec:
    """Electro resonance's particle, cited to gcsim's `SetupResonance` and KQM's table."""
    data = _load()
    entry = data["resonances"]["electro"]
    return ResonanceSpec(
        name=str(entry["name"]), element=str(entry["element"]),
        particles=float(entry["particles"]), cooldown_seconds=float(entry["cooldown_seconds"]),
        trigger_elements=tuple(entry["trigger_elements"]), note=str(entry["note"]),
        citation=_cited(entry, str(data["gcsim_commit"])),
        default_procs_per_second=float(entry["default_procs_per_second"]),
        default_note=str(entry["default_note"]),
    )


def team_resonance(member_elements: Sequence[str | None]) -> TeamResonance | None:
    """The team's High Voltage, by the same tally `resonance.py` applies to damage.

    Four members with two or more Electro (gcsim `setup.go:108-120`, GO's `Resonance.tsx`).
    A qualifying reaction needs a member of a trigger element; without one there is nothing
    for the resonance to fire on, and `team_can_trigger` says so.
    """
    if not any(r.key == "high_voltage" for r in resonance.active(member_elements)):
        return None
    spec = resonance_spec()
    elements = {e.lower() for e in member_elements if e}
    return TeamResonance(spec=spec, team_can_trigger=bool(elements & set(spec.trigger_elements)))


@cache
def not_curated() -> dict[str, str]:
    """Characters the table leaves to the user, each with the reason it gives."""
    return {name: str(e["reason"]) for name, e in _load().get("not_curated", {}).items()}


def favonius_proc(params: Sequence[float]) -> tuple[float, float]:
    """`(chance, cooldown seconds)` from a Favonius refinement `param_list` in our catalogue.

    Param 0 is the chance and param 1 the cooldown in seconds (`[0.6, 12, …]` at R1): gcsim
    computes the same from the refinement, `0.5 + 0.1 R` and `810 - 90 R` frames
    (`internal/weapons/common/favonius.go:28-29`), and a test holds every row to it.
    """
    if len(params) < 2 or not 0 < params[0] <= 1 or params[1] <= 0:  # noqa: PLR2004
        msg = f"not a Favonius refinement row: {list(params)!r}"
        raise FormulaEnergyError(msg)
    return float(params[0]), float(params[1])


_PARAM_REF = re.compile(r"\{param(\d+)")


def _row_value(build: Build, talent: str, label: str) -> tuple[float | None, str | None]:
    """A talent row's first value at the build's effective level, or why there is none."""
    character = build.character
    stored = dict(build.talent_levels or {})
    try:
        levels = effective_talent_levels(character, build.constellation_level, stored)
    except TalentBoostError as exc:
        return None, str(exc)
    level = levels.get(talent)
    if level is None:
        return None, f"the build has no {talent} level"
    for found_talent in character.talents:
        if str(found_talent.talent_type) != talent:
            continue
        for scaling in found_talent.scalings:
            if scaling.level != level:
                continue
            for entry in scaling.labels or []:
                name, _, spec = (entry or "").partition("|")
                found = _PARAM_REF.search(spec)
                if name == label and found:
                    return float((scaling.params or [])[int(found.group(1)) - 1]), None
            return None, f"{talent} level {level} has no {label!r} row"
    return None, f"no {talent} row at level {level}"


def _refunds(build: Build) -> tuple[Refund, ...]:
    out = []
    for spec in refund_table().get(build.character.name, ()):
        if (spec.requires_constellation is not None
                and (build.constellation_level or 0) < spec.requires_constellation):
            # A constellation the build lacks: not a refund this build has, so not served.
            continue
        amount, unavailable = spec.amount, None
        if spec.amount_row is not None:
            amount, unavailable = _row_value(build, *spec.amount_row)
        scaling = spec.scaling
        short = (spec.requires_ascension is not None
                 and build.ascension_phase < spec.requires_ascension)
        if short and scaling == "raiden_a4":
            # Without her A4 the restoration is the row's alone (gcsim `asc.go:39`).
            scaling = "none"
        elif short:
            unavailable = (f"needs ascension {spec.requires_ascension}; the build is at "
                           f"{build.ascension_phase}")
        out.append(Refund(
            label=spec.label, per=spec.per, count=spec.count, recipients=spec.recipients,
            scaling=scaling, amount=amount, citation=spec.citation, note=spec.note,
            unavailable=unavailable, requires_constellation=spec.requires_constellation,
            basis=spec.basis, condition=spec.condition, absorbs=spec.absorbs,
            interval=spec.interval, max_seconds=spec.max_seconds, on=spec.on,
        ))
    return tuple(out)


def _favonius(build: Build) -> FavoniusProc | None:
    names, particles, citation = favonius_spec()
    weapon = build.weapon
    if weapon is None or weapon.name not in names:
        return None
    refinement = int(build.refinement or 1)
    row = next((r for r in weapon.refinements if r.level == refinement), None)
    if row is None:
        msg = f"{weapon.name} has no refinement {refinement} row"
        raise FormulaEnergyError(msg)
    chance, cooldown_s = favonius_proc(list(row.param_list or []))
    return FavoniusProc(
        weapon=weapon.name, refinement=refinement, chance=chance,
        cooldown_seconds=cooldown_s, particles=particles,
        citation=f"{citation}; chance and cooldown: {weapon.name} R{refinement} "
                 f"refinement row (game data)",
    )


def _own_stats(build: Build) -> tuple[float | None, float | None]:
    """`(ER, crit rate)` from the build alone (pass 1), or `None`s when it cannot assemble."""
    try:
        calculator = Calculator(kit_buffs.pass_one(build))
        er = float(calculator.compute(sheets.GIVER_STATS[tags.Q_ENERGY_RECHARGE]))
        cr = float(calculator.compute(sheets.GIVER_STATS[tags.Q_CRIT_RATE]))
    except (BuildAssemblyError, StatInputError):
        return None, None
    return er, cr


def table_commit() -> str:
    """The gcsim commit the particle table cites."""
    return str(_load()["gcsim_commit"])


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
                 "particle, `Intn(end - start)` frames after `start`, distributed to every "
                 "member, the active one at full value: pkg/core/player/player.go:197-200); "
                 "the line is "
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
    reasons = not_curated()
    out = []
    for build in members:
        character = build.character
        sources = table.get(character.name, ())
        er, cr = _own_stats(build)
        out.append(MemberEnergy(
            build_id=str(build.id), name=character.name,
            element=character.element.value.lower() if character.element else None,
            burst_energy_cost=character.burst_energy_cost,
            burst_cooldown=burst_cooldown(build),
            is_subject=str(build.id) == subject_build_id,
            status="curated" if sources else "no_particle_data",
            sources=sources,
            refunds=_refunds(build),
            favonius=_favonius(build),
            energy_recharge=er, crit_rate=cr,
            note=reasons.get(character.name),
        ))
    return TeamEnergy(
        members=out, drip=drip(), gcsim_commit=table_commit(),
        resonance=team_resonance([m.element for m in out]),
    )
