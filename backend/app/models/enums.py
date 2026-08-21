"""Domain enums for Genshin Impact, derived from committed nanoka payloads.

**Provenance.** Every value set here was read off
`backend/tests/fixtures/nanoka_gi/` at nanoka version **7.0.51** (`manifest.json` →
`gi.latest`, fetched 2026-08-21) — never from memory, and never from a live call. The
fixtures' `PROVENANCE.md` records how they were captured;
`tests/unit/test_genshin_enums.py` asserts every enum below against them, so an upstream
change arrives as a failing assertion beside a reviewable fixture diff.

Nothing here is renamed from the ZZZ enums B.4 deleted. `Specialty`, `AttackType`,
`DiscSlot`, `AnomalyType`, `HitMode` and the `Potential*` family have no Genshin
counterpart and are simply gone.

Two encoding traps live in this file because the upstream data has them, not because the
model wants them — see `WeaponType.parse` and `stat_type_for`.
"""

from __future__ import annotations

import enum
import logging

logger = logging.getLogger(__name__)


class UserStatus(enum.StrEnum):
    """Admin-approval lifecycle state for a `User` account."""

    PENDING = "pending"
    APPROVED = "approved"
    DISABLED = "disabled"


class Element(enum.StrEnum):
    """The seven visions.

    Source: distinct `element` values in `gi/7.0.51/character.json` — `Anemo`, `Cryo`,
    `Dendro`, `Electro`, `Geo`, `Hydro`, `Pyro`, plus a literal `"None"` carried by two
    characters (the Traveler entries), which is **handled by `parse`, not mapped**.

    **Physical is deliberately absent.** It is a damage type, not a vision; modelling it as
    a peer of the seven is the ZZZ-shaped trap DESIGN §2.6 calls out by name. See
    `DamageType`.
    """

    ANEMO = "Anemo"
    CRYO = "Cryo"
    DENDRO = "Dendro"
    ELECTRO = "Electro"
    GEO = "Geo"
    HYDRO = "Hydro"
    PYRO = "Pyro"

    @classmethod
    def parse(cls, raw: str | None) -> Element | None:
        """Map a payload `element` string, returning None for the unaligned literal "None".

        Returns None — rather than raising or inventing a member — for `"None"` and for a
        missing value, because "this character has no vision" is a real state in the data.
        An unrecognised non-empty value warns, so a new element in a future patch surfaces
        as a log line instead of a silent drop.
        """
        if raw in (None, "", "None"):
            return None
        try:
            return cls(raw)
        except ValueError:
            logger.warning("Unmapped element %r — nanoka payload has a value this build "
                           "does not know; see app/models/enums.py", raw)
            return None


class DamageType(enum.StrEnum):
    """Whether an instance of damage is elemental or physical.

    Genshin's damage bonuses and enemy resistances are indexed by *eight* channels: the
    seven visions plus Physical. `Element` covers the seven; this covers the split.
    """

    ELEMENTAL = "elemental"
    PHYSICAL = "physical"


class WeaponType(enum.StrEnum):
    """The six weapon classes.

    Source: `character.json` `weapon` and `weapon.json` `type`. **The two indexes disagree
    on the sixth.** Characters spell the crossbow class `WEAPON_CROSSBOW` (2 characters);
    weapons spell it `ITEM_TPS_WEAPON` (8 weapons) and `WEAPON_CROSSBOW` appears nowhere in
    `weapon.json`. Both spellings therefore map here, via `parse`.

    DESIGN §2.6 recorded only `WEAPON_CROSSBOW`, having read the character index alone.
    """

    SWORD = "WEAPON_SWORD_ONE_HAND"
    CLAYMORE = "WEAPON_CLAYMORE"
    POLEARM = "WEAPON_POLE"
    BOW = "WEAPON_BOW"
    CATALYST = "WEAPON_CATALYST"
    CROSSBOW = "WEAPON_CROSSBOW"

    @classmethod
    def parse(cls, raw: str | None) -> WeaponType | None:
        """Map either index's spelling to a single member; warn on anything unknown."""
        if raw is None:
            return None
        if raw == _TPS_WEAPON_KEY:
            return cls.CROSSBOW
        try:
            return cls(raw)
        except ValueError:
            logger.warning("Unmapped weapon type %r — see app/models/enums.py", raw)
            return None


