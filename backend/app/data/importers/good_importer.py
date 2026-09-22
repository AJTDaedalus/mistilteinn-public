"""Import a GOOD export — a user's artifact inventory — into this repo's vocabulary.

GOOD ("Genshin Open Object Description") is the interchange format Genshin Optimizer defined
and the scanners (Inventory Kamera, Amenoma, Adeptus) emit. It is the reason a user does not
have to re-enter 800 artifacts by hand.

## Reject, do not coerce — a deliberate divergence from the reference implementation

Genshin Optimizer's own schema **coerces**: `zodEnumWithDefault(allArtifactSlotKeys,
'flower')` turns an unrecognised slot into a flower, an unknown stat key into `hp`, and an
out-of-range level into a clamped one. That is right for a UI whose job is never to lose a
user's inventory — a mangled artifact they can fix beats an import that refuses.

It is wrong here, and DESIGN §3 says so: this importer feeds an **optimizer**, and a
silently-defaulted artifact gets scored as though it were real. A user would then be
recommended a build around a piece that does not exist. So an unknown key is an error naming
the offending artifact, and the import reports every rejection rather than stopping at the
first — someone with 800 artifacts and two odd ones wants the 798.

## Provenance

Schema and vocabulary read from Genshin Optimizer at commit
`984d82cda1e37a3a634ab14d2059b6ad91b90a4a`:

* `libs/gi/good/src/schemas/good-format.ts` — the envelope (`format`, `source`, `version`)
* `libs/gi/schema/src/artifact.ts` — the artifact record
* `libs/gi/consts/src/artifact.ts` — slot keys, stat keys, per-slot pools, `artMaxLevel`

**GO's per-slot main-stat pools agree exactly with the ones E.5 derived from the
YuanShenResources tables** — 1/1/5/12/7. Two independent derivations, one from a datamined
config join and one hand-maintained by another project, reaching the same answer.
`tests/unit/test_good_importer.py` asserts it: if they ever diverge, one is wrong and it
matters which.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from app.models.enums import ArtifactSlot, Rarity

if TYPE_CHECKING:
    from collections.abc import Iterable

#: The envelope. `libs/gi/good/src/schemas/good-format.ts:12-21`.
GOOD_FORMAT = "GOOD"
SUPPORTED_VERSIONS = (1, 2, 3)

#: GOOD's slot key → this repo's `ArtifactSlot`. GOOD uses the community names; the payload
#: (and therefore this database) uses the game's internal `equip_*` keys.
SLOT_KEYS: dict[str, ArtifactSlot] = {
    "flower": ArtifactSlot.FLOWER,
    "plume": ArtifactSlot.PLUME,
    "sands": ArtifactSlot.SANDS,
    "goblet": ArtifactSlot.GOBLET,
    "circlet": ArtifactSlot.CIRCLET,
}

#: GOOD's stat key → `FIGHT_PROP_*`. Covers `allMainStatKeys` and `allSubstatKeys`; the two
#: overlap heavily, differing only in that main stats add the DMG-bonus and healing keys
#: while substats add flat DEF.
STAT_KEYS: dict[str, str] = {
    "hp": "FIGHT_PROP_HP",
    "hp_": "FIGHT_PROP_HP_PERCENT",
    "atk": "FIGHT_PROP_ATTACK",
    "atk_": "FIGHT_PROP_ATTACK_PERCENT",
    "def": "FIGHT_PROP_DEFENSE",
    "def_": "FIGHT_PROP_DEFENSE_PERCENT",
    "eleMas": "FIGHT_PROP_ELEMENT_MASTERY",
    "enerRech_": "FIGHT_PROP_CHARGE_EFFICIENCY",
    "critRate_": "FIGHT_PROP_CRITICAL",
    "critDMG_": "FIGHT_PROP_CRITICAL_HURT",
    "heal_": "FIGHT_PROP_HEAL_ADD",
    "physical_dmg_": "FIGHT_PROP_PHYSICAL_ADD_HURT",
    "anemo_dmg_": "FIGHT_PROP_WIND_ADD_HURT",
    "geo_dmg_": "FIGHT_PROP_ROCK_ADD_HURT",
    "electro_dmg_": "FIGHT_PROP_ELEC_ADD_HURT",
    "hydro_dmg_": "FIGHT_PROP_WATER_ADD_HURT",
    "pyro_dmg_": "FIGHT_PROP_FIRE_ADD_HURT",
    "cryo_dmg_": "FIGHT_PROP_ICE_ADD_HURT",
    "dendro_dmg_": "FIGHT_PROP_GRASS_ADD_HURT",
}

#: Highest upgrade level per rarity. `libs/gi/consts/src/artifact.ts:artMaxLevel`.
#:
#: **Not the constant 20.** A rarity-3 piece stops at +12 and a rarity-1 at +4, so a scan
#: claiming a +20 three-star describes something the game cannot produce. (The
#: YuanShenResources value table publishes 16 rows for rarity 1 — rows exist for levels the
#: game does not let you reach, which is why the *reachable* cap is cited to GO rather than
#: inferred from that table's length.)
MAX_LEVEL_BY_RARITY: dict[int, int] = {1: 4, 2: 4, 3: 12, 4: 16, 5: 20}

#: Percentage stats arrive as **percent numbers** in GOOD (`46.6` for 46.6%); everything in
#: this repo is a fraction. Flat stats do not scale.
_PERCENT_SCALE = 100.0


class GoodImportError(ValueError):
    """The export is not a GOOD file this importer will read."""


@dataclass(frozen=True, slots=True)
class RejectedArtifact:
    """One artifact that could not be imported, and why."""

    index: int
    reason: str
    #: The record as given, so a user can find it in their export.
    record: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"artifact[{self.index}]: {self.reason}"


@dataclass(frozen=True, slots=True)
class ParsedArtifact:
    """One validated artifact, in this repo's vocabulary."""

    slot: ArtifactSlot
    rarity: Rarity
    level: int
    main_stat: str
    substats: tuple[dict[str, Any], ...]
    set_key: str
    location: str = ""
    lock: bool = False
    #: Where this record sat in the export's `artifacts` array. Carried because a rejection
    #: reported later — by the *importer*, for a set this database does not know — has to
    #: name the same record the user is looking at. Enumerating the surviving artifacts
    #: gives an index into the filtered list, which drifts from the file by however many
    #: records the parser refused before it.
    source_index: int = -1


