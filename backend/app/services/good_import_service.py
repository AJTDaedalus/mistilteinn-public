"""Turn a parsed GOOD export into rows in this user's `artifacts` table.

`app/data/importers/good_importer.py` validates the file and speaks the format's
vocabulary; this puts the result in the database. The split matters because the two have
different jobs: the parser refuses anything the game cannot produce, and this refuses
anything **this database cannot identify**.

## Resolving GOOD's `setKey` — the one derivation here, and why it refuses

A GOOD record names its set as `"BlizzardStrayer"`. This database stores
`"Blizzard Strayer"`, the English display name the nanoka payload publishes. Genshin
Optimizer builds its keys by stripping the punctuation and spaces out of that same name, so
the two sides match once both are reduced to lowercase alphanumerics.

**That correspondence is a mechanical normalisation, not a citation**, and it is not
verified against GO's own key list — that list is not committed to this repo and the
snapshot rule forbids fetching it at runtime. So the mechanism is built to fail loudly
instead of quietly:

* an unresolvable `setKey` **rejects the artifact**, naming the key. It does *not* import
  with a null `artifact_set_id`. A piece with no set is one the optimizer can never award a
  bonus for, so a silent null would hand a user a search that ignores half of what artifacts
  do — and it would do so for a whole set at a time, invisibly.
* `test_set_key_normalisation_is_injective` asserts no two of the 65 seeded sets reduce to
  the same key. If they ever did, a match could bind the wrong set, and *that* failure would
  be invisible in a way a rejection is not.

## Import modes are chosen, never defaulted

`replace` deletes every artifact this user owns before inserting; `append` adds to what is
there. Neither is a safe default: GOOD carries **no stable per-artifact identifier**, so
`append` run twice duplicates an entire inventory — and duplicates are worse than clutter
here, because the optimizer will happily build around wearing the same goblet twice. And
`replace` deletes data. The request has to say which, so the destructive one is never
reached by omission.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from app.data.snapshot import artifact_main_stat_value
from app.models.artifact import Artifact, ArtifactSet
from app.models.planner import Material, UserMaterial
from app.models.user import User
from app.services.quotas import enforce_headroom
from app.services.substat_rolls import analyse

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.data.importers.good_importer import GoodImportResult, ParsedArtifact

#: Everything that is not a letter or a digit. GOOD's keys are the display name with these
#: removed; reducing both sides the same way is the whole of the mapping.
_NOT_ALNUM = re.compile(r"[^a-z0-9]+")

REPLACE = "replace"
APPEND = "append"
MODES = (REPLACE, APPEND)


def set_lookup_key(name: str) -> str:
    """`"Gladiator's Finale"` and `"GladiatorsFinale"` both reduce to `gladiatorsfinale`."""
    return _NOT_ALNUM.sub("", name.lower())


class ReplaceRefusedError(RuntimeError):
    """A `replace` import would have deleted an inventory and stored nothing."""


@dataclass(frozen=True, slots=True)
class StoredImport:
    """What reached the database, and what did not."""

    inserted: int
    deleted: int
    #: `(index, reason)` for artifacts the parser refused **and** ones whose set this
    #: database does not know. Both are refusals; a caller should not have to tell them
    #: apart to show a user what happened.
    rejected: tuple[tuple[int, str], ...]
    #: Builds left with an empty slot because the piece that filled it is not in the new
    #: export, each named. Never silent: a user who sold an artifact should be told the slot
    #: emptied, not discover it later from a damage number.
    unequipped: tuple[str, ...] = ()
    #: How many `user_materials` rows the export's `materials` map produced. Zero is a
    #: legitimate outcome — plenty of scanners write artifacts only — and is reported rather
    #: than inferred, because "your scanner does not export materials" and "you hold none"
    #: look identical to a planner otherwise.
    materials_written: int = 0
    #: Material keys in the export that this catalogue could not name. Reported for the same
    #: reason `unresolved_weapons` is: usually the export is newer than the seeded patch.
    materials_unresolved: tuple[str, ...] = ()
    #: `{source_index: row}` for everything written, so build reconstitution can equip the
    #: exact piece the export named. Not part of what a client sees.
    rows_by_source: dict[int, Artifact] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when every artifact in the export was stored."""
        return not self.rejected


