"""Import Genshin game data from the nanoka.cc static API.

nanoka.cc is the successor to hakush.in and republishes the game's own config tables,
one JSON per entity, refreshed each patch. This module is the **transport layer** (D.1):
manifest pin → index fetch → detail fetch → upsert → stale prune. The field mappings that
turn a payload into a `Character`/`Weapon`/`ArtifactSet`/`EnemyProfile` are D.3-D.6 and
live below the transport, each against the committed fixtures in
`tests/fixtures/nanoka_gi/`.

URL grammar, verified live against 7.0.51 on 2026-08-21 (all four entities, 200s):

    manifest   https://static.nanoka.cc/manifest.json                  -> ["gi"]["latest"]
    index      https://static.nanoka.cc/gi/{version}/{entity}.json     -> {id: summary}
    detail     https://static.nanoka.cc/gi/{version}/en/{entity}/{id}.json

It is the ZZZ grammar with `zzz` swapped for `gi`; the `en/` segment is in the detail path
only, and the index is language-free.

**Version is pinned, never floating.** `_resolve_version` reads `gi.latest` once and caches
it, so every fetch in a run comes from one patch. `gi.live` (7.0 at the time of writing)
lags `gi.latest` (7.0.51) and excludes beta content; fairy chose `latest` deliberately so
an upcoming character is importable before release, and D.7 writes the resolved version to
a provenance row so "which patch is this database" stays a query rather than a guess.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from sqlalchemy import delete, select

from app.data.importers.base_importer import BaseImporter
from app.data.importers.nanoka_gi_mappings import (
    character_fields,
    constellation_rows,
    passive_rows,
    talent_rows,
)
from app.models.character import AscensionPassive, Character, Constellation, Talent, TalentScaling

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

BASE_URL = "https://static.nanoka.cc"

#: The four entity indexes this importer consumes, in seed order. Deliberately not every
#: index nanoka publishes: `item`, `gcg`, `furniture` and the rest have no model here.
ENTITIES: tuple[str, ...] = ("character", "weapon", "artifact", "monster")

#: How many detail payloads to fetch concurrently. A full run is ~1,100 detail requests
#: (150 characters, 286 weapons, 65 artifact sets, 585 monsters at 7.0.51); sequentially
#: that is minutes of round-trips. Batched-and-gathered keeps the mapping strictly in index
#: order — results are consumed in the order the ids were requested, not completion order —
#: so a run is reproducible and a failure names the right id.
DETAIL_CONCURRENCY = 8

#: Attempts per request, and the base for exponential backoff between them. Retries cover
#: transport errors and 5xx only: a 404 is a real answer (the index listed an id the detail
#: tree does not serve) and retrying it would just turn a reportable gap into a slow one.
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.5

#: nanoka answers **403 Forbidden** to urllib's default User-Agent — C.2's harvest run hit
#: this and lost a fetch to it (LOG, "Operational note for D.1"). httpx's own default is
#: accepted, but relying on that is relying on a third party's allowlist; sending a header
#: that names the project and how to reach it is both politer and one less thing to
#: rediscover.
USER_AGENT = "mistilteinn/0.1 (+https://github.com/AJTDaedalus/mistilteinn) httpx"


class NanokaTransport(Protocol):
    """How the importer reaches nanoka. A protocol so tests can serve fixtures.

    Every mapping test in D.3-D.6 runs against `FixtureTransport`
    (`tests/unit/nanoka_transport.py`), so no test in this repo touches the network — the
    same rule Chunk E's E.6 makes explicit. Only `scripts/seed_db` builds the HTTP one.
    """

    async def resolve_version(self) -> str:
        """The pinned nanoka version this transport serves."""
        ...

    async def fetch_index(self, entity: str) -> dict[str, Any]:
        """The `{id: summary}` index for one entity."""
        ...

    async def fetch_detail(self, entity: str, entity_id: int | str) -> dict[str, Any]:
        """One entity's full detail payload."""
        ...

    async def close(self) -> None:
        """Release any underlying resources."""
        ...


