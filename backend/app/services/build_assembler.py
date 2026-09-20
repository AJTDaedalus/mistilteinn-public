"""Turn stored rows into the shapes the damage chain and the optimizer read.

Chunk F's `stat_calculator` and Chunk G's `artifact_optimizer` take dataclasses, not ORM
rows, and deliberately so: the optimizer scores hypothetical builds that were never in a
database, and the crossval harness scores builds that never will be. This module is the one
place the two vocabularies meet.

**One place, because it was already two.** The `Character` row → `CharacterStats` mapping
existed only inside `tests/integration/test_stat_calculator_against_seed.py`. Writing a
second copy for the API would have left the tested mapping and the served mapping free to
drift, with both looking right — so the test now imports these functions and the mapping has
one definition.

## What this cannot do yet

**It does not know what a talent's hit is, and still does not.** A caller hands it a `Hit`.
What changed in M.2 is *where the caller gets one*: `app/services/talent_hits.py` resolves a
multiplier from the character's published rows, so the API layer no longer requires a user to
type one. This module is deliberately not the place that happens — it assembles stats, and a
second route into the damage chain is a second thing to keep honest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.pando.calculator import NodeRegistry
from app.services.artifact_optimizer import ArtifactCandidate, SetBonus
from app.services.stat_calculator import (
    CharacterStats,
    WeaponStats,
    _quantity_for_prop,
    add_character,
    add_weapon,
    build_log,
)
from app.services.traveler import is_traveler

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from app.formula.genshin.explain import Contribution
    from app.models.artifact import Artifact, ArtifactSet
    from app.models.build import Build
    from app.models.character import Character
    from app.models.weapon import Weapon


class BuildAssemblyError(ValueError):
    """A stored build cannot be evaluated as it stands."""


def character_stats(row: Character) -> CharacterStats:
    """A `Character` row in the vocabulary `stat_calculator` reads."""
    return CharacterStats(
        name=row.name,
        base_hp=row.base_hp,
        base_atk=row.base_atk,
        base_def=row.base_def,
        prop_curves=row.prop_curves,
        ascension_rows=row.ascension_stats,
        # The payload's published values, never gcsim's hardcoded 5%/50%: Lauma publishes
        # 200 base EM and the unreleased Traveler bodies publish `crit_rate: 0`.
        elemental_mastery=row.base_elemental_mastery,
        crit_rate=row.base_crit_rate,
        crit_dmg=row.base_crit_dmg,
        # Story-quest buffs are the Traveler's alone, and gcsim applies them by default —
        # `formula/genshin/story_buffs.py`. `traveler.py` owns the question of which rows
        # are Travelers; asking it here keeps one answer rather than two.
        is_traveler=is_traveler(name=row.name, icon=row.icon),
    )


def weapon_stats(row: Weapon) -> WeaponStats:
    """A `Weapon` row in the vocabulary `stat_calculator` reads.

    Both entries of `props` carry their `GROW_CURVE_*` name, because both the base ATK and
    the substat grow. A weapon with neither — the eight `ITEM_TPS_WEAPON` rows publish
    `atk: null` and `sub: null` — yields an empty `props` rather than a pair of nulls the
    curve lookup would then raise on.
    """
    props: list[dict[str, object]] = []
    if row.base_atk is not None:
        props.append({
            "prop_type": "FIGHT_PROP_BASE_ATTACK",
            "init_value": row.base_atk,
            "type": row.base_atk_curve,
        })
    if row.sub_stat_type is not None:
        props.append({
            "prop_type": row.sub_stat_type,
            "init_value": row.sub_stat_base_value,
            "type": row.sub_stat_curve,
        })
    return WeaponStats(name=row.name, props=props, ascension=row.ascension_atk)


def base_contributions(build: Build) -> tuple[Contribution, ...]:
    """The character-and-weapon half of a build — everything artifacts do not change.

    Resolved once and replayed by the optimizer across every combination it scores, which is
    why it is a list of contributions rather than a live log.

    A build with no character raises: an optimizer run against a character-less build would
    score five artifacts on a base of zero and rank them by their own stats alone, which is
    a plausible-looking answer to a question nobody asked.
    """
    if build.character is None:
        msg = (
            f"build {build.id} has no character, so there is no base to add artifacts to. "
            f"Scoring one anyway would rank pieces by their own stats and call it a build."
        )
        raise BuildAssemblyError(msg)

    log = build_log(NodeRegistry())
    add_character(
        log,
        character_stats(build.character),
        level=build.character_level,
        ascension_phase=build.ascension_phase,
    )
    if build.weapon is not None:
        add_weapon(
            log,
            weapon_stats(build.weapon),
            level=build.weapon_level,
            ascension_phase=build.ascension_phase,
        )
    return tuple(log.contributions)


def base_contributions_with_weapon(
    build: Build, weapon: Weapon, *, weapon_level: int | None = None,
) -> tuple[Contribution, ...]:
    """The same base, with `weapon` substituted for the build's own.

    D.5 compares candidate weapons in a fixed build, and every candidate needs the character
    half of that build unchanged beneath it. Written here rather than in the comparison,
    because assembling a base from rows is this module's job and a second way of doing it is
    how two definitions of "what a build starts from" begin — the drift the note-format
    finding in D.4 had already made concrete once.

    Deliberately **not** a copy of `base_contributions`: it delegates, so a change to how a
    character contributes reaches both.
    """
    if build.character is None:
        msg = (
            f"build {build.id} has no character, so there is no base to put a weapon on. "
            f"Comparing weapons on it would rank them by their own stats and call it a build."
        )
        raise BuildAssemblyError(msg)

    log = build_log(NodeRegistry())
    add_character(
        log,
        character_stats(build.character),
        level=build.character_level,
        ascension_phase=build.ascension_phase,
    )
    add_weapon(
        log,
        weapon_stats(weapon),
        level=build.weapon_level if weapon_level is None else weapon_level,
        ascension_phase=build.ascension_phase,
    )
    return tuple(log.contributions)


def candidates(artifacts: Iterable[Artifact]) -> list[ArtifactCandidate]:
    """Owned artifacts as search candidates.

    `set_id` is the **catalogue** `nanoka_id`, not the row's UUID: set bonuses are looked up
    by it and `SetBonus.set_id` is the same number. A piece whose set row is missing is
    skipped rather than given a placeholder id — an id nothing matches would silently make
    it its own one-piece set and defeat every set bonus it should have counted toward.
    """
    out = []
    for artifact in artifacts:
        if artifact.artifact_set is None:
            continue
        out.append(ArtifactCandidate(
            artifact_id=str(artifact.id),
            slot=artifact.slot.value,
            set_id=artifact.artifact_set.nanoka_id,
            rarity=artifact.rarity.stars,
            level=artifact.level,
            main_stat=artifact.main_stat_type,
            substats=tuple(dict(s) for s in artifact.substats),
        ))
    return out


def set_bonuses(artifact_sets: Sequence[ArtifactSet]) -> list[SetBonus]:
    """Every tier of every given set, keyed by catalogue id.

    Thresholds come from each set's own affix rows (C.5), so the five one-piece "Prayers"
    circlets contribute at one piece and a `[2, 4]` set does not.
    """
    return [
        SetBonus(
            set_id=row.nanoka_id,
            set_name=row.name,
            pieces_required=affix.pieces_required,
            add_props=tuple(dict(p) for p in affix.add_props),
        )
        for row in artifact_sets
        for affix in row.affixes
    ]


def bonus_stats(tier: SetBonus) -> dict[str, float]:
    """A set tier's static props, in kernel quantities.

    A prop the mapping refuses is **skipped rather than guessed**, which is what
    `artifact_optimizer` does with the same rows — a conditional affix's props are all
    `FIGHT_PROP_NONE`, and inventing a quantity for one would add a bonus the game does not
    give.

    Lives here rather than in a route module because two routes now need it —
    `/builds/{id}/search-context` and `/artifacts/set-bonuses` — and DESIGN §1 A6 asks that
    each mechanic have **one** implementation everything reuses. Two copies of a mapping that
    decides what every stat means is the drift nobody notices until a ranking is wrong.
    """
    stats: dict[str, float] = {}
    for prop in tier.add_props or ():
        quantity = _quantity_for_prop(prop.get("prop_type"), allow_absent=True)
        if quantity is None:
            continue
        stats[quantity] = stats.get(quantity, 0.0) + float(prop.get("value", 0.0))
    return stats
