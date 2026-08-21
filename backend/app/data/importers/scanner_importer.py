"""ZOD-format disc scanner importer.

ZOD (ZenlessOptimizerData) is the JSON format produced by AdeptiScanner
and other community scanners — disc-only inventory. Each disc has a set
key (PascalCase set name), slot 1-6, level, rarity (S/A/B), main stat
key, and a list of substats with ``upgrades`` counts.

This importer:

1. Resolves the ZOD ``setKey`` to an internal :class:`DiscSet` by
   normalizing both sides (strip non-alphabetic, lowercase).
2. Maps ZOD stat keys to :class:`StatType`. ZOD uses different keys
   for main stat vs. substat (``pen_`` is PEN Ratio % main; ``pen``
   is flat PEN substat).
3. Computes ``main_stat_value`` from a hardcoded max-value table per
   (rarity, slot, stat_key), scaled linearly by current level. The
   scale is approximate — exact main-stat curves live in Dimbreath's
   EquipmentLevelTemplateTb data (not yet loaded). Most scanner
   exports are at max level so this is rarely a meaningful gap.
4. Computes substat values as ``base_value × upgrades``; substats
   don't scale with disc level, only with roll count.
5. Skips duplicates by content hash (no DB-level constraint — two
   scanner imports of the same file won't double the inventory).

Outputs unequipped Disc rows (``build_id`` / ``build_slot`` left null).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Rarity, StatType
from app.repositories.disc import DiscRepository
from app.services.disc_constants import SUBSTAT_BASE_PER_ROLL_BY_RARITY

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Hardening limits
MAX_DISC_COUNT = 5_000  # generous ceiling; real ZZZ inventories top out ~1600
_MAX_STRING_LEN = 100  # setKey, stat key fields
_MAX_SUBSTATS = 4  # ZZZ disc mechanic hard cap
_MAX_UPGRADES = 9  # S-rank substat roll ceiling


# ---- ZOD vocabulary mapping -----------------------------------------------

# Main-stat keys can include flat or percent variants — ZOD uses the
# trailing underscore for percent fields. Element DMG bonuses use
# ``{element}_dmg_``.
_MAIN_STAT_MAP: dict[str, StatType] = {
    "hp": StatType.HP,
    "hp_": StatType.HP_PCT,
    "atk": StatType.ATK,
    "atk_": StatType.ATK_PCT,
    "def": StatType.DEF,
    "def_": StatType.DEF_PCT,
    "crit_": StatType.CRIT_RATE,
    "crit_dmg_": StatType.CRIT_DMG,
    "pen_": StatType.PEN_RATIO,
    "anomMas_": StatType.ANOMALY_MASTERY,
    "anomProf": StatType.ANOMALY_PROFICIENCY,
    "impact_": StatType.IMPACT_PCT,
    "enerRegen_": StatType.ENERGY_REGEN,
    "physical_dmg_": StatType.PHYSICAL_DMG,
    "fire_dmg_": StatType.FIRE_DMG,
    "ice_dmg_": StatType.ICE_DMG,
    "electric_dmg_": StatType.ELECTRIC_DMG,
    "ether_dmg_": StatType.ETHER_DMG,
    "wind_dmg_": StatType.WIND_DMG,
}

# Substats use the same vocabulary but with one quirk: ``pen`` (no
# trailing underscore) is flat PEN, distinct from the ``pen_`` PEN
# Ratio % main stat.
_SUBSTAT_MAP: dict[str, StatType] = {
    "hp": StatType.HP,
    "hp_": StatType.HP_PCT,
    "atk": StatType.ATK,
    "atk_": StatType.ATK_PCT,
    "def": StatType.DEF,
    "def_": StatType.DEF_PCT,
    "crit_": StatType.CRIT_RATE,
    "crit_dmg_": StatType.CRIT_DMG,
    "pen": StatType.PEN_FLAT,
    "anomProf": StatType.ANOMALY_PROFICIENCY,
}

# eZOD rarity integers → Rarity enum (ZOD uses "S"/"A"/"B" strings).
_RARITY_INT_MAP: dict[int, Rarity] = {4: Rarity.S, 3: Rarity.A, 2: Rarity.B}

# Substats whose eZOD ``value`` is expressed as a percent float (e.g.
# 9.0 = 9%).  Convert to basis points by multiplying by 100.  Flat
# substats arrive as the raw integer and are stored as-is.
_PERCENT_SUBSTATS: frozenset[StatType] = frozenset({
    StatType.HP_PCT,
    StatType.ATK_PCT,
    StatType.DEF_PCT,
    StatType.CRIT_RATE,
    StatType.CRIT_DMG,
})


def _substat_value_from_exact(stat: StatType, value: float) -> int:
    """Convert an eZOD exact substat value to the stored integer.

    Percent substats arrive as floats (e.g. 9.0 = 9%) and are stored as
    basis points (900).  Flat substats are stored as plain ints.
    """
    if stat in _PERCENT_SUBSTATS:
        return round(value * 100)
    return int(value)


# Max level by rarity (B-rank caps at level 9 = 3 rolls; A=12=5; S=15=9).
_MAX_LEVEL: dict[Rarity, int] = {Rarity.S: 15, Rarity.A: 12, Rarity.B: 9}

# Max-level main-stat values per (rarity, slot, stat). Numbers from the
# ZZZ-Plugin reference and community calc sheets. A-rank ≈ 0.8 × S,
# B-rank ≈ 0.5 × S — close enough for buildplanning UI (exact tables
# require Dimbreath EquipmentLevelTemplateTb data).
_MAIN_STAT_MAX_S: dict[tuple[int, StatType], int] = {
    # Slot 1 — flat HP only
    (1, StatType.HP): 2200,
    # Slot 2 — flat ATK only
    (2, StatType.ATK): 316,
    # Slot 3 — flat DEF only
    (3, StatType.DEF): 184,
    # Slots 4-6: HP%, ATK%, DEF% common
    (4, StatType.HP_PCT): 3000,
    (4, StatType.ATK_PCT): 3000,
    (4, StatType.DEF_PCT): 4800,
    (4, StatType.CRIT_RATE): 2400,
    (4, StatType.CRIT_DMG): 4800,
    (4, StatType.ANOMALY_PROFICIENCY): 92,
    (5, StatType.HP_PCT): 3000,
    (5, StatType.ATK_PCT): 3000,
    (5, StatType.DEF_PCT): 4800,
    (5, StatType.PEN_RATIO): 2400,
    (5, StatType.PHYSICAL_DMG): 3000,
    (5, StatType.FIRE_DMG): 3000,
    (5, StatType.ICE_DMG): 3000,
    (5, StatType.ELECTRIC_DMG): 3000,
    (5, StatType.ETHER_DMG): 3000,
    (5, StatType.WIND_DMG): 3000,
    (6, StatType.HP_PCT): 3000,
    (6, StatType.ATK_PCT): 3000,
    (6, StatType.DEF_PCT): 4800,
    (6, StatType.ANOMALY_MASTERY): 92,
    (6, StatType.IMPACT_PCT): 1800,
    (6, StatType.ENERGY_REGEN): 6000,
}


def _main_stat_max(rarity: Rarity, slot: int, stat: StatType) -> int | None:
    """Max-level main value lookup. Approximate for non-S rarities."""
    base = _MAIN_STAT_MAX_S.get((slot, stat))
    if base is None:
        return None
    if rarity == Rarity.S:
        return base
    if rarity == Rarity.A:
        return int(base * 0.80)
    return int(base * 0.50)  # B-rank


def _normalize_set_key(name: str) -> str:
    """Strip non-alphabetic, lowercase. ``Phaethon's Melody`` ↔ ``PhaethonsMelody``."""
    return re.sub(r"[^a-zA-Z]", "", name).lower()