#: `weapon.json` spells the crossbow class this way. Held outside `WeaponType` on purpose:
#: as a class attribute it would either become a seventh member or need a `noqa`, and
#: downstream code should have exactly one crossbow value to compare against.
_TPS_WEAPON_KEY = "ITEM_TPS_WEAPON"


class Rarity(enum.StrEnum):
    """Star rating, normalised across the two encodings the source uses.

    Characters carry `rank` as a `QUALITY_*` string; weapons carry it as an integer 1-5, and
    weapon *detail* payloads call the same thing `rarity`. `parse` accepts all of them.

    `QUALITY_ORANGE_SP` is 5-star. It is **not** a one-off: 15 of the 150 characters carry
    it, against DESIGN §2.6's "Aloy-class special" reading. Whether the SP distinction
    matters to anything downstream is a Chunk D question; it does not change the star count.
    """

    ONE_STAR = "one_star"
    TWO_STAR = "two_star"
    THREE_STAR = "three_star"
    FOUR_STAR = "four_star"
    FIVE_STAR = "five_star"

    @property
    def stars(self) -> int:
        """Star count as an integer, for comparisons and for round-tripping to the source."""
        return _RARITY_STARS[self]

    @classmethod
    def parse(cls, raw: str | int | None) -> Rarity | None:
        """Map a `QUALITY_*` string or an integer 1-5; warn on anything unknown."""
        if raw is None:
            return None
        found = (
            _RARITY_BY_STARS.get(raw)
            if isinstance(raw, int)
            else _RARITY_BY_QUALITY.get(raw)
        )
        if found is None:
            logger.warning("Unmapped rarity %r — see app/models/enums.py", raw)
        return found


_RARITY_STARS: dict[Rarity, int] = {
    Rarity.ONE_STAR: 1,
    Rarity.TWO_STAR: 2,
    Rarity.THREE_STAR: 3,
    Rarity.FOUR_STAR: 4,
    Rarity.FIVE_STAR: 5,
}
_RARITY_BY_STARS: dict[int, Rarity] = {v: k for k, v in _RARITY_STARS.items()}

#: Source: distinct `rank` values in `gi/7.0.51/character.json`.
_RARITY_BY_QUALITY: dict[str, Rarity] = {
    "QUALITY_ORANGE": Rarity.FIVE_STAR,
    "QUALITY_ORANGE_SP": Rarity.FIVE_STAR,
    "QUALITY_PURPLE": Rarity.FOUR_STAR,
}



class ArtifactSlot(enum.StrEnum):
    """The five artifact slots, keyed by the source's internal names.

    Source: the `parts` keys of an artifact *detail* payload
    (`gi/7.0.51/en/artifact/15025.json`, committed under `tests/fixtures/nanoka_gi/detail/`).

    A `StrEnum` and not an `IntEnum`, per DESIGN §3: Genshin's slots are named rather than
    ordered, and the fixed-main-stat property of flower and plume belongs in a
    slot-to-allowed-mains table (C.5), not in the ordering of an enum.

    Member names are the community/display terms; **values are the payload's keys**, which
    is what the importer matches on.
    """

    FLOWER = "equip_bracer"
    PLUME = "equip_necklace"
    SANDS = "equip_shoes"
    GOBLET = "equip_ring"
    CIRCLET = "equip_dress"

    @property
    def sort_index(self) -> int:
        """Position in the conventional flower→plume→sands→goblet→circlet order.

        Needed because the *values* are the payload's internal keys, so sorting on the
        column sorts alphabetically — `equip_bracer, equip_dress, equip_necklace,
        equip_ring, equip_shoes`, i.e. **flower, circlet, plume, goblet, sands**. Any UI or
        export iterating in column order would put the circlet second.
        """
        return _SLOT_ORDER.index(self)


#: Declaration order of `ArtifactSlot` is the conventional display order; the enum's values
#: are not, so this list is what `sort_index` and the SQL ordering both key off.
_SLOT_ORDER: list[ArtifactSlot] = [
    ArtifactSlot.FLOWER,
    ArtifactSlot.PLUME,
    ArtifactSlot.SANDS,
    ArtifactSlot.GOBLET,
    ArtifactSlot.CIRCLET,
]


