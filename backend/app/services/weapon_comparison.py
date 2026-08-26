"""Which weapon should I use — the ranker's question, on a different axis.

DESIGN §3.5:

> **The G.4 ranker generalises to it for free.** "Which weapon should I use" is the same
> marginal-value question as "which artifact should I use" — swap it in, hold the rest
> constant, report the difference against what is equipped. The ranker does not need a new
> concept, only a new axis.

That is what this is: one build, one set of artifacts held fixed, and each candidate weapon
swapped into it. No new scoring path — `build_combination_log` and `BuildEvaluator`, the same
two the search and the ranker use.

## The caveat that is larger here than anywhere else, and is not a footnote

**Weapon passives are not applied.** They are imported and stored — `weapon_refinements` has
each step's name, text and `param_list` — but turning text into modifiers is Chunk H's job,
and nothing reads them yet.

For artifact sets the equivalent gap is reported as `skipped_conditional_bonuses` and is
usually a correction. **For weapons it is frequently decisive.** A comparison that sees only
base ATK and the substat will rank a stat-stick above a weapon whose passive is the entire
reason anyone equips it, and it will do so with a precise-looking number.

So `WeaponComparison` carries `unmodelled_passives`: every candidate whose refinement row has
text, named, with the text itself. A caller that hides that list is publishing a ranking this
module does not claim to have made. It is not a warning about precision — the ordering itself
can be wrong.

**There is a second tier that does apply them, and this module stays as it is.** W.6 added
`POST /builds/{id}/compare-weapons/gcsim`, which emits configs the browser runs through gcsim
— the authority on passives, since deriving 237 conditions from refinement prose is the
fabricated-citation failure fairy actually suffered. That tier costs minutes; this one costs
milliseconds and is honest about what it left out, so **both are offered** (OQ-W4). Deleting
a fast honest answer because a slow better one exists is a downgrade for anyone who wanted
the fast one.

## And the other half of §3.5, deliberately not attempted here

> for each weapon, find its best artifacts; then compare the winners

That is N searches, and searches belong on the client (DESIGN §3.5: nothing combinatorial
lands on the server). This answers the cheaper and different question — *"which weapon is
better in the build I have"* — and says so in its own field name. The two answers can differ:
a weapon that wants a completely different artifact set loses a fixed-artifact comparison it
would win with its own pieces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services import build_explanation
from app.services.artifact_optimizer import bonuses_by_set, build_combination_log
from app.services.damage_calculator import BuildEvaluator

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from app.formula.genshin.damage import Hit
    from app.formula.genshin.explain import Contribution
    from app.services.artifact_optimizer import ArtifactCandidate, SetBonus
    from app.services.damage_calculator import Enemy


@dataclass(frozen=True, slots=True)
class WeaponCandidate:
    """One weapon to try, already resolved to what it contributes.

    `base_contributions` is the whole character-and-weapon half of the build with *this*
    weapon in it — resolved by the caller through `build_assembler`, because assembling a
    build from rows is that module's job and doing it twice is how two definitions start.
    """

    weapon_id: str
    name: str
    base_contributions: tuple[Contribution, ...]
    #: `(refinement name, text)` for a passive this repo does not apply. Empty when the
    #: weapon has none — which is a real answer and the only case where the comparison is
    #: complete.
    unmodelled_passive: tuple[str, str] | None = None
    #: Which refinement step's text `unmodelled_passive` was read from. The build's own, since
    #: a candidate the user does not own has no refinement to read — an assumption, so it is
    #: reported rather than left for a reader to infer.
    passive_refinement: int = 1


@dataclass(frozen=True, slots=True)
class WeaponScore:
    """One weapon's damage in this build, and what it changes."""

    weapon_id: str
    name: str
    damage: float
    #: Against the weapon currently equipped. Zero for the equipped weapon itself.
    delta: float
    delta_pct: float
    #: The contribution diff against the equipped weapon — the "why", not just the "how
    #: much". Empty for the equipped weapon.
    differences: tuple[build_explanation.StatDifference, ...] = ()

    def __lt__(self, other: WeaponScore) -> bool:
        return self.damage < other.damage


@dataclass(frozen=True, slots=True)
class UnmodelledPassive:
    """A passive this comparison could not apply, named so a reader can weigh it."""

    weapon_id: str
    weapon_name: str
    passive_name: str
    text: str
    #: The refinement step this text was read at. See `WeaponCandidate.passive_refinement`.
    refinement: int = 1


