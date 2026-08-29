"""Schemas for a user's owned artifacts and for importing them from a GOOD export."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from app.data.snapshot import SnapshotUnavailableError
from app.models.enums import Rarity
from app.services.artifact_potential import upgrade_potential
from app.services.good_import_service import APPEND, REPLACE
from app.services.substat_rolls import resolve_artifact


class StatVocabularyEntry(BaseModel):
    """One stat, as a page needs to render it."""

    #: The `FIGHT_PROP_*` key, which is what `main_stat_type` and substats carry.
    key: str
    #: `HP%`, `CRIT DMG` — how the game writes it.
    display: str
    #: The stored value is a **fraction**: `0.466` is 46.6%. Without this a page prints
    #: "0.466 HP%" or "478000% HP", and neither looks obviously wrong at a glance.
    percentage: bool


class SlotVocabularyEntry(BaseModel):
    """One artifact slot, as a page needs to render it."""

    #: The payload key — `equip_bracer`, which is what `ArtifactRead.slot` carries.
    key: str
    #: `Flower`. The value is the source's internal spelling and is not a label.
    display: str


class RarityVocabularyEntry(BaseModel):
    """One rarity, as a page needs to render it."""

    #: The enum value — `five_star`, which is what `ArtifactRead.rarity` carries.
    key: str
    #: How many stars that is. `Rarity.stars` already knows; parsing `five_star` on the
    #: client would be a second implementation of it.
    stars: int


class ArtifactOptions(BaseModel):
    """The vocabulary an inventory needs to draw a row.

    Published **once** rather than decorated onto every artifact: 26 stats and 5 slots
    repeated across 800 pieces is the same table 800 times. The same reasoning as
    `/rotations/options`, arrived at from the other direction — there the risk was a client
    list drifting from the validator, here it is a client list existing at all.
    """

    stats: list[StatVocabularyEntry]
    slots: list[SlotVocabularyEntry]
    rarities: list[RarityVocabularyEntry]


class ArtifactEquip(BaseModel):
    """Body for `PATCH /artifacts/{id}` — the equip binding, and nothing else.

    **Only `build_id`.** An artifact's stats come from the GOOD import, with `main_stat_value`
    *derived* from the committed value table for its rarity, level and main stat rather than
    read off a screen. A patch that accepted `level` or `main_stat_value` would let the one
    number this repo derives be overwritten by hand, and every later use of that piece would
    be a confident calculation over a figure a user typed.

    `None` means unequip, and is not the same as omitting the field — which
    `extra="forbid"` plus a required `build_id` makes impossible to confuse.
    """

    model_config = {"extra": "forbid"}

    #: The build to attach this piece to, or `None` to take it off.
    build_id: str | None


class UpgradePotentialRead(BaseModel):
    """How much upgrading a piece has left, and the parts behind it.

    The parts, not just a figure, because **a score is a claim** and this repo's standing rule
    is that a number must be able to explain itself. "Potential: 3" is something a reader has
    to take on trust; three rolls of a possible five, at +9 of a possible +20, is something
    they can check.

    The piece's own substats are **not** repeated here: `ArtifactRead` carries them in full,
    with values and roll counts, so listing their names again would be the same answer in a
    worse form. And which substat a roll enhances is not in the committed data at all — see
    `app/services/artifact_potential.py`.
    """

    rolls_remaining: int
    rolls_total: int
    level: int
    max_level: int
    levels_to_max: int


class SubstatAnalysisRead(BaseModel):
    """One substat's reconstruction. Every field is nullable, and the nulls are the point."""

    #: Rolls behind the line, or null when the decompositions disagree about how many.
    rolls: int | None = None
    #: Each roll's tier, `0` (worst) to `3` (best). Null unless exactly one decomposition
    #: fits, so a client colouring per roll never colours a guess.
    roll_tiers: list[int] | None = None
    #: The total as a multiple of one best-case roll — `3.2` for 24.9% CRIT DMG against a
    #: 7.77% maximum. Needs no decomposition, so it survives the ambiguity above.
    roll_value: float | None = None
    #: True when `rolls` is the likeliest count rather than the only possible one. Genshin
    #: Optimizer takes the same fallback and does not say so; a client can draw the bars
    #: differently instead of implying certainty it does not have.
    estimated: bool = False