# ---- Public API ----------------------------------------------------------


@dataclass
class ImportResult:
    """Outcome counts for a single ZOD scanner import run."""

    imported: int
    skipped_duplicate: int
    skipped_unknown_set: int
    skipped_invalid: int
    errors: list[str]
    discs_deleted: int = 0


@dataclass
class _DiscDraft:
    """Resolved disc fields ready for SQLAlchemy insert."""

    disc_set_id: str
    slot: DiscSlot
    rarity: Rarity
    level: int
    main_stat_type: StatType
    main_stat_value: int
    substats: list[dict]


def parse_zod_payload(raw: str | bytes | dict) -> dict:
    """Validate the top-level ZOD shape, return the parsed dict."""
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e
    else:
        data = raw
    if not isinstance(data, dict):
        msg = "ZOD payload must be a JSON object"
        raise TypeError(msg)
    if data.get("format") != "ZOD":
        msg = f"Expected format=ZOD, got {data.get('format')!r}"
        raise ValueError(msg)
    discs = data.get("discs")
    if not isinstance(discs, list):
        msg = "ZOD payload missing 'discs' array"
        raise ValueError(msg)  # noqa: TRY004
    if len(discs) > MAX_DISC_COUNT:
        msg = f"ZOD payload exceeds maximum of {MAX_DISC_COUNT} discs (got {len(discs)})"
        raise ValueError(msg)
    return data


