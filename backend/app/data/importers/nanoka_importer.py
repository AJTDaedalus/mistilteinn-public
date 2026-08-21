"""Import game data from nanoka.cc static API.

nanoka.cc is the successor to hakush.in, actively updated each patch.
API: https://static.nanoka.cc/zzz/{version}/en/{entity}/{id}.json
Manifest: https://static.nanoka.cc/manifest.json

Data format: identical to zzz-hakushin-data but with snake_case keys.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import delete, select

from app.data.importers.base_importer import AnomalyStats, BaseImporter

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent import Agent, AgentSkill, Attack, CoreSkill, Mindscape
from app.models.build import EnemyProfile
from app.models.disc import DiscSet
from app.models.enums import (
    ELEMENT_ID_MAP,
    RARITY_INT_MAP,
    SPECIALTY_ID_MAP,
    Element,
    PotentialTag,
    PotentialVariant,
)
from app.models.w_engine import WEngine

logger = logging.getLogger(__name__)

BASE_URL = "https://static.nanoka.cc"

SKILL_TYPE_MAP = {
    "basic": "Basic",
    "dodge": "Dodge",
    "special": "Special",
    "chain": "Chain",
    "assist": "Assist",
}


def _skill_key_from_name(mapped_key: str, name: str) -> str:
    """Refine the SKILL_TYPE_MAP-resolved key based on the attack/skill name.

    Nanoka folds EX Special moves under skill_key="special" and Ultimate moves
    under skill_key="chain". Name-based override re-classifies them to the
    canonical DB keys so buff_resolver scope filtering works correctly.
    """
    if name.startswith("EX Special"):
        return "EXSpecial"
    if name.startswith("Ultimate"):
        return "Ultimate"
    return mapped_key


RAND_PROPERTY_MAP: dict[str, str] = {
    "Percent ATK": "atk_pct",
    "ATK": "atk_pct",
    "Percent HP": "hp_pct",
    "HP": "hp_pct",
    "Percent DEF": "def_pct",
    "DEF": "def_pct",
    "CRIT Rate": "crit_rate",
    "CRIT DMG": "crit_dmg",
    "Impact": "impact",
    "Anomaly Proficiency": "anomaly_proficiency",
    "Anomaly Mastery": "anomaly_mastery_pct",
    "PEN Ratio": "pen_ratio",
    "Energy Regen": "energy_regen",
}


def _strip_color_tags(text: str) -> str:
    return re.sub(r"<color=#[0-9A-Fa-f]+>(.*?)</color>", r"\1", text)


# `<Term:NNNNNNN>` is a narrative noun/mechanic ref used throughout skill/core/
# mindscape text (nanoka mirrors the Dimbreath TextMap's raw markup). There is
# no generic ``Term_<id>`` TextMap key that resolves these ids — the merged
# TextMap (pinned SHA 475dd0195645) has zero such keys (see
# `app/data/dimbreath/schema/term_map.json`'s `term_tag_note`). Each id is a
# per-agent mechanic name, curated by cross-referencing where the game's own
# `{Code}_NounPrompts_NN` / `_NN_Title` entries introduce the same concept.
#
# Curated 2026-07-28 (Task 4, docs/LOG_remielle.md) from Remielle's own
# NounPrompts titles in the merged TextMap:
#   Remielle_NounPrompts_01 / _01_Title = "Anomaly Effect Strength" (id 1000023)
#   Remielle_NounPrompts_02 / _02_Title = "Refringe"                (id 1000031)
#   Remielle_NounPrompts_03 / _03_Title = "Floating Radiance"       (id 1000032)
#   Remielle_NounPrompts_04 / _04_Title = "Voidflare"               (id 1000033)
#   Remielle_NounPrompts_05 / _05_Title = "Luminize"                (id 1000034)
#   Remielle_NounPrompts_06 / _06_Title = "Phase Flow"              (id 1000035)
# Extend this map as future agents introduce new term ids.
TERM_ID_MAP: dict[str, str] = {
    "1000023": "Anomaly Effect Strength",
    "1000031": "Refringe",
    "1000032": "Floating Radiance",
    "1000033": "Voidflare",
    "1000034": "Luminize",
    "1000035": "Phase Flow",
}

# Single pass, two alternatives (tried left-to-right per match position so the
# paired form wins whenever it applies):
#   1. Paired: `<Term:1000031></Term>` (empty — resolve via TERM_ID_MAP) or
#      `<Term:1000031>Refringed</Term>` (wraps its own visible text — keep the
#      text, same treatment as `<color>`/`<IconMap>` tags). The `[^<]*`
#      content class keeps this from crossing into an unrelated later
#      `</Term>` elsewhere in the string.
#   2. Solo/self-closing, with no matching `</Term>` immediately following.
# Combining both into one regex (rather than two sequential `.sub()` passes)
# ensures each placeholder is matched — and, if unresolved, warned about —
# exactly once.
_TERM_RE = re.compile(r"<Term:(\d+)>([^<]*)</Term>|<Term:(\d+)>")


def _inline_term_placeholders(text: str) -> str:
    """Resolve `<Term:NNNNNNN>` placeholders to their display names.

    An id with no ``TERM_ID_MAP`` entry is left as the raw placeholder and
    logged as a warning — never silently blanked. Before this fix, nothing
    resolved `<Term:>` at all, so every such placeholder rendered empty.
    """

    def _sub(match: re.Match[str]) -> str:
        pair_id, content, solo_id = match.group(1), match.group(2), match.group(3)
        if pair_id is not None and content:
            return content
        term_id = pair_id if pair_id is not None else solo_id
        resolved = TERM_ID_MAP.get(term_id)
        if resolved is None:
            logger.warning("Unresolved <Term:%s> placeholder — leaving raw", term_id)
            return match.group(0)
        return resolved

    return _TERM_RE.sub(_sub, text)


def _unique_sorted_param_variants(param_dict: dict) -> list[tuple[str, dict]]:
    """Dedupe a param's skill_id entries by (damage%, growth), ascending.

    Multi-target hits share identical damage across skill_ids; variant moves
    (e.g. Soaring Light: 1-sword vs 6-swords) carry different values under
    different skill_ids in the same param. Sorting ascending puts the
    smallest variant at index 0.
    """
    seen_keys: set[tuple[int, int]] = set()
    unique_variants: list[tuple[str, dict]] = []
    for sid_str, v in param_dict.items():
        key = (v.get("damage_percentage", 0), v.get("damage_percentage_growth", 0))
        if key not in seen_keys:
            seen_keys.add(key)
            unique_variants.append((sid_str, v))
    unique_variants.sort(
        key=lambda sv: (
            sv[1].get("damage_percentage", 0),
            sv[1].get("damage_percentage_growth", 0),
        )
    )
    return unique_variants


# Markup and number extraction for the Potential value ramps (#90 Track 2). Kept as
# module constants so the derivation is one place, and so a test can exercise it without
# a DB or the network.
_POTENTIAL_TAG_RE = re.compile(r"<[^>]+>")
_POTENTIAL_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)(%?)")


def _parse_potential_values(desc: str) -> list[float]:
    """Every number in one Potential node's description, in document order.

    A ``%`` suffix means the value is a percentage and is stored as a DECIMAL (18% ->
    0.18), matching both the source text and ZO's convention; anything else is literal (a
    stack cap, a duration, a flat stat). Document order is load-bearing — it is the only
    thing that ties a value to its meaning, since the numbers carry no labels.
    """
    stripped = _POTENTIAL_TAG_RE.sub("", desc or "")
    return [
        float(num) / 100 if pct else float(num)
        for num, pct in _POTENTIAL_NUM_RE.findall(stripped)
    ]


def _parse_potential_ramps(potential_detail: dict) -> list[list[float]] | None:
    """Per-param six-element ramps from an agent's ``potential_detail``.

    Returns ``None`` when the agent has no Potential tree, or when the nodes carry no
    numbers to extract.

    Note that being UNRELEASED is not that case: Koleda's Potential is absent from
    nanoka's live manifest but her `latest` nodes already carry full text, so she parses
    to 2 params like any other agent. The importer reads `latest` by policy, so her ramps
    are imported as pre-release data — see her `known_issues.json` blocker, and note that
    a pre-release datamine of the 3.1 trio shipped with different values AND different
    move names (docs/evidence/potential_public_sources.md, D10).

    Shape: ``ramps[param_index][level_index]``, where ``level_index`` is
    ``builds.potential_rank - 1``:

    * index 0 is **Level I** and is 0 for every param — node ``<aid>00`` buys the kit
      variant and no value bonus, which is why it is skipped as a source and supplied as a
      zero instead. This mirrors ZO's generator, which drops that node and prepends a zero
      row.
    * indices 1..5 are Levels II..VI, read from nodes ``<aid>01``..``<aid>05``.

    A level whose number count disagrees with the others is a data-shape change rather
    than a value change, and is refused rather than zero-padded: silently short ramps
    would bind param *i* to a different meaning at different levels.
    """
    if not potential_detail:
        return None
    # Node ids sort lexicographically into level order (<aid>00..<aid>05); [1:] drops
    # Level I, whose values are supplied as the leading zero below.
    level_nodes = sorted(potential_detail)[1:]
    per_level = [
        _parse_potential_values(potential_detail[node].get("desc")) for node in level_nodes
    ]
    if not per_level or not per_level[0]:
        return None

    widths = {len(values) for values in per_level}
    if len(widths) != 1:
        logger.warning(
            "Potential ramp width disagrees across levels (%s); refusing to guess — "
            "the param order is what binds a value to its meaning",
            sorted(widths),
        )
        return None

    return [[0.0, *(level[i] for level in per_level)] for i in range(next(iter(widths)))]


def _potential_tag(entry: dict) -> PotentialTag | None:
    """Which Potential state ``entry`` belongs to, or None if it belongs to both.

    nanoka marks base-kit-only entries with ``potential: [0]`` and Potential-only
    entries with ``potential: [<aid>00..<aid>05]``; ``[]`` (or a missing key) means
    the entry is present in both states.

    The discriminating test is **"contains 0"**, never "is empty" — that distinction
    is the whole of #85. A positive "keep only empty" reading would classify all 18
    live Potential-only move names roster-wide as absent
    (docs/RESEARCH_potential_sweep_85.md §5), 16 of which also carry DMG params and so
    would lose their Attack rows (docs/RESEARCH_potential_impact_85.md §(a)).

    Before #90 this was ``_in_unlocked_kit``, which *dropped* the base rows. Both
    states are now imported and tagged, and the variant is selected per build.
    """
    potential = entry.get("potential") or []
    if not potential:
        return None
    return PotentialTag.BASE if 0 in potential else PotentialTag.UNLOCKED


def _visible_in(tag: PotentialTag | None, variant: PotentialVariant) -> bool:
    """Whether a row tagged ``tag`` is part of ``variant``'s kit.

    Argument-order convenience wrapper over ``PotentialVariant.includes`` for the
    import passes, which iterate entries within a fixed variant.
    """
    return variant.includes(tag)


@dataclass(frozen=True)
class _HitPlan:
    """One planned Attack row: which param it came from, and where it sits in the move."""

    skill_id: str
    values: dict
    param_name: str
    hit_index: int
    potential: PotentialTag | None


def _plan_move_hits(params: list[dict]) -> list[_HitPlan]:
    """Plan the Attack rows for one named move, across BOTH Potential states.

    **This function exists because ``hit_index`` is a running counter.** Numbering a
    single merged pass over both variants produces the sequence #85 was filed to
    remove: Soldier 0 - Anby as a 7-hit string that exists in neither kit, with
    1381004/005/006 at indices 4/5/6 rather than 3/4/5. So each variant is numbered on
    its own pass and the results are reconciled:

    * a hit present in both passes at the **same** index is one row, tagged None;
    * a hit present in only one pass is one row, tagged for that variant;
    * a hit present in both at **different** indices is not really shared — it is
      split into two tagged rows and warned about, rather than silently resolved to
      one of the two (DESIGN_potential_toggle.md §4.2, step 3).

    The third case does not occur in the current roster; it is a guard against a patch
    that reshapes a move around a variant-only hit.
    """
    passes: dict[PotentialVariant, dict[tuple[int, int, int], int]] = {}
    payloads: dict[tuple[int, int, int], tuple[str, dict, str, PotentialTag | None]] = {}
    order: list[tuple[int, int, int]] = []

    for variant in (PotentialVariant.LOCKED, PotentialVariant.UNLOCKED):
        hit_index = 0
        # Track (skill_id, damage_base, damage_growth) tuples already emitted for this
        # move so we don't create duplicate Attack rows when nanoka lists the same
        # physical hit under multiple named scenarios (e.g. "1 Qingming Sword DMG" and
        # "6 Qingming Sword DMG" both referencing the same skill_id).
        emitted_rows: set[tuple[int, int, int]] = set()
        indices: dict[tuple[int, int, int], int] = {}

        for param in params:
            tag = _potential_tag(param)
            if not _visible_in(tag, variant):
                continue

            outer_name = param.get("name", "")
            # Each move's DMG and Daze sequences are mirrored;
            # only the DMG side carries the damage multiplier.
            if "DMG" not in outer_name or "Daze" in outer_name:
                continue

            param_dict = param.get("param", {})
            if not param_dict:
                continue

            # Deduplicate by (damage_percentage, growth) so we emit exactly one Attack
            # row per distinct multiplier pair, smallest variant first.
            for sid_str, values in _unique_sorted_param_variants(param_dict):
                db_key = (
                    int(sid_str),
                    values.get("damage_percentage", 0),
                    values.get("damage_percentage_growth", 0),
                )
                if db_key in emitted_rows:
                    continue
                emitted_rows.add(db_key)
                indices[db_key] = hit_index
                if db_key not in payloads:
                    payloads[db_key] = (sid_str, values, outer_name, tag)
                    order.append(db_key)
                hit_index += 1

        passes[variant] = indices

    locked = passes[PotentialVariant.LOCKED]
    unlocked = passes[PotentialVariant.UNLOCKED]

    plans: list[_HitPlan] = []
    for db_key in order:
        sid_str, values, param_name, tag = payloads[db_key]
        in_locked, in_unlocked = db_key in locked, db_key in unlocked

        if in_locked and in_unlocked and locked[db_key] == unlocked[db_key]:
            plans.append(_HitPlan(sid_str, values, param_name, locked[db_key], None))
            continue

        if in_locked and in_unlocked:
            logger.warning(
                "skill_id %s sits at hit_index %s in the base kit but %s with Potential "
                "unlocked; splitting into two tagged rows rather than picking one",
                sid_str,
                locked[db_key],
                unlocked[db_key],
            )
            plans.append(
                _HitPlan(sid_str, values, param_name, locked[db_key], PotentialTag.BASE)
            )
            plans.append(
                _HitPlan(
                    sid_str, values, param_name, unlocked[db_key], PotentialTag.UNLOCKED
                )
            )
            continue

        variant_index = locked[db_key] if in_locked else unlocked[db_key]
        plans.append(
            _HitPlan(
                sid_str,
                values,
                param_name,
                variant_index,
                PotentialTag.BASE if in_locked else PotentialTag.UNLOCKED,
            )
        )

    plans.sort(key=lambda plan: (plan.hit_index, plan.potential or ""))
    return plans


def _extract_element(
    element_dict: dict,
    on_unmapped: Callable[[], None] | None = None,
) -> Element:
    """Resolve nanoka's ``element_type`` dict to our enum, falling back to Physical.

    If the dict carries id(s) but none of them are in ``ELEMENT_ID_MAP`` (e.g. a
    new element like Lumiflux whose numeric id hasn't been mapped yet), this is
    loud: it logs a warning naming the raw id(s) and, if given, invokes
    ``on_unmapped`` so the caller can surface a counter in the seed summary. The
    fallback behaviour itself is unchanged.
    """
    for eid_str in element_dict:
        eid = int(eid_str)
        if eid in ELEMENT_ID_MAP:
            return ELEMENT_ID_MAP[eid]
    if element_dict:
        logger.warning(
            "Unmapped element id(s) %s in element_type — no ELEMENT_ID_MAP entry; "
            "falling back to Element.PHYSICAL",
            list(element_dict.keys()),
        )
        if on_unmapped:
            on_unmapped()
    return Element.PHYSICAL


def _extract_specialty_id(specialty_dict: dict) -> int:
    for sid_str in specialty_dict:
        return int(sid_str)
    return 1


def _extract_anomaly_stats(stats: dict) -> AnomalyStats:
    """Return the agent's base Anomaly Mastery / Proficiency pair.

    nanoka's own field names are counter-intuitive: `element_abnormal_power` is
    Anomaly MASTERY and `element_mystery` is Anomaly PROFICIENCY. Confirmed
    in-game (ungeared Nangong Yu Lv1 reads AM 90 / AP 93; AM and AP do not
    scale with level), against ZO (character.ts:226-227), and against
    per-agent wiki stat tables for Miyabi/Alice/Vivian/Harumasa. Do not "fix"
    this mapping back — see docs/RESEARCH_batch32c_followups.md.
    """
    return AnomalyStats(
        mastery=stats.get("element_abnormal_power", 0),
        proficiency=stats.get("element_mystery", 0),
    )


def _extract_promotion_stats(level_data: dict) -> list[dict[str, int]] | None:
    """Map nanoka's ``level`` dict (1-indexed promotion tiers) to the model's
    0-indexed ``promotion_stats`` list of ``{hp, atk, def}`` bonuses.

    nanoka keys "1".."6" hold the cumulative bonus unlocked at that promotion
    (tier "1" is the pre-ascension baseline, always 0); the model's list is
    0-indexed so tier N maps to ``promotion_stats[N-1]``.
    """
    if not level_data:
        return None
    stats: list[dict[str, int]] = []
    for tier in range(1, 7):
        tier_data = level_data.get(str(tier), {})
        stats.append(
            {
                "hp": tier_data.get("hp_max", 0),
                "atk": tier_data.get("attack", 0),
                "def": tier_data.get("defence", 0),
            }
        )
    return stats


# nanoka's ``extra_level`` stat labels -> ZO ``coreStats`` field names, split by
# whether the label denotes a flat or a percentage stat. The label alone is not
# enough: "HP" appears as both (flat for Yixuan, percent for Manato), so the
# entry's ``format`` string is the discriminator -- "{0:0.#%}" means percent.
_CORE_FLAT_FIELDS = {
    "Base ATK": "atk",
    "HP": "hp",
    "DEF": "def",
    "Impact": "impact",
    "Anomaly Mastery": "anomMas",
    "Anomaly Proficiency": "anomProf",
}
_CORE_PCT_FIELDS = {
    "ATK": "atk_",
    "HP": "hp_",
    "DEF": "def_",
    "CRIT Rate": "crit_",
    "CRIT DMG": "crit_dmg_",
    "PEN Ratio": "pen_",
}
# Energy Regen is neither: nanoka reports it in hundredths (36 -> 0.36), and its
# format string carries no percent sign.
_CORE_ENERGY_REGEN_LABEL = "Base Energy Regen"


def _extract_core_stats(extra_level: dict) -> list[dict[str, float]] | None:
    """Map nanoka's ``extra_level`` to ZO-shaped ``coreStats`` rows.

    nanoka keys "1".."6" are the Core Skill tiers A..F; the model's list is
    0-indexed, so tier N maps to ``core_stats[N-1]``. Percentage values arrive
    as basis points (1440 -> 0.144) and are scaled to the decimal fractions
    ``snapshot_builder`` expects; flat values pass through unchanged.
    """
    if not extra_level:
        return None
    rows: list[dict[str, float]] = []
    for tier in range(1, 7):
        entries = (extra_level.get(str(tier)) or {}).get("extra") or {}
        row: dict[str, float] = {}
        for entry in entries.values():
            label = entry.get("name")
            value = entry.get("value")
            if label is None or value is None:
                continue
            if label == _CORE_ENERGY_REGEN_LABEL:
                row["enerRegen"] = value / 100
            elif "%" in (entry.get("format") or ""):
                if field := _CORE_PCT_FIELDS.get(label):
                    row[field] = value / 10000
            elif field := _CORE_FLAT_FIELDS.get(label):
                row[field] = value
        rows.append(row)
    return rows


class NanokaImporter(BaseImporter):
    """Fetches data from nanoka.cc static API (live, updated each patch)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        version: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(session)
        self._version = version
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        # Counter for element ids with no ELEMENT_ID_MAP entry, incremented by
        # both _extract_element (agent-level) and the per-hit path in
        # _import_attacks; surfaced in import_all()'s seed summary as
        # "unmapped_elements" so a new/renumbered element doesn't silently
        # fall back to Physical unnoticed.
        self._unmapped_element_count = 0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _resolve_version(self) -> str:
        if self._version:
            return self._version
        client = await self._get_client()
        resp = await client.get(f"{BASE_URL}/manifest.json")
        resp.raise_for_status()
        manifest = resp.json()
        # Use latest version to include beta/upcoming content
        self._version = manifest["zzz"]["latest"]
        logger.info("Resolved nanoka ZZZ version: %s", self._version)
        return self._version

    async def _fetch_index(self, entity: str) -> dict:
        version = await self._resolve_version()
        client = await self._get_client()
        url = f"{BASE_URL}/zzz/{version}/{entity}.json"
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def _fetch_detail(self, entity: str, entity_id: int | str) -> dict:
        version = await self._resolve_version()
        client = await self._get_client()
        url = f"{BASE_URL}/zzz/{version}/en/{entity}/{entity_id}.json"
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        """Close the underlying HTTP client, if one was opened."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _note_unmapped_element(self) -> None:
        """Bump the unmapped-element counter surfaced by `import_all`."""
        self._unmapped_element_count += 1

    async def import_all(self) -> dict[str, int]:
        """Run all importers, then surface the unmapped-element counter."""
        counts = await super().import_all()
        counts["unmapped_elements"] = self._unmapped_element_count
        return counts

    async def _prune(self, model: type, source_ids: set[int]) -> int:
        """Delete entities whose hakushin_id is no longer in the source index.

        Returns the number of pruned rows. This handles beta content being
        retracted between patches.
        """
        result = await self.session.execute(
            select(model.hakushin_id).where(model.hakushin_id.isnot(None))
        )
        db_ids = {row[0] for row in result.all()}
        stale_ids = db_ids - source_ids
        if not stale_ids:
            return 0
        await self.session.execute(delete(model).where(model.hakushin_id.in_(stale_ids)))
        logger.info(
            "Pruned %d stale %s(s): hakushin_ids=%s",
            len(stale_ids),
            model.__tablename__,
            sorted(stale_ids),
        )
        return len(stale_ids)

    # -- Agents --

    async def import_agents(self) -> int:
        """Fetch and upsert agents from the nanoka.cc ``character`` index, pruning stale ones."""
        index = await self._fetch_index("character")
        source_ids = {int(cid) for cid in index}
        count = 0
        for char_id_str in index:
            try:
                detail = await self._fetch_detail("character", char_id_str)
                agent = await self._import_one_agent(int(char_id_str), detail)
                if agent:
                    count += 1
            except Exception:
                logger.exception("Failed to import character %s", char_id_str)
        pruned = await self._prune(Agent, source_ids)
        await self.session.flush()
        logger.info("Imported %d agents, pruned %d stale", count, pruned)
        return count

    async def _import_one_agent(self, hakushin_id: int, data: dict[str, Any]) -> Agent | None:
        result = await self.session.execute(select(Agent).where(Agent.hakushin_id == hakushin_id))
        agent = result.scalar_one_or_none()

        stats = data.get("stats", {})
        element = _extract_element(
            data.get("element_type", {}), on_unmapped=self._note_unmapped_element
        )
        specialty_id = _extract_specialty_id(data.get("weapon_type", {}))
        specialty = SPECIALTY_ID_MAP.get(specialty_id, SPECIALTY_ID_MAP[1])
        rarity = RARITY_INT_MAP.get(data.get("rarity", 3), RARITY_INT_MAP[3])
        anomaly = _extract_anomaly_stats(stats)

        camp = data.get("camp", {})
        faction_name = ""
        faction_id = 0
        for fid, fname in camp.items():
            faction_id = int(fid)
            faction_name = fname
            break

        fields = {
            "name": data.get("name", ""),
            "full_name": data.get("code_name", data.get("name", "")),
            "element": element,
            "specialty": specialty,
            "rarity": rarity,
            "faction": faction_name,
            "faction_id": faction_id,
            "icon_path": data.get("icon", "")[:500],
            "base_hp": stats.get("hp_max", 0),
            "base_atk": stats.get("attack", 0),
            "base_def": stats.get("defence", 0),
            "hp_growth": stats.get("hp_growth", 0),
            "atk_growth": stats.get("attack_growth", 0),
            "def_growth": stats.get("defence_growth", 0),
            "base_crit_rate": stats.get("crit", 500),
            "base_crit_dmg": stats.get("crit_damage", 5000),
            "base_anomaly_mastery": anomaly.mastery,
            "base_anomaly_proficiency": anomaly.proficiency,
            "base_impact": stats.get("break_stun", 0),
            "base_energy_regen": stats.get("sp_recover", 0),
            "base_pen_flat": stats.get("pen_delta", 0),
            "base_pen_ratio": stats.get("pen_rate", 0),
            "promotion_stats": _extract_promotion_stats(data.get("level", {})),
            "core_stats": _extract_core_stats(data.get("extra_level", {})),
            # Root `potential` is the node roster (`<aid>00`..`<aid>05`); a non-empty
            # list means this agent has a Potential tree (#90). 11 of 60 do.
            "has_potential": bool(data.get("potential")),
            # Per-level value ramps, derived from the same nodes (#90 Track 2).
            "potential_params": _parse_potential_ramps(data.get("potential_detail") or {}),
        }

        if agent:
            for key, value in fields.items():
                setattr(agent, key, value)
            # Replace sub-resources — cascade delete handles old ones
            await self._clear_agent_sub_resources(agent)
        else:
            agent = Agent(hakushin_id=hakushin_id, **fields)
            self.session.add(agent)
        await self.session.flush()

        await self._import_agent_skills(agent, data)
        await self._import_attacks(agent, data)
        await self._import_core_skills(agent, data)
        await self._import_mindscapes(agent, data)

        return agent

    async def _clear_agent_sub_resources(self, agent: Agent) -> None:
        """Delete existing sub-resources so they can be re-imported fresh."""
        for model in (AgentSkill, Attack, CoreSkill, Mindscape):
            await self.session.execute(delete(model).where(model.agent_id == agent.id))

    async def _import_agent_skills(self, agent: Agent, data: dict) -> None:
        skill_data = data.get("skill", {})
        for skill_key, skill_info in skill_data.items():
            if skill_key not in SKILL_TYPE_MAP:
                continue
            descriptions = skill_info.get("description", [])
            if not isinstance(descriptions, list):
                continue
            # First-wins per name, resolved *per variant* (#90). A name whose winning
            # entry is the same in both states is one row tagged None; a name whose
            # entries differ between the states -- 25 moves across 9 agents, several of
            # which omit the whole mechanic in their base text -- becomes two tagged
            # rows, so a locked build reads the text its kit actually has.
            winners: dict[str, dict] = {}
            for variant in (PotentialVariant.LOCKED, PotentialVariant.UNLOCKED):
                seen_names: set[str] = set()
                for entry in descriptions:
                    if not _visible_in(_potential_tag(entry), variant):
                        continue
                    name = entry.get("name", "").strip()
                    if not name or name in seen_names:
                        continue
                    seen_names.add(name)
                    winners.setdefault(name, {})[variant] = entry

            for name, by_variant in winners.items():
                locked_entry = by_variant.get(PotentialVariant.LOCKED)
                unlocked_entry = by_variant.get(PotentialVariant.UNLOCKED)

                if locked_entry is unlocked_entry:
                    rows = [(locked_entry, None)]
                else:
                    rows = [
                        (entry, tag)
                        for entry, tag in (
                            (locked_entry, PotentialTag.BASE),
                            (unlocked_entry, PotentialTag.UNLOCKED),
                        )
                        if entry is not None
                    ]

                for entry, tag in rows:
                    desc = _strip_color_tags(_inline_term_placeholders(entry.get("desc", "")))
                    self.session.add(
                        AgentSkill(
                            agent_id=agent.id,
                            skill_key=_skill_key_from_name(SKILL_TYPE_MAP[skill_key], name),
                            name=name[:200],
                            description=desc,
                            potential=tag,
                        )
                    )

    async def _import_attacks(self, agent: Agent, data: dict) -> None:
        """Import per-hit damage rows for each named move on the agent.

        Nanoka's ``description`` array groups per-attack data by the
        named ``desc_entry`` (e.g. "Basic Attack: Sunderlight Maximum").
        Each entry's ``param`` list interleaves DMG and Daze multipliers
        for every hit in that move; the inner ``skill_id`` keys are
        bookkeeping IDs that don't match the section's name (ZZZ's data
        layout is genuinely confusing on this point — see the audit in
        commit history). We treat ``desc_entry.name`` as the attack
        name and pull the **DMG** params (skipping Daze) as the
        sequenced hits — values come from the first ``skill_id`` in
        each param's ``param`` dict, since duplicates inside one param
        carry the same numbers.
        """
        skill_data = data.get("skill", {})
        skill_list = data.get("skill_list", {})

        for skill_key, skill_info in skill_data.items():
            if skill_key not in SKILL_TYPE_MAP:
                continue

            descriptions = skill_info.get("description", [])
            for desc_entry in descriptions:
                attack_name = desc_entry.get("name", "")
                params = desc_entry.get("param", [])
                if not attack_name or not isinstance(params, list):
                    continue

                # A tag on the *entry* covers every row it produces: the whole move
                # belongs to one kit. A tag on an individual param is the narrower
                # case -- a shared move whose Nth hit differs between the states --
                # and _plan_move_hits works that out per variant.
                entry_tag = _potential_tag(desc_entry)

                for plan in _plan_move_hits(params):
                    sid_str, values = plan.skill_id, plan.values

                    skill_info_entry = skill_list.get(sid_str, {})
                    hit_element_id = skill_info_entry.get("element_type", 0)
                    # element_type 0 means "no override, inherit the agent's
                    # element" -- that is a legitimate, silent case. A *non-zero*
                    # id with no ELEMENT_ID_MAP entry is different: it means an
                    # unmapped element (e.g. a new patch id), so it must warn
                    # instead of silently inheriting.
                    if hit_element_id and hit_element_id not in ELEMENT_ID_MAP:
                        logger.warning(
                            "Unmapped per-hit element id %s on skill_id %s "
                            "(agent hakushin_id=%s); inheriting agent element %s",
                            hit_element_id,
                            sid_str,
                            agent.hakushin_id,
                            agent.element,
                        )
                        self._note_unmapped_element()
                    hit_element = ELEMENT_ID_MAP.get(hit_element_id, agent.element)

                    self.session.add(
                        Attack(
                            agent_id=agent.id,
                            hakushin_skill_id=int(sid_str),
                            skill_key=_skill_key_from_name(
                                SKILL_TYPE_MAP[skill_key], attack_name
                            ),
                            name=attack_name[:200],
                            # The per-hit param label ("Enhanced Basic Attack
                            # 5th-Hit DMG Multiplier"). One param can expand to
                            # several rows, so rows sharing a param_name is legal
                            # and must not be deduplicated on it.
                            param_name=plan.param_name[:200] or None,
                            hit_index=plan.hit_index,
                            element=hit_element,
                            damage_base=values.get("damage_percentage", 0),
                            damage_growth=values.get("damage_percentage_growth", 0),
                            stun_base=values.get("stun_ratio", 0),
                            stun_growth=values.get("stun_ratio_growth", 0),
                            energy_gain=values.get("sp_recovery", 0),
                            anomaly_buildup=values.get("attribute_infliction", 0),
                            potential=entry_tag if entry_tag is not None else plan.potential,
                        )
                    )

    async def _import_core_skills(self, agent: Agent, data: dict) -> None:
        passive = data.get("passive", {})
        levels = passive.get("level", {})

        # No dedup needed here: the base and Potential halves carry *distinct*
        # hakushin_ids (e.g. Nekomata 1021501-507 vs 1021508-514), so tagging is
        # enough to tell them apart. Their `name` arrays are identical, which is
        # why `potential` is the only thing that can (#90, RESEARCH sweep §7).
        for level_id, level_info in levels.items():
            tag = _potential_tag(level_info)
            level_num = level_info.get("level", 0)
            names = level_info.get("name", [])
            descs = level_info.get("desc", [])

            name = names[0] if names else ""
            desc = _strip_color_tags(_inline_term_placeholders(" | ".join(descs))) if descs else ""

            core_skill = CoreSkill(
                agent_id=agent.id,
                hakushin_id=int(level_id),
                level=level_num,
                name=name[:200],
                description=desc,
                potential=tag,
            )
            self.session.add(core_skill)

    async def _import_mindscapes(self, agent: Agent, data: dict) -> None:
        talent = data.get("talent", {})

        for level_str, talent_info in talent.items():
            level_num = talent_info.get("level", int(level_str))
            name = talent_info.get("name", "")
            desc = _strip_color_tags(_inline_term_placeholders(talent_info.get("desc", "")))

            mindscape = Mindscape(
                agent_id=agent.id,
                level=level_num,
                name=name[:200],
                description=desc,
            )
            self.session.add(mindscape)

    # -- W-Engines --

    async def import_w_engines(self) -> int:
        """Fetch and upsert W-Engines from the nanoka.cc ``weapon`` index, pruning stale ones."""
        index = await self._fetch_index("weapon")
        source_ids = {int(wid) for wid in index}
        count = 0
        for weapon_id_str in index:
            try:
                detail = await self._fetch_detail("weapon", weapon_id_str)
                engine = await self._import_one_w_engine(detail)
                if engine:
                    count += 1
            except Exception:
                logger.exception("Failed to import weapon %s", weapon_id_str)
        pruned = await self._prune(WEngine, source_ids)
        await self.session.flush()
        logger.info("Imported %d W-Engines, pruned %d stale", count, pruned)
        return count

    async def _import_one_w_engine(self, data: dict) -> WEngine | None:
        hakushin_id = data["id"]
        result = await self.session.execute(
            select(WEngine).where(WEngine.hakushin_id == hakushin_id)
        )
        engine = result.scalar_one_or_none()

        rarity = RARITY_INT_MAP.get(data.get("rarity", 2), RARITY_INT_MAP[2])
        weapon_type = data.get("weapon_type", {})
        specialty_id = _extract_specialty_id(weapon_type)
        specialty = SPECIALTY_ID_MAP.get(specialty_id, SPECIALTY_ID_MAP[1])

        base_prop = data.get("base_property", {})
        base_atk = base_prop.get("value", 0)

        rand_prop = data.get("rand_property", {})
        rand_name = rand_prop.get("name2", rand_prop.get("name", ""))
        secondary_type = RAND_PROPERTY_MAP.get(rand_name, rand_name.lower())
        secondary_value = rand_prop.get("value", 0)

        level_data = data.get("level", {})
        level_scaling = {
            lv: {"rate": info.get("rate", 0), "rate2": info.get("rate2", 0)}
            for lv, info in level_data.items()
        }

        stars = data.get("stars", {})
        star_scaling = {
            lv: {
                "star_rate": info.get("star_rate", 0),
                "rand_rate": info.get("rand_rate", 0),
            }
            for lv, info in stars.items()
        }

        scaling = {"level": level_scaling, "stars": star_scaling}

        talents = data.get("talents", {})
        passive_name = ""
        passive_descs: dict[str, str] = {}
        for rank_str, talent_info in talents.items():
            if not passive_name:
                passive_name = talent_info.get("name", "")
            passive_descs[rank_str] = _strip_color_tags(
                _inline_term_placeholders(talent_info.get("desc", ""))
            )

        fields = {
            "name": data.get("name", "")[:200],
            "rarity": rarity,
            "specialty": specialty,
            "icon_path": data.get("icon", "")[:500],
            "base_atk": base_atk,
            "secondary_stat_type": secondary_type[:30],
            "secondary_stat_value": secondary_value,
            "level_scaling": scaling,
            "passive_name": passive_name[:200],
            "passive_descriptions": passive_descs,
            "description": data.get("desc", "")[:2000],
        }

        if engine:
            for key, value in fields.items():
                setattr(engine, key, value)
        else:
            engine = WEngine(hakushin_id=hakushin_id, **fields)
            self.session.add(engine)
        return engine

    # -- Disc Sets --

    async def import_disc_sets(self) -> int:
        """Fetch and upsert disc sets from the nanoka.cc ``equipment`` index, pruning stale."""
        index = await self._fetch_index("equipment")
        source_ids = {int(eid) for eid in index}
        count = 0
        for equip_id_str in index:
            try:
                detail = await self._fetch_detail("equipment", equip_id_str)
                disc_set = await self._import_one_disc_set(detail)
                if disc_set:
                    count += 1
            except Exception:
                logger.exception("Failed to import equipment %s", equip_id_str)
        pruned = await self._prune(DiscSet, source_ids)
        await self.session.flush()
        logger.info("Imported %d disc sets, pruned %d stale", count, pruned)
        return count

    async def _import_one_disc_set(self, data: dict) -> DiscSet | None:
        hakushin_id = data["id"]
        result = await self.session.execute(
            select(DiscSet).where(DiscSet.hakushin_id == hakushin_id)
        )
        disc_set = result.scalar_one_or_none()

        two_piece_text = _strip_color_tags(_inline_term_placeholders(data.get("desc2", "")))
        four_piece_text = _strip_color_tags(_inline_term_placeholders(data.get("desc4", "")))

        two_piece_effects = _parse_set_bonus(two_piece_text)
        four_piece_effects = _parse_set_bonus(four_piece_text)

        fields = {
            "name": data.get("name", "")[:200],
            "two_piece_text": two_piece_text[:1000],
            "four_piece_text": four_piece_text[:2000],
            "two_piece_effects": two_piece_effects or None,
            "four_piece_effects": four_piece_effects or None,
            "icon_path": data.get("icon", "")[:500],
        }

        if disc_set:
            for key, value in fields.items():
                setattr(disc_set, key, value)
        else:
            disc_set = DiscSet(hakushin_id=hakushin_id, **fields)
            self.session.add(disc_set)
        return disc_set

    # -- Enemies --

    async def import_enemies(self) -> int:
        """Fetch and upsert enemies from the nanoka.cc ``monster`` index, pruning stale ones."""
        index = await self._fetch_index("monster")
        source_ids = {int(mid) for mid in index}
        count = 0
        for monster_id_str in index:
            try:
                detail = await self._fetch_detail("monster", monster_id_str)
                enemy = await self._import_one_enemy(detail)
                if enemy:
                    count += 1
            except Exception:
                logger.exception("Failed to import monster %s", monster_id_str)
        pruned = await self._prune(EnemyProfile, source_ids)
        await self.session.flush()
        logger.info("Imported %d enemies, pruned %d stale", count, pruned)
        return count

    async def _import_one_enemy(self, data: dict) -> EnemyProfile | None:
        hakushin_id = data.get("id")

        # Skip placeholder rows for unreleased / internal monsters — the
        # source data leaks the literal "OfficialName_" string when the
        # display name hasn't been published yet.
        raw_name = data.get("name", "Unknown")
        if not raw_name or raw_name.startswith("OfficialName"):
            return None

        result = await self.session.execute(
            select(EnemyProfile).where(EnemyProfile.hakushin_id == hakushin_id)
        )
        enemy = result.scalar_one_or_none()

        monster_info = data.get("monster_info", {})
        stats: dict = {}
        for minfo in monster_info.values():
            stats = minfo.get("stats", {})
            break

        rarity_val = data.get("rarity", 1)
        tags = data.get("tag", [])
        tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)

        element_abnormal = data.get("element_abnormal", {})

        def _get_capacity(curve_id: int | None) -> int:
            if not curve_id or not element_abnormal:
                return 100
            key = str(curve_id)
            if key in element_abnormal:
                return element_abnormal[key]
            # Fallback: the curve's own prefix (1xxxx/2xxxx/3xxxx) is the gauge
            # tier, independent of monster rarity — reconstruct from the curve
            # itself, never from `rarity_val`.
            tier = curve_id // 10000
            suffix = curve_id % 10000
            fallback_key = str(tier * 10000 + suffix)
            return element_abnormal.get(fallback_key, 100)

        fields = {
            "name": raw_name[:200],
            "level": 60,
            "hp": stats.get("hp", 0),
            "atk": stats.get("attack", 0),
            "defense": stats.get("defence", 50),
            "physical_res": stats.get("physical_damage_res", 0),
            "fire_res": stats.get("fire_damage_res", 0),
            "ice_res": stats.get("ice_damage_res", 0),
            "electric_res": stats.get("electric_damage_res", 0),
            "ether_res": stats.get("ether_damage_res", 0),
            "wind_res": stats.get("wind_damage_res", 0),
            "anomaly_capacity_physical": _get_capacity(stats.get("physical_buildup_curve")),
            "anomaly_capacity_fire": _get_capacity(stats.get("fire_buildup_curve")),
            "anomaly_capacity_ice": _get_capacity(stats.get("ice_buildup_curve")),
            "anomaly_capacity_electric": _get_capacity(stats.get("electric_buildup_curve")),
            "anomaly_capacity_ether": _get_capacity(stats.get("ether_buildup_curve")),
            "anomaly_capacity_wind": _get_capacity(stats.get("wind_buildup_curve")),
            "anomaly_res_physical": stats.get("physical_buildup_res", 0),
            "anomaly_res_fire": stats.get("fire_buildup_res", 0),
            "anomaly_res_ice": stats.get("ice_buildup_res", 0),
            "anomaly_res_electric": stats.get("electric_buildup_res", 0),
            "anomaly_res_ether": stats.get("ether_buildup_res", 0),
            "anomaly_res_wind": stats.get("wind_buildup_res", 0),
            "anomaly_duration_default": 10.0,
            "stun_buildup_multiplier": 10000,
            "stun_threshold": stats.get("stun", 0),
            "stun_dmg_taken_ratio": stats.get("stun_damage_taken_ratio", 5000),
            "rarity": rarity_val if isinstance(rarity_val, int) else 1,
            "tags": tags_str[:500],
        }

        if enemy:
            for key, value in fields.items():
                setattr(enemy, key, value)
        else:
            enemy = EnemyProfile(hakushin_id=hakushin_id, **fields)
            self.session.add(enemy)
        return enemy


# --- Bonus text parser ---

_BONUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"CRIT Rate \+(\d+)%"), "crit_rate"),
    (re.compile(r"CRIT DMG \+(\d+)%"), "crit_dmg"),
    (re.compile(r"ATK \+(\d+)%"), "atk_pct"),
    (re.compile(r"HP \+(\d+)%"), "hp_pct"),
    (re.compile(r"DEF \+(\d+)%"), "def_pct"),
    (re.compile(r"PEN Ratio \+(\d+)%"), "pen_ratio"),
    (re.compile(r"Energy Regen \+(\d+)%"), "energy_regen"),
    (re.compile(r"Anomaly Proficiency \+(\d+)"), "anomaly_proficiency"),
    (re.compile(r"Anomaly Mastery \+(\d+)"), "anomaly_mastery"),
    (re.compile(r"Impact \+(\d+)%"), "impact_pct"),
    (re.compile(r"Physical DMG \+(\d+)%"), "physical_dmg"),
    (re.compile(r"Fire DMG \+(\d+)%"), "fire_dmg"),
    (re.compile(r"Ice DMG \+(\d+)%"), "ice_dmg"),
    (re.compile(r"Electric DMG \+(\d+)%"), "electric_dmg"),
    (re.compile(r"Ether DMG \+(\d+)%"), "ether_dmg"),
]

_PCT_STATS = {
    "crit_rate",
    "crit_dmg",
    "atk_pct",
    "hp_pct",
    "def_pct",
    "pen_ratio",
    "energy_regen",
    "impact_pct",
    "physical_dmg",
    "fire_dmg",
    "ice_dmg",
    "electric_dmg",
    "ether_dmg",
}


def _parse_set_bonus(text: str) -> list[dict]:
    """Parse set bonus description text into structured effects.

    e.g. "CRIT Rate +8%" → [{"stat": "crit_rate", "value": 800, "is_conditional": false}]
    """
    effects: list[dict] = []
    for pattern, stat_name in _BONUS_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_value = int(match.group(1))
            value = raw_value * 100 if stat_name in _PCT_STATS else raw_value
            effects.append(
                {
                    "stat": stat_name,
                    "value": value,
                    "is_conditional": False,
                }
            )

    conditional_keywords = [
        "when",
        "after",
        "upon",
        "during",
        "if",
        "increases by",
        "for 6s",
        "for 8s",
        "for 10s",
        "for 12s",
        "for 15s",
    ]
    has_condition = any(kw in text.lower() for kw in conditional_keywords)
    if has_condition and effects:
        for effect in effects:
            effect["is_conditional"] = True

    return effects
