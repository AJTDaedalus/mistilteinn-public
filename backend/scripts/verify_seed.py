"""Post-seed verification: row counts against the source indexes, plus hand-checked anchors.

    cd backend && python -m scripts.verify_seed           # against the committed fixtures
    cd backend && python -m scripts.verify_seed --live    # re-fetch the indexes from nanoka

Exit 0 only if every check passed. **A check that could not run is a failure, never a
pass** — no seed row, no fixtures, a version mismatch and an unreachable nanoka all exit
non-zero with a reason. That is this repo's gate rule, and this script exists because fairy
shipped a field-mapping regression (Anomaly Mastery and Proficiency stored swapped on every
agent) that reached production silently: `seed_db.py` had no post-seed assertions at all.

Three layers, each catching what the others cannot:

1. **Provenance** — a `seed_runs` row exists and says it finished.
2. **Counts** — the index length the run *recorded* matches the index length that *exists*,
   and the rows in the database match what the run said it imported. Two-sided: a pass that
   silently imported half the roster fails the second, and a stale database that was never
   re-seeded after a patch fails the first.
3. **Anchors** — a short list of values read off the committed payloads **by hand**, with
   the file and key noted at each one. These are the only check that can catch a *mapping*
   regression, because everything else compares the importer against itself.

**The anchor list is deliberately short and it is expected to rot.** A patch that changes
Aquila Favonia's base ATK should turn this red; that is the drift signal, not a defect in
the check. Keep it short enough that every entry stays worth trusting — a long list of
unverified expectations rots and then gets deleted instead of fixed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.data.importers.nanoka_gi_importer import ENTITIES, HttpNanokaTransport
from app.database import async_session_factory
from app.models.artifact import ArtifactSet, ArtifactSetAffix
from app.models.build import EnemyProfile
from app.models.character import Character, Talent
from app.models.enums import Element, Rarity, StatType, TalentType, WeaponType
from app.models.seed_provenance import SeedRun
from app.models.weapon import Weapon, WeaponRefinement

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nanoka_gi"

#: The version `tests/fixtures/nanoka_gi/` was captured at — see its PROVENANCE.md. A seed
#: from a different version is a **failure** in offline mode, not a skip: the counts would
#: be compared against the wrong patch, and quietly passing would be worse than either.
FIXTURE_VERSION = "7.0.51"

#: The ids the anchors below are read off. Named rather than inlined so the query and the
#: anchor's `source` line cannot drift apart.
AYAKA = "10000002"
PYRO_TRAVELER = "10000005-2"
AQUILA_FAVONIA = 11501
DEEPWOOD_MEMORIES = 15025
RUIN_GUARD = 24010101

#: Entity → the model whose rows that pass writes.
ENTITY_MODELS: dict[str, type] = {
    "character": Character,
    "weapon": Weapon,
    "artifact": ArtifactSet,
    "monster": EnemyProfile,
}


@dataclass(frozen=True)
class Anchor:
    """One hand-checked value, with where a human read it from."""

    name: str
    source: str
    expected: Any


async def _anchor_values(session: AsyncSession) -> list[tuple[Anchor, Any]]:
    """Every anchor paired with what the database actually holds.

    Each `source` names the committed payload and the key the expected value was read from,
    so the next person can re-check it in one step instead of trusting this list.
    """
    ayaka = await session.scalar(select(Character).where(Character.nanoka_id == AYAKA))
    traveler = await session.scalar(
        select(Character).where(Character.nanoka_id == PYRO_TRAVELER),
    )
    aquila = await session.scalar(select(Weapon).where(Weapon.nanoka_id == AQUILA_FAVONIA))
    deepwood = await session.scalar(
        select(ArtifactSet).where(ArtifactSet.nanoka_id == DEEPWOOD_MEMORIES),
    )
    guard = await session.scalar(
        select(EnemyProfile).where(EnemyProfile.nanoka_id == RUIN_GUARD),
    )

    checks: list[tuple[Anchor, Any]] = [
        (
            Anchor(
                "Ayaka is a 5★ Cryo sword user",
                "detail/character_10000002.json: element, weapon, rarity",
                (Element.CRYO, WeaponType.SWORD, Rarity.FIVE_STAR),
            ),
            None if ayaka is None else (ayaka.element, ayaka.weapon_type, ayaka.rarity),
        ),
        (
            Anchor(
                "Ayaka's burst costs 80 energy",
                'detail/character_10000002.json: skills[3].promote["0"].desc '
                '"Energy Cost|{param5:I}" -> param[4]',
                80,
            ),
            None if ayaka is None else ayaka.burst_energy_cost,
        ),
        (
            Anchor(
                "Ayaka ascends into Crit DMG",
                "detail/character_10000002.json: the non-base key of "
                "stats_modifier.ascension (fight_prop_critical_hurt)",
                StatType.CRIT_DMG,
            ),
            None if ayaka is None else ayaka.ascension_stat_type,
        ),
        (
            Anchor(
                "Ayaka's four talents include an alternate sprint",
                "detail/character_10000002.json: skills[2] is Skill_S_Ayaka_02 with a "
                "1-level promote ladder",
                [
                    TalentType.NORMAL_ATTACK,
                    TalentType.ELEMENTAL_SKILL,
                    TalentType.ALTERNATE_SPRINT,
                    TalentType.ELEMENTAL_BURST,
                ],
            ),
            None if ayaka is None else await _talent_types(session, ayaka.id),
        ),
        (
            Anchor(
                "the Pyro Traveler survived the string-keyed id",
                "character.json key 10000005-2 — the shape an Integer column could not hold",
                ("Traveler", Element.PYRO),
            ),
            None if traveler is None else (traveler.name, traveler.element),
        ),
        (
            Anchor(
                "Aquila Favonia's base ATK and substat",
                "detail/weapon_11501.json: weapon_prop[0].init_value, weapon_prop[1]",
                (47.537, StatType.PHYSICAL_DMG_BONUS, 5),
            ),
            None if aquila is None else (
                aquila.base_atk,
                aquila.sub_stat_type,
                await _count_where(
                    session, WeaponRefinement, WeaponRefinement.weapon_id, aquila.id,
                ),
            ),
        ),
        (
            Anchor(
                "Deepwood Memories is a 2/4-piece set with two affixes",
                "detail/artifact_15025.json: need, len(affix)",
                ([2, 4], 2),
            ),
            None if deepwood is None else (
                deepwood.piece_thresholds,
                await _count_where(
                    session, ArtifactSetAffix, ArtifactSetAffix.artifact_set_id, deepwood.id,
                ),
            ),
        ),
        (
            Anchor(
                "a Ruin Guard resists 70% physical damage",
                "detail/monster_24010101.json: child.24010101.sub_hurt.physical — the "
                "value that proves RES is not the uniform 0.1 every ordinary enemy has",
                (0.7, 0.1),
            ),
            None if guard is None else (guard.physical_res, guard.pyro_res),
        ),
        (
            Anchor(
                "the one-piece Prayers sets are not forced to 2/4",
                "artifact.json 15009-15013: five sets whose detail `need` is [1]",
                5,
            ),
            await session.scalar(
                select(func.count())
                .select_from(ArtifactSet)
                .where(ArtifactSet.piece_thresholds == [1]),
            ),
        ),
    ]
    return checks


#: The order the payload lists a character's `skills[]`, which is the order the Ayaka
#: anchor was read in. Not the order `TalentType` declares its members, and not something
#: SQL can produce — hence the sort here rather than an `ORDER BY`.
_PAYLOAD_TALENT_ORDER = [
    TalentType.NORMAL_ATTACK,
    TalentType.ELEMENTAL_SKILL,
    TalentType.ALTERNATE_SPRINT,
    TalentType.ELEMENTAL_BURST,
]


async def _talent_types(session: AsyncSession, character_id: str) -> list[TalentType]:
    """A character's talent types, in payload order."""
    rows = await session.execute(
        select(Talent.talent_type).where(Talent.character_id == character_id),
    )
    return sorted(rows.scalars(), key=_PAYLOAD_TALENT_ORDER.index)


