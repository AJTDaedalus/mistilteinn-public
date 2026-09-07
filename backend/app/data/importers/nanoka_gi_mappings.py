"""Pure payload → column-value mappings for the nanoka GI importer.

Split out from `nanoka_gi_importer.py` on purpose: everything here is a plain function
over a JSON payload, so the mapping tests run against the committed fixtures with no
session, no transport and no event loop. The importer keeps the session work.

**Every rule in this module was read off the committed payloads, and the ones that could
not be settled from a single payload were swept across all 150 characters.** The sweep
results are in `docs/LOG_mistilteinn.md`, the D.2 entry; the counts quoted in the
docstrings below come from it, not from memory.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.models.enums import (
    Element,
    Rarity,
    StatType,
    TalentType,
    WeaponType,
    is_absent_stat_key,
    stat_type_for,
)

logger = logging.getLogger(__name__)


class NanokaMappingError(ValueError):
    """A payload does not have the shape every committed sample has.

    Raised rather than logged-and-defaulted. The importer records it against that entity's
    id and D.7 exits non-zero, so an upstream shape change is a red seed run — not a
    quietly-wrong row that looks seeded.
    """


#: The three props every `stats_modifier.ascension` row carries. The *fourth* key is the
#: character's ascension stat, and it is the only way to know what that stat is — there is
#: no field naming it. Lower-case because this payload keys them that way and nothing else
#: does; `stat_type_for` is case-insensitive for exactly this reason (C.2).
_ASCENSION_BASE_KEYS = frozenset(
    {"fight_prop_base_hp", "fight_prop_base_attack", "fight_prop_base_defense"},
)

#: `"Energy Cost|{param5:I}"` — the burst's energy cost is a *row of its description*, not
#: a field. The number is `param[5 - 1]`.
_ENERGY_COST_LABEL = "Energy Cost"
_PARAM_REF = re.compile(r"\{param(\d+)[:}]")

#: Ascension phases a character or weapon has. Six, from `AvatarPromoteExcelConfigData`
#: and the payload alike — asserted rather than trusted, so a patch that adds a seventh
#: fails loudly instead of renumbering the ladder in silence.
ASCENSION_PHASES = 6

#: A real talent publishes 15 levels. The only 1-level entries at 7.0.51 are Ayaka's
#: "Kamisato Art: Senho" and Mona's "Illusory Torrent" — the two alternate sprints, which
#: carry a `Skill_S_*` icon exactly like an elemental skill does. Icon prefix alone
#: therefore cannot tell them apart; the promote ladder can.
_ALTERNATE_SPRINT_PROMOTE_LEVELS = 1


def character_fields(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The `Character` column values for one detail payload.

    `key` is the index key verbatim — `"10000002"`, or `"10000005-2"` for one of the 28
    Traveler variants. It is the row's identity; the payload carries no id of its own.
    """
    info = payload.get("chara_info") or {}
    ascension = payload.get("stats_modifier", {}).get("ascension") or []
    weapon_type = WeaponType.parse(payload.get("weapon"))
    if weapon_type is None:
        msg = f"character {key}: unmappable weapon type {payload.get('weapon')!r}"
        raise NanokaMappingError(msg)
    rarity = Rarity.parse(payload.get("rarity"))
    if rarity is None:
        msg = f"character {key}: unmappable rarity {payload.get('rarity')!r}"
        raise NanokaMappingError(msg)
    return {
        "nanoka_id": key,
        "name": payload.get("name", ""),
        # `Element.parse` returns None for the literal "None" the two unreleased Traveler
        # bodies carry — a real state, not an error.
        "element": Element.parse(payload.get("element")),
        "weapon_type": weapon_type,
        "rarity": rarity,
        "region": info.get("region"),
        "release_date": info.get("release_date"),
        "base_hp": payload.get("base_hp", 0.0),
        "base_atk": payload.get("base_atk", 0.0),
        "base_def": payload.get("base_def", 0.0),
        "ascension_stat_type": ascension_stat_type(key, ascension),
        "ascension_stats": ascension,
        # Without the curves the three base stats above cannot be evaluated at any level,
        # so this raises rather than defaulting — it was the one mapping in this module
        # that let a missing field through, and the failure would have surfaced much later
        # as a calculation error on a database that seeded clean.
        "prop_curves": _prop_curves(key, payload),
        "base_elemental_mastery": payload.get("elemental_mastery", 0.0) or 0.0,
        "base_crit_rate": payload.get("crit_rate", 0.0) or 0.0,
        "base_crit_dmg": payload.get("crit_dmg", 0.0) or 0.0,
        "burst_energy_cost": burst_energy_cost(payload),
        "icon": payload.get("icon"),
        # **Per level, not cumulative** — entry `i` is the EXP to go from level `i+1` to
        # `i+2`, and the first 89 sum to 8,362,650, the published total to level 90. Stored
        # verbatim; the planner is the only reader and it reads the whole list.
        "level_exp": list(payload.get("level_exp") or []),
    }