async def store_good_import(
    session: AsyncSession,
    owner_id: str,
    parsed: GoodImportResult,
    mode: str,
    *,
    max_artifacts: int = 0,
) -> StoredImport:
    """Write a parsed GOOD export to `owner_id`'s inventory.

    Set resolution happens **before** anything is deleted, and a `replace` that resolved
    nothing at all refuses rather than wiping — see `ReplaceRefusedError`.

    *max_artifacts* (`MAX_ARTIFACTS_PER_USER`; 0 disables it) is checked against what this
    import would leave the caller holding, after resolution and **before** anything is
    deleted or written, so a refused import changes nothing (security audit F3).
    """
    if mode not in MODES:
        msg = f"import mode must be one of {MODES}; got {mode!r}"
        raise ValueError(msg)

    sets_by_key = await _sets_by_lookup_key(session)

    resolved: list[tuple[ParsedArtifact, str]] = []
    rejected = [(row.index, row.reason) for row in parsed.rejected]
    for artifact in parsed.artifacts:
        set_id = sets_by_key.get(set_lookup_key(artifact.set_key))
        if set_id is None:
            reason = (
                f"unknown artifact set {artifact.set_key!r}. Importing it without a set "
                f"would hide every set bonus it could contribute to, so it is refused "
                f"instead."
            )
            # `source_index`, not the position in `parsed.artifacts`: those differ by
            # however many records the parser already refused, so enumerating here would
            # point a user at the wrong line of their own export.
            rejected.append((artifact.source_index, reason))
            continue
        impossible = _impossible_substats(artifact)
        if impossible:
            rejected.append((artifact.source_index, _impossible_reason(impossible)))
            continue
        resolved.append((artifact, set_id))

    if mode == REPLACE and parsed.artifacts and not resolved:
        # The seeder's `PRUNE REFUSED` rule, one layer up (D.7). A file that parsed as valid
        # GOOD but whose sets this build cannot resolve — a patch adding sets this snapshot
        # predates, most obviously — would otherwise delete the user's whole inventory and
        # insert nothing, reporting a successful import of zero artifacts. Resolving first
        # is not enough on its own; the delete has to be conditional on the resolution
        # having produced something.
        msg = (
            f"refusing to replace an inventory with nothing: all "
            f"{len(parsed.artifacts)} artifacts in this export were rejected. "
            f"Nothing was deleted."
        )
        raise ReplaceRefusedError(msg)

    # A replace deletes the inventory first, so only what it brings counts; an append adds to
    # what is already held.
    held = _Held(0) if mode == REPLACE else _Held(await _artifact_count(session, owner_id))
    await enforce_headroom(held, max_artifacts, "Artifact", len(resolved))

    deleted = 0
    equipped_before: list[tuple[str, tuple]] = []
    if mode == REPLACE:
        # Taken **before** the delete, which is the only moment it exists: `Artifact.build_id`
        # is on the rows about to go, and every build would otherwise come back stripped.
        equipped_before = await _equipped_fingerprints(session, owner_id)
        result = await session.execute(
            delete(Artifact).where(Artifact.owner_id == owner_id),
        )
        deleted = int(result.rowcount or 0)

    rows_by_source: dict[int, Artifact] = {}
    rows = [
        Artifact(
            owner_id=owner_id,
            artifact_set_id=set_id,
            slot=artifact.slot,
            rarity=artifact.rarity,
            level=artifact.level,
            main_stat_type=artifact.main_stat,
            # Derived from the committed value table, **not** taken from the export. GOOD
            # carries the number a scanner read off the screen; E.5 committed the table it
            # came from. Storing the OCR result where the table exists would let a misread
            # digit become a stat the optimizer then builds around — and the damage path
            # reads the table anyway, so the two would silently disagree.
            main_stat_value=artifact_main_stat_value(
                artifact.rarity.stars, artifact.level, artifact.main_stat,
            ),
            substats=list(artifact.substats),
            # **Carried through at last.**  has been read since the
            # importer was written; the column to put it in is new.
            locked=artifact.lock,
        )
        for artifact, set_id in resolved
    ]
    session.add_all(rows)
    # Keyed by where the record sat in the export, so a caller that also wants to rebuild
    # builds can bind the piece the user actually owns rather than re-matching on stats —
    # which is what `_restore_equipment` has to do, and only because it has nothing better.
    rows_by_source = {
        artifact.source_index: row
        for (artifact, _), row in zip(resolved, rows, strict=True)
    }
    await session.flush()

    unequipped = await _restore_equipment(session, owner_id, equipped_before)

    # **Stamped here, once the write has actually happened.** A GOOD import replaces an
    # inventory wholesale, and this is what later tells a user whether a saved optimization
    # result predates their last farming session — the commonest reason a stored number
    # stops being true. Setting it before the write would date an import that failed.
    materials_written, materials_unresolved = await _store_materials(
        session, owner_id, parsed.materials,
    )

    owner = await session.get(User, owner_id)
    if owner is not None:
        owner.gear_imported_at = datetime.now(UTC)
        # Flushed with the rest of the write rather than left for the caller's commit: this
        # function's other effects are already visible by the time it returns, and a stamp
        # that is not would be a field whose presence depended on who called it.
        await session.flush()

    return StoredImport(
        inserted=len(resolved),
        deleted=deleted,
        rejected=tuple(sorted(rejected)),
        unequipped=unequipped,
        materials_written=materials_written,
        materials_unresolved=materials_unresolved,
        rows_by_source=rows_by_source,
    )