async def _count_where(session: AsyncSession, model: type, column: Any, value: Any) -> int:
    return await session.scalar(
        select(func.count()).select_from(model).where(column == value),
    )


async def load_indexes(*, live: bool, version: str) -> dict[str, int]:
    """Index lengths per entity, from the committed fixtures or from nanoka.

    Offline is the default because it always runs. A seed from a version other than the
    fixtures' fails rather than being compared against the wrong patch.
    """
    if not live:
        if version != FIXTURE_VERSION:
            msg = (
                f"database was seeded from nanoka {version} but the committed fixtures are "
                f"{FIXTURE_VERSION}. Re-capture them (python -m scripts.capture_nanoka_"
                f"fixtures) or re-run with --live; comparing against the wrong patch would "
                f"be worse than not comparing at all."
            )
            raise SystemExit(msg)
        return {
            entity: len(
                json.loads((FIXTURE_DIR / f"{entity}.json").read_text(encoding="utf-8")),
            )
            for entity in ENTITIES
        }

    transport = HttpNanokaTransport(version=version)
    try:
        return {entity: len(await transport.fetch_index(entity)) for entity in ENTITIES}
    finally:
        await transport.close()


async def verify(
    session: AsyncSession,
    *,
    live: bool = False,
    indexes: dict[str, int] | None = None,
) -> list[str]:
    """Run every check. Returns the failures — empty means the seed is verified.

    `indexes` overrides where the index lengths come from; the tests pass them directly so
    the checks can be exercised against a four-row database instead of a full seed.
    """
    run = await session.scalar(select(SeedRun).order_by(SeedRun.started_at.desc()).limit(1))
    if run is None:
        return [
            (
                "no seed_runs row: nothing has been seeded. A verifier with nothing to "
                "verify must not report a pass (run python -m scripts.seed_db)."
            ),
        ]
    failures: list[str] = []
    if not run.succeeded:
        failures.append(
            f"the most recent seed run ({run.version}, started {run.started_at}) did not "
            f"finish: entity_counts={run.entity_counts}",
        )

    if indexes is None:
        indexes = await load_indexes(live=live, version=run.version)
    for entity, model in ENTITY_MODELS.items():
        recorded = run.entity_counts.get(entity)
        if recorded is None:
            failures.append(f"{entity}: the seed run recorded no counts for this pass")
            continue
        if recorded["total"] != indexes[entity]:
            failures.append(
                f"{entity}: the run saw {recorded['total']} index entries but the index "
                f"holds {indexes[entity]} — the database is from a different patch",
            )
        if recorded["failed"]:
            failures.append(f"{entity}: the run failed on {recorded['failed']}")
        # Scoped to rows the importer owns. `EnemyProfile.nanoka_id` is deliberately
        # nullable — a hand-authored crossval target is a legitimate row — and `_prune`
        # deliberately preserves those. Counting them here would turn the first Chunk F
        # test dummy into a permanent red gate, and a gate that goes red for a supported
        # configuration is a gate that gets switched off.
        rows = await session.scalar(
            select(func.count()).select_from(model).where(model.nanoka_id.isnot(None)),
        )
        if rows != recorded["imported"]:
            failures.append(
                f"{entity}: {rows} importer-owned rows in {model.__tablename__} against "
                f"{recorded['imported']} the run says it imported",
            )
        if recorded.get("prune_blocked"):
            failures.append(
                f"{entity}: the run refused to prune — {recorded['prune_blocked']}",
            )

    for anchor, actual in await _anchor_values(session):
        if actual != anchor.expected:
            failures.append(
                f"anchor {anchor.name!r}: expected {anchor.expected!r}, found {actual!r} "
                f"(source: {anchor.source})",
            )
    return failures


async def main_async(*, live: bool) -> int:
    """Verify the configured database and print the result."""
    async with async_session_factory() as session:
        failures = await verify(session, live=live)
        run = await session.scalar(
            select(SeedRun).order_by(SeedRun.started_at.desc()).limit(1),
        )
        if run is not None:
            print(f"seeded from nanoka GI {run.version} at {run.started_at}")
        counts = {
            entity: await session.scalar(select(func.count()).select_from(model))
            for entity, model in ENTITY_MODELS.items()
        }
    for entity, rows in counts.items():
        print(f"  {entity}: {rows} rows")
    # Flushed so the failure list below cannot appear above the summary it refers to when
    # stdout is a pipe and stderr is not.
    sys.stdout.flush()
    if failures:
        print(f"\n{len(failures)} check(s) FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("\nall checks passed")
    return 0


def main() -> int:
    """Parse arguments and verify."""
    parser = argparse.ArgumentParser(description="Verify a seeded Genshin database.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="re-fetch the indexes from nanoka instead of using the committed fixtures",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(live=args.live))


if __name__ == "__main__":
    raise SystemExit(main())