class HttpNanokaTransport:
    """The live transport: httpx against static.nanoka.cc."""

    def __init__(
        self,
        *,
        version: str | None = None,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._version = version
        self._timeout = timeout
        #: Injectable so the transport tests can drive `httpx.MockTransport` rather than
        #: reaching in and rebinding a private attribute.
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout, headers={"User-Agent": USER_AGENT},
            )
        return self._client

    async def resolve_version(self) -> str:
        """Pin `gi.latest` from the manifest, once per transport."""
        if self._version:
            return self._version
        manifest = await self._get_json(f"{BASE_URL}/manifest.json")
        self._version = str(manifest["gi"]["latest"])
        logger.info("Pinned nanoka GI version %s", self._version)
        return self._version

    async def fetch_index(self, entity: str) -> dict[str, Any]:
        """Fetch one entity index at the pinned version."""
        version = await self.resolve_version()
        return await self._get_json(f"{BASE_URL}/gi/{version}/{entity}.json")

    async def fetch_detail(self, entity: str, entity_id: int | str) -> dict[str, Any]:
        """Fetch one entity's English detail payload at the pinned version."""
        version = await self.resolve_version()
        return await self._get_json(f"{BASE_URL}/gi/{version}/en/{entity}/{entity_id}.json")

    async def _get_json(self, url: str) -> dict[str, Any]:
        client = await self._get_client()
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < httpx.codes.INTERNAL_SERVER_ERROR:
                    raise
                last_error = exc
            except httpx.TransportError as exc:
                last_error = exc
            else:
                return response.json()
            if attempt < MAX_ATTEMPTS:
                delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
                logger.warning(
                    "nanoka %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    url, attempt, MAX_ATTEMPTS, last_error, delay,
                )
                await asyncio.sleep(delay)
        if last_error is None:  # pragma: no cover - the loop cannot exit without one
            msg = f"nanoka {url} exhausted retries without recording an error"
            raise RuntimeError(msg)
        raise last_error

    async def close(self) -> None:
        """Close the httpx client, if one was opened. Safe to call more than once."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


@dataclass
class EntityResult:
    """What one entity pass did, in enough detail for D.8 to assert against.

    `failed` is a list and not a count on purpose: a seed that reports "3 failures" tells
    you to go read the log, and a seed that reports *which* ids failed can be diffed
    between runs. `imported + skipped + len(failed)` equals `total` by construction.
    """

    entity: str
    total: int = 0
    imported: int = 0
    skipped: int = 0
    pruned: int = 0
    failed: list[str] = field(default_factory=list)
    #: Detail payloads pulled by `dry_run` to prove the detail URL grammar. Separate from
    #: `imported` because a dry run writes nothing, and a report reading "1/150 imported"
    #: describes a write that did not happen.
    sampled: int = 0

    @property
    def ok(self) -> bool:
        """True when every id in the index was accounted for without an exception."""
        return not self.failed

    def __str__(self) -> str:
        if self.sampled or not (self.imported or self.skipped or self.pruned):
            return (
                f"{self.entity}: {self.total} in index, {self.sampled} detail(s) sampled, "
                f"{len(self.failed)} failed"
            )
        return (
            f"{self.entity}: {self.imported}/{self.total} imported, "
            f"{self.skipped} skipped, {self.pruned} pruned, {len(self.failed)} failed"
        )


class NanokaImportError(RuntimeError):
    """Raised when an entity pass is asked for before its mapping exists."""


class NanokaGIImporter(BaseImporter):
    """Fetch Genshin data from nanoka.cc and upsert it into the database.

    Transport is injected, so the same class runs live from `scripts/seed_db` and offline
    from the unit tests. `dry_run()` exercises the whole transport — manifest, all four
    indexes, and optionally one detail payload per entity — without opening a write path.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        transport: NanokaTransport | None = None,
        version: str | None = None,
        timeout: float = 30.0,
        concurrency: int = DETAIL_CONCURRENCY,
    ) -> None:
        super().__init__(session)
        self.transport: NanokaTransport = transport or HttpNanokaTransport(
            version=version, timeout=timeout,
        )
        self._concurrency = max(1, concurrency)
        #: One `EntityResult` per completed pass, in the order the passes ran. `seed_db`
        #: (D.7) reports these and exits non-zero if any pass has failures.
        self.results: list[EntityResult] = []

    async def close(self) -> None:
        """Release the transport. Safe to call more than once."""
        await self.transport.close()

    async def version(self) -> str:
        """The pinned version every fetch in this run comes from."""
        return await self.transport.resolve_version()

    # -- Dry run ---------------------------------------------------------------

    async def dry_run(self, *, sample_details: bool = False) -> dict[str, EntityResult]:
        """Fetch every index (and optionally one detail each) and report counts.

        Writes nothing: no session call happens anywhere on this path. `sample_details`
        additionally pulls the first id of each index, which is what proves the *detail*
        grammar rather than just the index grammar — the two differ by the `en/` segment,
        so an index-only dry run would pass against a broken detail URL.
        """
        summaries: dict[str, EntityResult] = {}
        for entity in ENTITIES:
            index = await self.transport.fetch_index(entity)
            result = EntityResult(entity=entity, total=len(index))
            if sample_details and index:
                sample_key = _index_keys(index)[0]
                try:
                    await self.transport.fetch_detail(entity, sample_key)
                except Exception:  # a dry run reports failures, it does not raise them
                    logger.exception("Detail fetch failed for %s %s", entity, sample_key)
                    result.failed.append(sample_key)
                else:
                    result.sampled = 1
            summaries[entity] = result
            logger.info("dry-run %s", result)
        return summaries

    # -- Entity passes ---------------------------------------------------------

    async def import_characters(self) -> int:
        """Upsert every character in the index, with its talents, cons and passives."""
        result = await self._run_pass("character", Character, self._map_character)
        return result.imported

    async def _map_character(self, key: str, payload: dict[str, Any]) -> bool:
        """One character row plus its four child tables. Always writes; never skips."""
        fields = character_fields(key, payload)
        character = await self._get_existing(Character, key)
        if character is None:
            character = Character(**fields)
            self.session.add(character)
        else:
            for column, value in fields.items():
                setattr(character, column, value)
        await self.session.flush()

        # Children are replaced wholesale rather than diffed. A talent's identity is its
        # nanoka id and nothing outside this table references it, so a rebuild is cheaper
        # to reason about than a three-way merge — and it cannot leave an orphan behind
        # when a kit is reworked. The flush in between matters: the unique constraints are
        # on (character_id, nanoka_id), so re-inserting before the DELETE lands would
        # collide with the rows being replaced.
        await self._delete_children(character.id)
        await self.session.flush()

        for row in talent_rows(key, payload):
            scalings = row.pop("scalings")
            talent = Talent(character_id=character.id, **row)
            self.session.add(talent)
            await self.session.flush()
            for scaling in scalings:
                self.session.add(TalentScaling(talent_id=talent.id, **scaling))
        for row in constellation_rows(payload):
            self.session.add(Constellation(character_id=character.id, **row))
        for row in passive_rows(payload):
            self.session.add(AscensionPassive(character_id=character.id, **row))
        return True

    async def _delete_children(self, character_id: str) -> None:
        """Drop a character's talents, constellations and passives.

        `talent_scalings` is not deleted explicitly: its FK is `ON DELETE CASCADE`, and the
        DELETE below is emitted as SQL rather than through the ORM's cascade, so the
        database is what removes them.
        """
        for model in (Talent, Constellation, AscensionPassive):
            await self.session.execute(
                delete(model).where(model.character_id == character_id),
            )

    async def import_weapons(self) -> int:
        """TODO(chunk-D.4): map the weapon detail payload to `Weapon`/`WeaponRefinement`."""
        raise NanokaImportError(_NOT_MAPPED.format(entity="weapon", task="D.4"))

    async def import_artifact_sets(self) -> int:
        """TODO(chunk-D.5): map the artifact detail payload to `ArtifactSet` and affixes."""
        raise NanokaImportError(_NOT_MAPPED.format(entity="artifact", task="D.5"))

    async def import_enemies(self) -> int:
        """TODO(chunk-D.6): map the monster detail payload to `EnemyProfile`."""
        raise NanokaImportError(_NOT_MAPPED.format(entity="monster", task="D.6"))

    # -- Shared machinery the D.3-D.6 mappings run on --------------------------

    async def _run_pass(
        self,
        entity: str,
        model: type,
        mapper: Callable[[str, dict[str, Any]], Awaitable[bool]],
    ) -> EntityResult:
        """Index → details → mapper → prune, recording an `EntityResult`.

        The mapper returns True when it wrote a row and False when it deliberately skipped
        one (a monster with no combat stats, say). An exception from the mapper is caught
        per id — one malformed payload must not abandon the other 584 — but it is recorded
        in `failed`, and D.7 turns a non-empty `failed` into a non-zero exit. Swallowing it
        into a log line is how fairy shipped a silent field-mapping regression.
        """
        index = await self.transport.fetch_index(entity)
        keys = _index_keys(index)
        result = EntityResult(entity=entity, total=len(keys))

        for batch in _batched(keys, self._concurrency):
            payloads = await asyncio.gather(
                *(self.transport.fetch_detail(entity, key) for key in batch),
                return_exceptions=True,
            )
            for key, payload in zip(batch, payloads, strict=True):
                if isinstance(payload, BaseException):
                    logger.error(
                        "Detail fetch failed for %s %s: %s", entity, key, payload,
                    )
                    result.failed.append(key)
                    continue
                try:
                    wrote = await mapper(key, payload)
                except Exception:
                    logger.exception("Failed to map %s %s", entity, key)
                    result.failed.append(key)
                else:
                    if wrote:
                        result.imported += 1
                    else:
                        result.skipped += 1

        result.pruned = await self._prune(model, set(keys))
        await self.session.flush()
        self.results.append(result)
        logger.info("%s", result)
        return result

    async def _prune(self, model: type, source_keys: set[str]) -> int:
        """Delete rows whose `nanoka_id` has left the index.

        Every catalogue model names the column `nanoka_id`, but its *type* differs by
        entity: characters hold the raw string key (`10000005-2`, see `_index_keys`),
        everything else an integer. Comparison is on the string form of the stored value,
        so one code path serves both.

        Rows with a NULL key are untouched: `EnemyProfile` allows hand-authored profiles,
        and pruning those would delete the user's own data on every seed.
        """
        column = model.nanoka_id
        rows = await self.session.execute(select(column).where(column.isnot(None)))
        stored = {row[0] for row in rows.all()}
        stale = {value for value in stored if str(value) not in source_keys}
        if not stale:
            return 0
        await self.session.execute(delete(model).where(column.in_(stale)))
        logger.info(
            "Pruned %d stale %s row(s): nanoka_id=%s",
            len(stale), model.__tablename__, sorted(map(str, stale)),
        )
        return len(stale)

    async def _get_existing(self, model: type, key: int | str) -> Any | None:
        """The existing row for a source key, or None. The upsert half of every mapping.

        `key` must already be the column's type — the string index key for characters, an
        int for everything else. The mapping knows which; this does not guess.
        """
        rows = await self.session.execute(
            select(model).where(model.nanoka_id == key),
        )
        return rows.scalar_one_or_none()