class TalentType(enum.StrEnum):
    """What a character's `skills[]` entry actually is.

    Source: the `promote["0"].icon` prefix in a character detail payload
    (`gi/7.0.51/en/character/10000002.json`): `Skill_A_*` is the normal-attack talent,
    `Skill_S_*` an elemental skill or an alternate sprint, `Skill_E_*` the burst.

    **Never classify by list position.** Ayaka has four `skills[]` entries because she has
    an alternate sprint; most characters have three. Positional indexing is a bug waiting
    for the first character with a non-standard kit.

    Telling an alternate sprint from an elemental skill needs more than the icon prefix —
    both are `Skill_S_*`. That is D.3's problem, and `ALTERNATE_SPRINT` exists so D.3 has
    somewhere to put the answer rather than inventing a member later.
    """

    NORMAL_ATTACK = "normal_attack"
    ELEMENTAL_SKILL = "elemental_skill"
    ELEMENTAL_BURST = "elemental_burst"
    ALTERNATE_SPRINT = "alternate_sprint"

    @classmethod
    def from_skill_icon(cls, icon: str | None) -> TalentType | None:
        """Classify a `skills[].promote[].icon`; warn on an unrecognised prefix."""
        if not icon:
            return None
        if icon.startswith("Skill_A"):
            return cls.NORMAL_ATTACK
        if icon.startswith("Skill_E"):
            return cls.ELEMENTAL_BURST
        if icon.startswith("Skill_S"):
            return cls.ELEMENTAL_SKILL
        logger.warning("Unclassifiable skill icon %r — see app/models/enums.py", icon)
        return None


class StatType(enum.StrEnum):
    """The `FIGHT_PROP_*` stat vocabulary.

    Source: `weapon.json` `sub` (the weapon substat pool) and the `affix[].add_props[]`
    `prop_type` values aggregated across **all 65** artifact set detail payloads — captured
    in `tests/fixtures/nanoka_gi/fight_prop_vocabulary.json`, which records how it was
    derived.

    Internal names are not display names: `GRASS` is Dendro, `ROCK` is Geo, `ELEC` is
    Electro, `WATER` is Hydro, `WIND` is Anemo, `ICE` is Cryo, `FIRE` is Pyro. That mapping
    is not asserted from memory — it was read out of each affix's own English description
    text ("Dendro DMG Bonus +15%" beside `FIGHT_PROP_GRASS_ADD_HURT`) and is asserted in
    `test_elemental_dmg_bonus_props_map_to_the_element_the_payload_names`.

    **Not complete for artifacts.** Artifact *main-stat* and *substat* pools live in
    `ReliquaryMainPropExcelConfigData` / `ReliquaryAffixExcelConfigData`, which is
    YuanShenResources data and therefore Chunk E. This covers the set-bonus and weapon
    vocabulary nanoka exposes today; expect to extend it there.
    """

    HP_FLAT = "FIGHT_PROP_HP"
    HP_PCT = "FIGHT_PROP_HP_PERCENT"
    ATK_FLAT = "FIGHT_PROP_ATTACK"
    ATK_PCT = "FIGHT_PROP_ATTACK_PERCENT"
    DEF_FLAT = "FIGHT_PROP_DEFENSE"
    DEF_PCT = "FIGHT_PROP_DEFENSE_PERCENT"
    # The three "base" props a character's ascension rows are keyed by, plus the weapon's
    # base ATK. Added after `test_stat_keys_are_matched_case_insensitively` warned on
    # `fight_prop_base_defense` — the unmapped-key path finding a real gap on its first use.
    BASE_HP = "FIGHT_PROP_BASE_HP"
    BASE_ATK = "FIGHT_PROP_BASE_ATTACK"
    BASE_DEF = "FIGHT_PROP_BASE_DEFENSE"

    ELEMENTAL_MASTERY = "FIGHT_PROP_ELEMENT_MASTERY"
    ENERGY_RECHARGE = "FIGHT_PROP_CHARGE_EFFICIENCY"
    CRIT_RATE = "FIGHT_PROP_CRITICAL"
    CRIT_DMG = "FIGHT_PROP_CRITICAL_HURT"

    HEALING_BONUS = "FIGHT_PROP_HEAL_ADD"
    INCOMING_HEALING_BONUS = "FIGHT_PROP_HEALED_ADD"
    SHIELD_STRENGTH = "FIGHT_PROP_SHIELD_COST_MINUS_RATIO"

    # DMG bonus, one per damage channel. See `dmg_bonus_for`.
    ANEMO_DMG_BONUS = "FIGHT_PROP_WIND_ADD_HURT"
    CRYO_DMG_BONUS = "FIGHT_PROP_ICE_ADD_HURT"
    DENDRO_DMG_BONUS = "FIGHT_PROP_GRASS_ADD_HURT"
    ELECTRO_DMG_BONUS = "FIGHT_PROP_ELEC_ADD_HURT"
    GEO_DMG_BONUS = "FIGHT_PROP_ROCK_ADD_HURT"
    HYDRO_DMG_BONUS = "FIGHT_PROP_WATER_ADD_HURT"
    PYRO_DMG_BONUS = "FIGHT_PROP_FIRE_ADD_HURT"
    PHYSICAL_DMG_BONUS = "FIGHT_PROP_PHYSICAL_ADD_HURT"

    # RES shred, observed on set affixes (`*_SUB_HURT`).
    ELECTRO_RES = "FIGHT_PROP_ELEC_SUB_HURT"
    PYRO_RES = "FIGHT_PROP_FIRE_SUB_HURT"

    @classmethod
    def dmg_bonus_for(cls, element: Element) -> StatType:
        """The DMG-bonus stat for a vision. Total, so a new element cannot slip through."""
        return _DMG_BONUS_BY_ELEMENT[element]