@dataclass(frozen=True, slots=True)
class ParsedCharacter:
    """One character as the export records them: how far they are levelled.

    Parsed so a build can be reconstituted rather than retyped. GOOD carries everything a
    build needs — levels, ascension, constellation and the three levelled talents — and
    `location` on the weapons and artifacts says who holds what.
    """

    #: GOOD's own key, e.g. `KamisatoAyaka`. Resolved against the catalogue by the service,
    #: which is where an unknown or ambiguous name is refused.
    key: str
    level: int
    ascension: int
    #: **None means the export did not say**, which is not C0. `character_roster` keeps that
    #: distinction because an unknown constellation and a zero one give different starglitter
    #: refunds and only one of them is a claim — `docs/DESIGN_wish_planner.md` section 9.4.
    #: Builds still coerce it to 0, because a build column cannot hold "unknown".
    constellation: int | None
    #: `{normal_attack, elemental_skill, elemental_burst}` — GOOD's `auto`/`skill`/`burst`
    #: renamed to this repo's `TalentType` spellings at the boundary, so nothing downstream
    #: carries GO's vocabulary.
    talents: dict[str, int]


@dataclass(frozen=True, slots=True)
class ParsedWeapon:
    """One weapon, and who is holding it. Unheld weapons are parsed and simply unused."""

    key: str
    level: int
    ascension: int
    refinement: int
    #: The character key holding it, or `""`. This is the only link between a build and its
    #: weapon that GOOD provides.
    location: str = ""


