"""Genshin artifacts: the set catalogue and the individual owned pieces.

**New file, new class names** — nothing renamed from the deleted `disc.py`. Six disc slots
become five artifact slots, and ZZZ's 2pc/4pc equivalents become per-set affix rows whose
piece requirement is data rather than a constant (see `ArtifactSet.piece_thresholds`).

Field provenance: `tests/fixtures/nanoka_gi/artifact.json` (index),
`tests/fixtures/nanoka_gi/detail/artifact_15025.json` (detail), nanoka 7.0.51.
"""

from __future__ import annotations

from sqlalchemy import (
    Case,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    case,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.data.snapshot import SnapshotUnavailableError, main_stat_pools
from app.models.base import GUARDED_LAZY, Base, TimestampMixin, enum_column, uuid_pk
from app.models.enums import ArtifactSlot, Rarity, StatType, stat_type_for


#: Slot → the main stats that slot can roll, **as data rather than `if` branches** (C.5).
#:
#: Loaded from `app/data/yuanshen/snapshot/artifact_main_stat_pools.json`, which E.5
#: derived from the pinned YuanShenResources commit. C.5 left this empty on purpose rather
#: than writing "flower is always HP, plume is always flat ATK, sands rolls HP%/ATK%/DEF%/
#: EM/ER…" from memory — a table that would have looked authoritative, been right, and had
#: no citation. The snapshot's `note` and
#: `scripts/yuanshen/build_snapshot.py:derive_main_stat_pools` carry the derivation, which
#: cross-checks six config tables against each other and refuses to resolve anything it
#: cannot pin.
#:
#: **These are the 5★ pools.** The snapshot is derived at `rank 5` — what the optimizer
#: searches — and its `rank` field says so. Lower rarities share most of the pools but not
#: all of them, so a caller building a 4★ or 3★ piece is reading an assumption; when
#: something needs those, the builder takes a rank and this becomes a lookup.
#:
#: Still empty if the snapshot file is missing — a broken checkout, not a supported state.
#: `main_stats_for` raises in that case, and
#: `tests/unit/test_yuanshen_snapshot.py::test_every_slot_has_a_main_stat_pool` fails, so
#: it cannot pass unnoticed.
def _load_main_stat_pool() -> dict[ArtifactSlot, tuple[StatType, ...]]:
    """Read the committed snapshot into `{slot: (stat, …)}`.

    Reads through `app.data.snapshot`, which is the **only** module that opens those files
    (DESIGN §1 A6). This function used to parse the JSON itself; a second parser for the
    substat table would have followed, and then the two would have disagreed about what a
    missing file means.

    A prop the snapshot names and `StatType` does not is a **hard** error: it means the two
    halves of this repo disagree about the stat vocabulary, and the optimizer would silently
    search a smaller space than the game allows.
    """
    try:
        pools = main_stat_pools()
    except SnapshotUnavailableError:
        # An absent snapshot leaves the pool empty and `main_stats_for` raises with the
        # rebuild command — a broken checkout, not a supported state.
        return {}
    loaded: dict[ArtifactSlot, tuple[StatType, ...]] = {}
    for raw_slot, props in pools.items():
        stats = []
        for prop in props:
            stat = stat_type_for(prop)
            if stat is None:
                msg = (
                    f"artifact_main_stat_pools.json lists {prop!r} for {raw_slot}, which "
                    f"is not in app/models/enums.py:StatType"
                )
                raise ValueError(msg)
            stats.append(stat)
        loaded[ArtifactSlot(raw_slot)] = tuple(stats)
    return loaded


MAIN_STAT_POOL: dict[ArtifactSlot, tuple[StatType, ...]] = _load_main_stat_pool()


class ArtifactMainStatPoolUnavailableError(RuntimeError):
    """Raised when the slot→main-stat table is consulted before Chunk E populates it."""


def main_stats_for(slot: ArtifactSlot) -> tuple[StatType, ...]:
    """The main stats `slot` can roll **at 5★** — see `MAIN_STAT_POOL` on the rarity scope.

    Raises rather than returning an empty tuple: a caller that treats "no allowed main
    stats" as a valid answer would silently generate an empty candidate set in the
    optimizer, and an optimizer that returns nothing looks like a hard search problem
    rather than missing data.
    """
    pool = MAIN_STAT_POOL.get(slot)
    if not pool:
        raise ArtifactMainStatPoolUnavailableError(
            f"No main-stat pool for {slot!r}. MAIN_STAT_POOL is loaded from "
            f"app/data/yuanshen/snapshot/artifact_main_stat_pools.json; rebuild it with "
            f"`cd backend && python -m scripts.yuanshen.build_snapshot`.",
        )
    return pool


class ArtifactSet(TimestampMixin, Base):
    """An artifact set and its bonus affixes.

    **`piece_thresholds` is data, not the constant `[2, 4]`.** DESIGN §2.5 says the index
    supplies `need: [2,4]`; it supplies no `need` at all, and the detail payload's value is
    not always `[2, 4]`. Measured across all 65 sets at 7.0.51: **60 are `[2, 4]` and 5 are
    `[1]`** — the "Prayers" circlets (15009-15013), which are genuine one-piece sets. A
    model hardcoding 2pc/4pc gets those five wrong.

    `available_ranks` is likewise per-set: the index's `rank` list is `[4,5]` for 30 sets,
    `[3,4,5]` for 22, `[1,2,3,4,5]` for 9, `[1,2,3,4]` for 3 and `[2,3,4,5]` for 1.
    """

    __tablename__ = "artifact_sets"

    id: Mapped[uuid_pk]
    nanoka_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: The icon for each slot, keyed by `ArtifactSlot` value.
    #:
    #: **`icon` above is the flower and nothing else.** nanoka publishes one icon per set —
    #: `UI_RelicIcon_15025_4` — and five more under `parts`, one per slot. Only the first was
    #: seeded, so every artifact card in the app drew a flower whatever slot it was, which is
    #: what the owner noticed: *"Do we not have icons for anything but the flowers?"*
    #:
    #: The suffix-to-slot mapping is **read from the payload, never derived from the number**:
    #: `tests/fixtures/nanoka_gi/detail/artifact_15025.json` names `_1` as `equip_ring` and
    #: `_4` as `equip_bracer`, and inferring that from the digit is exactly the kind of guess
    #: the seeding rule forbids.
    part_icons: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: e.g. `[2, 4]` or `[1]` — how many pieces each affix row requires, in affix order.
    piece_thresholds: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: The rarities this set exists at, from the index's `rank`.
    available_ranks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    affixes: Mapped[list[ArtifactSetAffix]] = relationship(
        lazy=GUARDED_LAZY,
        back_populates="artifact_set",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ArtifactSetAffix.position",
    )

    def __repr__(self) -> str:
        return f"<ArtifactSet {self.name} {self.piece_thresholds}>"


class ArtifactSetAffix(TimestampMixin, Base):
    """One set-bonus row — the 2-piece or 4-piece text, or a 1-piece set's only bonus.

    `position` is the index within the set's affix list and pairs with the same index of
    `ArtifactSet.piece_thresholds`; the payload's affix ids end in that ordinal, but the
    ordinal is what the pairing relies on, not the id arithmetic.

    `add_props` is the payload's structured effect (`[{prop_type, value}, …]`) and
    `param_list` its numeric parameters. Both are kept alongside the human text so Chunk H
    builds modifiers from data rather than from parsed prose. **`param_list` is the load-
    bearing one**: 324 of the affix rows across the 65 sets have `add_props` entirely
    `FIGHT_PROP_NONE`, because a conditional bonus has no static prop — for those rows
    `param_list` holds the only numbers that exist outside the description markup.
    """

    __tablename__ = "artifact_set_affixes"
    __table_args__ = (
        UniqueConstraint(
            "artifact_set_id", "position", name="uq_artifact_set_affixes_set_id_position",
        ),
    )

    id: Mapped[uuid_pk]
    artifact_set_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_sets.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    pieces_required: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    add_props: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    #: The affix's numeric parameters, e.g. `[0.3, 8, …]` for a 30% RES shred lasting 8s.
    #: **This is where the numbers actually are.** 324 of the affix rows across the 65 sets
    #: have `add_props` entirely `FIGHT_PROP_NONE`, because a conditional bonus has no static
    #: prop — for those rows `param_list` is the only structured data, and the prose is
    #: `<color=#99FFFFFF>30%</color>` markup. Dropping it would leave Chunk H regexing HTML.
    param_list: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    artifact_set: Mapped[ArtifactSet] = relationship(back_populates="affixes")

    def __repr__(self) -> str:
        return f"<ArtifactSetAffix {self.pieces_required}pc {self.name}>"


class Artifact(TimestampMixin, Base):
    """One artifact a user owns.

    Substats are JSONB rather than four nullable column pairs: a piece has one to four of
    them, the whole list is always read together, and nothing queries an individual roll.
    The roll *count* per substat matters for scoring, so the shape is
    `[{"stat": "<StatType>", "value": <float>, "rolls": <int>}, …]` and D/G own filling it.

    `build_id` is the equip binding, nullable and `SET NULL` — unequipping a piece must not
    delete it, and deleting a build must not delete the user's artifacts.
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_owner_slot", "owner_id", "slot"),
        # A build holds at most one piece per slot. Without this, a GOOD import or an
        # optimizer write path that equips before unequipping leaves two flowers attached:
        # `Build.artifacts` then yields six pieces and every set-bonus count and stat sum is
        # silently wrong. Partial, so unequipped pieces (`build_id IS NULL`) are unaffected —
        # same idiom as `uq_builds_owner_character`.
        Index(
            "uq_artifacts_build_slot",
            "build_id", "slot",
            unique=True,
            postgresql_where=text("build_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid_pk]
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    artifact_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_sets.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    build_id: Mapped[str | None] = mapped_column(
        ForeignKey("builds.id", ondelete="SET NULL"), nullable=True, index=True,
    )

    slot: Mapped[ArtifactSlot] = mapped_column(enum_column(ArtifactSlot, 24), nullable=False)
    rarity: Mapped[Rarity] = mapped_column(enum_column(Rarity, 16), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    main_stat_type: Mapped[StatType] = mapped_column(enum_column(StatType, 48), nullable=False)
    main_stat_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    substats: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    artifact_set: Mapped[ArtifactSet | None] = relationship(lazy=GUARDED_LAZY)

    def __repr__(self) -> str:
        return f"<Artifact {self.slot} +{self.level} {self.main_stat_type}>"

    @property
    def set_name(self) -> str | None:
        """The set's display name, for `ArtifactRead`.

        **Reads an eager relationship on purpose.** `lazy` is `raise_on_sql`, so a route that
        hands this to `ArtifactRead` without loading `artifact_set` fails loudly rather than
        emitting a query per row — which is what a defensive `None` here would hide. Every
        such route uses `search` or `get_with_set`, and
        `tests/integration/test_artifact_inventory.py` expires the session to prove it.
        """
        return self.artifact_set.name if self.artifact_set is not None else None

def artifact_slot_sort_order() -> Case:
    """A SQL `CASE` putting artifacts in flower→plume→sands→goblet→circlet order.

    `ORDER BY slot` sorts the *payload keys* alphabetically — `equip_bracer, equip_dress,
    equip_necklace, equip_ring, equip_shoes` — which is flower, circlet, plume, goblet,
    sands. Correct-looking, and wrong for any UI or export that iterates the collection.
    """
    return case(
        {slot.value: slot.sort_index for slot in ArtifactSlot},
        value=Artifact.slot,
    )
