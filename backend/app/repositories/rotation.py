"""Data access for user-authored rotations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from app.models.base import generate_uuid7
from app.models.build import Build
from app.models.character import Character
from app.models.enums import Visibility
from app.models.rotation import Rotation, RotationCharacter, RotationLike
from app.models.team import Team
from app.repositories.base import BaseRepository
from app.schemas.team import TEAM_SLOTS

if TYPE_CHECKING:
    from collections.abc import Sequence



class RotationStaleError(RuntimeError):
    """A rotation names characters its team no longer has.

    Raised rather than repaired. The alternatives are to drop the offending steps — deleting
    a user's authored work so an operation can succeed — or to reinterpret them against
    whoever now occupies the position, which is the silent-wrong-answer this repo refuses
    everywhere else. Saying no, and naming exactly which steps, leaves the user in control of
    their own rotation.
    """


class DuplicateTeamMemberError(RuntimeError):
    """A team row holds two builds of one character — impossible through the API (T.1a)."""


class RotationRepository(BaseRepository[Rotation]):
    """Sole data-access point for rotations."""

    model = Rotation

    def _for_team(self, team_id: str) -> Select[tuple[Rotation]]:
        """The one WHERE both the page and its count are built from.

        Two hand-written filters would be two chances to forget the owner scope, and the
        half that forgot it would be the one reporting `total` — the exact shape the base
        repository's unscoped `count` had before the Chunk A+B review.
        """
        stmt = select(Rotation).where(Rotation.team_id == team_id)
        if self.owner_id is not None:
            stmt = stmt.where(Rotation.owner_id == self.owner_id)
        return stmt

    # ---- the character index (L.3) --------------------------------------

    @staticmethod
    def _characters_in(steps: object) -> set[str]:
        """The nanoka ids a step list names, deduplicated.

        Tolerant of a malformed step rather than raising: the write path validates steps
        against the team before this runs, and an index that refused to build would turn a
        validation bug into a failed save. A step with no `character` simply indexes nothing.
        """
        found: set[str] = set()
        for step in steps if isinstance(steps, list) else []:
            if isinstance(step, dict):
                character = step.get("character")
                if isinstance(character, str) and character:
                    found.add(character)
        return found

    async def _reindex(self, rotation: Rotation) -> None:
        """Rebuild `rotation_characters` for one rotation, wholesale.

        **Never diffed.** The steps are read and written whole for the reason the JSONB column
        gives, and a diff would be a second implementation of "what characters does this
        rotation name". The two would eventually disagree, and the library would then offer a
        rotation for a team it cannot run on — which reads as a bug in the search rather than
        in a stale index.
        """
        await self.session.execute(
            delete(RotationCharacter).where(RotationCharacter.rotation_id == rotation.id),
        )
        for nanoka_id in sorted(self._characters_in(rotation.steps)):
            self.session.add(
                RotationCharacter(rotation_id=rotation.id, nanoka_id=nanoka_id),
            )
        await self.session.flush()

    async def create(self, data: dict[str, object]) -> Rotation:
        """Insert, then index. Overridden so no caller can save without indexing."""
        rotation = await super().create(data)
        await self._reindex(rotation)
        return rotation

    async def update(self, entity_id: str, data: dict[str, object]) -> Rotation | None:
        """Patch, then re-index — including when `steps` was not among the fields patched.

        Re-indexing unconditionally costs one delete and a handful of inserts on a rename, and
        buys the guarantee that the index cannot be stale. A conditional would be correct until
        someone adds a second way to change the steps.
        """
        rotation = await super().update(entity_id, data)
        if rotation is not None:
            await self._reindex(rotation)
        return rotation

    async def list_for_team(
        self, team_id: str, *, offset: int = 0, limit: int = 50,
    ) -> Sequence[Rotation]:
        """One page of the rotations saved against a team, newest first."""
        stmt = self._for_team(team_id).order_by(Rotation.created_at.desc())
        return (await self.session.execute(stmt.offset(offset).limit(limit))).scalars().all()

    async def count_for_team(self, team_id: str) -> int:
        """How many there are in total, so the page envelope is not guesswork."""
        stmt = select(func.count()).select_from(self._for_team(team_id).subquery())
        return int((await self.session.execute(stmt)).scalar_one())

    async def team_characters(self, team_id: str) -> set[str]:
        """The nanoka ids of every character on a team — for validating steps on write."""
        return set(await self.character_rows(team_id))

    def _teams(self, *, with_talents: bool = False) -> Select[tuple[Team]]:
        """Teams, owner-scoped, eager-loaded down to each build's character.

        Eager, because a lazy hop here is a `MissingGreenlet` inside a request — the shape
        Chunk G met three times before `lazy="raise_on_sql"` made it loud.

        `with_talents` reaches one level further, to each character's talent rows. **Off by
        default and on only for `/options`**, which is the one caller that publishes ability
        names: the compiler and the library need a character's key, not what their burst is
        called, and loading three talent rows per member on every library listing would be
        payload nobody reads.
        """
        stmt = select(Team)
        if self.owner_id is not None:
            stmt = stmt.where(Team.owner_id == self.owner_id)
        return stmt.options(
            *(
                (
                    selectinload(getattr(Team, name.removesuffix("_id")))
                    .selectinload(Build.character)
                    .selectinload(Character.talents)
                )
                if with_talents
                else selectinload(getattr(Team, name.removesuffix("_id"))).selectinload(
                    Build.character,
                )
                for name in TEAM_SLOTS
            ),
        )

    @staticmethod
    def _roster(team: Team) -> dict[str, Character]:
        """`nanoka_id -> Character` for one already-loaded team.

        **Refuses a team holding one character twice rather than collapsing it.** Keying by
        `nanoka_id` means a duplicate would silently become a single entry, and a four-build
        team would compile a rotation against three characters — a wrong answer that looks
        like a right one, with nothing anywhere reporting a problem.

        `app/api/v1/teams.py` refuses such a team on write, so this is not reachable through
        the API (T.1a). It stays because the rule lives in the application and not in the
        schema: a row written by a script, a fixture or a future code path would arrive here
        with no other check in its way.
        """
        found: dict[str, Character] = {}
        for slot in TEAM_SLOTS:
            build = getattr(team, slot.removesuffix("_id"))
            if build is None or build.character is None:
                continue
            nanoka_id = str(build.character.nanoka_id)
            if nanoka_id in found:
                msg = (
                    f"team {team.id} holds {build.character.name} twice. A party cannot "
                    f"field the same character twice — gcsim refuses one outright — and "
                    f"keying the roster by character would have hidden the duplicate rather "
                    f"than reported it."
                )
                raise DuplicateTeamMemberError(msg)
            found[nanoka_id] = build.character
        return found

    async def character_rows(self, team_id: str) -> dict[str, Character]:
        """`nanoka_id -> Character` for every build on a team.

        Rows rather than ids, because the compiler needs a character's name and element to
        reach its gcsim key. `team_characters` derives its set from this, so the two cannot
        disagree about who is on a team — which they would if each ran its own query and one
        forgot a slot.
        """
        team = (
            await self.session.execute(self._teams().where(Team.id == team_id))
        ).scalar_one_or_none()
        return {} if team is None else self._roster(team)

    async def rosters_for(self, team_ids: Sequence[str]) -> dict[str, dict[str, Character]]:
        """`team_id -> {nanoka_id: Character}` for several teams, in **one** query.

        The batched form of `character_rows`, and it exists because the single form was called
        in a loop over a page of rotations — a genuine N+1 that
        `tests/integration/test_rotation_library_query_count.py` caught on its first honest
        run, having passed while it was silently counting the wrong engine.

        Owner-scoped through `_teams()`, so a team the caller does not own is simply absent
        rather than raising. That is what makes a shared rotation report no DPS of yours.
        """
        if not team_ids:
            return {}
        teams = (
            await self.session.execute(self._teams().where(Team.id.in_(list(team_ids))))
        ).scalars().all()
        return {str(team.id): self._roster(team) for team in teams}

    async def team_build_ids(self, team_id: str) -> list[str]:
        """Every build id on a team, in slot order.

        Ids rather than rows: a calibration needs each teammate's **weapon and artifacts**,
        which `_teams()` does not eager-load, so the caller re-reads them through
        `BuildRepository`. Returning half-loaded rows here would be the `MissingGreenlet`
        shape the eager-loading comment above is about.
        """
        team = (
            await self.session.execute(self._teams().where(Team.id == team_id))
        ).scalar_one_or_none()
        if team is None:
            return []
        return [
            str(getattr(team, name))
            for name in TEAM_SLOTS
            if getattr(team, name) is not None
        ]

    async def rosters(
        self, *, with_talents: bool = False,
    ) -> list[tuple[Team, dict[str, Character]]]:
        """Every team the caller owns, with who is on it.

        This is what the editor offers as step options, and it comes through `_roster` —
        the same extraction the write path validates against. Two implementations would
        eventually offer a character the validator then refused, and the user would be told
        their own selection was invalid.

        `with_talents` reaches one level further so the editor can label an action with the
        character's own name for it — see `_teams`.
        """
        teams = (
            (await self.session.execute(
                self._teams(with_talents=with_talents).order_by(Team.created_at.desc()),
            ))
            .scalars()
            .unique()
            .all()
        )
        return [(team, self._roster(team)) for team in teams]


class RotationLibraryRepository(BaseRepository[Rotation]):
    """Reads across **every** user's published rotations, and only those.

    ## Why this is a second repository

    `RotationRepository` is owner-scoped, and that scope is load-bearing: it is what stops one
    user reading another's rotations. Adding a "sometimes ignore the owner" mode to it would
    put the check and its exception in the same object, and the exception would eventually win
    an argument it should not be in.

    So the scope here is `visibility == published` instead, applied in **one** place for the
    same reason `_for_team` exists — two hand-written filters are two chances to forget one,
    and the half that forgot would be the one reporting `total`.
    """

    model = Rotation

    def _published(self) -> Select[tuple[Rotation]]:
        """The only WHERE in this class. Everything else narrows this."""
        return select(Rotation).where(Rotation.visibility == Visibility.PUBLISHED)

    def _filtered(
        self, *, characters: Sequence[str] = (), query: str = "",
    ) -> Select[tuple[Rotation]]:
        stmt = self._published()
        if query:
            stmt = stmt.where(Rotation.name.ilike(f"%{query}%"))
        if characters:
            wanted = sorted(set(characters))
            # **Exactly this set**, not a superset. `DESIGN_rotation_library.md` §3 calls the
            # character filter "a filter that claims nothing", and that is only true if it
            # means what it says: a four-character rotation surfacing for a three-character
            # query would be a recommendation wearing a filter's clothes.
            #
            # Two conditions, because either alone is wrong: the first says every wanted
            # character is present, the second that nothing else is.
            has_all = (
                select(func.count(func.distinct(RotationCharacter.nanoka_id)))
                .where(RotationCharacter.rotation_id == Rotation.id)
                .where(RotationCharacter.nanoka_id.in_(wanted))
                .scalar_subquery()
            )
            has_total = (
                select(func.count(func.distinct(RotationCharacter.nanoka_id)))
                .where(RotationCharacter.rotation_id == Rotation.id)
                .scalar_subquery()
            )
            stmt = stmt.where(has_all == len(wanted), has_total == len(wanted))
        return stmt

    async def search(
        self,
        *,
        characters: Sequence[str] = (),
        query: str = "",
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[Rotation]:
        """One page of published rotations, newest first.

        **Not sorted by DPS or likes here.** Both are per-caller facts assembled above this
        layer, and ordering by a subquery the caller may not even have a row for would be a
        ranking dressed as a query.
        """
        stmt = (
            self._filtered(characters=characters, query=query)
            .order_by(Rotation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def count(
        self, *, characters: Sequence[str] = (), query: str = "",
    ) -> int:  # type: ignore[override]
        """How many match — from the same WHERE the page is built from."""
        stmt = select(func.count()).select_from(
            self._filtered(characters=characters, query=query).subquery(),
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def characters_for(self, rotation_ids: Sequence[str]) -> dict[str, list[str]]:
        """The character set of each rotation, in **one** query.

        A query per row is the shape that turns a twenty-row page into twenty-one round trips
        and looks fine until the page grows.
        """
        if not rotation_ids:
            return {}
        rows = await self.session.execute(
            select(RotationCharacter.rotation_id, RotationCharacter.nanoka_id)
            .where(RotationCharacter.rotation_id.in_(list(rotation_ids)))
            .order_by(RotationCharacter.nanoka_id),
        )
        found: dict[str, list[str]] = {rid: [] for rid in rotation_ids}
        for rotation_id, nanoka_id in rows.all():
            found[rotation_id].append(nanoka_id)
        return found

    async def like_counts(self, rotation_ids: Sequence[str]) -> dict[str, int]:
        """Likes per rotation, in one aggregate rather than one query per row (L.7)."""
        if not rotation_ids:
            return {}
        rows = await self.session.execute(
            select(RotationLike.rotation_id, func.count())
            .where(RotationLike.rotation_id.in_(list(rotation_ids)))
            .group_by(RotationLike.rotation_id),
        )
        counts = dict(rows.all())
        return {rid: int(counts.get(rid, 0)) for rid in rotation_ids}

    async def liked_by(self, user_id: str, rotation_ids: Sequence[str]) -> set[str]:
        """Which of these the caller has liked. One query, not one per row."""
        if not rotation_ids:
            return set()
        rows = await self.session.execute(
            select(RotationLike.rotation_id)
            .where(RotationLike.user_id == user_id)
            .where(RotationLike.rotation_id.in_(list(rotation_ids))),
        )
        return {row[0] for row in rows.all()}

    async def like(self, rotation_id: str, user_id: str) -> None:
        """Record a like. **Idempotent**: liking twice is a no-op, not a 500.

        `ON CONFLICT DO NOTHING` rather than a read-then-write, because the read-then-write
        loses the race it exists to handle — two tabs, one unique constraint, one 500.
        """
        await self.session.execute(
            insert(RotationLike)
            .values(id=generate_uuid7(), rotation_id=rotation_id, user_id=user_id)
            .on_conflict_do_nothing(constraint="uq_rotation_likes_pair"),
        )
        await self.session.flush()

    async def unlike(self, rotation_id: str, user_id: str) -> None:
        """Remove a like. Also idempotent — un-liking what you never liked is not an error."""
        await self.session.execute(
            delete(RotationLike)
            .where(RotationLike.rotation_id == rotation_id)
            .where(RotationLike.user_id == user_id),
        )
        await self.session.flush()

    async def published(self, rotation_id: str) -> Rotation | None:
        """One published rotation, by id. `None` covers both "no such row" and "private",
        which is the same 404 to a caller who is not its author."""
        stmt = self._published().where(Rotation.id == rotation_id)
        return (await self.session.execute(stmt)).scalars().first()