@dataclass(frozen=True, slots=True)
class GoodImportResult:
    """What an import produced, including everything it refused."""

    artifacts: tuple[ParsedArtifact, ...]
    rejected: tuple[RejectedArtifact, ...]
    source: str
    version: int
    #: Empty when the export carries no `characters`/`weapons` array — older scanners write
    #: artifacts only, and that is a valid GOOD file rather than a broken one.
    characters: tuple[ParsedCharacter, ...] = ()
    weapons: tuple[ParsedWeapon, ...] = ()
    #: `{GOOD material key: count}`, straight from the export's optional `materials` map.
    #:
    #: **An absent key means zero**, and that is what the export means too — measured on a
    #: real Irminsul export carrying 1,384 entries with *no* zero-valued one (minimum 1,
    #: maximum 11,250). So a material the file omits is one the account has none of, not one
    #: the scanner failed to read.
    #:
    #: Keys are bound to the catalogue by `good_build_service.lookup_key`, the same
    #: normalisation artifact sets use. It is injective over all 508 planner materials —
    #: measured — which is what makes binding by name safe. Note it strips the apostrophe
    #: without capitalising the next letter: `Hero's Wit` is `HerosWit`, not `HeroSWit`.
    #: `None` when the export carries no `materials` key at all — a scanner that does not
    #: report them — against `{}` for one that carries the section and nothing usable in it.
    #: The two mean different things to the importer and it could not tell them apart while
    #: both were `{}`.
    materials: dict[str, int] | None = None

    @property
    def ok(self) -> bool:
        """True when nothing was refused."""
        return not self.rejected


def parse_good(payload: dict[str, Any]) -> GoodImportResult:
    """Validate a GOOD export and convert its artifacts.

    Every artifact is checked; a bad one is recorded in `rejected` rather than aborting.
    """
    _check_envelope(payload)

    parsed: list[ParsedArtifact] = []
    rejected: list[RejectedArtifact] = []
    for index, record in enumerate(payload.get("artifacts") or []):
        try:
            parsed.append(replace(_parse_artifact(record), source_index=index))
        except GoodImportError as exc:
            rejected.append(RejectedArtifact(index=index, reason=str(exc), record=record))

    return GoodImportResult(
        artifacts=tuple(parsed),
        rejected=tuple(rejected),
        source=str(payload.get("source", "")),
        version=int(payload["version"]),
        characters=tuple(_parse_characters(payload.get("characters") or [])),
        weapons=tuple(_parse_weapons(payload.get("weapons") or [])),
        materials=_parse_materials(payload.get("materials")),
    )


def _parse_materials(record: Any) -> dict[str, int] | None:
    """The export's `materials` map, keeping only sane positive counts.

    Non-integer and non-positive values are dropped rather than refused: this map is a
    convenience for the planner, and a single odd entry must not cost the user an import of
    2,370 artifacts. A dropped entry reads as "none held", which is the same as absent.

    Returns `None` when the key is missing entirely, so a scanner that reports no materials
    leaves stored stock alone while one that reports an empty inventory clears it.
    """
    if not isinstance(record, dict):
        return None
    return {
        str(key): int(value)
        for key, value in record.items()
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }


def _check_envelope(payload: dict[str, Any]) -> None:
    """Reject anything that is not a supported GOOD file, before reading its contents."""
    if not isinstance(payload, dict):
        msg = f"a GOOD export is a JSON object; got {type(payload).__name__}"
        raise GoodImportError(msg)
    if payload.get("format") != GOOD_FORMAT:
        msg = (
            f"not a GOOD export: `format` is {payload.get('format')!r}, expected "
            f"{GOOD_FORMAT!r}"
        )
        raise GoodImportError(msg)
    version = payload.get("version")
    if isinstance(version, bool) or version not in SUPPORTED_VERSIONS:
        msg = (
            f"GOOD version {version!r} is not supported (this reads {SUPPORTED_VERSIONS}). "
            f"A newer version may have changed field meanings, and reading it as though it "
            f"had not is how a silently wrong inventory gets imported."
        )
        raise GoodImportError(msg)


