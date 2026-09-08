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
    NanokaMappingError,
    artifact_affix_rows,
    artifact_set_fields,
    character_ascension_cost_rows,
    character_fields,
    constellation_rows,
    enemy_profile_fields,
    is_statless_monster,
    is_weapon_skin,
    material_rows,
    passive_rows,
    refinement_rows,
    talent_cost_rows,
    talent_rows,
    weapon_ascension_cost_rows,
    weapon_fields,
)
from app.models.artifact import ArtifactSet, ArtifactSetAffix
from app.models.build import EnemyProfile
from app.models.character import AscensionPassive, Character, Constellation, Talent, TalentScaling
from app.models.planner import (
    CharacterAscensionCost,
    CharacterTalentCost,
    Material,
    WeaponAscensionCost,
)
from app.models.weapon import Weapon, WeaponRefinement
from app.services.planner.economy import economy

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

BASE_URL = "https://static.nanoka.cc"

#: The four entity indexes this importer consumes, in seed order. Deliberately not every
#: index nanoka publishes: `item`, `gcg`, `furniture` and the rest have no model here.
ENTITIES: tuple[str, ...] = ("character", "weapon", "artifact", "monster")

#: Entities whose unreleased rows are **marked** rather than held out of the database.
#:
#: Artifacts and enemies are not here because nothing prices them: the planner bills a
#: character's ascension, their talents and a weapon's ascension, and an artifact set has no
#: levelling cost to ask about. Adding one would put a datamined name on a page for no gain,
#: which is the trade #271 was about.
_MARKED_NOT_WITHHELD = frozenset({"character", "weapon"})

#: How many detail payloads to fetch concurrently. A full run is ~1,100 detail requests
#: (150 characters, 286 weapons, 65 artifact sets, 585 monsters at 7.0.51); sequentially
#: that is minutes of round-trips. Batched-and-gathered keeps the mapping strictly in index
#: order — results are consumed in the order the ids were requested, not completion order —
#: so a run is reproducible and a failure names the right id.
DETAIL_CONCURRENCY = 8

#: The largest share of an existing table a single prune may delete before it is treated as
#: a bad index rather than as upstream retracting content. nanoka answering `{}` — or a
#: truncated index — with HTTP 200 during a deploy is not something a retry can detect: it is
#: a valid response. Without this rail, one such answer deletes all 150 characters, takes
#: every user's build with them through `builds.character_id ON DELETE CASCADE`, and reports
#: success. Real churn is a handful of retracted beta ids; the threshold is deliberately far
#: above that, because the failure it guards is catastrophic and the false-positive is a
#: re-run with `--force-prune` once someone has looked.
PRUNE_STALE_LIMIT = 0.25

#: …but a prune of at most this many rows is always allowed, whatever share of the table it
#: is. Retracted beta content is a handful of ids, and a fraction alone would block that on
#: any small table while still permitting it on a large one — the wrong way round. A bad
#: index strands the whole table, which is orders of magnitude above this.
PRUNE_STALE_FLOOR = 5

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

    async def fetch_manifest(self) -> dict[str, Any]:
        """The raw manifest, which names the versions and the unreleased ids."""
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
        manifest = await self.fetch_manifest()
        self._version = str(manifest["gi"]["latest"])
        logger.info("Pinned nanoka GI version %s", self._version)
        return self._version

    async def fetch_manifest(self) -> dict[str, Any]:
        """The raw manifest. Fetched even when a version was pinned explicitly, because
        `scripts/capture_nanoka_fixtures` commits this file and has to see the live one."""
        return await self._get_json(f"{BASE_URL}/manifest.json")

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


class PruneGuardError(RuntimeError):
    """Raised when a prune would delete an implausible share of a table."""