def _prop_curves(key: str, payload: dict[str, Any]) -> dict[str, str]:
    """`{FIGHT_PROP_BASE_*: GROW_CURVE_*}` from `stats_modifier.prop_grow_curves`.

    All 150 characters at 7.0.51 publish exactly three complete entries, and the three base
    stats are unusable without them, so anything else raises. Note that **every character
    grows DEF on an HP curve** — the pairing is read here, never derived from the stat.
    """
    entries = payload.get("stats_modifier", {}).get("prop_grow_curves") or []
    curves = {
        entry["type"]: entry["grow_curve"]
        for entry in entries
        if entry.get("type") and entry.get("grow_curve")
    }
    missing = {"FIGHT_PROP_BASE_HP", "FIGHT_PROP_BASE_ATTACK", "FIGHT_PROP_BASE_DEFENSE"} - set(
        curves,
    )
    if missing:
        msg = (
            f"character {key}: no growth curve for {sorted(missing)}. The published base "
            f"stats cannot be evaluated at any level without them, and a character seeded "
            f"without them would fail at calculation time instead of at import time."
        )
        raise NanokaMappingError(msg)
    return curves


def ascension_stat_type(key: str, ascension: list[dict[str, Any]]) -> StatType | None:
    """The stat a character gains on ascension, derived from the ascension rows.

    All 150 characters at 7.0.51 have exactly six rows and exactly one non-base key across
    them, spread over 16 distinct props (ATK% on 48, Crit DMG on 22, Crit Rate on 20, …).
    Anything else is an upstream shape change: **two** candidate keys means the payload now
    grants two ascension stats and picking either would be a guess, so it raises. An empty
    ascension list returns None, since there is then nothing to derive from.
    """
    if not ascension:
        return None
    extras = {key_ for row in ascension for key_ in row} - _ASCENSION_BASE_KEYS
    if len(extras) != 1:
        msg = (
            f"character {key}: expected exactly one non-base ascension prop, found "
            f"{sorted(extras)}. All 150 characters at 7.0.51 have exactly one; this is an "
            f"upstream shape change, and choosing one of several would be a guess."
        )
        raise NanokaMappingError(msg)
    raw = next(iter(extras))
    mapped = stat_type_for(raw)
    if mapped is None:
        # Same reasoning as `_substat`: a prop this build does not know is a moved
        # vocabulary, and storing NULL would say "this character gains nothing on
        # ascension" — which is not a thing that is true of any character.
        msg = (
            f"character {key}: ascension prop {raw!r} is not in StatType. Add it to "
            f"app/models/enums.py and refresh tests/fixtures/nanoka_gi/."
        )
        raise NanokaMappingError(msg)
    return mapped