@dataclass(frozen=True, slots=True)
class _Held:
    """A count already taken, in the shape `enforce_headroom` asks for."""

    n: int

    async def count(self) -> int:
        return self.n


async def _artifact_count(session: AsyncSession, owner_id: str) -> int:
    stmt = select(func.count()).select_from(Artifact).where(Artifact.owner_id == owner_id)
    return int((await session.execute(stmt)).scalar_one())


async def _store_materials(
    session: AsyncSession,
    owner_id: str,
    counts: dict[str, int] | None,
) -> tuple[int, tuple[str, ...]]:
    """Replace this account's material stock from the export's `materials` map.

    **Always a replace, never a merge, and only when the export carried the section at all.**
    A GOOD export is a snapshot of an inventory, so merging would leave a user holding
    materials they have since spent. `None` — no `materials` key — leaves the stored stock
    untouched, because that is a scanner which does not report materials rather than an
    account that emptied; `{}` clears it, because that is an account reporting nothing.

    **This replaces even in `append` mode**, and that is deliberate rather than an oversight:
    `append` exists because GOOD carries no stable per-artifact id, so adding an export twice
    would duplicate an inventory. Materials are keyed by material, so a re-import is
    idempotent and the snapshot reading is the right one for them either way.

    Binding is by `set_lookup_key`, the normalisation artifact sets already use, which is
    injective over every planner material — measured across all 508. Unresolvable keys are
    counted and returned rather than dropped: an export newer than the seeded patch is the
    usual cause and the user can act on being told.
    """
    if counts is None:
        return 0, ()

    materials = (await session.execute(select(Material.id, Material.name))).all()
    by_key: dict[str, int] = {set_lookup_key(name): material_id for material_id, name in materials}

    resolved: dict[int, int] = {}
    unresolved: list[str] = []
    for key, count in counts.items():
        material_id = by_key.get(set_lookup_key(key))
        if material_id is None:
            unresolved.append(key)
            continue
        resolved[material_id] = count

    await session.execute(delete(UserMaterial).where(UserMaterial.owner_id == owner_id))
    await session.flush()
    for material_id, count in resolved.items():
        session.add(
            UserMaterial(owner_id=owner_id, material_id=material_id, count=count),
        )
    await session.flush()
    return len(resolved), tuple(sorted(unresolved))


def _fingerprint(artifact: Artifact) -> tuple:
    """What makes two artifacts interchangeable.

    GOOD carries **no stable per-artifact id** — the reason `mode` has no default — so a
    restore cannot match on identity. It matches on what a piece *is*: set, slot, rarity,
    level, main stat and substats. Two pieces equal in all of those are interchangeable for
    every purpose this app has, so either will do.

    Substats are sorted, because the export's order is not meaningful and a re-scan may list
    them differently. Values are rounded to six places for the same reason
    `sim_context._canonical` rounds: `0.1 + 0.2` and `0.30000000000000004` describe one
    artifact and must not miss each other.
    """
    substats = sorted(
        (str(sub.get("stat")), round(float(sub.get("value", 0.0)), 6))
        for sub in (artifact.substats or [])
        if isinstance(sub, dict)
    )
    return (
        str(artifact.artifact_set_id),
        artifact.slot,
        artifact.rarity,
        artifact.level,
        artifact.main_stat_type,
        tuple(substats),
    )


