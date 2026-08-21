"""Backfill blank ``CoreSkill.description`` rows from the zzz-hakushin-data mirror.

nanoka.cc's live API can genuinely serve an empty Core Passive / Additional Ability
description for a very recently released agent — confirmed for Velina (hakushin_id
1561) and Norma (1571), both served as ``desc: ["", ""]`` by
``https://static.nanoka.cc/zzz/.../en/character/<id>.json``. This is not an importer
parsing bug: ``NanokaImporter._import_core_skills`` joins the two halves it is given
with ``" | "``, so a genuinely empty source degenerates to the literal string ``" | "``.

The offline pre-scraped ``zzz-hakushin-data`` mirror
(github.com/Genshin-Optimizer/zzz-hakushin-data) carries the full text for both
agents. This importer runs **after** the primary seed: it finds every ``CoreSkill``
row nanoka left blank, fetches just that agent's file from the mirror, and fills the
text in. It only ever writes into a row that was already blank — never overwrites a
description nanoka did populate.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select

from app.models.agent import Agent, CoreSkill

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RAW_BASE_URL = "https://raw.githubusercontent.com/Genshin-Optimizer/zzz-hakushin-data/master"

_COLOR_TAG_RE = re.compile(r"<color=#[0-9A-Fa-f]+>(.*?)</color>")


def _strip_color_tags(text: str) -> str:
    return _COLOR_TAG_RE.sub(r"\1", text)


def is_blank_core_description(description: str | None) -> bool:
    """True for '', None, or the join-of-nothing artifact ``" | "``, ``"|"``, etc."""
    return not description or not description.replace("|", "").strip()


def parse_passive_descriptions(data: dict[str, Any]) -> dict[int, str]:
    """Extract ``{core_level: joined_description}`` from a hakushin character JSON.

    Mirrors the join logic in ``HakushinJsonImporter._import_core_skills`` /
    ``NanokaImporter._import_core_skills`` exactly, so a patched row is
    indistinguishable from one seeded normally by either importer.
    """
    levels = data.get("Passive", {}).get("Level", {})
    result: dict[int, str] = {}
    for level_info in levels.values():
        level_num = level_info.get("Level", 0)
        descs = level_info.get("Desc", [])
        result[level_num] = _strip_color_tags(" | ".join(descs)) if descs else ""
    return result


class HakushinCoreDescriptionPatchImporter:
    """Fetches zzz-hakushin-data character JSON to backfill blank CoreSkill text."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.session = session
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client, if this instance opened one."""
        if self._client and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def _blank_rows_by_agent(self) -> dict[int, list[CoreSkill]]:
        result = await self.session.execute(
            select(CoreSkill, Agent.hakushin_id).join(Agent, CoreSkill.agent_id == Agent.id)
        )
        blank_by_agent: dict[int, list[CoreSkill]] = {}
        for core_skill, hakushin_id in result.all():
            if hakushin_id is not None and is_blank_core_description(core_skill.description):
                blank_by_agent.setdefault(hakushin_id, []).append(core_skill)
        return blank_by_agent

    async def patch_blank_core_descriptions(self) -> int:
        """Backfill every blank ``CoreSkill.description``. Returns count of rows patched."""
        blank_by_agent = await self._blank_rows_by_agent()
        if not blank_by_agent:
            return 0

        patched = 0
        client = await self._get_client()
        for hakushin_id, core_skills in blank_by_agent.items():
            url = f"{RAW_BASE_URL}/character/{hakushin_id}.json"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError:
                logger.warning(
                    "HakushinCoreDescriptionPatchImporter: fetch failed for "
                    "hakushin_id=%d (%s) — leaving blank",
                    hakushin_id,
                    url,
                )
                continue

            desc_by_level = parse_passive_descriptions(data)
            for core_skill in core_skills:
                replacement = desc_by_level.get(core_skill.level, "")
                if is_blank_core_description(replacement):
                    logger.warning(
                        "HakushinCoreDescriptionPatchImporter: hakushin-data is also "
                        "blank for hakushin_id=%d level=%d — leaving as-is",
                        hakushin_id,
                        core_skill.level,
                    )
                    continue
                core_skill.description = replacement
                patched += 1

        if patched:
            await self.session.flush()
        logger.info(
            "HakushinCoreDescriptionPatchImporter: patched %d blank CoreSkill row(s)", patched
        )
        return patched