def burst_energy_cost(payload: dict[str, Any]) -> int | None:
    """The burst's energy cost, parsed out of its own description rows.

    Returns None when there is no burst talent or no `Energy Cost` row — true for four
    characters at 7.0.51 (Mavuika, Skirk, and the two Traveler bodies with no skills at
    all), which is why `Character.burst_energy_cost` is nullable rather than defaulted to a
    number that would read as real data.
    """
    for skill in payload.get("skills") or []:
        if classify_talent(skill) is not TalentType.ELEMENTAL_BURST:
            continue
        promote = _first_promote(skill)
        labels = promote.get("desc") or []
        params = promote.get("param") or []
        for label in labels:
            if not label.startswith(_ENERGY_COST_LABEL):
                continue
            match = _PARAM_REF.search(label)
            if match is None:
                continue
            index = int(match.group(1)) - 1
            if 0 <= index < len(params):
                return int(params[index])
            logger.warning(
                "Energy Cost row %r references param%d but only %d params exist",
                label, index + 1, len(params),
            )
    return None


def classify_talent(skill: dict[str, Any]) -> TalentType | None:
    """What a `skills[]` entry is, from its icon **and** its promote ladder.

    `TalentType.from_skill_icon` maps `Skill_A_*` → normal attack, `Skill_E_*` → burst and
    `Skill_S_*` → elemental skill. Across all 446 skill entries at 7.0.51 that is 148, 148
    and 150 respectively — so two characters have *two* `Skill_S_` entries and the prefix
    alone cannot separate an alternate sprint from an elemental skill. The one-level
    promote ladder does: every real talent publishes 15.
    """
    promote = skill.get("promote") or {}
    talent_type = TalentType.from_skill_icon(_first_promote(skill).get("icon"))
    if (
        talent_type is TalentType.ELEMENTAL_SKILL
        and len(promote) == _ALTERNATE_SPRINT_PROMOTE_LEVELS
    ):
        return TalentType.ALTERNATE_SPRINT
    return talent_type