_DMG_BONUS_BY_ELEMENT: dict[Element, StatType] = {
    Element.ANEMO: StatType.ANEMO_DMG_BONUS,
    Element.CRYO: StatType.CRYO_DMG_BONUS,
    Element.DENDRO: StatType.DENDRO_DMG_BONUS,
    Element.ELECTRO: StatType.ELECTRO_DMG_BONUS,
    Element.GEO: StatType.GEO_DMG_BONUS,
    Element.HYDRO: StatType.HYDRO_DMG_BONUS,
    Element.PYRO: StatType.PYRO_DMG_BONUS,
}

#: The source spells "this row has no stat" two ways: a JSON `null` (34 weapons) and the
#: literal string `FIGHT_PROP_NONE` (10 weapons, and 324 artifact affix slots). Both mean
#: absent. Neither is an error, so neither warns — warning on 368 legitimate absences would
#: train everyone to ignore the log, which is how a real unmapped key gets missed.
_ABSENT_STAT_KEYS = frozenset({None, "", "FIGHT_PROP_NONE"})


def is_absent_stat_key(raw: str | None) -> bool:
    """True when `raw` is one of the two ways the source spells "there is no stat here".

    Exists so a caller can tell **absent** from **unmapped**: `stat_type_for` returns None
    for both, and a mapping that treats a brand-new `FIGHT_PROP_*` as "no stat" stores a
    weapon the optimizer reads as having no substat — quietly wrong, on a green run.
    """
    if raw in _ABSENT_STAT_KEYS:
        return True
    return isinstance(raw, str) and raw.upper() in _ABSENT_STAT_KEYS


def stat_type_for(raw: str | None) -> StatType | None:
    """Map a `FIGHT_PROP_*` key, returning None for the two "absent" encodings.

    **Case-insensitive, because the source is not consistent.** `weapon_prop[].prop_type`
    and `affix[].add_props[].prop_type` are UPPER_CASE, but
    `stats_modifier.ascension[]` keys the very same properties in lower_case
    (`fight_prop_critical_hurt`). Matching case-sensitively would make every character's
    ascension stat silently unmappable — and it would warn 150 times while doing it, which
    is the sort of noise that gets a warning path switched off.

    An unrecognised key warns and returns None — it is never silently dropped, which is
    DESIGN §3's requirement for Chunk C: a new patch's new prop shows up as a log line.
    """
    if raw in _ABSENT_STAT_KEYS or (isinstance(raw, str) and raw.upper() in _ABSENT_STAT_KEYS):
        return None
    try:
        return StatType(raw.upper() if isinstance(raw, str) else raw)
    except ValueError:
        logger.warning(
            "Unmapped stat key %r — nanoka payload carries a FIGHT_PROP this build does "
            "not know. Add it to app/models/enums.py:StatType and refresh "
            "tests/fixtures/nanoka_gi/.",
            raw,
        )
        return None