class ArtifactRead(BaseModel):
    """One owned artifact."""

    id: str
    slot: str
    rarity: str
    level: int
    main_stat_type: str
    #: Derived from the committed value table for this rarity, level and main stat — not a
    #: number a scanner read off a screen. See `good_import_service`.
    main_stat_value: float
    substats: list[Any] = []
    artifact_set_id: str | None = None
    #: The set's display name, beside the id rather than instead of it.
    #:
    #: Denormalised for drawing, like `BuildRead.character` (T.2): a list showing "Blizzard
    #: Strayer · Flower" should not need a second request per row, and resolving a UUID
    #: against a catalogue keyed by `nanoka_id` is a conversion the client has no business
    #: performing. Null for a piece whose set was not resolved on import.
    set_name: str | None = None
    #: Null when the piece is not equipped. Unequipping does not delete it.
    build_id: str | None = None

    @computed_field
    @property
    def substat_analysis(self) -> list[SubstatAnalysisRead]:
        """What each substat is made of, positionally aligned with `substats`.

        Genshin publishes no roll count — a substat is a *sum* — so it is reconstructed by
        decomposing the total over the values the stat can roll. Over a real 2,370-artifact
        export, 85.0% of substats decompose exactly one way (every roll value known), 10.2%
        more admit several decompositions that agree on the count, and 4.8% match nothing.

        **Ambiguity is reported, never smoothed.** `rolls` is null where the decompositions
        disagree on how many there were, and `roll_tiers` is null unless exactly one fits.
        `roll_value` needs no decomposition and is therefore present on almost every line —
        it is the total as a multiple of one best-case roll, and the number that actually
        answers "is this line any good".

        A parallel list rather than keys inside `substats`, because `substats` is a JSONB
        column with no schema behind it: rows written by an older importer are still valid
        and must not be rewritten to carry fields they never had.
        """
        try:
            stars = Rarity(self.rarity).stars
        except ValueError:
            # The sibling `potential` guards the identical call so an unreadable row returns
            # null rather than failing the response. Two computed fields on one model must
            # not make opposite promises about the same input.
            return [SubstatAnalysisRead() for _ in self.substats]
        # Readable lines only, but their **positions kept**: the result is aligned with
        # `substats` by index, so a row the tables cannot read must not shift the rest.
        readable: list[tuple[int, str, float]] = []
        for index, sub in enumerate(self.substats):
            stat = sub.get("stat") if isinstance(sub, dict) else None
            value = sub.get("value") if isinstance(sub, dict) else None
            if isinstance(stat, str) and isinstance(value, (int, float)):
                readable.append((index, stat, float(value)))

        # The whole piece at once. A substat's roll count is constrained by its neighbours,
        # because every roll the artifact received landed on one of them.
        # An unreadable row is *dropped from the solve but not from the piece*: it still
        # holds rolls. The budget comes from rarity and level alone, so this is already true
        # — noted because an earlier version derived it from the substat count, where losing
        # one row shrank the budget by exactly 1 while removing a line worth 1 to 3, and the
        # survivors were then confidently narrowed against a budget describing no artifact.
        found = resolve_artifact(
            stars=stars,
            level=self.level,
            substats=[(stat, value) for _, stat, value in readable],
        )
        out = [SubstatAnalysisRead() for _ in self.substats]
        for (index, _stat, _value), analysis in zip(readable, found, strict=True):
            out[index] = SubstatAnalysisRead(
                rolls=analysis.rolls,
                roll_tiers=list(analysis.roll_tiers) if analysis.roll_tiers else None,
                roll_value=analysis.roll_value,
                estimated=analysis.estimated,
            )
        return out

    @computed_field
    @property
    def potential(self) -> UpgradePotentialRead | None:
        """A.5/G.9 — how much upgrading this piece has left.

        **Null when the schedule cannot answer for this piece**: a rarity it does not cover,
        or a level that rarity cannot reach. Null rather than raising, because one impossible
        row must not take down a list of eight hundred — the failure the inventory page met
        from the other side. And null rather than zero, because zero is the honest answer for
        a maxed piece, so collapsing the two would hide the broken row behind a plausible
        number.

        Computed here rather than on the model: `app/models` importing `app/services` is the
        wrong way round, and this needs nothing the row does not already carry.
        """
        try:
            found = upgrade_potential(
                stars=Rarity(self.rarity).stars, level=self.level,
            )
        except (SnapshotUnavailableError, ValueError):
            return None
        return UpgradePotentialRead(
            rolls_remaining=found.rolls_remaining,
            rolls_total=found.rolls_total,
            level=found.level,
            max_level=found.max_level,
            levels_to_max=found.levels_to_max,
        )

    model_config = {"from_attributes": True}


