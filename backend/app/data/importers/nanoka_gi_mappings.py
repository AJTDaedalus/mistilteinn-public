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
        "burst_energy_cost": burst_energy_cost(payload),
        "icon": payload.get("icon"),
    }


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
    return stat_type_for(next(iter(extras)))


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
    sub_stat_type = stat_type_for(sub.get("prop_type")) if sub else None
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
    }


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