@dataclass
class EntityResult:
    """What one entity pass did, in enough detail for D.8 to assert against.

    `failed` is a list and not a count on purpose: a seed that reports "3 failures" tells
    you to go read the log, and a seed that reports *which* ids failed can be diffed
    between runs. `imported + skipped + len(failed) + len(unreleased)` equals `total` by
    construction.
    """

    entity: str
    total: int = 0
    imported: int = 0
    skipped: int = 0
    #: Ids held back because the game has not released them yet, named rather than counted.
    #:
    #: **Owner ruling: beta content must not reach the app.** nanoka's `latest` is a datamine
    #: patch that carries unreleased characters, weapons, sets and enemies; its manifest names
    #: them in `gi.new`, which is exactly `latest - live` (verified against both indexes for
    #: all four entities). Excluded here rather than filtered in the API, so an unreleased row
    #: never reaches the database in the first place.
    unreleased: list[str] = field(default_factory=list)
    #: Ids seeded but **marked** rather than held back — characters only.
    #:
    #: The ruling above still stands for weapons, artifacts and enemies. The owner reopened it
    #: for characters on 2026-09-07 so `/planner` can price an upcoming one, and a marked row
    #: is a different thing from an absent one: `CharacterRepository.list` hides these unless a
    #: caller opts in, so nothing that did not ask sees them.
    beta: list[str] = field(default_factory=list)
    pruned: int = 0
    failed: list[str] = field(default_factory=list)
    #: Detail payloads pulled by `dry_run` to prove the detail URL grammar. Separate from
    #: `imported` because a dry run writes nothing, and a report reading "1/150 imported"
    #: describes a write that did not happen.
    sampled: int = 0
    #: Set when the prune guard refused to delete; the rows are still there and the run is
    #: not allowed to report success.
    prune_blocked: str | None = None

    @property
    def ok(self) -> bool:
        """True when every id was accounted for and nothing was refused."""
        return not self.failed and self.prune_blocked is None

    def __str__(self) -> str:
        if self.prune_blocked:
            return (
                f"{self.entity}: {self.imported}/{self.total} imported, "
                f"{self.skipped} skipped, PRUNE REFUSED ({self.prune_blocked}), "
                f"{len(self.failed)} failed"
            )
        if self.sampled or not (self.imported or self.skipped or self.pruned):
            return (
                f"{self.entity}: {self.total} in index, {self.sampled} detail(s) sampled, "
                f"{len(self.failed)} failed"
            )
        # Reported, never silent: a seed that quietly drops rows is indistinguishable from one
        # whose upstream lost them, and this one drops rows *on purpose*.
        held = f", {len(self.unreleased)} unreleased" if self.unreleased else ""
        beta = f", {len(self.beta)} beta" if self.beta else ""
        return (
            f"{self.entity}: {self.imported}/{self.total} imported, "
            f"{self.skipped} skipped, {self.pruned} pruned, "
            f"{len(self.failed)} failed{held}{beta}"
        )


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
        force_prune: bool = False,
    ) -> None:
        super().__init__(session)
        self._force_prune = force_prune
        self.transport: NanokaTransport = transport or HttpNanokaTransport(
            version=version, timeout=timeout,
        )
        #: `{entity: unreleased ids}`, read from the manifest once per run.
        self._unreleased_ids: dict[str, frozenset[str]] | None = None
        #: Index keys of the current pass that are beta. Only ever non-empty for characters.
        self._beta_keys: set[str] = set()
        self._concurrency = max(1, concurrency)
        #: One `EntityResult` per completed pass, in the order the passes ran. `seed_db`
        #: (D.7) reports these and exits non-zero if any pass has failures.
        self.results: list[EntityResult] = []
        #: The six EXP denominations are created once per run rather than per character —
        #: they are the same six for everybody and no bill names them.
        self._exp_materials_written = False

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
        # **Set from the manifest, every run, in both branches.** An upsert that only set this
        # on insert would leave a character marked beta forever after it shipped — the flag has
        # to be able to go false again, and release is exactly when it should.
        fields["is_beta"] = key in self._beta_keys
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

        await self._ensure_exp_materials()
        await self._write_materials(payload)
        for row in character_ascension_cost_rows(payload):
            self.session.add(CharacterAscensionCost(character_id=character.id, **row))
        # The talent's own row is looked up by `nanoka_id` rather than reusing the loop
        # above, because a talent with no cost levels — an alternate sprint — contributes
        # no rows and would desynchronise a parallel walk.
        await self.session.flush()
        talent_ids = dict(
            (
                await self.session.execute(
                    select(Talent.nanoka_id, Talent.id).where(
                        Talent.character_id == character.id,
                    ),
                )
            ).all(),
        )
        for row in talent_cost_rows(key, payload):
            talent_id = talent_ids.get(row["nanoka_id"])
            if talent_id is None:
                msg = f"character {key}: talent cost names unknown skill {row['nanoka_id']}"
                raise NanokaMappingError(msg)
            self.session.add(
                CharacterTalentCost(
                    character_id=character.id,
                    talent_id=talent_id,
                    level=row["level"],
                    mora=row["mora"],
                    items=row["items"],
                ),
            )
        return True

    async def _ensure_exp_materials(self) -> None:
        """Create the six EXP denominations, which no bill names.

        Hero's Wit and Mystic Enhancement Ore are spent through `level_exp` and
        `xp_requirements`, never listed as materials, so `_write_materials` never meets them.
        Without these rows a GOOD export's `HerosWit: 204` binds to nothing and the planner
        prices the levelling as though the user held none — a wrong answer that looks exactly
        like a right one.
        """
        if self._exp_materials_written:
            return
        eco = economy()
        wanted = eco.exp_material_ids()
        existing = set(
            (
                await self.session.execute(
                    select(Material.id).where(Material.id.in_(wanted)),
                )
            )
            .scalars()
            .all(),
        )
        for material_id in wanted:
            if material_id in existing:
                continue
            name = eco.name(material_id)
            if not name:
                msg = f"EXP material {material_id} has no name in the snapshot"
                raise NanokaMappingError(msg)
            self.session.add(
                Material(
                    id=material_id,
                    name=name,
                    rarity=eco.rarity(material_id) or 0,
                    icon=eco.icon(material_id),
                ),
            )
        await self.session.flush()
        self._exp_materials_written = True

    async def _write_materials(self, payload: dict[str, Any]) -> None:
        """Upsert every material this payload names.

        Materials are shared across the whole catalogue, so they are upserted rather than
        rebuilt — a character's import must not delete a material a weapon still bills for.
        `icon` comes from the committed snapshot and is left null when the snapshot does not
        carry the material, because that is a *seeding* gap and hiding it here would paper
        over the importer, exactly as `download_icons.py` refuses to.
        """
        eco = economy()
        seen = material_rows(payload)
        if not seen:
            return
        existing = {
            row.id: row
            for row in (
                await self.session.execute(
                    select(Material).where(Material.id.in_(seen.keys())),
                )
            ).scalars()
        }
        for material_id, fields in seen.items():
            row = existing.get(material_id)
            if row is None:
                self.session.add(
                    Material(
                        id=material_id,
                        name=fields["name"],
                        rarity=fields["rarity"],
                        icon=eco.icon(material_id),
                    ),
                )
            else:
                row.name = fields["name"]
                row.rarity = fields["rarity"]
                row.icon = eco.icon(material_id)

    async def _delete_children(self, character_id: str) -> None:
        """Drop a character's talents, constellations and passives.

        `talent_scalings` is not deleted explicitly: its FK is `ON DELETE CASCADE`, and the
        DELETE below is emitted as SQL rather than through the ORM's cascade, so the
        database is what removes them.
        """
        for model in (
            Talent,
            Constellation,
            AscensionPassive,
            CharacterAscensionCost,
            CharacterTalentCost,
        ):
            await self.session.execute(
                delete(model).where(model.character_id == character_id),
            )

    async def import_weapons(self) -> int:
        """Upsert every weapon in the index with its refinement ladder, skipping skins."""
        result = await self._run_pass("weapon", Weapon, self._map_weapon)
        return result.imported

    async def _map_weapon(self, key: str, payload: dict[str, Any]) -> bool:
        """One weapon row plus its refinements, or a skip for a cosmetic skin."""
        if is_weapon_skin(payload):
            logger.debug("Skipping weapon skin %s (%s)", key, payload.get("name"))
            await self._delete_existing(Weapon, int(key))
            return False

        fields = weapon_fields(key, payload)
        # Set every run and in both branches, so a weapon stops being beta when it ships.
        # `_map_character` carries the same line and the same reason.
        fields["is_beta"] = key in self._beta_keys
        weapon = await self._get_existing(Weapon, int(key))
        if weapon is None:
            weapon = Weapon(**fields)
            self.session.add(weapon)
        else:
            for column, value in fields.items():
                setattr(weapon, column, value)
        await self.session.flush()

        # Rebuilt rather than diffed, and flushed in between, for the same reason as the
        # character children: the unique constraint is on (weapon_id, level).
        await self.session.execute(
            delete(WeaponRefinement).where(WeaponRefinement.weapon_id == weapon.id),
        )
        await self.session.flush()
        await self.session.execute(
            delete(WeaponAscensionCost).where(WeaponAscensionCost.weapon_id == weapon.id),
        )
        await self.session.flush()
        for row in refinement_rows(payload):
            self.session.add(WeaponRefinement(weapon_id=weapon.id, **row))
        await self._write_materials(payload)
        for row in weapon_ascension_cost_rows(payload):
            self.session.add(WeaponAscensionCost(weapon_id=weapon.id, **row))
        return True

    async def import_artifact_sets(self) -> int:
        """Upsert every artifact set in the index with its bonus affixes."""
        result = await self._run_pass("artifact", ArtifactSet, self._map_artifact_set)
        return result.imported

    async def _map_artifact_set(self, key: str, payload: dict[str, Any]) -> bool:
        """One set row plus its affix rows."""
        fields = artifact_set_fields(key, payload)
        artifact_set = await self._get_existing(ArtifactSet, int(key))
        if artifact_set is None:
            artifact_set = ArtifactSet(**fields)
            self.session.add(artifact_set)
        else:
            for column, value in fields.items():
                setattr(artifact_set, column, value)
        await self.session.flush()

        # Rebuilt, flushed in between: the unique constraint is on (artifact_set_id,
        # position), so a re-insert before the DELETE lands would collide.
        await self.session.execute(
            delete(ArtifactSetAffix).where(
                ArtifactSetAffix.artifact_set_id == artifact_set.id,
            ),
        )
        await self.session.flush()
        for row in artifact_affix_rows(key, payload):
            self.session.add(ArtifactSetAffix(artifact_set_id=artifact_set.id, **row))
        return True

    async def import_enemies(self) -> int:
        """Upsert one enemy profile per monster family, skipping the stat-less codex ones."""
        result = await self._run_pass("monster", EnemyProfile, self._map_enemy)
        return result.imported

    async def _map_enemy(self, key: str, payload: dict[str, Any]) -> bool:
        """One profile row, or a skip for a codex entry with no combat stats."""
        if is_statless_monster(payload):
            logger.debug("Skipping stat-less monster %s (%s)", key, payload.get("name"))
            await self._delete_existing(EnemyProfile, int(key))
            return False

        fields = enemy_profile_fields(key, payload)
        profile = await self._get_existing(EnemyProfile, int(key))
        if profile is None:
            profile = EnemyProfile(**fields)
            self.session.add(profile)
        else:
            for column, value in fields.items():
                setattr(profile, column, value)
        await self.session.flush()
        return True

    # -- Shared machinery the D.3-D.6 mappings run on --------------------------

    async def _unreleased(self, entity: str) -> frozenset[str]:
        """The ids of `entity` the game has not released, from the manifest's `gi.new`.

        Cached per run: one manifest fetch serves all four passes.

        **Version-independent, deliberately.** `gi.new` is `latest - live`, so it names what is
        unreleased *now* rather than what is new in the pinned patch. An id in it is unreleased
        whichever version is being seeded, which is why `--version 7.0.51` gets the same
        exclusions as an unpinned run.

        A manifest without `gi.new` yields nothing held back, which is the pre-existing
        behaviour rather than a silent empty seed.
        """
        if self._unreleased_ids is None:
            manifest = await self.transport.fetch_manifest()
            new = manifest.get("gi", {}).get("new", {}) or {}
            self._unreleased_ids = {
                name: frozenset(str(i) for i in (ids or []))
                for name, ids in new.items()
            }
        return self._unreleased_ids.get(entity, frozenset())

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

        Each item runs inside a **savepoint**, so a failure rolls back that item's partial
        writes and nothing else. The alternative is worse in both directions: without one, a
        database-level failure poisons the transaction and takes the rest of the pass with
        it; with a full rollback, a failure at item 900 discards 899 good rows.
        """
        index = await self.transport.fetch_index(entity)
        keys = _index_keys(index)
        held = await self._unreleased(entity)
        # **Marked, not withheld** for the entities the planner prices. Owner, 2026-09-07: an
        # upcoming character and their weapon are one decision, and pricing half of it is not
        # much use. The mapper reads this set and sets `is_beta`; the repositories hide those
        # rows from every caller that does not ask, so neither can reach a build and therefore
        # neither can reach the optimizer.
        #
        # **The picker is the line, not the database.** #271 was a report about a beta weapon
        # name on a public page, and that is still honoured: what changed is where the rule
        # lives. Hiding at read time keeps the row available to the one surface that was
        # granted it, where hiding at import time made it available to nothing.
        marking = entity in _MARKED_NOT_WITHHELD
        self._beta_keys = {key for key in keys if _base_id(key) in held} if marking else set()
        kept = keys if marking else [key for key in keys if _base_id(key) not in held]
        # **`total` stays the whole index**, and the held-back ids are counted beside it. It
        # is what `verify_seed` compares against the committed index to detect "the database
        # is from a different patch" — a detector that a deliberate exclusion must not trip,
        # or every seed would report drift that is not there.
        result = EntityResult(
            entity=entity,
            total=len(keys),
            unreleased=sorted(set(keys) - set(kept)),
            beta=sorted(self._beta_keys),
        )
        keys = kept

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
                    # Each item maps inside a SAVEPOINT. Without one, a mapper that fails
                    # *at the database* — an IntegrityError on flush, say — leaves the
                    # transaction poisoned, and every remaining item in the pass then fails
                    # too: one bad payload would be reported as 149 broken characters.
                    async with self.session.begin_nested():
                        wrote = await mapper(key, payload)
                except Exception:
                    logger.exception("Failed to map %s %s", entity, key)
                    result.failed.append(key)
                else:
                    if wrote:
                        result.imported += 1
                    else:
                        result.skipped += 1

        try:
            result.pruned = await self._prune(model, set(keys))
        except PruneGuardError as exc:
            # Reported, not raised: the rows that *were* imported are good, and the run
            # exits non-zero on `prune_blocked` anyway.
            logger.error("Prune refused for %s: %s", entity, exc)  # noqa: TRY400
            result.prune_blocked = str(exc)
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

        **Raises `PruneGuardError` rather than deleting an implausible share of the
        table** — see `PRUNE_STALE_LIMIT`. `force` overrides it for the case where a patch
        really did retract that much and a human has looked at the numbers.
        """
        column = model.nanoka_id
        rows = await self.session.execute(select(column).where(column.isnot(None)))
        stored = {row[0] for row in rows.all()}
        stale = {value for value in stored if str(value) not in source_keys}
        if not stale:
            return 0
        share = len(stale) / len(stored)
        guard_tripped = len(stale) > PRUNE_STALE_FLOOR and share > PRUNE_STALE_LIMIT
        if guard_tripped and not self._force_prune:
            msg = (
                f"{len(stale)} of {len(stored)} {model.__tablename__} rows "
                f"({share:.0%}) are missing from an index of {len(source_keys)} entries. "
                f"That is more likely a bad index than upstream retracting content, so "
                f"nothing was deleted. Re-run with force_prune=True if it is real."
            )
            raise PruneGuardError(msg)
        await self.session.execute(delete(model).where(column.in_(stale)))
        logger.info(
            "Pruned %d stale %s row(s): nanoka_id=%s",
            len(stale), model.__tablename__, sorted(map(str, stale)),
        )
        return len(stale)

    async def _delete_existing(self, model: type, key: int | str) -> None:
        """Remove the row for `key`, if there is one.

        Called when a mapper *skips* an entity. Without it, an entity that upstream
        reclassifies — a weapon that becomes a skin, a monster that loses its `child` map —
        keeps its old row forever: the upsert never runs for it, and prune never sees it as
        stale because its id is still in the index.
        """
        await self.session.execute(
            delete(model).where(model.nanoka_id == key),
        )
        await self.session.flush()

    async def _get_existing(self, model: type, key: int | str) -> Any | None:
        """The existing row for a source key, or None. The upsert half of every mapping.

        `key` must already be the column's type — the string index key for characters, an
        int for everything else. The mapping knows which; this does not guess.
        """
        rows = await self.session.execute(
            select(model).where(model.nanoka_id == key),
        )
        return rows.scalar_one_or_none()



def _base_id(key: str) -> str:
    """The entity id in an index key, without a Traveler's element suffix.

    `10000005-2` is the Anemo Traveler and its base id is `10000005`. The manifest names
    unreleased content by bare id, so a Traveler body held back upstream has to match all
    seven of its variant keys rather than none of them.
    """
    return key.split("-", 1)[0]


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