def _parse_artifact(record: dict[str, Any]) -> ParsedArtifact:
    """One artifact record, validated field by field."""
    if not isinstance(record, dict):
        msg = f"expected an object, got {type(record).__name__}"
        raise GoodImportError(msg)

    slot = _require(SLOT_KEYS, record.get("slotKey"), "slot")
    rarity_value = record.get("rarity")
    if isinstance(rarity_value, bool) or rarity_value not in MAX_LEVEL_BY_RARITY:
        # `True == 1` in Python, so a boolean would have imported as a one-star artifact.
        msg = f"unknown rarity {rarity_value!r}; GOOD publishes {sorted(MAX_LEVEL_BY_RARITY)}"
        raise GoodImportError(msg)

    level = record.get("level")
    maximum = MAX_LEVEL_BY_RARITY[rarity_value]
    if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= maximum:
        msg = (
            f"level {level!r} is out of range for a {rarity_value}-star artifact "
            f"(0..{maximum}); the game cannot produce it"
        )
        raise GoodImportError(msg)

    main_stat = _require(STAT_KEYS, record.get("mainStatKey"), "main stat")
    _check_slot_can_roll(slot, main_stat, record.get("mainStatKey"))
    set_key = record.get("setKey")
    if not isinstance(set_key, str) or not set_key:
        msg = f"missing or non-string `setKey`: {set_key!r}"
        raise GoodImportError(msg)

    return ParsedArtifact(
        slot=slot,
        rarity=Rarity.parse(rarity_value),
        level=level,
        main_stat=main_stat,
        substats=tuple(_parse_substats(record.get("substats") or [])),
        set_key=set_key,
        location=str(record.get("location") or ""),
        lock=bool(record.get("lock", False)),
    )


def _check_slot_can_roll(slot: ArtifactSlot, main_stat: str, given: Any) -> None:
    """Reject a slot/main-stat pair the game cannot produce.

    Checking the stat key against the flat vocabulary is not enough: a flower with CRIT DMG
    passes that and is not a thing. **One OCR misread from a scanner would otherwise import
    cleanly and then raise from inside the optimizer's hot loop**, turning 798 good artifacts
    into a search that dies partway through — the exact "a piece the game cannot produce
    would score as a real one" failure this importer exists to prevent.

    The per-slot table is already in this module; it is the same one E.5 derived and GO
    maintains independently.
    """
    allowed = slot_main_stat_keys()[slot.value]
    if main_stat not in allowed:
        msg = (
            f"a {slot.name.lower()} cannot roll {given!r} as a main stat "
            f"(it rolls {sorted(allowed)}). A scanner misread is the usual cause."
        )
        raise GoodImportError(msg)


#: GOOD's talent names against this repo's. Kept here, at the boundary, so `TalentType`
#: spellings never have to know GO's.
_TALENTS = {
    "auto": "normal_attack",
    "skill": "elemental_skill",
    "burst": "elemental_burst",
}


def _parse_characters(records: Iterable[Any]) -> list[ParsedCharacter]:
    """Every character the export records, skipping any record it cannot read.

    **Skipped rather than rejected.** An unreadable *artifact* is reported because the user
    owns it and would otherwise silently lose a piece from a search. A malformed character
    entry costs a build that can be made by hand in a minute, and failing the whole import
    over one would be a worse trade — the artifacts are the irreplaceable part.
    """
    parsed: list[ParsedCharacter] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        key = record.get("key")
        if not isinstance(key, str) or not key:
            continue
        talents = record.get("talent")
        talents = talents if isinstance(talents, dict) else {}
        parsed.append(
            ParsedCharacter(
                key=key,
                level=_bounded(record.get("level"), 1, 90, 1),
                ascension=_bounded(record.get("ascension"), 0, 6, 0),
                constellation=(
                    _bounded(record.get("constellation"), 0, 6, 0)
                    if record.get("constellation") is not None
                    else None
                ),
                talents={
                    ours: _bounded(talents.get(theirs), 1, 15, 1)
                    for theirs, ours in _TALENTS.items()
                },
            )
        )
    return parsed