class KernelCandidate(BaseModel):
    """One artifact, as `search.ts`'s `Candidate` reads it.

    O.2. Smaller than `ArtifactRead` and translated: `stats` is keyed by **kernel quantity**,
    with the main stat and every substat summed into one map, because the kernel takes one
    number per quantity.

    The translation is `stat_calculator._quantity_for_prop`, which decides what every stat
    means and refuses rather than guessing. Doing it in TypeScript would be a second
    definition of the vocabulary with a silent failure mode — a mis-mapped substat produces a
    build optimal for a stat the character does not have, presented as the answer.
    """

    id: str
    #: The payload key: `equip_dress`. `search.ts`'s `SLOTS` are the same five strings.
    slot: str
    #: Null for the 32 setless starter relics. **Not zero** — the kernel counts set pieces by
    #: id, and `0` would be a real catalogue id to it.
    set_id: int | None = None
    stats: dict[str, float]
    #: The main stat's raw property key — `FIGHT_PROP_CRITICAL_HURT`.
    #:
    #: **Carried separately even though it is already inside `stats`.** The kernel wants one
    #: number per quantity and does not care which of them was the main stat; a *user* cares
    #: enormously, because "the goblet must be Hydro DMG" is the first thing anyone decides
    #: about a Genshin build and it cannot be recovered from a summed pool — a CRIT DMG
    #: circlet with a CRIT DMG substat looks the same either way.
    #:
    #: The raw key rather than a display string: the client filters by identity and asks
    #: `/artifacts/options` for the label, which is the one place stat names are spelled.
    main_stat: str


class UnreadableArtifact(BaseModel):
    """A piece whose stats did not resolve, and why.

    OQ-O2. Reported rather than dropped: a silently omitted piece is an inventory the user
    cannot see is incomplete, and a search over it recommends the best of what it was *shown*
    while looking like the best of what they own.
    """

    artifact_id: str
    reason: str


class InventorySnapshot(BaseModel):
    """Every owned artifact in one response, plus the version that identifies it.

    **OQ-S3, answered: the browser holds the inventory and revalidates it.** The transfer is
    not the deciding factor — a 2,000-piece account is ~936 KB of JSON, ~234 KB gzipped, so
    fetching per search and holding across searches cost about the same. What differs is
    **staleness**: an inventory held across a GOOD re-import is an inventory containing
    artifacts the user no longer owns, and a search over it would recommend wearing them.

    So the payload carries a `version` and the route serves `304 Not Modified` against
    `If-None-Match`. The browser keeps the pieces and asks a cheap question before each
    search, which is the correctness of fetching at the cost of holding.

    Paging is deliberately not offered here. `GET /artifacts` pages for a UI list; a search
    needs the whole inventory at one instant, and four paged round-trips have no such
    instant — a concurrent import shifts every offset under the reader.
    """

    #: A digest over every piece's identity and stats. Changes when the inventory changes,
    #: and *only* then, so an unchanged account revalidates for free.
    version: str
    #: In the repository's game-slot order — slot, then level descending, then id. Fully
    #: determined, which is what the version depends on: a version that flipped because
    #: Postgres returned rows in another order would make every revalidation a full transfer.
    artifacts: list[KernelCandidate]
    total: int
    #: True when the account holds more pieces than one response will carry. The list is then
    #: a prefix of that order and the version covers only what was sent, so a search must
    #: treat it as "the server would not answer" rather than as a complete inventory.
    truncated: bool = False
    #: Pieces left out because their stats did not resolve, each with its reason (OQ-O2).
    #: Never silently omitted — see `UnreadableArtifact`.
    unreadable: list[UnreadableArtifact] = []


