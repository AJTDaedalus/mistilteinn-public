"""Backfill blank ``Mindscape.description`` rows from the zzz-hakushin-data mirror.

Same gap as ``hakushin_core_description_patch_importer`` (Task 23), one level down:
nanoka.cc's live API can serve an empty Mindscape ``desc`` for a very recently
released agent — confirmed for Velina M1 (hakushin_id 1561) and Norma M1/M6
(1571). Unlike Core Passive / Additional Ability, ``NanokaImporter._import_mindscapes``
writes nanoka's single ``desc`` field straight through with no join, so the blank
artifact here is a genuinely empty (or whitespace-only) string, not a
``" | "``-join byproduct.

The offline pre-scraped ``zzz-hakushin-data`` mirror carries the full Mindscape text
for both agents, keyed by the same 1-6 Mindscape level nanoka uses (no offset, unlike
the Core Passive tier — verified against both agents' M1/M6 names matching directly).
This importer runs after the primary seed: it finds every ``Mindscape`` row nanoka
left blank, fetches just that agent's file from the mirror, and fills the text in. It
only ever writes into a row that was already blank — never overwrites a description
nanoka did populate.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select

from app.models.agent import Agent, Mindscape

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RAW_BASE_URL = "https://raw.githubusercontent.com/Genshin-Optimizer/zzz-hakushin-data/master"

_COLOR_TAG_RE = re.compile(r"<color=#[0-9A-Fa-f]+>(.*?)</color>")


def _strip_color_tags(text: str) -> str:
    return _COLOR_TAG_RE.sub(r"\1", text)


def is_blank_mindscape_description(description: str | None) -> bool:
    """True for ``None``, ``""``, or a whitespace-only string."""
    return not description or not description.strip()


def parse_mindscape_descriptions(data: dict[str, Any]) -> dict[int, str]:
    """Extract ``{mindscape_level: description}`` from a hakushin character JSON."""
    talents = data.get("Talent", {})
    result: dict[int, str] = {}
    for talent_info in talents.values():
        level_num = talent_info.get("Level", 0)
        desc = talent_info.get("Desc", "")
        result[level_num] = _strip_color_tags(desc) if desc else ""
    return result


class HakushinMindscapeDescriptionPatchImporter:
    """Fetches zzz-hakushin-data character JSON to backfill blank Mindscape text."""

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

    async def _blank_rows_by_agent(self) -> dict[int, list[Mindscape]]:
        result = await self.session.execute(
            select(Mindscape, Agent.hakushin_id).join(Agent, Mindscape.agent_id == Agent.id)
        )
        blank_by_agent: dict[int, list[Mindscape]] = {}
        for mindscape, hakushin_id in result.all():
            if hakushin_id is not None and is_blank_mindscape_description(mindscape.description):
                blank_by_agent.setdefault(hakushin_id, []).append(mindscape)
        return blank_by_agent

    async def patch_blank_mindscape_descriptions(self) -> int:
        """Backfill every blank ``Mindscape.description``. Returns count of rows patched."""
        blank_by_agent = await self._blank_rows_by_agent()
        if not blank_by_agent:
            return 0

        patched = 0
        client = await self._get_client()
        for hakushin_id, mindscapes in blank_by_agent.items():
            url = f"{RAW_BASE_URL}/character/{hakushin_id}.json"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError:
                logger.warning(
                    "HakushinMindscapeDescriptionPatchImporter: fetch failed for "
                    "hakushin_id=%d (%s) — leaving blank",
                    hakushin_id,
                    url,
                )
                continue

            desc_by_level = parse_mindscape_descriptions(data)
            for mindscape in mindscapes:
                replacement = desc_by_level.get(mindscape.level, "")
                if is_blank_mindscape_description(replacement):
                    logger.warning(
                        "HakushinMindscapeDescriptionPatchImporter: hakushin-data is also "
                        "blank for hakushin_id=%d level=%d — leaving as-is",
                        hakushin_id,
                        mindscape.level,
                    )
                    continue
                mindscape.description = replacement
                patched += 1

        if patched:
            await self.session.flush()
        logger.info(
            "HakushinMindscapeDescriptionPatchImporter: patched %d blank Mindscape row(s)",
            patched,
        )
        return patched