def talent_rows(key: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One dict per `skills[]` entry, each carrying its own `scalings` list.

    An unclassifiable icon raises rather than dropping the talent: a character silently
    missing its burst is a wrong build, not a missing row.
    """
    rows: list[dict[str, Any]] = []
    for skill in payload.get("skills") or []:
        talent_type = classify_talent(skill)
        if talent_type is None:
            msg = (
                f"character {key}: talent {skill.get('id')} ({skill.get('name')!r}) has an "
                f"unclassifiable icon {_first_promote(skill).get('icon')!r}"
            )
            raise NanokaMappingError(msg)
        rows.append(
            {
                "nanoka_id": int(skill["id"]),
                "talent_type": talent_type,
                "name": skill.get("name", ""),
                "description": skill.get("desc", "") or "",
                "icon": _first_promote(skill).get("icon"),
                "scalings": _scaling_rows(skill),
            },
        )
    return rows


def _scaling_rows(skill: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per published talent level.

    The level is the entry's own `level` field, not `int(key) + 1` — they agree on all
    6,662 promote entries at 7.0.51, and using the payload's own number means a future
    payload that renumbers is a diff rather than an off-by-one.
    """
    rows = [
        {
            "level": int(entry["level"]),
            "labels": entry.get("desc") or [],
            "params": entry.get("param") or [],
        }
        for entry in (skill.get("promote") or {}).values()
    ]
    return sorted(rows, key=lambda row: row["level"])


def constellation_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """C1-C6, positioned by list order.

    `position` is the ordinal and **not** the payload id: the ids are 21-26 for Ayaka and
    51-56 for the Traveler — contiguous but arbitrary, so ordering on them would be a
    coincidence rather than a guarantee (C.3).
    """
    return [
        {
            "nanoka_id": int(entry["id"]),
            "position": position,
            "name": entry.get("name", ""),
            "description": entry.get("desc", "") or "",
            "icon": entry.get("icon"),
        }
        for position, entry in enumerate(payload.get("constellations") or [], start=1)
    ]


def passive_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The ascension and utility passives, splitting `unlock`'s two shapes.

    `passives[].unlock` is an integer 460 times across the 150 characters (`0`, `1`, `4`)
    and a **list** 33 times, always one id — `[603101]` on the Traveler's "Foreign
    Starfire", `[7469304]` on Cyno's. The list form goes to `unlock_condition_ids` and
    leaves `unlock_ascension` NULL; nothing here interprets what those ids point at.
    """
    rows = []
    for entry in payload.get("passives") or []:
        unlock = entry.get("unlock")
        is_gate = isinstance(unlock, int) and not isinstance(unlock, bool)
        rows.append(
            {
                "nanoka_id": int(entry["id"]),
                "unlock_ascension": unlock if is_gate else None,
                "unlock_condition_ids": list(unlock) if isinstance(unlock, list) else [],
                "name": entry.get("name", ""),
                "description": entry.get("desc", "") or "",
                "icon": entry.get("icon"),
            },
        )
    return rows


def _first_promote(skill: dict[str, Any]) -> dict[str, Any]:
    """`promote["0"]`, the level-1 entry — where the icon and the label rows live."""
    promote = skill.get("promote") or {}
    if not promote:
        return {}
    first_key = min(promote, key=int)
    return promote[first_key]


# -- Weapons (D.4) ------------------------------------------------------------------

#: `weapon_prop[]` always leads with the base-ATK entry (252 of 252 stat-carrying weapons at
#: 7.0.51), but the mapping matches on `prop_type` rather than on position, because
#: position is exactly the kind of thing a patch reorders silently.
_BASE_ATK_PROP = "FIGHT_PROP_BASE_ATTACK"


def is_weapon_skin(payload: dict[str, Any]) -> bool:
    """True for a cosmetic skin, which is in the weapon index but is not a weapon.

    26 of the 286 entries at 7.0.51 (ids `3xxxxx`) carry `"skin": true` and a completely
    different payload shape: no `weapon_prop`, no `ascension`, no `refinement`, no
    `stats_modifier`, and in two cases not even a name. Importing them would put stat-less
    rows in the catalogue that the optimizer would then have to learn to ignore.
    """
    return bool(payload.get("skin"))


def weapon_fields(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The `Weapon` column values for one detail payload.

    Tolerates the stat-less shape on purpose. The eight `ITEM_TPS_WEAPON` entries
    (224001-224008, `"tps": true`) carry no `weapon_prop`, `ascension` or `refinement` at
    all — C.4 made `base_atk` and `sub_stat_type` nullable for exactly them, so that they
    import visibly rather than dying on a NOT NULL violation, and whether they belong in
    the optimizer stays a Chunk G question.
    """
    weapon_type = WeaponType.parse(payload.get("weapon_type"))
    if weapon_type is None:
        msg = f"weapon {key}: unmappable weapon type {payload.get('weapon_type')!r}"
        raise NanokaMappingError(msg)
    rarity = Rarity.parse(payload.get("rarity"))
    if rarity is None:
        msg = f"weapon {key}: unmappable rarity {payload.get('rarity')!r}"
        raise NanokaMappingError(msg)

    base, sub = _split_weapon_props(key, payload.get("weapon_prop") or [])
    sub_stat_type = _substat(key, sub)
    return {
        "nanoka_id": int(key),
        "name": payload.get("name", ""),
        "weapon_type": weapon_type,
        "rarity": rarity,
        "base_atk": base.get("init_value") if base else None,
        "base_atk_curve": base.get("type") if base else None,
        "sub_stat_type": sub_stat_type,
        # Value and curve follow the *stat*, not the entry: the ten weapons whose second
        # prop is `FIGHT_PROP_NONE` still carry an `init_value` of 0 and a curve name, and
        # storing those would say "this weapon has a substat worth 0" rather than "this
        # weapon has no substat".
        "sub_stat_base_value": sub.get("init_value") if sub_stat_type else None,
        "sub_stat_curve": sub.get("type") if sub_stat_type else None,
        "ascension_atk": payload.get("ascension") or {},
        "icon": payload.get("icon"),
        "description": payload.get("desc", "") or "",
        # `{"1": 600, ... "90": 666050}` — the EXP to leave each level. Per weapon, so the
        # five parallel curves `WeaponLevelExcelConfigData` publishes are already resolved
        # to the right one by rarity.
        "xp_requirements": dict(payload.get("xp_requirements") or {}),
    }


def _substat(key: str, sub: dict[str, Any] | None) -> StatType | None:
    """The substat's `StatType`, or None when the weapon genuinely has none.

    **Absent and unmapped are different answers.** Ten weapons carry `FIGHT_PROP_NONE`,
    which means "no substat" and is fine. A prop this build does not know means the
    vocabulary moved, and returning None there would import a weapon the optimizer reads
    as having no secondary stat — on an otherwise green run. So that raises.
    """
    if sub is None:
        return None
    raw = sub.get("prop_type")
    if is_absent_stat_key(raw):
        return None
    mapped = stat_type_for(raw)
    if mapped is None:
        msg = (
            f"weapon {key}: substat {raw!r} is not in StatType. Add it to "
            f"app/models/enums.py and refresh tests/fixtures/nanoka_gi/ — importing it as "
            f"'no substat' would be a wrong row on a green run."
        )
        raise NanokaMappingError(msg)
    return mapped


def _split_weapon_props(
    key: str, props: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Separate the base-ATK entry from the substat entry.

    Observed shapes at 7.0.51 are exactly two: two entries (252 weapons) or none (the 26
    skins and 8 TPS weapons). A third entry would mean weapons now carry two substats, and
    silently keeping the first is the kind of guess that ships wrong numbers — so it raises.
    """
    base = next((prop for prop in props if prop.get("prop_type") == _BASE_ATK_PROP), None)
    others = [prop for prop in props if prop is not base]
    if len(others) > 1:
        msg = (
            f"weapon {key}: expected at most one substat prop, found "
            f"{[prop.get('prop_type') for prop in others]}"
        )
        raise NanokaMappingError(msg)
    return base, others[0] if others else None


def refinement_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """R1-R5, from the `refinement` object keyed `"1"`..`"5"`.

    Not always five, and not always present: 239 weapons publish five levels, three publish
    exactly one (Sword of Descension, Predator, Kagotsurube Isshin — the event weapons that
    cannot be refined), and 44 publish none at all (the ten 1★/2★ weapons with no passive,
    plus the 34 skins and TPS entries). All three are data, not gaps to fill in.
    """
    return sorted(
        (
            {
                "level": int(level),
                "name": entry.get("name", "") or "",
                "description": entry.get("desc", "") or "",
                "param_list": entry.get("param_list") or [],
            }
            for level, entry in (payload.get("refinement") or {}).items()
        ),
        key=lambda row: row["level"],
    )


# -- Artifact sets (D.5) ------------------------------------------------------------

def _part_icons(payload: dict[str, Any]) -> dict[str, str] | None:
    """`{slot: icon}` from the payload's `parts`, or None where it publishes none.

    **Read, not derived.** The basenames differ only in a trailing digit — `_1` for
    `equip_ring`, `_4` for `equip_bracer` — and computing them from the set icon would be a
    guess about a numbering nobody documents. `parts` states the pairing, so this copies it.

    None rather than `{}` for a set with no parts: a set that publishes no per-slot art and one
    whose art failed to parse should not look alike to a caller deciding whether to fall back.
    """
    parts = payload.get("parts")
    if not isinstance(parts, dict):
        return None
    found = {
        slot: part["icon"]
        for slot, part in parts.items()
        if isinstance(part, dict) and isinstance(part.get("icon"), str)
    }
    return found or None


def artifact_set_fields(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The `ArtifactSet` column values for one detail payload.

    **The set's name is not a top-level field.** It lives on each affix, and all 65 sets at
    7.0.51 have exactly one distinct name across their affixes — so `affix[0].name` is the
    set name rather than a first-of-several guess. A set with no affixes at all would have
    no name to take, and raises instead of being stored as `""`.
    """
    affixes = payload.get("affix") or []
    if not affixes:
        msg = f"artifact set {key}: no affix rows, so the payload carries no set name"
        raise NanokaMappingError(msg)
    return {
        "nanoka_id": int(key),
        "name": affixes[0].get("name", ""),
        "icon": payload.get("icon"),
        "part_icons": _part_icons(payload),
        # `need` is per-set data, not the constant [2, 4]: 60 sets are [2, 4] and five are
        # [1] — the "Prayers" circlets (15009-15013), genuine one-piece sets (C.5).
        "piece_thresholds": payload.get("need") or [],
        "available_ranks": payload.get("rank") or [],
    }


def artifact_affix_rows(key: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per set-bonus tier, paired with its piece requirement.

    `position` is the affix's own `level` (0 for the 2-piece bonus, 1 for the 4-piece), and
    it is cross-checked against the list index: they agree on all 125 affixes at 7.0.51, and
    a disagreement would mean the pairing with `need` — which is positional — is no longer
    sound. `pieces_required` comes from `need[position]`, so a mismatched length raises
    rather than pairing a 4-piece bonus with a 2-piece threshold.
    """
    affixes = payload.get("affix") or []
    thresholds = payload.get("need") or []
    if len(thresholds) != len(affixes):
        msg = (
            f"artifact set {key}: {len(affixes)} affix rows against {len(thresholds)} "
            f"piece thresholds {thresholds}; the pairing is positional and cannot be guessed"
        )
        raise NanokaMappingError(msg)

    rows = []
    for index, affix in enumerate(affixes):
        position = affix.get("level", index)
        if position != index:
            msg = (
                f"artifact set {key}: affix at index {index} declares level {position}; "
                f"the pairing with need={thresholds} is positional"
            )
            raise NanokaMappingError(msg)
        rows.append(
            {
                "position": position,
                "pieces_required": thresholds[index],
                "name": affix.get("name", ""),
                "description": affix.get("desc", "") or "",
                # Both kept: 324 affix rows across the 65 sets have `add_props` entirely
                # FIGHT_PROP_NONE, and for those `param_list` holds the only numbers that
                # exist outside `<color=…>` markup (C.5, PR #2 review finding 5).
                "add_props": affix.get("add_props") or [],
                "param_list": affix.get("param_list") or [],
            },
        )
    return rows


# -- Enemies (D.6) ------------------------------------------------------------------

#: `sub_hurt` key → the `EnemyProfile` resistance column. The payload's internal names are
#: not display names, and the mapping is the one C.2 already established and asserted
#: against the affix descriptions: GRASS is Dendro, ROCK is Geo, ELEC is Electro, WATER is
#: Hydro, WIND is Anemo, ICE is Cryo, FIRE is Pyro (`enums.StatType`).
_SUB_HURT_COLUMNS: dict[str, str] = {
    "fire": "pyro_res",
    "water": "hydro_res",
    "wind": "anemo_res",
    "ice": "cryo_res",
    "elec": "electro_res",
    "rock": "geo_res",
    "grass": "dendro_res",
    "physical": "physical_res",
}

#: A prop entry with no stat. Six children at 7.0.51 carry `FIGHT_PROP_NONE` with
#: `GROW_CURVE_NONE` (monster 29010101); they name no curve and are dropped rather than
#: stored as a curve called "none".
_NO_CURVE = "GROW_CURVE_NONE"


def is_statless_monster(payload: dict[str, Any]) -> bool:
    """True for a codex entry with no `child` map, and therefore no combat stats at all.

    225 of the 585 monster entries at 7.0.51 are this shape — a four-key payload of
    `codex`/`desc`/`icon`/`name`, all of them CRITTER, FISH, ANIMAL or AVIARY wildlife.
    They are codex entries, not damage targets, and a row with three zero stats and eight
    zero resistances would be indistinguishable from a mapping bug.
    """
    return not (payload.get("child") or {})


def canonical_variant(key: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Pick the `child` entry a profile's stats come from.

    A monster payload is a **family**: `child` holds 1-17 spawn configurations (a plain
    Hilichurl, its NoAI variant, its co-op challenge variant, …), and the stats live only
    on the children. The choice matters — 189 of the 360 families with children have
    children whose `base` differs, 85 whose `sub_hurt` differs — so it is made by a stated
    rule rather than by `next(iter(...))`:

    1. the child whose id **equals the family id**, which is the plain spawn and exists for
       358 of the 360 families;
    2. otherwise the **lowest** child id, which is deterministic where "first" is not.

    The chosen id and the family's child count are both stored (`variant_nanoka_id`,
    `variant_count`) so the choice is visible in the database rather than only here.
    """
    children = payload.get("child") or {}
    if not children:
        msg = f"monster {key}: no child entries to take stats from"
        raise NanokaMappingError(msg)
    if key in children:
        return key, children[key]
    lowest = min(children, key=lambda raw: (len(raw), raw))
    return lowest, children[lowest]


def enemy_profile_fields(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The `EnemyProfile` column values for one monster family.

    The three base stats are the child's curve **bases**, not level-90 values — see the
    `EnemyProfile` docstring. `base.em` is dropped: it is `0` on all 1,512 children at
    7.0.51 and enemy Elemental Mastery does not enter a player's damage calculation, so a
    column of zeroes would be a claim that it might.
    """
    variant_id, variant = canonical_variant(key, payload)
    base = variant.get("base") or {}
    fields: dict[str, Any] = {
        "nanoka_id": int(key),
        "name": payload.get("name", ""),
        # Read from the family payload, not the variant: `child` entries carry no art of
        # their own, and the codex shows one picture per family.
        "icon": payload.get("icon") or None,
        "tags": payload.get("codex", "") or "",
        "base_hp": base.get("hp", 0.0),
        "base_atk": base.get("atk", 0.0),
        "base_def": base.get("def", 0.0),
        "variant_nanoka_id": int(variant_id),
        "variant_count": len(payload.get("child") or {}),
        "stat_curves": _stat_curves(variant),
    }
    sub_hurt = variant.get("sub_hurt") or {}
    unknown = set(sub_hurt) - set(_SUB_HURT_COLUMNS)
    if unknown:
        msg = (
            f"monster {key}: unmapped sub_hurt channel(s) {sorted(unknown)}. Eight channels "
            f"are modelled as eight columns; a ninth needs a column, not a silent drop."
        )
        raise NanokaMappingError(msg)
    for channel, column in _SUB_HURT_COLUMNS.items():
        fields[column] = sub_hurt.get(channel, 0.0)
    return fields


def _stat_curves(variant: dict[str, Any]) -> dict[str, str]:
    """`{prop: grow_curve}` from a child's `prop[]`, dropping the no-curve entries."""
    return {
        prop["type"]: prop["grow_curve"]
        for prop in (variant.get("prop") or [])
        if prop.get("grow_curve") not in (None, "", _NO_CURVE)
        and prop.get("type") not in (None, "", "FIGHT_PROP_NONE")
    }


# -- Levelling costs ------------------------------------------------------------------
#
# `materials.ascensions`, `materials.talents` and the weapon's `materials` map have been in
# every pinned payload since Chunk D and were never read. `docs/RESEARCH_leveling_planner_data.md`
# §1 records that; these functions are what finally read them.


def _cost_items(entry: dict[str, Any]) -> list[dict[str, int]]:
    """`{"mats": [...], "cost": n}` → the material list, as `[{"id":…, "count":…}]`.

    Names and ranks are dropped here on purpose: they belong to the material, not to the
    bill, and `material_rows` collects them separately so one material has one row.
    """
    return [
        {"id": int(mat["id"]), "count": int(mat["count"])}
        for mat in entry.get("mats") or []
        if mat and mat.get("id") is not None
    ]


def character_ascension_cost_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per ascension phase, `phase` 1-6.

    The payload lists six entries in ladder order and `phase` is their 1-based position —
    which is positional, and the only thing available: nothing in the entry names its phase.
    The six-ness is asserted rather than trusted, because a payload that grew a seventh
    entry would otherwise renumber the whole ladder in silence.
    """
    entries = (payload.get("materials") or {}).get("ascensions") or []
    if entries and len(entries) != ASCENSION_PHASES:
        msg = f"expected {ASCENSION_PHASES} ascension cost entries, found {len(entries)}"
        raise NanokaMappingError(msg)
    return [
        {"phase": index, "mora": int(entry.get("cost", 0)), "items": _cost_items(entry)}
        for index, entry in enumerate(entries, start=1)
    ]


def talent_cost_rows(key: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per talent per upgrade step, carrying the talent's `nanoka_id`.

    **`materials.talents` is parallel to `skills[]` and there is no key to join on**, so this
    is positional and says so. The lengths are asserted to match, which is the only check
    available and is a real one: Ayaka has four skills and four cost lists holding **two
    distinct** sets, so a mismatch here would silently price her talents off each other's
    bills. Rosaria and Venti are uniform, which is why a spot check would have missed it.

    Nine steps take a talent from level 1 to 10. Levels 11-15 come from constellations and
    have no rows at all.
    """
    talent_costs = (payload.get("materials") or {}).get("talents") or []
    skills = payload.get("skills") or []
    if talent_costs and len(talent_costs) != len(skills):
        msg = (
            f"character {key}: {len(talent_costs)} talent cost lists against {len(skills)} "
            "skills — the two are joined by position and cannot be paired"
        )
        raise NanokaMappingError(msg)
    rows: list[dict[str, Any]] = []
    for skill, levels in zip(skills, talent_costs, strict=False):
        for level, entry in enumerate(levels, start=1):
            rows.append(
                {
                    "nanoka_id": int(skill["id"]),
                    "level": level,
                    "mora": int(entry.get("cost", 0)),
                    "items": _cost_items(entry),
                },
            )
    return rows


def weapon_ascension_cost_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per weapon ascension phase, from the `"1".."6"`-keyed `materials` map.

    Keyed rather than positional here — the weapon payload spells the phase out — so this
    one reads the key instead of counting.
    """
    materials = payload.get("materials") or {}
    rows = []
    for raw_phase, entry in materials.items():
        try:
            phase = int(raw_phase)
        except (TypeError, ValueError):
            continue
        if not 1 <= phase <= ASCENSION_PHASES:
            msg = f"weapon ascension phase {raw_phase!r} is outside 1-{ASCENSION_PHASES}"
            raise NanokaMappingError(msg)
        rows.append(
            {"phase": phase, "mora": int(entry.get("cost", 0)), "items": _cost_items(entry)},
        )
    return sorted(rows, key=lambda row: row["phase"])


def material_rows(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Every material this payload mentions, as `{id: {"name":…, "rarity":…}}`.

    Collected from both shapes — the character's `ascensions`/`talents` and the weapon's
    numbered map — so one function serves both importers. `rarity` is nanoka's `rank`; the
    seed cross-checks it against YuanShen's `rankLevel`, and at 7.0.51 all 508 agree.
    """
    materials = payload.get("materials") or {}
    groups: list[Any] = []
    if isinstance(materials, dict):
        groups.extend(materials.get("ascensions") or [])
        for levels in materials.get("talents") or []:
            groups.extend(levels)
        for raw_phase, entry in materials.items():
            if raw_phase not in {"ascensions", "talents"} and isinstance(entry, dict):
                groups.append(entry)
    out: dict[int, dict[str, Any]] = {}
    for entry in groups:
        for mat in (entry or {}).get("mats") or []:
            if not mat or mat.get("id") is None:
                continue
            out[int(mat["id"])] = {
                "name": str(mat.get("name", "")),
                "rarity": int(mat.get("rank", 0)),
            }
    return out
