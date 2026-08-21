"""eZOD (Expanded ZOD) import — characters, w-engines, and discs from Youkai.

eZOD extends ZOD with character metadata (level, constellation, talents)
and equipped-disc linkage. The top-level ``format`` field is ``"eZOD"``.

Key resolution:
- Agent and WEngine keys are PascalCase names (same convention as ZO).
- Normalize by stripping non-alphabetic characters and lowercasing.
- A small static alias table handles the two known non-normalizable keys:
  ``Astra`` → ``Astra Yao`` and ``Peacekeeper`` → ``Peacekeeper - Specialized``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.data.importers.scanner_importer import (
    _MAIN_STAT_MAP,
    _MAX_LEVEL,
    _MAX_STRING_LEN,
    _MAX_SUBSTATS,
    _RARITY_INT_MAP,
    _SUBSTAT_MAP,
    _content_hash,
    _DiscDraft,
    _main_stat_max,
    _normalize_set_key,
    _substat_value_from_exact,
)
from app.models.agent import Agent
from app.models.build import Build
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Rarity, StatType
from app.models.w_engine import WEngine
from app.repositories.build import BuildRepository
from app.repositories.disc import DiscRepository
from app.repositories.team import TeamRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Generous ceilings; guard against pathological payloads.
MAX_CHAR_COUNT = 200
_MAX_DISC_SLOT_NUM = 6  # ZZZ hard cap: disc slots 1–6
MAX_WEAPON_COUNT = 2_000
MAX_DISC_COUNT = 5_000  # mirrors scanner_importer.MAX_DISC_COUNT

# Static alias table for eZOD keys that don't normalize to their DB name.
# Key: normalized eZOD key  →  value: normalized DB name.
_AGENT_ALIASES: dict[str, str] = {
    "astra": "astrayao",
}
_WENGINE_ALIASES: dict[str, str] = {
    "peacekeeper": "peacekeeperspecialized",
}


def _normalize_key(name: str) -> str:
    """Strip non-alphabetic characters and lowercase. Same rule as _normalize_set_key."""
    return re.sub(r"[^a-zA-Z]", "", name).lower()


def parse_ezod_payload(raw: str | bytes | dict) -> dict:
    """Validate the top-level eZOD shape and return the parsed dict.

    Raises ValueError for format/structural/count errors, TypeError if the
    top-level value is not a JSON object.
    """
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e
    else:
        data = raw

    if not isinstance(data, dict):
        msg = "eZOD payload must be a JSON object"
        raise TypeError(msg)

    if data.get("format") != "eZOD":
        msg = f"Expected format=eZOD, got {data.get('format')!r}"
        raise ValueError(msg)

    for section in ("characters", "weapons", "discs"):
        if not isinstance(data.get(section), list):
            msg = f"eZOD payload missing '{section}' array"
            raise ValueError(msg)  # noqa: TRY004

    if len(data["characters"]) > MAX_CHAR_COUNT:
        raise ValueError(
            f"eZOD payload exceeds maximum of {MAX_CHAR_COUNT} characters"
            f" (got {len(data['characters'])})"
        )
    if len(data["weapons"]) > MAX_WEAPON_COUNT:
        raise ValueError(
            f"eZOD payload exceeds maximum of {MAX_WEAPON_COUNT} weapons"
            f" (got {len(data['weapons'])})"
        )
    if len(data["discs"]) > MAX_DISC_COUNT:
        raise ValueError(
            f"eZOD payload exceeds maximum of {MAX_DISC_COUNT} discs"
            f" (got {len(data['discs'])})"
        )

    return data


async def build_agent_lookup(session: AsyncSession) -> dict[str, Agent]:
    """Return a dict mapping normalized agent key → Agent row.

    Applies _AGENT_ALIASES so eZOD keys like ``Astra`` resolve to the
    ``Astra Yao`` DB row.
    """
    result = await session.execute(select(Agent))
    lookup: dict[str, Agent] = {}
    for agent in result.scalars().all():
        lookup[_normalize_key(agent.name)] = agent
    for alias_norm, target_norm in _AGENT_ALIASES.items():
        if target_norm in lookup:
            lookup[alias_norm] = lookup[target_norm]
    return lookup


async def build_wengine_lookup(session: AsyncSession) -> dict[str, WEngine]:
    """Return a dict mapping normalized w-engine key → WEngine row.

    Applies _WENGINE_ALIASES so eZOD keys like ``Peacekeeper`` resolve to
    the ``Peacekeeper - Specialized`` DB row.
    """
    result = await session.execute(select(WEngine))
    lookup: dict[str, WEngine] = {}
    for engine in result.scalars().all():
        lookup[_normalize_key(engine.name)] = engine
    for alias_norm, target_norm in _WENGINE_ALIASES.items():
        if target_norm in lookup:
            lookup[alias_norm] = lookup[target_norm]
    return lookup


def resolve_agent_key(key: str, lookup: dict[str, Agent]) -> Agent | tuple[None, str]:
    """Resolve an eZOD character key to an Agent row.

    Returns the Agent on success, or ``(None, reason)`` for unknown keys.
    """
    norm = _normalize_key(key)
    agent = lookup.get(norm)
    if agent is None:
        return None, f"unknown agent key: {key!r}"
    return agent


def resolve_wengine_key(key: str, lookup: dict[str, WEngine]) -> WEngine | tuple[None, str]:
    """Resolve an eZOD weapon key to a WEngine row.

    Returns the WEngine on success, or ``(None, reason)`` for unknown keys.
    """
    norm = _normalize_key(key)
    engine = lookup.get(norm)
    if engine is None:
        return None, f"unknown w-engine key: {key!r}"
    return engine


# ---- Character → Build draft -------------------------------------------------


def claim_ids_for_skipped_build(disc_rows: list, claimed_rows: set[int]) -> None:
    """Reserve a skipped build's disc rows so no later character can take them (#144).

    `claimed_rows` tracked only rows claimed *during* a run. A disc already attached
    to a skipped build was therefore unclaimed and free to steal: a later character
    equipping a content-identical disc took the row, dropping the skipped build from
    6 discs to 5, silently.

    Decision recorded (the issue asks for one, not a patch). `skip` reads as "leave
    this build exactly as it is", so it protects equipment as well as fields. The
    alternative reading — the payload is authoritative about current equipment — is
    defensible, but under it the option's name misleads AND the move goes unreported,
    which fails the acceptance criterion regardless. Under this reading the later
    character simply finds no free row, and that shortfall is reported.
    """
    for row in disc_rows:
        claimed_rows.add(id(row))


def mindscape_drift_problem(char: dict, stored_mindscape: int) -> str | None:
    """Return a description if a skipped build's mindscape is behind the scan (#156).

    `build_conflict="skip"` leaves a build alone — correctly, the caller asked for it —
    but it does so silently, and that silence is how 16 of 39 live builds ended up
    below the scanner's mindscape. Every mismatch was an understatement, each quietly
    dropping the kit rows gated on `min_mindscape`; Anby sat at M0 against a real M6,
    missing all six.

    Only reports the *behind* direction. Mindscapes only ever increase in game, so a
    stored value above the scan means the payload is old, not the build — reporting
    that would be noise, and noise is how a real warning gets ignored.
    """
    incoming = int(char.get("constellation", 0) or 0)
    if incoming <= stored_mindscape:
        return None
    return (
        f"build is at M{stored_mindscape} but the scan says M{incoming} — skipped, so "
        f"it keeps the stale value and stays without its M{stored_mindscape + 1}"
        f"-M{incoming} kit rows. Re-import with build_conflict=overwrite to update it."
    )


def skill_levels_problem(char: dict) -> str | None:
    """Return a description if a character's talents contradict its mindscape.

    `skill_levels` stores the EFFECTIVE level with the mindscape bonus already
    included (#153, established against a real scanner export), so the ceiling is
    ``12 + (4 if mc>=5 else 2 if mc>=3 else 0)``.

    This duplicates the rule `app.schemas.build` enforces for API writes, because
    the import path never touches those schemas — it builds `Build(**kwargs)` from a
    `BuildDraft` dataclass directly. Without this, imports remained free to write the
    exact self-contradicting rows the schema validator exists to stop (#156: Anby and
    Nicole are live examples, mindscape 0 with skills of 13 and 15).

    Reports rather than raises: one inconsistent character must not abort a 42-agent
    import, matching how unresolvable agent keys are handled.
    """
    talent = char.get("talent") or {}
    mindscape = int(char.get("constellation", 0) or 0)
    bonus = 4 if mindscape >= 5 else (2 if mindscape >= 3 else 0)  # noqa: PLR2004
    allowed = 12 + bonus
    over = {
        name: int(talent.get(name, 1) or 1)
        for name in ("basic", "dodge", "assist", "special", "chain")
        if int(talent.get(name, 1) or 1) > allowed
    }
    if not over:
        return None
    return (
        f"skill level(s) {over} exceed the maximum of {allowed} for mindscape "
        f"{mindscape} — the build's mindscape is probably stale (see #156), since "
        f"skill_levels carry the mindscape bonus already"
    )


@dataclass
class BuildDraft:
    """Resolved Build fields ready for DB insertion."""

    agent_id: str
    agent_level: int
    mindscape_level: int
    skill_levels: str  # "basic,dodge,special,chain,core" — matches Build.skill_levels format
    core_skill_level: int  # passive tier 0 (A) … 5 (F)
    w_engine_id: str | None  # None when no weapon equipped
    w_engine_level: int  # 60 default when no weapon
    w_engine_refinement: int  # 1 default when no weapon


def build_draft_from_character(
    char: dict,
    agent: Agent,
    weapon: WEngine | None = None,
    weapon_raw: dict | None = None,
) -> BuildDraft:
    """Map one eZOD character dict to a :class:`BuildDraft`.

    ``talent.assist`` is silently dropped — fairy's ``skill_levels`` has no
    assist slot.  When ``weapon`` is None (no equipped engine), w_engine
    fields use Build-model defaults (level=60, refinement=1).

    Core mapping:
    - ``talent.core`` is the A–F rank (1=A … 6=F; 0 = uninvested).
    - ``core_skill_level`` (passive tier) = ``clamp(talent.core - 1, 0, 5)``.
    - Core-attack entry in ``skill_levels`` = ``max(1, talent.core)``
      (game floors uninvested agents to level 1 in UI).
    """
    talent: dict = char.get("talent") or {}
    core_raw = int(talent.get("core", 0))

    core_attack_level = max(1, core_raw)
    core_skill_level = max(0, min(5, core_raw - 1))

    skill_levels = ",".join([
        str(int(talent.get("basic", 1))),
        str(int(talent.get("dodge", 1))),
        str(int(talent.get("special", 1))),
        str(int(talent.get("chain", 1))),
        str(core_attack_level),
    ])

    return BuildDraft(
        agent_id=agent.id,
        agent_level=int(char.get("level", 60)),
        mindscape_level=int(char.get("constellation", 0)),
        skill_levels=skill_levels,
        core_skill_level=core_skill_level,
        w_engine_id=weapon.id if weapon is not None else None,
        w_engine_level=int(weapon_raw.get("level", 60)) if weapon_raw is not None else 60,
        w_engine_refinement=int(weapon_raw.get("refinement", 1)) if weapon_raw is not None else 1,
    )


def disc_slots_for_character(char_key: str, discs_raw: list[dict]) -> dict[int, dict]:
    """Return ``{slot_int: disc_raw}`` for discs equipped by the given character.

    Discs with ``location == char_key`` and a valid integer ``slotKey`` (1–6)
    are included.  Malformed or unequipped entries are silently skipped.
    """
    result: dict[int, dict] = {}
    for disc in discs_raw:
        if not isinstance(disc, dict):
            continue
        if disc.get("location") != char_key:
            continue
        try:
            slot = int(disc["slotKey"])
        except (KeyError, ValueError, TypeError):
            continue
        if 1 <= slot <= _MAX_DISC_SLOT_NUM:
            result[slot] = disc
    return result


# ---- eZOD disc parsing -------------------------------------------------------


def _ezod_disc_to_draft(  # noqa: PLR0911, PLR0912
    raw: dict,
    *,
    set_lookup: dict[str, DiscSet],
) -> _DiscDraft | tuple[None, str]:
    """Convert one eZOD disc dict to a :class:`_DiscDraft`.

    Differs from the ZOD path in two ways: rarity is an int (4/3/2 →
    S/A/B via ``_RARITY_INT_MAP``), and substats carry an exact ``value``
    float instead of an ``upgrades`` roll count.  Empty-key substats
    (``key == ""``) are silently skipped — they are padding in the export.

    Returns the draft on success, or ``(None, reason)`` for skips.
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

    rarity_raw = raw.get("rarity")
    try:
        rarity_int = int(rarity_raw)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None, f"invalid rarity: {rarity_raw!r}"
    rarity = _RARITY_INT_MAP.get(rarity_int)
    if rarity is None:
        return None, f"unknown rarity int: {rarity_int}"

    try:
        level = int(raw.get("level", 0))
    except (ValueError, TypeError) as e:
        return None, f"invalid level: {e}"
    max_level = _MAX_LEVEL[rarity]
    if not 0 <= level <= max_level:
        return None, f"level {level} outside [0, {max_level}] for rarity {rarity_int}"

    main_key = raw.get("mainStatKey", "")
    if not isinstance(main_key, str) or len(main_key) > _MAX_STRING_LEN:
        return None, f"mainStatKey too long or wrong type: {main_key!r:.50}"
    main_stat = _MAIN_STAT_MAP.get(main_key)
    if main_stat is None:
        return None, f"unknown main stat key: {main_key!r}"

    max_main = _main_stat_max(rarity, slot.value, main_stat)
    if max_main is None:
        return None, f"no main-stat table for slot {slot.value} stat {main_stat.value}"
    main_value = int(max_main * (0.25 + 0.75 * level / max_level))

    raw_substats = raw.get("substats", []) or []
    if not isinstance(raw_substats, list):
        return None, "substats must be an array"

    substats: list[dict] = []
    for sub in raw_substats:
        if not isinstance(sub, dict):
            return None, f"substat entry is not an object (got {type(sub).__name__})"
        sub_key = sub.get("key", "")
        if not isinstance(sub_key, str):
            return None, f"substat key wrong type: {sub_key!r}"
        if sub_key == "":
            continue  # padding entry — skip silently
        if len(sub_key) > _MAX_STRING_LEN:
            return None, f"substat key too long: {sub_key!r:.50}"
        sub_stat = _SUBSTAT_MAP.get(sub_key)
        if sub_stat is None:
            return None, f"unknown substat key: {sub_key!r}"
        try:
            value_raw = float(sub.get("value", 0))
        except (ValueError, TypeError) as e:
            return None, f"substat {sub_key} invalid value: {e}"
        stored_value = _substat_value_from_exact(sub_stat, value_raw)
        substats.append({"stat": sub_stat.value, "value": stored_value})

    if len(substats) > _MAX_SUBSTATS:
        return None, f"too many real substats: {len(substats)} > {_MAX_SUBSTATS}"

    return _DiscDraft(
        disc_set_id=disc_set.id,
        slot=slot,
        rarity=rarity,
        level=level,
        main_stat_type=main_stat,
        main_stat_value=main_value,
        substats=substats,
    )


# ---- Orchestration -----------------------------------------------------------


@dataclass
class EzodImportResult:
    """Counts from a completed eZOD import."""

    imported: int = 0
    skipped_duplicate: int = 0
    skipped_unknown_set: int = 0
    skipped_invalid: int = 0
    errors: list[str] = field(default_factory=list)
    # Advisory, not failures. `errors` is rendered by the UI as "N error rows"
    # (import-page.html), so putting "your build's mindscape is stale" in there would
    # report a healthy import as N errors — the exact crying-wolf noise that teaches
    # people to skip the list. Separate channel, separate meaning.
    notices: list[str] = field(default_factory=list)
    builds_created: int = 0
    builds_overwritten: int = 0
    builds_skipped: int = 0
    discs_deleted: int = 0
    builds_deleted: int = 0
    teams_deleted: int = 0
    combos_deleted: int = 0
    team_slots_remapped: int = 0


async def import_ezod_payload(  # noqa: PLR0912, PLR0915
    data: dict,
    session: AsyncSession,
    owner_id: str | None = None,
    build_conflict: str = "overwrite",
    disc_mode: str = "merge",
    build_mode: str = "merge",
) -> EzodImportResult:
    """Import an eZOD payload: disc inventory + one Build per character.

    Phase 0 — wipe: when ``build_mode`` / ``disc_mode`` is ``"clean"``, the
    owner's existing builds / discs are deleted before anything is parsed, so
    phase 1 dedups against an intentionally emptied baseline.  Both wipes run
    inside the caller's transaction: a later failure rolls them back.

    Phase 1 — disc inventory: parse and deduplicate all discs in the
    payload against the owner's existing unequipped inventory.  New rows
    are flushed so they get IDs; a ``hash → Disc`` map is built for
    phase 2.

    Phase 2 — builds: for each character, resolve its agent key, handle
    the conflict (``skip`` or ``overwrite``), create a Build row, and
    attach equipped discs by slot using the hash map from phase 1.
    ``build_conflict`` only applies under ``build_mode="merge"`` — a clean
    leaves no existing build for any agent to conflict with.

    Unknown agent keys are recorded in ``result.errors`` and skipped.
    Unknown w-engine keys are silently ignored (build gets no engine).

    Raises ValueError for a malformed or over-cap payload, which
    ``POST /discs/import`` maps to 422.
    """
    # Validate before anything else — including before the phase 0 wipes, which
    # delete rows. `parse_ezod_payload` owns the structural checks and the
    # MAX_DISC_COUNT / MAX_CHAR_COUNT / MAX_WEAPON_COUNT ceilings, and until issue
    # #140 it had no caller in `app/` at all: the endpoint called this function
    # directly, so those ceilings were enforced only in tests while ZOD enforced its
    # own on the live path. Calling it here keeps one definition of the limits rather
    # than a second copy that can drift.
    data = parse_ezod_payload(data)

    result = EzodImportResult()

    # --- Phase 0: clean-mode wipes (owner-scoped, same transaction) ---

    if (disc_mode == "clean" or build_mode == "clean") and owner_id is None:
        raise ValueError("clean import modes require an owner_id")

    team_repo = TeamRepository(session, owner_id=owner_id)
    team_snapshot: list[tuple[str, int, str]] = []

    if build_mode == "clean":
        # Snapshot team composition by agent before the wipe nulls every slot;
        # it is restored after phase 2 creates the new builds (D-IM3).
        team_snapshot = await team_repo.snapshot_slots_for_owner()
        result.builds_deleted = await BuildRepository(
            session, owner_id=owner_id
        ).delete_all_for_owner()
    if disc_mode == "clean":
        result.discs_deleted = await DiscRepository(
            session, owner_id=owner_id
        ).delete_all_for_owner()

    # --- Phase 1: disc inventory ---

    sets_result = await session.execute(select(DiscSet))
    set_lookup = {_normalize_set_key(s.name): s for s in sets_result.scalars().all()}

    # Load all existing owner discs (equipped and unequipped) for dedup and
    # build attachment.  Equipped discs are still content-hashed to avoid
    # re-inserting them on a re-import; the attachment phase re-uses them.
    existing_stmt = select(Disc)
    if owner_id is not None:
        existing_stmt = existing_stmt.where(Disc.owner_id == owner_id)
    existing_rows = (await session.execute(existing_stmt)).scalars().all()

    # Keyed by content hash, but holding *every* row with that hash rather than one
    # (issue #139). Two discs of the same set, slot, level, rarity, main stat and
    # substat spread are indistinguishable by content, because there is nothing to
    # distinguish — at endgame a player genuinely owns several. Collapsing them to a
    # single row made the equip phase below point two characters at the same disc,
    # and last write wins, so one silently lost a slot while the counts reconciled.
    hash_to_discs: dict[str, list[Disc]] = {}
    # How many rows already exist per hash. The dedup rule is *multiplicity*, not mere
    # presence: a payload listing a disc twice when we hold one copy must import one
    # more, while a straight re-import of that same payload must import none. Presence
    # alone cannot express the difference.
    existing_counts: Counter[str] = Counter()
    for row in existing_rows:
        try:
            draft = _DiscDraft(
                disc_set_id=row.disc_set_id,
                slot=DiscSlot(row.slot.value if hasattr(row.slot, "value") else row.slot),
                rarity=Rarity(row.rarity.value if hasattr(row.rarity, "value") else row.rarity),
                level=row.level,
                main_stat_type=StatType(
                    row.main_stat_type.value
                    if hasattr(row.main_stat_type, "value")
                    else row.main_stat_type
                ),
                main_stat_value=row.main_stat_value,
                substats=row.substats or [],
            )
            h = _content_hash(draft)
            existing_counts[h] += 1
            hash_to_discs.setdefault(h, []).append(row)
        except (ValueError, TypeError):
            continue

    new_disc_pairs: list[tuple[str, Disc]] = []
    seen_in_payload: Counter[str] = Counter()
    for idx, raw_disc in enumerate(data.get("discs", [])):
        outcome = _ezod_disc_to_draft(raw_disc, set_lookup=set_lookup)
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
        # Skip only while this payload's occurrences are still covered by rows we
        # already hold. The Nth identical disc in the file is a duplicate exactly when
        # we already have N of them — which keeps a re-import a no-op (issue #139).
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
        disc_row = Disc(**row_kwargs)
        new_disc_pairs.append((h, disc_row))

    if new_disc_pairs:
        session.add_all([r for _, r in new_disc_pairs])
        await session.flush()
        for h, row in new_disc_pairs:
            hash_to_discs.setdefault(h, []).append(row)

    result.imported = len(new_disc_pairs)

    # --- Phase 2: builds ---

    # Disc rows already attached to a build during this run, by object identity.
    # Identity rather than `.id` because a row created in phase 1 has an id only
    # after the flush above, and two distinct rows can share every other attribute
    # — which is the whole point of issue #139.
    claimed_rows: set[int] = set()

    agent_lookup = await build_agent_lookup(session)
    wengine_lookup = await build_wengine_lookup(session)

    # Index equipped weapons by location (char key).
    weapon_by_location: dict[str, dict] = {}
    for weapon_raw in data.get("weapons", []):
        if not isinstance(weapon_raw, dict):
            continue
        loc = weapon_raw.get("location", "")
        if loc:
            weapon_by_location[loc] = weapon_raw

    for char in data.get("characters", []):
        if not isinstance(char, dict):
            continue
        char_key = char.get("key", "")

        agent_result = resolve_agent_key(char_key, agent_lookup)
        if isinstance(agent_result, tuple):
            _, reason = agent_result
            result.errors.append(f"character {char_key!r}: {reason}")
            continue
        agent = agent_result

        # Conflict check: at most one build per (owner, agent).
        existing_build_stmt = select(Build).where(Build.agent_id == agent.id)
        if owner_id is not None:
            existing_build_stmt = existing_build_stmt.where(Build.owner_id == owner_id)
        existing_build = (await session.execute(existing_build_stmt)).scalars().first()

        if existing_build is not None and build_conflict == "skip":
            # #156: skipping is silent by design, and that silence is how 16 of 39
            # builds ended up carrying a mindscape below the scanner's — every
            # mismatch an understatement, each one quietly dropping the kit rows
            # gated on `min_mindscape`. Mindscapes only ever increase in game, so an
            # incoming value ABOVE the stored one is drift, never a stale payload.
            # Report it; do not silently rewrite a build the caller asked to skip.
            _drift = mindscape_drift_problem(char, existing_build.mindscape_level or 0)
            if _drift is not None:
                result.notices.append(f"{char_key}: {_drift}")
            # #144: reserve this build's discs too. Identity-map guarantees these are
            # the same row objects `hash_to_discs` holds, so claiming by id() blocks a
            # later content-identical claim.
            _kept = (
                await session.execute(select(Disc).where(Disc.build_id == existing_build.id))
            ).scalars().all()
            claim_ids_for_skipped_build(list(_kept), claimed_rows)
            result.builds_skipped += 1
            continue

        # #156: flag, do not abort. A character whose talents exceed what its
        # mindscape allows is internally inconsistent — almost always a stale
        # mindscape — and the schema validator cannot see this path.
        _skill_problem = skill_levels_problem(char)
        if _skill_problem is not None:
            result.notices.append(f"{char_key}: {_skill_problem}")

        # Resolve equipped w-engine (if any).
        weapon_raw = weapon_by_location.get(char_key)
        weapon: WEngine | None = None
        if weapon_raw is not None:
            engine_result = resolve_wengine_key(weapon_raw.get("key", ""), wengine_lookup)
            if not isinstance(engine_result, tuple):
                weapon = engine_result

        draft = build_draft_from_character(
            char, agent,
            weapon=weapon,
            weapon_raw=weapon_raw if weapon is not None else None,
        )

        build_kwargs: dict = {
            "agent_id": draft.agent_id,
            "agent_level": draft.agent_level,
            "mindscape_level": draft.mindscape_level,
            "skill_levels": draft.skill_levels,
            "core_skill_level": draft.core_skill_level,
            "w_engine_id": draft.w_engine_id,
            "w_engine_level": draft.w_engine_level,
            "w_engine_refinement": draft.w_engine_refinement,
        }

        if existing_build is not None:
            # overwrite: mutate the existing row in place — keep its id so
            # any Team/Combo referencing this build survives (D-IM2). Detach
            # its old discs first; the slot-attachment loop below re-attaches
            # whichever ones are still in this file.
            old_discs_stmt = select(Disc).where(Disc.build_id == existing_build.id)
            old_discs = (await session.execute(old_discs_stmt)).scalars().all()
            for d in old_discs:
                # A detached row is by definition unclaimed, so release it. Without
                # this, a payload that names the same character twice (or two keys
                # that resolve to one agent) detaches the discs the first pass
                # attached and then finds every candidate already claimed, leaving
                # that build with nothing.
                claimed_rows.discard(id(d))
                d.build_id = None
                d.build_slot = None
            for key, value in build_kwargs.items():
                setattr(existing_build, key, value)
            build = existing_build
            result.builds_overwritten += 1
        else:
            if owner_id is not None:
                build_kwargs["owner_id"] = owner_id
            build = Build(**build_kwargs)
            session.add(build)
            # Counted here, not after the disc-attachment block below. There it ran
            # unconditionally, so an overwrite incremented `builds_overwritten` and then
            # `builds_created` as well — 3 overwritten builds reported as 6 build events,
            # and the import page rendered "Builds created: 3" for builds that already
            # existed (issue #141). The three counters now partition the characters the
            # payload resolved: created + overwritten + skipped == that total.
            result.builds_created += 1
        await session.flush()

        # Attach equipped discs by slot.
        equipped = disc_slots_for_character(char_key, data.get("discs", []))
        for slot, disc_raw in equipped.items():
            disc_outcome = _ezod_disc_to_draft(disc_raw, set_lookup=set_lookup)
            if isinstance(disc_outcome, tuple):
                continue
            h = _content_hash(disc_outcome)
            # Claim a row not already claimed in this run. With one row per hash the
            # second character to equip a content-identical disc overwrote the first
            # character's attachment, and the first silently lost the slot (#139).
            disc_row = next(
                (r for r in hash_to_discs.get(h, []) if id(r) not in claimed_rows),
                None,
            )
            if disc_row is not None:
                claimed_rows.add(id(disc_row))
                disc_row.build_id = build.id
                disc_row.build_slot = slot

        await session.flush()

    # --- Phase 3: restore team composition across a build wipe (D-IM3) ---

    if build_mode == "clean":
        result.team_slots_remapped = await team_repo.remap_slots(team_snapshot)
        result.teams_deleted, result.combos_deleted = (
            await team_repo.delete_all_null_teams_for_owner(
                team_ids={team_id for team_id, _, _ in team_snapshot}
            )
        )

    return result