def _parse_weapons(records: Iterable[Any]) -> list[ParsedWeapon]:
    """Every weapon the export records. Skipped-not-rejected, as for characters."""
    parsed: list[ParsedWeapon] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        key = record.get("key")
        if not isinstance(key, str) or not key:
            continue
        parsed.append(
            ParsedWeapon(
                key=key,
                level=_bounded(record.get("level"), 1, 90, 1),
                ascension=_bounded(record.get("ascension"), 0, 6, 0),
                refinement=_bounded(record.get("refinement"), 1, 5, 1),
                location=str(record.get("location") or ""),
            )
        )
    return parsed


def _bounded(value: Any, low: int, high: int, fallback: int) -> int:
    """An int inside `[low, high]`, or `fallback`.

    Clamped rather than refused: these are levels, and a scanner that read `999` off a
    screen has misread a number rather than described a character this importer should
    refuse to place. The build's own validators bound the same fields on write, so an
    out-of-range value could not reach the database anyway — clamping here just means the
    rest of the character survives it.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return max(low, min(high, int(value)))


def _parse_substats(substats: Iterable[Any]) -> list[dict[str, Any]]:
    """Substats in this repo's shape, dropping GOOD's empty placeholders.

    A scan of an unupgraded artifact carries `{"key": "", "value": 0}` entries — GOOD's
    schema defaults an absent key to `''` — and those are genuinely "no substat here", not
    an unknown one. An empty key with a *non-zero* value is neither, and is rejected.
    """
    parsed = []
    for entry in substats:
        if not isinstance(entry, dict):
            msg = f"substat entries must be objects; got {type(entry).__name__}"
            raise GoodImportError(msg)
        key = entry.get("key", "")
        value = entry.get("value", 0)
        if key == "":
            if value:
                msg = f"a substat with no key carries a value of {value!r}"
                raise GoodImportError(msg)
            continue
        parsed.append({
            "stat": _require(STAT_KEYS, key, "substat"),
            "value": _scale(key, value),
        })
    return parsed


def _scale(key: str, value: Any) -> float:
    """GOOD's number in this repo's units: percentages become fractions.

    The trailing underscore is GO's own marker for a percentage stat, so this reads the
    convention rather than carrying a second hand-maintained list that could disagree with
    `STAT_KEYS`.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        msg = f"stat value must be a number; got {value!r}"
        raise GoodImportError(msg)
    return float(value) / _PERCENT_SCALE if key.endswith("_") else float(value)


def _require(table: dict[str, Any], key: Any, what: str) -> Any:
    """Look `key` up, or refuse.

    The reject-don't-coerce rule, in one function. Genshin Optimizer returns a default here;
    an optimizer fed a defaulted artifact scores a piece that does not exist.
    """
    if key not in table:
        msg = (
            f"unknown {what} key {key!r}. This importer rejects rather than defaulting, "
            f"because a defaulted artifact would be optimized over as though it were real."
        )
        raise GoodImportError(msg)
    return table[key]


def slot_main_stat_keys() -> dict[str, tuple[str, ...]]:
    """GOOD's per-slot main-stat pools, as `FIGHT_PROP_*`.

    Source: `libs/gi/consts/src/artifact.ts:artSlotMainKeys`. Exposed so the test comparing
    them against E.5's independently derived pools has something to compare.
    """
    shared = ("hp_", "def_", "atk_", "eleMas")
    pools = {
        "flower": ("hp",),
        "plume": ("atk",),
        "sands": (*shared, "enerRech_"),
        "goblet": (
            *shared, "physical_dmg_", "anemo_dmg_", "geo_dmg_", "electro_dmg_",
            "hydro_dmg_", "pyro_dmg_", "cryo_dmg_", "dendro_dmg_",
        ),
        "circlet": (*shared, "critRate_", "critDMG_", "heal_"),
    }
    return {
        SLOT_KEYS[slot].value: tuple(STAT_KEYS[key] for key in keys)
        for slot, keys in pools.items()
    }