_NOT_MAPPED = (
    "The nanoka GI {entity} mapping is not written yet (task {task}). D.1 landed the "
    "transport layer only; use dry_run() until the mapping lands. This raises rather "
    "than returning 0, because an importer that reports zero rows imported is "
    "indistinguishable from one that found an empty index."
)


def _index_keys(index: dict[str, Any]) -> list[str]:
    """The index's keys, verbatim, in a stable numeric order.

    **Keys are strings, not ints, and that is not pedantry.** 28 of the 150 entries in the
    7.0.51 `character` index are `"{body}-{element}"` — `10000005-2` … `10000005-8` and the
    same for 10000007, 10000117 and 10000118: four Traveler bodies × seven elements, each
    a genuinely different kit. The bare `10000005` is **not** in the index at all. An
    importer that did `int(key)` would raise on the first Traveler, and one that skipped
    unparseable keys would silently drop every Traveler in the game. `weapon`, `artifact`
    and `monster` are all-integer at 7.0.51 — but nothing says they stay that way, and the
    transport does not need to care.

    Sorted numerically by (body, variant) so a run is deterministic and two runs' logs diff
    cleanly. Plain string sort would put `10000101` before `10000005-2`; nanoka's own key
    order is JSON object order, which nothing promises to keep stable across patches.
    """
    return sorted(index, key=_key_sort_order)


def _key_sort_order(key: str) -> tuple[int, int, str]:
    """`(body, variant, raw)` for a nanoka index key. Non-numeric keys sort last, by text."""
    body, _, variant = key.partition("-")
    if not body.isdigit():
        return (2**63, 0, key)
    return (int(body), int(variant) if variant.isdigit() else 0, key)


def _batched(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    """Fixed-size windows over `items`, order preserved.

    `itertools.batched` exists in 3.12 and does the same thing; this is spelled out because
    the *order* guarantee is the point — see `DETAIL_CONCURRENCY`.
    """
    for start in range(0, len(items), size):
        yield items[start : start + size]