async def _equipped_fingerprints(
    session: AsyncSession, owner_id: str,
) -> list[tuple[str, tuple]]:
    """`(build_id, fingerprint)` for every piece this owner has equipped.

    Owner-scoped, so a foreign build's slot is never recorded and never re-pointed — the
    subtlety the chunk-G marker said to keep rather than re-derive.
    """
    rows = (await session.execute(
        select(Artifact).where(
            Artifact.owner_id == owner_id, Artifact.build_id.isnot(None),
        ),
    )).scalars().all()
    return [(str(row.build_id), _fingerprint(row)) for row in rows]


async def _restore_equipment(
    session: AsyncSession, owner_id: str, snapshot: list[tuple[str, tuple]],
) -> tuple[str, ...]:
    """Re-equip what the wipe took, and name what could not be restored."""
    if not snapshot:
        return ()

    fresh = (await session.execute(
        select(Artifact).where(
            Artifact.owner_id == owner_id, Artifact.build_id.is_(None),
        ),
    )).scalars().all()

    by_fingerprint: dict[tuple, list[Artifact]] = {}
    for row in fresh:
        by_fingerprint.setdefault(_fingerprint(row), []).append(row)

    unequipped: list[str] = []
    for build_id, fingerprint in snapshot:
        candidates = by_fingerprint.get(fingerprint)
        if not candidates:
            unequipped.append(
                f"build {build_id} lost its {fingerprint[1]} — no matching piece in the "
                f"import",
            )
            continue
        # Popped, so one export piece cannot fill two builds' slots. Two builds wearing
        # identical artifacts each had their own; handing them the same row would leave one
        # build short and `uq_artifacts_build_slot` would reject the second write anyway.
        candidates.pop().build_id = build_id

    await session.flush()
    return tuple(unequipped)


def _impossible_substats(artifact: ParsedArtifact) -> list[tuple[str, float]]:
    """Substats whose value no combination of rolls can produce, at any legal count.

    **Not a rounding complaint.** `substat_rolls` compares the *displayed* value, the way the
    game rounds it, so a legitimate roll matches even on a boundary. What is left is a value
    the game could not have produced.

    **That claim was false twice, and both times this check refused real pieces.** The first
    was single-roll boundaries; the second was multi-roll ones — a CRIT DMG line of **25.7%**
    is `6.22 x3 + 6.99`, and two users had their pieces dropped for it before `_denoise` moved
    the float32 correction onto the table where it belongs. The sentence that used to stand
    here named 25.7 as the one genuine scanner error in a 2,370-piece inventory, and it was
    this bug's own symptom written down as evidence.

    So the standard for adding to the "impossible" story is a piece re-checked against the
    tables *after* the arithmetic is right, not a value that looked odd once.
    `docs/RESEARCH_substat_rounding.md`.
    """
    # `rarity` is a `Rarity` enum and `substats` is a tuple of dicts — not an int and not
    # pairs. Getting that wrong flagged all 2,370 pieces as impossible, which is why this ran
    # against the real export before it shipped rather than after.
    stars = artifact.rarity.stars
    found: list[tuple[str, float]] = []
    for sub in artifact.substats:
        stat = str(sub.get("stat", ""))
        value = sub.get("value")
        if not stat or not isinstance(value, (int, float)):
            continue
        analysis = analyse(stars=stars, stat=stat, value=float(value), level=artifact.level)
        # `rolls is None` covers two cases and only one is a bad value: a line the *piece-level*
        # solve left ambiguous is legitimate and common. `candidates` is empty only when no
        # roll count at all could produce this number, which is the one worth refusing.
        if analysis.rolls is None and not analysis.candidates:
            found.append((stat, float(value)))
    return found


def _impossible_reason(impossible: list[tuple[str, float]]) -> str:
    """Why the piece was refused, naming the values so a user can find them in-game."""
    lines = ", ".join(f"{stat}={value}" for stat, value in impossible)
    return (
        f"substat value(s) no combination of rolls can produce: {lines}. This is a scanner "
        f"error rather than a rarity or level this build does not know — the piece is left out "
        f"rather than imported, because every number computed from it would inherit the fault. "
        f"Re-scan the piece, or edit the value to what the game shows."
    )



async def _sets_by_lookup_key(session: AsyncSession) -> dict[str, str]:
    """`{normalised name: artifact_sets.id}` for every seeded set."""
    rows: Sequence[ArtifactSet] = (
        await session.execute(select(ArtifactSet))
    ).scalars().all()
    return {set_lookup_key(row.name): str(row.id) for row in rows}