@dataclass(frozen=True, slots=True)
class WeaponComparison:
    """Every candidate scored in one build, best first."""

    #: Best first. Ordering is by damage **as modelled**, which is not the same as best.
    weapons: tuple[WeaponScore, ...]
    equipped_weapon_id: str
    #: Every candidate whose passive is stored but not applied. **Not a footnote**: for
    #: weapons the unmodelled part is frequently the reason the weapon exists, so this list
    #: being non-empty means the ordering above may be wrong rather than merely imprecise.
    unmodelled_passives: tuple[UnmodelledPassive, ...] = ()

    @property
    def is_complete(self) -> bool:
        """True only when every candidate's effect is fully modelled.

        There is no partial credit here on purpose. One unapplied passive is enough to
        reorder the list, so "mostly complete" would be a comfort with nothing behind it.
        """
        return not self.unmodelled_passives

    def caveat(self) -> str:
        """One sentence naming what the ranking does not know."""
        if self.is_complete:
            return (
                "Every candidate's effect is modelled. Artifacts are held fixed, so this "
                "answers which weapon is better in the build you have, not which weapon is "
                "better with its own best artifacts."
            )
        names = ", ".join(
            f"{p.weapon_name} ({p.passive_name})" for p in self.unmodelled_passives
        )
        return (
            f"This ranking does not apply weapon passives, and {len(self.unmodelled_passives)} "
            f"of these weapons have one: {names}. For a weapon whose passive is the reason to "
            f"equip it, the order above can be wrong rather than merely imprecise. Artifacts "
            f"are also held fixed, so this is which weapon is better in the build you have."
        )


def compare_weapons(
    candidates: Sequence[WeaponCandidate],
    equipped_weapon_id: str,
    artifacts: Sequence[ArtifactCandidate],
    hit: Hit,
    enemy: Enemy,
    character_level: int,
    set_bonuses: Iterable[SetBonus] = (),
) -> WeaponComparison:
    """Score each candidate weapon in one fixed build.

    N independent evaluations, not one problem N times harder — the separability DESIGN §3.5
    turns on. The artifacts, the hit, the enemy and the character are identical across every
    one, so a difference in the answer is a difference the weapon made.
    """
    bonuses = bonuses_by_set(set_bonuses)

    def _score(candidate: WeaponCandidate) -> tuple[float, tuple[Contribution, ...]]:
        log, _ = build_combination_log(candidate.base_contributions, artifacts, bonuses)
        evaluator = BuildEvaluator(
            registry=log.registry, enemy=enemy, character_level=character_level,
        )
        return evaluator.evaluate(hit).expected, tuple(log.contributions)

    scored = {c.weapon_id: _score(c) for c in candidates}
    baseline = scored.get(equipped_weapon_id)
    if baseline is None:
        # Without the equipped weapon there is nothing to be better *than*, and a comparison
        # that silently used the first candidate as its baseline would report every other
        # weapon's delta against an arbitrary one while looking like a ranking.
        msg = (
            f"the equipped weapon {equipped_weapon_id!r} is not among the candidates. A "
            f"marginal-value comparison measures against what is worn, so it must be there."
        )
        raise ValueError(msg)
    baseline_damage, baseline_contributions = baseline

    weapons = []
    passives = []
    for candidate in candidates:
        damage, contributions = scored[candidate.weapon_id]
        is_equipped = candidate.weapon_id == equipped_weapon_id
        weapons.append(WeaponScore(
            weapon_id=candidate.weapon_id,
            name=candidate.name,
            damage=damage,
            delta=damage - baseline_damage,
            delta_pct=(
                (damage - baseline_damage) / baseline_damage * 100.0
                if baseline_damage
                else 0.0
            ),
            differences=() if is_equipped else build_explanation.compare(
                baseline_contributions, contributions,
            ).differences,
        ))
        if candidate.unmodelled_passive is not None:
            name, text = candidate.unmodelled_passive
            passives.append(UnmodelledPassive(
                weapon_id=candidate.weapon_id,
                weapon_name=candidate.name,
                passive_name=name,
                text=text,
                refinement=candidate.passive_refinement,
            ))

    return WeaponComparison(
        weapons=tuple(sorted(weapons, reverse=True)),
        equipped_weapon_id=equipped_weapon_id,
        unmodelled_passives=tuple(passives),
    )
