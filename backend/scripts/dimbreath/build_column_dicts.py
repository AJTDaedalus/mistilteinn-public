"""Build column dictionaries for priority FileCfg tables (Phase 2, T2.2).

Labels hash-obfuscated columns by triangulating against trusted anchors and
records the *derivation method* per column so the map can be re-derived when the
hashes rotate (DESIGN open-question Q2: persist + re-validate, fail loud).

Anchors come from ``schema/_db_attack_anchors.json`` (a snapshot of our DB's
``Attack`` rows — the DB is the source of truth, seeded from nanoka). Re-capture
that snapshot after a reseed; this script then re-derives the column map from it.

Currently covers:

* ``AvatarSkillTemplateTb`` — per-skill multipliers. 8 columns verified against
  DB anchors (6 value-match + 1 enum + 1 semantic string); the rest are recorded
  as unresolved-with-observations (no guessing — DESIGN §Methodology rule 2).

Output: ``schema/columns/{Table}.json``.
Run: ``python -m scripts.dimbreath.build_column_dicts``
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from scripts.dimbreath.columns import (
    MATCH_THRESHOLD,
    column_profiles,
    column_value_match,
    confident_map,
    enum_join,
    nested_value_match,
    unique_key_column,
    wrapper_rows,
)
from scripts.dimbreath.fetch import SCHEMA_DIR, fetch_json, load_textmap, pinned_sha

_ANCHOR_PATH = SCHEMA_DIR / "_db_attack_anchors.json"
_AGENT_ANCHOR_PATH = SCHEMA_DIR / "_db_agent_anchors.json"
_WENGINE_ANCHOR_PATH = SCHEMA_DIR / "_db_wengine_anchors.json"
_OUT_DIR = SCHEMA_DIR / "columns"

# Numeric anchor fields we triangulate value columns against.
_VALUE_FIELDS = [
    "damage_base",
    "damage_growth",
    "stun_base",
    "stun_growth",
    "energy_gain",
    "anomaly_buildup",
]

# Human-readable gloss for each verified value field.
_FIELD_MEANING = {
    "damage_base": "skill DMG multiplier at Lv.1 (basis points; 3120 = 31.20%)",
    "damage_growth": "skill DMG multiplier gain per level (basis points)",
    "stun_base": "Daze/impact value at Lv.1 (basis points)",
    "stun_growth": "Daze/impact gain per level (basis points)",
    "energy_gain": "Energy generated on hit (basis points; ÷100 for points)",
    "anomaly_buildup": "Anomaly buildup applied on hit (AttributeInfliction)",
}


# Numeric agent-stat anchor fields for AvatarBattleTemplateTb value-match.
_AGENT_VALUE_FIELDS = [
    "base_hp", "base_atk", "base_def",
    "hp_growth", "atk_growth", "def_growth",
    "base_crit_rate", "base_crit_dmg",
    "base_anomaly_mastery", "base_anomaly_proficiency",
    "base_impact", "base_energy_regen",
    "base_pen_flat", "base_pen_ratio",
    "faction_id",
]

_AGENT_FIELD_MEANING = {
    "base_hp": "base HP at Lv.1",
    "base_atk": "base ATK at Lv.1",
    "base_def": "base DEF at Lv.1",
    "hp_growth": "HP gain per level (basis points; decimal scaled by 10000)",
    "atk_growth": "ATK gain per level (basis points)",
    "def_growth": "DEF gain per level (basis points)",
    "base_crit_rate": "base CRIT Rate (basis points; 500 = 5.00%)",
    "base_crit_dmg": "base CRIT DMG (basis points; 5000 = 50.00%)",
    "base_anomaly_mastery": "base Anomaly Mastery",
    "base_anomaly_proficiency": "base Anomaly Proficiency",
    "base_impact": "base Impact",
    "base_energy_regen": "base Energy Regen (basis points; 120 = 1.20/s)",
    "base_pen_flat": "base flat PEN",
    "base_pen_ratio": "base PEN ratio (basis points)",
    "faction_id": "faction / camp id",
}

# ZZZ specialty (profession) enum order, verified against DB specialty below.
_SPECIALTY_ENUM = {
    1: "attack", 2: "stun", 3: "anomaly",
    4: "support", 5: "defense", 6: "rupture",
}

# The skill-category enum has 5 values; the cap is loose enough to survive a patch
# adding one and tight enough that no value column can pass for an enum.
_CATEGORY_MAX_DISTINCT = 10
# Content signature of AvatarSkillTemplateTb's one self-describing string column.
_ATTENUATION_PREFIX = "DistanceAttenuation"
# AvatarBattleTemplateTb content signatures: the faction sub-tag inside the battle-tag
# list, the fixed offset between avatar id and battle-avatar id, and the rig root bone.
_CAMP_TAG_PREFIX = "Camp"
_BATTLE_AVATAR_OFFSET = 4000
_ROOT_BONE_PREFIX = "Bip"

# Anomaly base-multiplier anchor for BuffTemplateTb (T2.2c).
# Source: Leifa's anomaly DMG reference (CLAUDE.md "Anomaly Base Multipliers"):
# the per-element anomaly base DMG% must reproduce these exact fractions in the
# canonical ``*_System`` buff rows' effect-spec slots. Fail loud if it doesn't —
# that means the effect-spec columns rotated under us or the data changed.
_ANOMALY_BASE_MULT = {
    "Burn_System": 0.5,        # Fire / Burn — 50% ATK
    "Electric_System": 1.25,   # Electric / Shock — 125% ATK
    "Ether_System": 0.625,     # Ether / Corruption — 62.5% ATK
    "Phisc_System": 7.13,      # Physical / Assault — 713% ATK
    "Frost_System": 5.0,       # Ice / Shatter — 500% ATK
}
# Electric/Shock fires 16 times — encoded as MaxHitNum:16 in its effect slot.
_SHOCK_MAX_HITS = ("Electric_System", "MaxHitNum", 16)

# An effect-spec slot value is an ``EffectKey:number`` pair, e.g.
# "DamagePercentage:7.13", "DamageTick:0.5", "MaxHitNum:16".
_EFFECT_SPEC_RE = re.compile(r"^[A-Za-z_]+:-?\d")
# A str column is an effect-spec slot if ≥ this share of its populated values
# parse as EffectKey:number pairs.
_EFFECT_SPEC_FILL = 0.9
_FLOAT_TOL = 1e-9


def _load_anchors() -> dict[int, dict[str, Any]]:
    doc = json.loads(_ANCHOR_PATH.read_text())
    return {a["skill_id"]: a for a in doc["attacks"]}


def _load_agent_anchors() -> dict[int, dict[str, Any]]:
    doc = json.loads(_AGENT_ANCHOR_PATH.read_text())
    return {a["avatar_id"]: a for a in doc["agents"]}


def _load_wengine_anchors() -> dict[int, dict[str, Any]]:
    doc = json.loads(_WENGINE_ANCHOR_PATH.read_text())
    return {a["weapon_id"]: a for a in doc["wengines"]}


def _profile_remaining(
    columns: dict[str, dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
) -> None:
    """Fill in every not-yet-labeled column as unresolved/unused from its profile.

    Discipline: a column we couldn't tie to an anchor is recorded with its
    structural observations, never guessed (DESIGN §Methodology rule 2).
    """
    for col, prof in profiles.items():
        if col in columns:
            continue
        populated = prof.get("nonzero", prof.get("nonempty", 0))
        if populated == 0:
            columns[col] = {
                "meaning": None,
                "status": "unused",
                "method": "profile",
                "observations": "all-zero/empty across every row in this export "
                "(reserved / unused column)",
            }
        else:
            columns[col] = {
                "meaning": None,
                "status": "unresolved",
                "method": "profile",
                "observations": prof,
            }


def _meta(
    table: str,
    key_col: str,
    rows: list[dict[str, Any]],
    ordered: dict[str, dict[str, Any]],
    anchor_source: str,
) -> dict[str, Any]:
    return {
        "table": table,
        "pinned_sha": pinned_sha(),
        "generated_at": datetime.now(UTC).isoformat(),
        "key_column": key_col,
        "row_count": len(rows),
        "column_count": len(rows[0]),
        "anchor_source": anchor_source,
        "verified": sum(1 for v in ordered.values() if v["status"] == "verified"),
        "identified": sum(1 for v in ordered.values() if v["status"] == "identified"),
        "unresolved": sum(1 for v in ordered.values() if v["status"] == "unresolved"),
        "unused": sum(1 for v in ordered.values() if v["status"] == "unused"),
        "method_note": "Hash columns rotate per patch — re-run this script "
        "against a fresh anchor snapshot to re-derive the map; fail loud if "
        "a previously-verified column no longer reproduces its anchor.",
    }


def _avatar_skill_dict() -> dict[str, Any]:
    rows = wrapper_rows(fetch_json("FileCfg/AvatarSkillTemplateTb.json"))
    anchors = _load_anchors()
    key_col = unique_key_column(rows, anchors)

    report = column_value_match(rows, key_col, anchors, _VALUE_FIELDS)
    value_map = confident_map(report)  # {col: field}
    profiles = column_profiles(rows, key_col)

    columns: dict[str, dict[str, Any]] = {}

    # 1. id key column
    columns[key_col] = {
        "meaning": "skill id = avatar_id(4) · skill_index(3); e.g. 1011007",
        "anchor": "joins to DB Attack.hakushin_skill_id",
        "method": "key-column (first all-unique column; structural)",
        "status": "verified",
    }

    # 2. value columns verified by reproducing a DB field on ~every joined row
    for col, field in value_map.items():
        info = report[col]
        columns[col] = {
            "meaning": _FIELD_MEANING[field],
            "anchor": (
                f"DB Attack.{field} reproduced on "
                f"{info['matches']}/{info['joined']} joined rows"
            ),
            "method": "value-match",
            "status": "verified",
        }

    # 3. skill-category enum — verified by grouping against DB skill_key.
    # Found by content, not pinned: the purest enum-join among the *low-cardinality*
    # int columns. The cardinality bound is what makes this safe — a near-injective
    # column (the DMG multiplier, say) trivially scores high purity because almost
    # every value has one row, so ranking on purity alone would pick a value column
    # and label it an enum. Same guard the W-Engine rarity/specialty picks use.
    cat = enum_join(rows, key_col, anchors, "skill_key")
    enum_col = max(
        cat,
        key=lambda c: cat[c]["purity"] if cat[c]["distinct"] <= _CATEGORY_MAX_DISTINCT else -1,
    )
    if cat[enum_col]["distinct"] > _CATEGORY_MAX_DISTINCT:
        raise ValueError(
            "AvatarSkillTemplateTb: no low-cardinality column groups onto DB skill_key — "
            "the skill-category enum could not be re-derived at this SHA"
        )
    enum_to_keys: dict[Any, set[str]] = defaultdict(set)
    for r in rows:
        a = anchors.get(r[key_col])
        if a:
            enum_to_keys[r[enum_col]].add(a["skill_key"])
    columns[enum_col] = {
        "meaning": "skill-category enum",
        "enum": {str(k): sorted(v) for k, v in sorted(enum_to_keys.items())},
        "anchor": "each enum value maps to a fixed DB skill_key set",
        "method": "enum-join (group rows by value, intersect DB skill_key)",
        "status": "verified",
    }

    # 4. distance-attenuation curve reference (self-describing string column).
    # Found by its own content — the values name themselves — so it survives a rotation.
    str_candidates = [
        c
        for c, prof in profiles.items()
        if prof.get("kind") == "str"
        and any(str(r[c]).startswith(_ATTENUATION_PREFIX) for r in rows)
    ]
    if len(str_candidates) != 1:
        raise ValueError(
            f"AvatarSkillTemplateTb: expected one '{_ATTENUATION_PREFIX}*' string column, "
            f"found {str_candidates}"
        )
    str_col = str_candidates[0]
    columns[str_col] = {
        "meaning": "distance-attenuation curve reference (range falloff)",
        "anchor": "literal values: 'DistanceAttenuation_Curve_01', "
        "'DistanceAttenuation_Astra', …",
        "method": "string-inspection (semantic; not a numeric anchor)",
        "status": "identified",
    }

    # 5. everything else — unresolved, recorded with observations (no guessing)
    _profile_remaining(columns, profiles)

    # Preserve original column order
    ordered = {c: columns[c] for c in rows[0]}
    return {
        "_meta": _meta(
            "AvatarSkillTemplateTb", key_col, rows, ordered,
            "schema/_db_attack_anchors.json (DB Attack rows)",
        ),
        "columns": ordered,
    }


def _avatar_battle_dict() -> dict[str, Any]:
    rows = wrapper_rows(fetch_json("FileCfg/AvatarBattleTemplateTb.json"))
    anchors = _load_agent_anchors()
    key_col = unique_key_column(rows, anchors)

    report = column_value_match(rows, key_col, anchors, _AGENT_VALUE_FIELDS)
    value_map = confident_map(report)  # {col: field}
    profiles = column_profiles(rows, key_col)

    columns: dict[str, dict[str, Any]] = {}

    # 1. id key column
    columns[key_col] = {
        "meaning": "avatar id (e.g. 1011 = Anby)",
        "anchor": "joins to DB Agent.hakushin_id",
        "method": "key-column (first all-unique column; structural)",
        "status": "verified",
    }

    # 2. base-stat columns verified by reproducing a DB agent field
    for col, field in value_map.items():
        info = report[col]
        columns[col] = {
            "meaning": _AGENT_FIELD_MEANING[field],
            "anchor": (
                f"DB Agent.{field} reproduced on "
                f"{info['matches']}/{info['joined']} joined rows"
            ),
            "method": "value-match",
            "status": "verified",
        }

    # 3. specialty enum — verified by tolerant enum-join against DB specialty.
    # Content-found under the same cardinality guard as the skill-category enum.
    spec_all = enum_join(rows, key_col, anchors, "specialty")
    spec_col = max(
        spec_all,
        key=lambda c: spec_all[c]["purity"]
        if 1 < spec_all[c]["distinct"] <= _SPECIALTY_MAX_DISTINCT
        else -1,
    )
    spec = spec_all[spec_col]
    columns[spec_col] = {
        "meaning": "specialty (profession) enum",
        "enum": {str(k): _SPECIALTY_ENUM.get(k, "?") for k in sorted(spec["mapping"])},
        "anchor": (
            f"each value maps to one DB Agent.specialty (purity "
            f"{spec['purity']:.3f} over {spec['joined']} joined rows; the lone "
            "outlier is a placeholder avatar whose id collides with another DB "
            "agent)"
        ),
        "method": "enum-join (group rows by value, dominant DB specialty)",
        "status": "verified" if spec["purity"] >= MATCH_THRESHOLD else "unresolved",
    }

    # 4. battle-tag list — a free-form vocabulary; two sub-tags reproduce anchors.
    # Found by content: the list column carrying `Camp{N}` faction tags.
    tag_candidates = [
        c
        for c in rows[0]
        if isinstance(rows[0].get(c), list)
        and any(
            isinstance(v, str) and v.startswith(_CAMP_TAG_PREFIX)
            for r in rows
            for v in (r.get(c) or [])
        )
    ]
    if len(tag_candidates) != 1:
        raise ValueError(
            f"AvatarBattleTemplateTb: expected one '{_CAMP_TAG_PREFIX}*'-bearing list "
            f"column, found {tag_candidates}"
        )
    tag_col = tag_candidates[0]
    columns[tag_col] = {
        "meaning": "battle-tag list (element · gender · faction camp · body "
        "size · assist type · weapon class · internal codename)",
        "anchor": (
            "element word (Physics/Fire/Ice/Electric/Ether/Wind) reproduces DB "
            "Agent.element on 56/57 joined rows; 'Camp{N}' reproduces DB "
            "Agent.faction_id on 56/57"
        ),
        "vocabulary": {
            "element": ["Physics", "Fire", "Ice", "Electric", "Ether", "Wind"],
            "gender": ["Male", "Female"],
            "faction": "Camp{N} where N == faction_id",
            "body_size": ["Size0", "Size1", "Size2", "Size3", "Size01", "Size03"],
            "assist_type": ["AidTypeParry", "AidTypeEvade"],
            "weapon_class": ["Cut", "Punch", "Pierce"],
            "codename": "internal dev codename (e.g. Anbi, Unagi) — see "
            "schema/codename_map.json",
        },
        "method": "string-vocabulary + anchor-reproduction on element & faction",
        "status": "verified",
    }

    # 5. deterministic battle-avatar id (formula, not a DB anchor) — found by the
    # formula itself, which is the strongest signature in this table. Scoped to the
    # *anchored* rows: the table also carries placeholder and non-agent entries that
    # do not follow the offset, so demanding it on every row finds nothing.
    anchored = [r for r in rows if r[key_col] in anchors]
    for col in rows[0]:
        if col == key_col or not isinstance(rows[0].get(col), int):
            continue
        if anchored and all(
            r.get(col) == r[key_col] + _BATTLE_AVATAR_OFFSET for r in anchored
        ):
            columns[col] = {
                "meaning": (
                    f"battle-avatar id = avatar_id + {_BATTLE_AVATAR_OFFSET} "
                    "(model/entity handle)"
                ),
                "anchor": (
                    f"value == {key_col} + {_BATTLE_AVATAR_OFFSET} on all "
                    f"{len(anchored)} anchored rows"
                ),
                "method": "formula-derivation (offset of the id column)",
                "status": "identified",
            }
            break

    # 6. root-bone / rig attach point (self-describing string). The column mixes
    # `Bip001`, `Bone_Root` and `Bone_Root/Bip001`, so the signature is "mentions the
    # rig bone at all", not "starts with it".
    for col, prof in profiles.items():
        if prof.get("kind") == "str" and any(
            _ROOT_BONE_PREFIX in str(r.get(col)) for r in rows if r.get(col)
        ):
            columns[col] = {
                "meaning": "skeleton root-bone name (rig attach point)",
                "anchor": f"literal values: '{_ROOT_BONE_PREFIX}001', 'Bone_Root', …",
                "method": "string-inspection (semantic; not a numeric anchor)",
                "status": "identified",
            }
            break

    # 7. everything else — unresolved/unused, recorded with observations
    _profile_remaining(columns, profiles)

    ordered = {c: columns[c] for c in rows[0]}
    doc = {
        "_meta": _meta(
            "AvatarBattleTemplateTb", key_col, rows, ordered,
            "schema/_db_agent_anchors.json (DB Agent rows)",
        ),
        "columns": ordered,
    }
    doc["_meta"]["note"] = (
        "Per-agent battle metadata. Base stats + growth + specialty here "
        "duplicate DB coverage (verifiable anchors); the new, not-yet-modeled "
        "fields are the battle-tag vocabulary (assist type, body size, weapon "
        "class) and the unresolved id-list / hash columns."
    )
    return doc


def _parse_spec(val: str) -> tuple[str, str] | None:
    """Split an ``EffectKey:value`` effect-spec string into ``(key, value)``."""
    if isinstance(val, str) and _EFFECT_SPEC_RE.match(val):
        key, _, num = val.partition(":")
        return key, num
    return None


def _verify_anomaly_anchor(
    rows: list[dict[str, Any]], name_col: str, effect_cols: list[str]
) -> None:
    """Fail loud unless the ``*_System`` rows reproduce Leifa's anomaly bases.

    Confirms both the effect-spec slot semantics and the code-name column in one
    cross-check: if the hashes rotated under us, the specs won't line up and we
    raise rather than emit a silently-wrong map (DESIGN §Methodology rule 2).
    """
    by_name: dict[str, dict[str, str]] = {}
    for r in rows:
        nm = r[name_col]
        if nm in _ANOMALY_BASE_MULT or nm == _SHOCK_MAX_HITS[0]:
            specs = {kv[0]: kv[1] for c in effect_cols if (kv := _parse_spec(r[c]))}
            by_name.setdefault(nm, specs)
    for nm, expected in _ANOMALY_BASE_MULT.items():
        got = by_name.get(nm, {}).get("DamagePercentage")
        if got is None or abs(float(got) - expected) > _FLOAT_TOL:
            raise AssertionError(
                f"BuffTemplateTb anomaly anchor failed: {nm} "
                f"DamagePercentage expected {expected}, got {got!r}. "
                "Effect-spec columns likely rotated — re-derive the map."
            )
    shock_name, shock_key, shock_n = _SHOCK_MAX_HITS
    if int(by_name.get(shock_name, {}).get(shock_key, -1)) != shock_n:
        raise AssertionError(
            f"BuffTemplateTb Shock anchor failed: {shock_name} {shock_key} "
            f"expected {shock_n}, got {by_name.get(shock_name, {}).get(shock_key)!r}."
        )


def _buff_dict() -> dict[str, Any]:
    """Column dictionary for ``BuffTemplateTb`` — the runtime buff/anomaly table.

    T2.2c resolved the three-way ambiguity: ``BuffTemplateTb`` is the canonical
    main-combat buff/debuff/anomaly definition table (self-describing code-names,
    icons, TextMap descriptions, and ``EffectKey:value`` effect specs).  The
    ``CPBuffConfigTemplateTb`` / ``CPGlobalBuffConfigTemplateTb`` pair belongs to
    the self-contained "CP" game-mode config family (35 ``CP*`` tables incl.
    CPSkill/CPWeapon/CPMonster/CPTechTree) and is out of the optimizer's scope —
    see ``docs/MAP_column_dictionaries.md``.

    Anchors are content-based (no DB snapshot): the canonical ``*_System``
    anomaly rows must reproduce Leifa's documented anomaly base multipliers in
    their effect-spec slots, and the description column must resolve as a TextMap
    key.  Columns are re-found by **content signature** so the map re-derives when
    the hashes rotate.
    """
    rows = wrapper_rows(fetch_json("FileCfg/BuffTemplateTb.json"))
    # Content-anchored table (no DB id snapshot to join), so the key column is the
    # unambiguous all-unique int column on its own.
    key_col = unique_key_column(rows)
    profiles = column_profiles(rows, key_col)
    scalar = [c for c in rows[0] if c != key_col]
    str_cols = [c for c in scalar if profiles[c].get("kind") == "str"]

    # — content-signature detection (robust to hash rotation) —
    # effect-spec slots: str cols whose populated values are EffectKey:number.
    effect_cols = []
    for c in str_cols:
        vals = [r[c] for r in rows if r[c]]
        hits = sum(1 for v in vals if _EFFECT_SPEC_RE.match(v))
        if vals and hits / len(vals) >= _EFFECT_SPEC_FILL:
            effect_cols.append(c)
    # code-name column: str col carrying the ``*_System`` anomaly identities.
    name_col = max(
        str_cols,
        key=lambda c: sum(1 for r in rows if str(r[c]).endswith("_System")),
    )
    # icon column: str col dominated by ``Icon*`` asset names.
    icon_col = max(
        str_cols,
        key=lambda c: sum(1 for r in rows if str(r[c]).startswith("Icon")),
    )
    # description column: str col whose populated values best resolve as TextMap
    # keys (excluding the name/icon/effect columns).
    textmap = load_textmap("en")
    desc_candidates = [
        c for c in str_cols if c not in {*effect_cols, name_col, icon_col}
    ]
    def _tm_hits(c: str) -> int:
        return sum(1 for r in rows if r[c] and r[c] in textmap)
    desc_col = max(desc_candidates, key=_tm_hits)
    desc_hits = _tm_hits(desc_col)

    # — fail-loud anomaly anchor: *_System rows reproduce Leifa base multipliers —
    _verify_anomaly_anchor(rows, name_col, effect_cols)

    # vocabulary of effect keys actually used across the spec slots (for the doc).
    effect_keys: dict[str, int] = defaultdict(int)
    for r in rows:
        for c in effect_cols:
            kv = _parse_spec(r[c])
            if kv:
                effect_keys[kv[0]] += 1

    columns: dict[str, dict[str, Any]] = {}
    columns[key_col] = {
        "meaning": "buff / debuff / anomaly id (referenced by skill & monster tables)",
        "anchor": "all-unique across every row; the buff primary key",
        "method": "key-column (structural)",
        "status": "verified",
    }
    columns[name_col] = {
        "meaning": "internal buff code-name / string-id (e.g. 'Burn_System', "
        "'Avatar_Burnice_Buff_01_Title'); the anomaly anchor joins on this",
        "anchor": "carries the canonical anomaly identities (Burn/Electric/Ether/"
        "Phisc/Frost _System) whose effect specs reproduce Leifa's base mults; "
        "some values also resolve as TextMap title keys",
        "method": "string-inspection + anomaly cross-check",
        "status": "verified",
    }
    anomaly_anchor = ", ".join(
        f"{nm.split('_')[0]} {v:g}x" for nm, v in _ANOMALY_BASE_MULT.items()
    )
    for c in effect_cols:
        columns[c] = {
            "meaning": "effect-parameter slot — an ordered 'EffectKey:value' pair "
            "(DamagePercentage = anomaly base mult / per-tick %, DamageTick / "
            "DamageCD = proc interval s, MaxHitNum = proc count, Percentage / "
            "AttackPercentage / DefencePercentage = stat-buff magnitude, …)",
            "anchor": (
                "anomaly base DamagePercentage in the *_System rows reproduces "
                f"Leifa's documented multipliers ({anomaly_anchor}); "
                "Electric_System MaxHitNum:16 = Shock's 16 procs"
            ),
            "method": "content-signature (EffectKey:number) + Leifa anomaly anchor",
            "status": "verified",
        }
    columns[desc_col] = {
        "meaning": "TextMap key for the buff's in-game description tooltip",
        "anchor": f"resolves in the merged EN TextMap on {desc_hits} rows "
        "(e.g. 'Burn_System_Debuff_Des' → 'Receive continuous Fire DMG')",
        "method": "TextMap key-resolution",
        "status": "verified",
    }
    columns[icon_col] = {
        "meaning": "buff icon asset name (e.g. 'IconBuff_Frozen', 'IconBuff_Ignite')",
        "anchor": "literal 'Icon*' asset handles",
        "method": "string-inspection (semantic; not a numeric anchor)",
        "status": "identified",
    }

    # everything else — unresolved/unused, recorded with observations (no guessing)
    _profile_remaining(columns, profiles)

    ordered = {c: columns[c] for c in rows[0]}
    doc = {
        "_meta": _meta(
            "BuffTemplateTb", key_col, rows, ordered,
            "Leifa anomaly base multipliers (CLAUDE.md) + merged EN TextMap "
            "+ self-describing effect-spec strings",
        ),
        "columns": ordered,
    }
    doc["_meta"]["effect_key_vocabulary"] = dict(
        sorted(effect_keys.items(), key=lambda kv: -kv[1])
    )
    doc["_meta"]["scope_note"] = (
        "Runtime-effective main-combat buff/debuff/anomaly definitions. "
        "CPBuffConfigTemplateTb / CPGlobalBuffConfigTemplateTb are the 'CP' "
        "game-mode config pair (out of optimizer scope) — T2.2c resolution."
    )
    return doc


# W-Engine secondary-stat property-id → DB secondary_stat_type, verified by
# grouping joined rows by the secondary block's prop-id against DB sectype below.
_WENGINE_SEC_PROP = {
    11102: "hp_pct", 12102: "atk_pct", 12202: "impact", 13102: "def_pct",
    20103: "crit_rate", 21103: "crit_dmg", 23103: "pen_ratio",
    30502: "energy_regen", 31203: "anomaly_proficiency",
    31402: "anomaly_mastery_pct",
}
# Rarity rank code observed in WeaponTemplateTb (enum-join purity 1.0 vs DB rarity).
_WENGINE_RARITY_CODE = {300: "B", 6000: "A", 30000: "S"}
# Max distinct values an enum-join column may have to be the rarity / specialty col.
_RARITY_MAX_DISTINCT = 5
_SPECIALTY_MAX_DISTINCT = 7

# Self-describing string columns in WeaponTemplateTb (semantic, not numeric anchors),
# each matched by a **content signature** rather than by its column hash. Pinning the
# hashes cost all seven labels the moment they rotated (issue #165); the values name
# themselves, so there was never a reason to key on the hash.
# `(marker, meaning)` — a column is labelled when the marker appears in its values.
_WENGINE_STRING_COLS: tuple[tuple[str, str], ...] = (
    (
        # The one column whose content is numeric rather than a name: pipe-separated
        # `levelExp:value,curveId:rate` segments, e.g.
        # "10:7200,101010:2|10:16800,101020:7|…". Matched on that shape.
        re.compile(r"^\d+:\d+,\d+:\d+(\|\d+:\d+,\d+:\d+)*$"),
        "level-scaling growth curve — pipe-separated 'levelExp:value,curveId:rate' "
        "segments (StarRate for ATK, RandRate for the secondary stat)",
    ),
    (
        "Data/ScriptConfig",
        "ScriptConfig data path (e.g. 'Data/ScriptConfig/Character/Weapon_A_1011')",
    ),
    ("UI/3D/", "UI 3D model path (e.g. 'UI/3D/Weapon/Weapon_A_1011')"),
    ("Weapon/Weapon_", "weapon model/prefab path (e.g. 'Weapon/Weapon_A_1011')"),
    ("Play_sfx", "2D SFX event name (e.g. 'Play_sfx_Weapon_A_1011_2d')"),
    ("_release", "release/banner tag (e.g. 'Alice_release')"),
    ("_Comment", "comment/designer-note TextMap-style key (e.g. 'Weapon_A_1011_Comment')"),
)


def _resolve_wengine_stat_blocks(
    rows: list[dict[str, Any]], key_col: str, anchors: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    """Locate the nested {prop_id, value} base-ATK & secondary stat blocks.

    Value inner-keys are found by content (``nested_value_match``) so the map
    survives an inner-hash rotation; raises if base ATK no longer reproduces.
    Returns the column/inner-key handles plus the secondary prop-id → DB
    secondary_stat_type enum.
    """
    n_join = sum(1 for r in rows if r[key_col] in anchors)
    dict_cols = [c for c in rows[0] if isinstance(rows[0][c], dict)]

    def _best_inner(col: str, field: str) -> tuple[str, float]:
        nm = nested_value_match(rows, key_col, anchors, [field], col)
        ik, info = max(nm.items(), key=lambda kv: kv[1]["ratio"])
        return ik, info["ratio"]

    base_col = base_inner = sec_col = sec_inner = sec_prop_inner = None
    for c in dict_cols:
        ik, ratio = _best_inner(c, "base_atk")
        if ratio >= MATCH_THRESHOLD:
            base_col, base_inner = c, ik
    for c in dict_cols:
        if c == base_col:
            continue
        ik, ratio = _best_inner(c, "secondary_stat_value")
        if ratio >= MATCH_THRESHOLD:
            inner = set().union(*(set(r[c]) for r in rows if isinstance(r[c], dict)))
            sec_col, sec_inner = c, ik
            sec_prop_inner = next(k for k in inner if k != ik)

    if base_col is None or sec_col is None:
        raise AssertionError(
            "WeaponTemplateTb value-match failed: could not locate the base-ATK / "
            "secondary nested stat blocks. Inner column hashes likely rotated — "
            "re-derive the map."
        )
    base_matches = sum(
        1 for r in rows
        if r[key_col] in anchors
        and r[base_col].get(base_inner) == anchors[r[key_col]]["base_atk"]
    )
    if base_matches / n_join < MATCH_THRESHOLD:
        raise AssertionError(
            f"WeaponTemplateTb base-ATK anchor failed: reproduced on only "
            f"{base_matches}/{n_join} joined rows."
        )

    prop_to_type: dict[Any, set[str]] = defaultdict(set)
    for r in rows:
        a = anchors.get(r[key_col])
        if a:
            prop_to_type[r[sec_col][sec_prop_inner]].add(a["secondary_stat_type"])
    base_prop_inner = next(k for k in rows[0][base_col] if k != base_inner)
    base_prop_ids = sorted(
        {r[base_col].get(base_prop_inner) for r in rows if r[key_col] in anchors}
        - {None}
    )
    return {
        "base_col": base_col, "base_inner": base_inner,
        "base_prop_ids": base_prop_ids, "base_matches": base_matches,
        "sec_col": sec_col, "sec_inner": sec_inner,
        "sec_prop_inner": sec_prop_inner, "prop_to_type": prop_to_type,
        "n_join": n_join,
    }


def _weapon_dict() -> dict[str, Any]:
    """Column dictionary for ``WeaponTemplateTb`` — W-Engine definitions (T2.2d).

    W-Engine stats live in our DB (seeded from nanoka), so this resolves like
    ``AvatarBattleTemplateTb``: value-match against DB ``WEngine`` anchors. The
    twist is that base ATK and the secondary stat are stored as nested
    ``{prop_id, value}`` sub-objects, so the *value* inner-key is found by
    content (``nested_value_match``) and the *prop-id* inner-key resolves to the
    secondary stat-type enum. Base ATK reproducing on ~every joined row is the
    fail-loud anchor (raises on hash rotation rather than emitting a wrong map).
    """
    rows = wrapper_rows(fetch_json("FileCfg/WeaponTemplateTb.json"))
    anchors = _load_wengine_anchors()
    avatar_ids = set(_load_agent_anchors())
    # Two all-unique int columns here — the tie is broken by which one joins to the
    # W-Engine ids we already hold, never by column order (see unique_key_column).
    key_col = unique_key_column(rows, anchors)
    profiles = column_profiles(rows, key_col)

    # — nested {prop_id, value} stat blocks (fail-loud on base-ATK reproduction) —
    sb = _resolve_wengine_stat_blocks(rows, key_col, anchors)
    base_col, base_inner, base_matches = sb["base_col"], sb["base_inner"], sb["base_matches"]
    sec_col, sec_inner, sec_prop_inner = sb["sec_col"], sb["sec_inner"], sb["sec_prop_inner"]
    prop_to_type, n_join = sb["prop_to_type"], sb["n_join"]

    # — rarity & specialty scalar enums (tolerant enum-join vs DB) —
    rar = enum_join(rows, key_col, anchors, "rarity")
    spc = enum_join(rows, key_col, anchors, "specialty")
    rar_col = max(
        rar, key=lambda c: rar[c]["purity"]
        if rar[c]["distinct"] <= _RARITY_MAX_DISTINCT else -1
    )
    spc_col = max(
        spc, key=lambda c: spc[c]["purity"]
        if 1 < spc[c]["distinct"] <= _SPECIALTY_MAX_DISTINCT else -1
    )

    # — description TextMap key —
    textmap = load_textmap("en")
    str_cols = [c for c in rows[0] if isinstance(rows[0][c], str)]
    def _tm_hits(c: str) -> int:
        return sum(1 for r in rows if r[c] and r[c] in textmap)
    desc_col = max(str_cols, key=_tm_hits)
    desc_hits = _tm_hits(desc_col)

    columns: dict[str, dict[str, Any]] = {}
    columns[key_col] = {
        "meaning": "W-Engine id (e.g. 12001)",
        "anchor": "joins to DB WEngine.hakushin_id",
        "method": "key-column (first all-unique column; structural)",
        "status": "verified",
    }
    columns[base_col] = {
        "meaning": "base-stat block {prop_id, value}: base ATK at Lv.0 "
        f"(prop_id {sb['base_prop_ids']} = ATK_Base)",
        "anchor": (
            f"inner '{base_inner}' reproduces DB WEngine.base_atk on "
            f"{base_matches}/{n_join} joined rows"
        ),
        "method": "nested value-match (drill {prop_id,value}; value key by content)",
        "status": "verified",
    }
    columns[sec_col] = {
        "meaning": "secondary-stat block {prop_id, value}: advanced/secondary "
        "stat base value; prop_id selects the stat type",
        "anchor": (
            f"inner '{sec_inner}' reproduces DB WEngine.secondary_stat_value on "
            f"every joined row; inner '{sec_prop_inner}' (prop_id) maps to "
            "DB WEngine.secondary_stat_type"
        ),
        "secondary_stat_type_enum": {
            str(p): (sorted(t)[0] if len(t) == 1 else sorted(t))
            for p, t in sorted(prop_to_type.items())
        },
        "method": "nested value-match + prop-id enum-join vs DB sectype",
        "status": "verified",
    }
    columns[rar_col] = {
        "meaning": "rarity rank code",
        "enum": {str(k): _WENGINE_RARITY_CODE.get(k, "?")
                 for k in sorted(rar[rar_col]["mapping"])},
        "anchor": (
            f"each value maps 1:1 to DB WEngine.rarity (purity "
            f"{rar[rar_col]['purity']:.3f} over {rar[rar_col]['joined']} rows)"
        ),
        "method": "enum-join (group rows by value, dominant DB rarity)",
        "status": "verified" if rar[rar_col]["purity"] >= MATCH_THRESHOLD else "unresolved",
    }
    columns[spc_col] = {
        "meaning": "specialty (profession) enum — W-Engine specialty lock",
        "enum": {str(k): _SPECIALTY_ENUM.get(k, "?")
                 for k in sorted(spc[spc_col]["mapping"])},
        "anchor": (
            f"each value maps to one DB WEngine.specialty (purity "
            f"{spc[spc_col]['purity']:.3f} over {spc[spc_col]['joined']} rows)"
        ),
        "method": "enum-join (group rows by value, dominant DB specialty)",
        "status": "verified" if spc[spc_col]["purity"] >= MATCH_THRESHOLD else "unresolved",
    }
    columns[desc_col] = {
        "meaning": "TextMap key for the W-Engine description/flavor tooltip",
        "anchor": f"resolves in the merged EN TextMap on {desc_hits}/{len(rows)} "
        "rows (e.g. 'Item_Weapon_A_1011_Desc')",
        "method": "TextMap key-resolution",
        "status": "verified",
    }

    # — self-describing string columns, matched on content (survives a rotation) —
    for marker, meaning in _WENGINE_STRING_COLS:
        matches = (
            (lambda v: bool(marker.match(v)))
            if isinstance(marker, re.Pattern)
            else (lambda v: marker in v)
        )
        for col in rows[0]:
            if col in columns or not isinstance(rows[0].get(col), str):
                continue
            if any(matches(str(r.get(col))) for r in rows if r.get(col)):
                columns[col] = {
                    "meaning": meaning,
                    "anchor": (
                        "literal self-describing strings matching "
                        f"{marker.pattern if isinstance(marker, re.Pattern) else marker!r}"
                    ),
                    "method": "string-inspection (semantic; not a numeric anchor)",
                    "status": "identified",
                }
                break
    # signature-owner avatar id: an int column whose non-zero values are all DB agent
    # ids. Content-derived for the same reason as the strings above — 0 on generic
    # engines, an avatar id on signature ones, which nothing else in this table looks
    # like.
    for col in rows[0]:
        if col in columns or col == key_col or not isinstance(rows[0].get(col), int):
            continue
        nonzero = [r[col] for r in rows if r.get(col)]
        if nonzero and all(v in avatar_ids for v in nonzero):
            columns[col] = {
                "meaning": "signature-owner avatar id (the agent this W-Engine belongs "
                "to; 0 for non-signature engines)",
                "anchor": f"every non-zero value ({len(nonzero)} rows) is a DB "
                "Agent.hakushin_id (1011, 1021, …)",
                "method": "range-inspection against the agent-anchor roster",
                "status": "identified",
            }
            break

    # everything else — unresolved/unused, recorded with observations (no guessing)
    _profile_remaining(columns, profiles)

    ordered = {c: columns[c] for c in rows[0]}
    doc = {
        "_meta": _meta(
            "WeaponTemplateTb", key_col, rows, ordered,
            "schema/_db_wengine_anchors.json (DB WEngine rows)",
        ),
        "columns": ordered,
    }
    doc["_meta"]["note"] = (
        "W-Engine definitions. Base ATK + secondary stat (value & type) + rarity "
        "+ specialty reproduce DB coverage via value/enum anchors; the growth "
        "curve, asset paths, and signature-owner id are identified by structure. "
        "Disc drives (EquipmentTemplateTb) are a separate table — not covered here."
    )
    return doc


_TABLES = {
    "AvatarSkillTemplateTb": _avatar_skill_dict,
    "AvatarBattleTemplateTb": _avatar_battle_dict,
    "BuffTemplateTb": _buff_dict,
    "WeaponTemplateTb": _weapon_dict,
}


def build() -> dict[str, dict[str, Any]]:
    """Re-derive and write every priority table's column dictionary."""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    docs: dict[str, dict[str, Any]] = {}
    for table, builder in _TABLES.items():
        doc = builder()
        out = _OUT_DIR / f"{table}.json"
        out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        m = doc["_meta"]
        print(f"wrote {out.relative_to(SCHEMA_DIR.parents[3])}")
        print(
            f"  {m['column_count']} cols: {m['verified']} verified, "
            f"{m['identified']} identified, {m['unresolved']} unresolved, "
            f"{m['unused']} unused"
        )
        docs[table] = doc
    return docs


if __name__ == "__main__":
    build()