def _zod_disc_to_draft(  # noqa: PLR0911, PLR0912
    raw: dict,
    *,
    set_lookup: dict[str, DiscSet],
) -> _DiscDraft | tuple[None, str]:
    """Convert one ZOD disc dict to a :class:`_DiscDraft`.

    Returns the draft on success, or ``(None, reason)`` for skips.
    Reasons distinguish unknown sets from malformed entries.
    """
    if not isinstance(raw, dict):
        return None, f"disc entry is not an object (got {type(raw).__name__})"

    set_key = raw.get("setKey", "")
    if not isinstance(set_key, str) or len(set_key) > _MAX_STRING_LEN:
        return None, f"setKey too long or wrong type: {set_key!r:.50}"
    norm = _normalize_set_key(set_key)
    disc_set = set_lookup.get(norm)
    if disc_set is None:
        return None, f"unknown set: {set_key}"

    try:
        slot_int = int(raw["slotKey"])
        slot = DiscSlot(slot_int)
    except (KeyError, ValueError, TypeError) as e:
        return None, f"invalid slot: {e}"

    rarity_str = raw.get("rarity", "")
    if rarity_str not in {"S", "A", "B"}:
        return None, f"invalid rarity: {rarity_str!r}"
    rarity = Rarity(rarity_str)

    try:
        level = int(raw.get("level", 0))
    except (ValueError, TypeError) as e:
        return None, f"invalid level: {e}"
    max_level = _MAX_LEVEL[rarity]
    if not 0 <= level <= max_level:
        return None, f"level {level} outside [0, {max_level}] for {rarity_str}"

    main_key = raw.get("mainStatKey", "")
    if not isinstance(main_key, str) or len(main_key) > _MAX_STRING_LEN:
        return None, f"mainStatKey too long or wrong type: {main_key!r:.50}"
    main_stat = _MAIN_STAT_MAP.get(main_key)
    if main_stat is None:
        return None, f"unknown main stat key: {main_key!r}"

    max_main = _main_stat_max(rarity, slot.value, main_stat)
    if max_main is None:
        return None, f"no main-stat table for slot {slot.value} stat {main_stat.value}"
    # +0 disc starts at 25% of max; each level adds an equal share of the
    # remaining 75% (e.g. S-rank 15 levels -> +5% of max per level).
    main_value = int(max_main * (0.25 + 0.75 * level / max_level))

    raw_substats = raw.get("substats", []) or []
    if not isinstance(raw_substats, list):
        return None, "substats must be an array"
    if len(raw_substats) > _MAX_SUBSTATS:
        return None, f"too many substats: {len(raw_substats)} > {_MAX_SUBSTATS}"

    substats: list[dict] = []
    for sub in raw_substats:
        if not isinstance(sub, dict):
            return None, f"substat entry is not an object (got {type(sub).__name__})"
        sub_key = sub.get("key", "")
        if not isinstance(sub_key, str) or len(sub_key) > _MAX_STRING_LEN:
            return None, f"substat key too long or wrong type: {sub_key!r:.50}"
        sub_stat = _SUBSTAT_MAP.get(sub_key)
        if sub_stat is None:
            return None, f"unknown substat key: {sub_key!r}"
        try:
            rolls = int(sub.get("upgrades", 0))
        except (ValueError, TypeError) as e:
            return None, f"substat {sub_key} invalid upgrades: {e}"
        if rolls < 1:
            return None, f"substat {sub_key} has rolls={rolls}"
        if rolls > _MAX_UPGRADES:
            return None, f"substat {sub_key} has rolls={rolls} > max {_MAX_UPGRADES}"
        # Per-roll base scales with rarity, so an A/B disc's substat value is
        # NOT the S-rank base × rolls. Getting this wrong doesn't just store a
        # bad value — `disc_scorer._count_rolls` re-derives the roll count from
        # the value against the rarity-aware table, so an S-scaled value on an
        # A/B disc reads back as ~1.5–3× the real roll count and zeroes out the
        # disc's remaining upgrade budget (issue #65).
        base = SUBSTAT_BASE_PER_ROLL_BY_RARITY[rarity.value].get(sub_stat)
        if base is None:
            return None, f"no base value for substat {sub_stat.value}"
        substats.append(
            {
                "stat": sub_stat.value,
                "value": base * rolls,
                "rolls": rolls,
            }
        )

    return _DiscDraft(
        disc_set_id=disc_set.id,
        slot=slot,
        rarity=rarity,
        level=level,
        main_stat_type=main_stat,
        main_stat_value=main_value,
        substats=substats,
    )


def _content_hash(d: _DiscDraft) -> str:
    """Stable hash for dedup. Sorts substats so order doesn't matter."""
    payload = {
        "set": d.disc_set_id,
        "slot": d.slot.value,
        "rarity": d.rarity.value,
        "level": d.level,
        "main": (d.main_stat_type.value, d.main_stat_value),
        "subs": sorted((s["stat"], s["value"]) for s in d.substats),
    }
    blob = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha1(blob, usedforsecurity=False).hexdigest()