class GoodImportRequest(BaseModel):
    """Body for `POST /artifacts/import/good`.

    `mode` has **no default**, and that is the point. GOOD carries no stable per-artifact
    identifier, so `append` run twice duplicates a whole inventory — and a duplicated goblet
    is not clutter, it is a search that will happily recommend wearing the same piece twice.
    `replace` deletes. Neither is safe to reach by omission, so the request states which.
    """

    mode: Literal[REPLACE, APPEND]
    #: The export itself, verbatim. Validated by `app/data/importers/good_importer.py`,
    #: which refuses rather than coerces — see its docstring for why that differs from
    #: Genshin Optimizer's own reader.
    payload: dict[str, Any] = Field(..., description="A GOOD export, as exported.")
    #: Also reconstitute builds from `characters`, `weapons` and each artifact's `location`.
    #:
    #: **Off by default**, because it writes rows outside the inventory the caller asked to
    #: import. Never destructive: existing builds are kept and reported, so a re-import can
    #: refresh the artifacts without touching decisions a user made about a build. Teams are
    #: not imported at all — GOOD has no concept of one.
    rebuild_builds: bool = False


class ImportRejection(BaseModel):
    """One artifact that did not make it in, and why."""

    index: int
    reason: str


class BuildImportSummary(BaseModel):
    """What reconstituting builds from the export did, and did not do."""

    created: int = 0
    #: Characters that already had a build, named. "Nothing happened" and "your edits were
    #: kept" are indistinguishable otherwise.
    skipped_existing: list[str] = []
    #: Character keys the catalogue could not identify — usually an export newer than the
    #: seeded patch.
    unresolved: list[str] = []
    #: Equipped pieces that could not be placed, with the reason.
    unplaced: list[str] = []
    #: Weapons the catalogue could not identify, `"character: weapon"`. Reported because a
    #: build with no weapon is a legitimate state, so an unresolved one is otherwise silent.
    unresolved_weapons: list[str] = []
    #: Characters given artifacts but **no weapon at all** by the export — absent, not
    #: unresolvable. Reported for the same reason `unresolved_weapons` is: a weaponless build
    #: is a legitimate state, so a missing weapon is silent, and a user reads that silence as
    #: the importer having lost something.
    #:
    #: **The gap is in the export.** A real Irminsul file carrying 2,370 artifacts and 320
    #: weapons named a holder for only 68 of them, leaving 7 fully-equipped characters
    #: weaponless. Naming them is what lets a user tell an export problem from an import one
    #: — they can re-scan, and nothing here can.
    no_weapon_in_export: list[str] = []
    #: Pieces taken from a build that was already wearing them.
    reassigned: list[str] = []


class GoodImportResponse(BaseModel):
    """What the import did.

    `rejected` lists both the artifacts the parser refused and the ones whose set this
    database does not know. A caller showing a user what happened should not have to tell
    those apart, and a partial import that reported only a count would be the thing this
    importer exists not to be.
    """

    inserted: int
    deleted: int
    #: Owned weapons written. The export lists every weapon a user has, not only the equipped
    #: ones — 320 against 68 on a real file — and before `good_weapon_service` the other 252
    #: were parsed and thrown away.
    weapons_stored: int = 0
    #: Export weapon keys the catalogue could not identify. Reported rather than stored: a row
    #: with no catalogue match has no name, rarity or icon, so it would appear in the inventory
    #: as a blank the user could neither identify nor act on.
    weapons_unresolved: list[str] = []
    rejected: list[ImportRejection] = []
    ok: bool
    #: Builds left with an empty slot because the piece that filled it is not in the new
    #: export (N.3). A `replace` re-equips what it can by matching stats — GOOD has no stable
    #: per-artifact id — and names what it could not.
    unequipped: list[str] = []
    #: Null unless the caller asked for builds. A summary rather than the builds themselves:
    #: `/builds` already publishes those, and duplicating them here would be a second shape
    #: for one thing.
    builds: BuildImportSummary | None = None
    source: str = ""
    version: int = 0