async def import_zod_payload(
    data: dict,
    session: AsyncSession,
    owner_id: str | None = None,
    disc_mode: str = "merge",
) -> ImportResult:
    """Insert ZOD discs as unequipped :class:`Disc` rows.

    Builds a :class:`DiscSet` lookup once, dedups against existing
    unequipped discs by content hash, and bulk-flushes new rows.

    When ``disc_mode`` is ``"clean"``, the owner's entire disc inventory —
    equipped discs included — is deleted before the import, so the payload
    dedups against an intentionally emptied baseline.  The wipe runs inside
    the caller's transaction: a later failure rolls it back.  Builds survive
    the wipe with empty disc slots (``Disc.build_id`` is the only link).
    """
    payload = parse_zod_payload(data)

    if disc_mode == "clean" and owner_id is None:
        raise ValueError("clean import modes require an owner_id")

    result = ImportResult(
        imported=0,
        skipped_duplicate=0,
        skipped_unknown_set=0,
        skipped_invalid=0,
        errors=[],
    )

    if disc_mode == "clean":
        result.discs_deleted = await DiscRepository(
            session, owner_id=owner_id
        ).delete_all_for_owner()

    # Build set lookup keyed on normalized name.
    sets_result = await session.execute(select(DiscSet))
    set_lookup = {_normalize_set_key(s.name): s for s in sets_result.scalars().all()}

    # Build hash lookup of the owner's existing discs to avoid duplicates.
    # Scope to the importing owner so legacy / other-user rows don't
    # cause every disc to be reported as skipped_duplicate.
    #
    # *Every* owned disc counts, equipped or not. A ZOD file is a scan of the whole
    # in-game inventory — equipping a disc in fairy does not stop the scanner from
    # listing it — so a denominator of unequipped rows alone under-counts what the
    # player owns and the payload's copies get imported a second time. Under the
    # counting rule below that inflates the inventory by one row per equipped disc
    # that also has an identical unequipped twin; under the old presence rule it
    # doubled a fully-equipped inventory outright. Equipped rows are only counted,
    # never touched: ZOD carries no builds, so this importer never re-attaches.
    existing_stmt = select(Disc)
    if owner_id is not None:
        existing_stmt = existing_stmt.where(Disc.owner_id == owner_id)
    existing_result = await session.execute(existing_stmt)
    # Counted, not merely present (issue #139). Two discs of the same set, slot,
    # level, rarity, main stat and substat spread hash identically because there is
    # nothing to distinguish them — a player at endgame genuinely owns several. A
    # presence-only set imported the first and reported the rest `skipped_duplicate`,
    # so the inventory came up short while the counts reconciled. The rule is: the Nth
    # identical disc in the payload is a duplicate exactly when we already hold N of
    # them, which still makes a straight re-import a no-op.
    existing_counts: Counter[str] = Counter()
    for row in existing_result.scalars().all():
        # Reconstruct a minimal draft from the row to compute the hash.
        try:
            draft = _DiscDraft(
                disc_set_id=row.disc_set_id,
                slot=DiscSlot(row.slot.value if hasattr(row.slot, "value") else row.slot),
                rarity=Rarity(row.rarity.value if hasattr(row.rarity, "value") else row.rarity),
                level=row.level,
                main_stat_type=StatType(
                    row.main_stat_type.value
                    if hasattr(row.main_stat_type, "value")
                    else row.main_stat_type,
                ),
                main_stat_value=row.main_stat_value,
                substats=row.substats or [],
            )
            existing_counts[_content_hash(draft)] += 1
        except (ValueError, TypeError):
            continue

    new_rows: list[Disc] = []
    seen_in_payload: Counter[str] = Counter()
    for idx, raw_disc in enumerate(payload["discs"]):
        outcome = _zod_disc_to_draft(raw_disc, set_lookup=set_lookup)
        if isinstance(outcome, tuple):
            _, reason = outcome
            if reason.startswith("unknown set"):
                result.skipped_unknown_set += 1
            else:
                result.skipped_invalid += 1
            result.errors.append(f"disc[{idx}]: {reason}")
            continue
        draft = outcome

        h = _content_hash(draft)
        seen_in_payload[h] += 1
        if seen_in_payload[h] <= existing_counts[h]:
            result.skipped_duplicate += 1
            continue

        row_kwargs: dict = {
            "disc_set_id": draft.disc_set_id,
            "slot": draft.slot,
            "rarity": draft.rarity,
            "level": draft.level,
            "main_stat_type": draft.main_stat_type,
            "main_stat_value": draft.main_stat_value,
            "substats": draft.substats,
        }
        if owner_id is not None:
            row_kwargs["owner_id"] = owner_id
        new_rows.append(Disc(**row_kwargs))

    if new_rows:
        session.add_all(new_rows)
        await session.flush()

    result.imported = len(new_rows)
    return result
